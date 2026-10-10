"""Signal track record: log the strongest buy/sell signals and measure what the stock did next.

Each scan records its top buys and sells (one entry per ticker, side and trading day) to
user_data/signal_log.json with the price on the signal day. outcomes() then looks up the
return after 1 day, 1 week, 1 month and 3 months, and the same-period return of SPY.
"""
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import numpy as np
import pandas as pd

from . import data
from .portfolio import DATA_DIR

LOG_FILE = DATA_DIR / "signal_log.json"
HORIZONS = {"1 day": 1, "1 week": 5, "1 month": 21, "3 months": 63}     # trading days
BENCHMARK = "SPY"


def load() -> list[dict]:
    try:
        return json.loads(LOG_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save(entries: list[dict]) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    tmp = LOG_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(entries, indent=1), encoding="utf-8")
    tmp.replace(LOG_FILE)


def record(signals: list[dict]) -> int:
    """Add signals not already logged. Each: {ticker, name, side ('buy'/'sell'), score, verdict, price,
    date (signal day, ISO), reasons, indicators}. Returns how many were added."""
    entries = load()
    seen = {(e["ticker"], e["side"], e["date"]) for e in entries}
    new = [{**s, "recorded_at": datetime.now().isoformat(timespec="seconds")}
           for s in signals if (s["ticker"], s["side"], s["date"]) not in seen]
    if new:
        _save(entries + new)
    return len(new)


def clear() -> None:
    LOG_FILE.unlink(missing_ok=True)


def _forward_returns(ticker: str, day: str) -> dict:
    """% change from the signal-day close to N trading days later (None while still pending)."""
    df = data.get_history(ticker, "2y")
    if df.empty:
        return {h: None for h in HORIZONS}
    closes = df["Close"]
    pos = closes.index.searchsorted(pd.Timestamp(day), side="right") - 1      # signal day (or the one before)
    if pos < 0:
        return {h: None for h in HORIZONS}
    out = {}
    for h, n in HORIZONS.items():
        out[h] = float((closes.iloc[pos + n] / closes.iloc[pos] - 1) * 100) if pos + n < len(closes) else None
    out["latest"] = float((closes.iloc[-1] / closes.iloc[pos] - 1) * 100)
    return out


def outcomes(entries: list[dict]) -> pd.DataFrame:
    """One row per logged signal with forward returns, the benchmark's, and whether the call was right."""
    rows = []
    bench_cache: dict[str, dict] = {}
    with ThreadPoolExecutor(8) as ex:                  # warm the price-history cache in parallel
        list(ex.map(lambda t: data.get_history(t, "2y"), {e["ticker"] for e in entries} | {BENCHMARK}))
    for e in entries:
        fwd = _forward_returns(e["ticker"], e["date"])
        bench = bench_cache.setdefault(e["date"], _forward_returns(BENCHMARK, e["date"]))
        row = {"Date": pd.Timestamp(e["date"]), "Ticker": e["ticker"], "Name": e.get("name", e["ticker"]),
               "Side": e["side"].title(), "Score": e["score"], "Verdict": e["verdict"], "Price then": e["price"],
               "Since": fwd.get("latest"), "Reason": (e.get("reasons") or [""])[0]}
        for h in HORIZONS:
            r, b = fwd.get(h), bench.get(h)
            row[h] = r
            row[f"{h} vs {BENCHMARK}"] = r - b if r is not None and b is not None else None
            # right call: buys should rise, sells should fall
            row[f"{h} right"] = None if r is None else (r > 0 if e["side"] == "buy" else r < 0)
        rows.append(row)
    df = pd.DataFrame(rows)
    num = ["Since", *HORIZONS, *(f"{h} vs {BENCHMARK}" for h in HORIZONS)]
    if not df.empty:
        df[num] = df[num].apply(pd.to_numeric)          # None -> NaN for pending horizons
    return df


def summary(df: pd.DataFrame, side: str) -> pd.DataFrame:
    """Per horizon: signals measured, % that went the predicted way, average move, average vs benchmark."""
    d = df[df["Side"] == side.title()]
    rows = []
    for h in HORIZONS:
        done = d[d[h].notna()]
        rows.append({"Horizon": h, "Signals": len(done), "Pending": int(d[h].isna().sum()),
                     "Hit rate %": float(done[f"{h} right"].astype(bool).mean() * 100) if len(done) else np.nan,
                     "Avg move %": float(done[h].mean()) if len(done) else np.nan,
                     f"Avg vs {BENCHMARK} (pts)": float(done[f"{h} vs {BENCHMARK}"].mean()) if len(done) else np.nan})
    return pd.DataFrame(rows)
