"""Portfolio storage, valuation and history.

A holding is a plain dict saved to user_data/portfolio.json:
    id, kind ("security" | "metal"), ticker, name, asset_type, currency (market currency),
    quantity (shares / units / troy oz as bought), display_unit, price (paid per unit,
    in cost_currency), cost_currency, date (ISO date or None), tracking, notes, added
"""
import json
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from . import data

DATA_DIR = Path(os.environ.get("STOCK_ANALYSER_DATA") or Path(__file__).resolve().parent.parent / "user_data")
PORTFOLIO_FILE = DATA_DIR / "portfolio.json"

BASE_CURRENCIES = ["NZD", "USD", "AUD", "EUR", "GBP"]
CURRENCY_SYMBOLS = {"NZD": "NZ$", "USD": "US$", "AUD": "A$", "EUR": "€", "GBP": "£", "CAD": "C$", "JPY": "¥"}

METALS = {"Gold": "GC=F", "Silver": "SI=F"}          # USD per troy oz (COMEX front month)
TROY_OZ_G = 31.1034768
UNITS = {"troy oz": 1.0, "grams": 1 / TROY_OZ_G, "kilograms": 1000 / TROY_OZ_G}   # oz per unit

TRACKING_LABELS = {"date": "From purchase date", "today": "From date added", "price": "From price paid"}


# ---------- storage ----------
def load() -> dict:
    try:
        pf = json.loads(PORTFOLIO_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        pf = {}
    pf.setdefault("base_currency", "NZD")
    pf.setdefault("holdings", [])
    return pf


def save(pf: dict) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    tmp = PORTFOLIO_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(pf, indent=2, default=str), encoding="utf-8")
    tmp.replace(PORTFOLIO_FILE)


def new_holding(*, kind, ticker, name, asset_type, currency, quantity, price, cost_currency,
                buy_date, tracking, display_unit="units", notes="") -> dict:
    return {
        "id": uuid.uuid4().hex[:10], "kind": kind, "ticker": ticker, "name": name,
        "asset_type": asset_type, "currency": currency, "quantity": float(quantity),
        "display_unit": display_unit, "price": float(price), "cost_currency": cost_currency,
        "date": buy_date.isoformat() if buy_date else None, "tracking": tracking,
        "notes": notes, "added": datetime.now().isoformat(timespec="seconds"),
    }


def money(v: float, ccy: str, decimals: int | None = 2) -> str:
    """Format with currency symbol. decimals=None drops cents on amounts of 10,000+ (for headline tiles)."""
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "—"
    if decimals is None:
        decimals = 0 if abs(v) >= 10_000 else 2
    sym = CURRENCY_SYMBOLS.get(ccy, ccy + " ")
    return f"-{sym}{abs(v):,.{decimals}f}" if v < 0 else f"{sym}{v:,.{decimals}f}"


def _date(h) -> date | None:
    return date.fromisoformat(h["date"]) if h.get("date") else None


def _market_df(h: dict, start: date) -> pd.DataFrame:
    return data.position_history(h["ticker"], start)


def _split_factor(df: pd.DataFrame, d: date | None) -> float:
    """Shares bought on day d are now worth this many shares (after later splits)."""
    if d is None or df.empty or "Factor" not in df:
        return 1.0
    f = df["Factor"].asof(pd.Timestamp(d))
    return float(f) if pd.notna(f) else float(df["Factor"].iloc[0])


# ---------- valuation ----------
def _prefetch(calls) -> None:
    """Run network-bound lookups in parallel so the cached functions are warm before the (cheap)
    sequential maths below. Each holding needs several Yahoo requests; one at a time took ~30 s."""
    with ThreadPoolExecutor(8) as ex:
        list(ex.map(lambda c: c[0](*c[1:]), calls))


def value(holdings: list[dict], base: str) -> pd.DataFrame:
    """One row per holding with current value, cost and P/L in the base currency."""
    today = date.today()
    calls = []
    for h in holdings:
        d = _date(h)
        calls += [(_market_df, h, d or today - timedelta(days=10)), (data.get_quote, h["ticker"]),
                  (data.fx_rate, h["cost_currency"], base, d), (data.fx_rate, h["currency"], base)]
    _prefetch(calls)
    rows = []
    for h in holdings:
        d = _date(h)
        df = _market_df(h, d or today - timedelta(days=10))
        row = {"id": h["id"], "Name": h["name"], "Type": h["asset_type"],
               "Ticker": h["name"] if h["kind"] == "metal" else h["ticker"],
               "Quantity": h["quantity"] / UNITS.get(h.get("display_unit"), 1.0) if h["kind"] == "metal"
               else h["quantity"],
               "Unit": h.get("display_unit", "units"), "Currency": h["currency"],
               "Buy price": h["price"] * (UNITS.get(h.get("display_unit"), 1.0) if h["kind"] == "metal" else 1),
               "Cost currency": h["cost_currency"],
               "Bought": d, "Tracking": TRACKING_LABELS.get(h.get("tracking"), "")}
        cost = h["quantity"] * h["price"] * data.fx_rate(h["cost_currency"], base, d)
        row["Cost"] = cost
        if df.empty:
            row.update({"Price": np.nan, "Value": np.nan, "P/L": np.nan, "P/L %": np.nan,
                        "Day change": np.nan, "Days held": np.nan, "Ann. %": np.nan, "As of": pd.NaT,
                        "Live": False})
            rows.append(row)
            continue
        cur, prev = df["Close"].iloc[-1], df["Close"].iloc[-2] if len(df) > 1 else df["Close"].iloc[-1]
        q = data.get_quote(h["ticker"])       # fresher (1-minute cache) than the daily history
        if q:
            cur, prev = q["price"], q["prev"]
        row.update({"As of": q["as_of"] if q else df.index[-1].tz_localize("UTC"), "Live": bool(q and q["live"])})
        qty_now = h["quantity"] * _split_factor(df, d)
        fx_now = data.fx_rate(h["currency"], base)
        val = qty_now * cur * fx_now
        pnl_pct = val / cost - 1 if cost else np.nan
        days = (today - d).days if d else np.nan
        row.update({
            "Price": cur * (UNITS.get(h.get("display_unit"), 1.0) if h["kind"] == "metal" else 1),
            "Value": val, "P/L": val - cost, "P/L %": pnl_pct * 100,
            # bought today: today's change is just the change since buying
            "Day change": val - cost if d == today else qty_now * (cur - prev) * fx_now,
            "Days held": days,
            "Ann. %": ((1 + pnl_pct) ** (365 / days) - 1) * 100 if d and days >= 365 and pnl_pct > -1 else np.nan,
        })
        rows.append(row)
    return pd.DataFrame(rows)


