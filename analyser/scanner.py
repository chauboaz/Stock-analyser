"""Read holdings out of broker screenshots with Claude's vision + structured outputs,
then match each one to a Yahoo Finance symbol."""
import base64
import difflib
import io
import json

import anthropic
from PIL import Image

from . import data

MODEL = "claude-opus-5"
MAX_EDGE = 2000              # px - plenty for reading text, keeps uploads small
MAX_BYTES = 4_500_000        # API limit is 5 MB per image


def _nullable(t: str) -> dict:
    return {"anyOf": [{"type": t}, {"type": "null"}]}


SCHEMA = {
    "type": "object",
    "properties": {
        "broker": _nullable("string"),
        "holdings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "ticker": _nullable("string"),
                    "yahoo_symbol": _nullable("string"),
                    "asset_type": {"type": "string",
                                   "enum": ["stock", "etf", "fund", "crypto", "gold", "silver", "other"]},
                    "quantity": _nullable("number"),
                    "quantity_unit": _nullable("string"),
                    "average_price": _nullable("number"),
                    "total_cost": _nullable("number"),
                    "current_value": _nullable("number"),
                    "currency": _nullable("string"),
                },
                "required": ["name", "ticker", "yahoo_symbol", "asset_type", "quantity", "quantity_unit",
                             "average_price", "total_cost", "current_value", "currency"],
                "additionalProperties": False,
            },
        },
        "warnings": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["broker", "holdings", "warnings"],
    "additionalProperties": False,
}

PROMPT = """These are screenshots from an investing app or brokerage account (for example Sharesies, \
Hatch, Stake, Kernel, InvestNow, CommSec, Robinhood, Interactive Brokers, a crypto exchange or a \
bullion dealer). Extract every investment position the user holds.

For each position:
- name: the security's name as shown.
- ticker: the ticker or code exactly as shown, or null if none is visible.
- yahoo_symbol: your best guess of the Yahoo Finance symbol. Yahoo uses suffixes by exchange: \
NZX "FPH.NZ", ASX "BHP.AX", LSE "VOD.L", TSX "RY.TO"; US listings have no suffix ("AAPL"); crypto is \
"BTC-USD". New Zealand apps such as Sharesies, Hatch and Kernel often show NZX codes without a suffix. \
Null for physical metals or when you cannot tell.
- asset_type: stock, etf, fund (managed/unlisted funds), crypto, gold, silver (physical bullion) or other.
- quantity: number of shares/units/coins held, or for metals the weight held. Null if not shown - \
do not calculate it.
- quantity_unit: for metals "oz", "g" or "kg"; otherwise null.
- average_price: average purchase price per share/unit if shown, else null.
- total_cost: total amount invested / cost basis if shown, else null.
- current_value: current market value of the position if shown, else null.
- currency: the 3-letter currency of the prices shown (NZD, USD, AUD...), or null if unclear.

Only report numbers that are visible; never invent or estimate them. If the same position appears in \
more than one screenshot, include it once. Ignore cash balances, watchlists, news and price charts of \
things the user does not hold. Use warnings for anything ambiguous (cut-off rows, unreadable numbers, \
a quantity that could be shares or dollars)."""


class ScanError(Exception):
    pass


def _prepare_image(raw: bytes) -> tuple[str, str]:
    """Downscale/re-encode as needed; returns (media_type, base64 data)."""
    img = Image.open(io.BytesIO(raw))
    img.load()
    if max(img.size) > MAX_EDGE:
        img.thumbnail((MAX_EDGE, MAX_EDGE))
    if img.mode not in ("RGB", "RGBA", "L"):
        img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    media_type = "image/png"
    if buf.tell() > MAX_BYTES:            # photos of screens compress better as JPEG
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=88)
        media_type = "image/jpeg"
    return media_type, base64.standard_b64encode(buf.getvalue()).decode()


def make_client(api_key: str | None = None) -> anthropic.Anthropic:
    """Explicit key if given, otherwise the SDK's normal credential lookup (ANTHROPIC_API_KEY etc.)."""
    return anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()


def scan(images: list[bytes], client: anthropic.Anthropic) -> dict:
    """Send screenshots to Claude and return {"broker", "holdings": [...], "warnings": [...]}."""
    content = []
    for raw in images:
        media_type, b64 = _prepare_image(raw)
        content.append({"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}})
    content.append({"type": "text", "text": PROMPT})

    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",                       # re-run on a recommended model if declined
        output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": content}],
    )
    if response.stop_reason == "refusal":
        raise ScanError("Claude declined to read these images. Try a cropped screenshot of just the holdings.")
    if response.stop_reason == "max_tokens":
        raise ScanError("Too many holdings to read in one go - try fewer screenshots at a time.")
    text = next((b.text for b in response.content if b.type == "text"), None)
    if not text:
        raise ScanError("Claude returned no result.")
    return json.loads(text)


# ---------- matching to Yahoo symbols ----------
EXCHANGE_SUFFIXES = {"NZD": ".NZ", "AUD": ".AX", "GBP": ".L", "CAD": ".TO"}


def _similar(a: str, b: str) -> bool:
    a, b = a.lower(), b.lower()
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.6 or a.split()[0] in b or b.split()[0] in a


def resolve_symbol(h: dict) -> dict | None:
    """Find a Yahoo symbol with live prices for an extracted holding.

    Tries Claude's guess, then the shown ticker (with the currency's exchange suffix first, then
    bare), then a name search. Returns a search-style result dict with "guess": True when it only
    came from a name search, or None.
    """
    candidates = []
    if h.get("asset_type") == "crypto":
        # bare "BTC" on Yahoo is a US-listed ETF, not the coin
        for sym in (h.get("yahoo_symbol"), h.get("ticker")):
            if sym:
                sym = sym.strip().upper()
                candidates.append(sym if sym.endswith("-USD") else f"{sym}-USD")
    for sym in (h.get("yahoo_symbol"), h.get("ticker")):
        if sym:
            sym = sym.strip().upper()
            # try the local-exchange listing first: bare "FPH" is a different (US) company to FPH.NZ
            suffix = EXCHANGE_SUFFIXES.get((h.get("currency") or "").upper())
            if suffix and "." not in sym and "-" not in sym:
                candidates.append(sym + suffix)
            candidates.append(sym)
    for sym in dict.fromkeys(candidates):   # dedupe, keep order
        if data.get_quote(sym):
            meta = data.get_meta(sym)
            return {"symbol": sym, "name": meta["name"], "type": meta["type"], "exchange": meta["exchange"],
                    "guess": False}
    # last resort: name search, only accepting investable results whose name resembles the screenshot's
    if h.get("name"):
        for r in data.search(h["name"]):
            if r["type"] in ("Stock", "ETF", "Fund", "Crypto") and _similar(h["name"], r["name"]) \
                    and data.get_quote(r["symbol"]):
                return {**r, "guess": True}
    return None