def history(holdings: list[dict], base: str) -> pd.DataFrame:
    """Daily portfolio value and money invested since the earliest dated purchase.

    Only holdings with a purchase date are included. Columns: Value, Invested, plus one
    value column per holding id.
    """
    dated = [h for h in holdings if h.get("date")]
    if not dated:
        return pd.DataFrame()
    start = min(_date(h) for h in dated)
    _prefetch([c for h in dated for c in ((_market_df, h, _date(h)), (data.fx_series, h["currency"], base, start),
                                           (data.fx_rate, h["cost_currency"], base, _date(h)))])
    idx = pd.date_range(start, date.today(), freq="D")
    values, invested = {}, pd.Series(0.0, index=idx)
    for h in dated:
        d = _date(h)
        df = _market_df(h, d)
        if df.empty:
            continue
        close = df["Close"].reindex(df.index.union(idx)).ffill().reindex(idx)
        fx = data.fx_series(h["currency"], base, start)
        fx = fx.reindex(fx.index.union(idx)).ffill().bfill().reindex(idx) if fx is not None else 1.0
        held = idx >= pd.Timestamp(d)
        values[h["id"]] = (h["quantity"] * _split_factor(df, d) * close * fx).where(held, 0.0)
        invested += np.where(held, h["quantity"] * h["price"] * data.fx_rate(h["cost_currency"], base, d), 0.0)
    if not values:
        return pd.DataFrame()
    out = pd.DataFrame(values).fillna(0.0)
    out.insert(0, "Invested", invested)
    out.insert(0, "Value", out.drop(columns="Invested").sum(axis=1))
    return out


# ---------- "when did I buy it?" helper ----------
def suggest_dates(ticker: str, price: float, price_ccy: str, market_ccy: str,
                  unit_factor: float = 1.0, years: int = 5, limit: int = 6) -> dict:
    """Find periods in the last `years` when `price` (per unit, in price_ccy) was within the
    day's traded range. unit_factor converts the ticker's quote unit into the user's unit
    (e.g. oz -> grams for metals).

    Returns {"periods": [{start, end, best, best_close, low, high}], "closest": (date, close),
             "min": float, "max": float}
    """
    df = data.position_history(ticker, date.today() - timedelta(days=365 * years))
    if df.empty:
        return {"periods": [], "closest": None, "min": np.nan, "max": np.nan}
    fx = data.fx_series(market_ccy, price_ccy, df.index[0].date())
    fx = fx.reindex(fx.index.union(df.index)).ffill().bfill().reindex(df.index) if fx is not None else 1.0
    mult = df["Factor"] * fx * unit_factor
    low, high, close = df["Low"] * mult, df["High"] * mult, df["Close"] * mult

    hit = (low <= price) & (price <= high)
    run_id = (hit != hit.shift()).cumsum()
    periods = []
    for _, grp in hit[hit].groupby(run_id[hit]):
        days = grp.index
        diff = (close.loc[days] - price).abs()
        best = diff.idxmin()
        periods.append({"start": days[0].date(), "end": days[-1].date(), "best": best.date(),
                        "best_close": float(close.loc[best]),
                        "low": float(low.loc[days].min()), "high": float(high.loc[days].max())})
    periods.sort(key=lambda p: p["end"], reverse=True)
    ci = (close - price).abs().idxmin()
    return {"periods": periods[:limit], "total_periods": len(periods),
            "closest": (ci.date(), float(close.loc[ci])),
            "min": float(low.min()), "max": float(high.max())}


def reference_price(ticker: str, on: date, price_ccy: str, market_ccy: str,
                    unit_factor: float = 1.0) -> tuple[date, float] | None:
    """Traded close on (or just before) `on`, converted to price_ccy and the user's unit."""
    df = data.position_history(ticker, on)
    hit = data.price_on(df, on) if not df.empty else None
    if not hit:
        return None
    d, px = hit
    return d, px * data.fx_rate(market_ccy, price_ccy, d) * unit_factor


def current_price(ticker: str, price_ccy: str, market_ccy: str, unit_factor: float = 1.0) -> float | None:
    q = data.get_quote(ticker)
    if not q:
        return None
    return q["price"] * data.fx_rate(market_ccy, price_ccy) * unit_factor
