"""Market data via Yahoo Finance (covers US, NZX, ASX, ETFs, crypto, gold and FX)."""
import functools
import threading
import time
from datetime import date, timedelta

import pandas as pd
import yfinance as yf

# Yahoo ticker suffixes per market
MARKET_SUFFIX = {"US": "", "NZX": ".NZ", "ASX": ".AX", "Crypto": "-USD"}

# Yahoo quoteType -> friendly asset type
QUOTE_TYPES = {"EQUITY": "Stock", "ETF": "ETF", "CRYPTOCURRENCY": "Crypto", "MUTUALFUND": "Fund",
               "INDEX": "Index", "FUTURE": "Future", "CURRENCY": "Currency"}

# Minor-unit currencies Yahoo quotes some exchanges in (price / 100 = major unit)
MINOR_CURRENCIES = {"GBp": "GBP", "GBX": "GBP", "ILA": "ILS", "ZAc": "ZAR"}


def ttl_cache(seconds: int, max_stale: int | None = None):
    """Thread-safe time-based cache with stale-while-revalidate.

    Fresh for `seconds`. After that, and up to `max_stale` seconds old (default 4x `seconds`), the old
    value is returned immediately while a background thread fetches a new one - so pages never wait
    on a refresh, only on the very first load. Empty results are not cached so network blips retry.
    """
    max_stale = max_stale if max_stale is not None else seconds * 4

    def deco(fn):
        store, lock, refreshing = {}, threading.Lock(), set()

        def fetch(key, args, kwargs):
            val = fn(*args, **kwargs)
            empty = val is None or getattr(val, "empty", False) or (isinstance(val, (list, dict)) and not val)
            if not empty:
                with lock:
                    store[key] = (time.time(), val)
            return val

        def refresh(key, args, kwargs):
            try:
                fetch(key, args, kwargs)
            except Exception:
                pass                                  # keep serving the stale value
            finally:
                with lock:
                    refreshing.discard(key)

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            key = (args, tuple(sorted(kwargs.items())))
            with lock:
                hit = store.get(key)
            age = time.time() - hit[0] if hit else None
            if hit and age < seconds:
                val = hit[1]
            elif hit and age < max_stale:
                val = hit[1]
                with lock:
                    start = key not in refreshing
                    refreshing.add(key)
                if start:
                    threading.Thread(target=refresh, args=(key, args, kwargs), daemon=True).start()
            else:
                val = fetch(key, args, kwargs)
            return val.copy() if hasattr(val, "copy") else val

        wrapper.cache_clear = store.clear
        return wrapper
    return deco


def normalise_ticker(ticker: str, market: str = "US") -> str:
    """Add the Yahoo suffix for a market if the user left it off (e.g. FPH -> FPH.NZ)."""
    ticker = ticker.strip().upper()
    suffix = MARKET_SUFFIX.get(market, "")
    if suffix and not ticker.endswith(suffix) and "." not in ticker and "-" not in ticker:
        ticker += suffix
    return ticker


@ttl_cache(3600)          # daily bars; the live price comes from get_quote
def get_history(ticker: str, period: str | None = "2y", interval: str = "1d",
                start: str | None = None, auto_adjust: bool = True) -> pd.DataFrame:
    """OHLCV history with a timezone-naive DatetimeIndex. Empty frame if not found.

    auto_adjust=True adjusts for dividends and splits (best for charts/backtests).
    auto_adjust=False gives split-adjusted traded prices plus a 'Stock Splits' column
    (best for valuing real positions).
    """
    try:
        if start:
            df = yf.Ticker(ticker).history(start=start, interval=interval, auto_adjust=auto_adjust)
        else:
            df = yf.Ticker(ticker).history(period=period, interval=interval, auto_adjust=auto_adjust)
    except Exception:
        return pd.DataFrame()
    if df.empty:
        return df
    df.index = df.index.tz_localize(None).normalize()
    df = df[~df.index.duplicated(keep="last")]
    cols = ["Open", "High", "Low", "Close", "Volume"] + (["Stock Splits"] if not auto_adjust and "Stock Splits" in df else [])
    return df[cols].dropna(subset=["Close"])


@ttl_cache(3600 * 6)      # company profile / fundamentals barely change intraday
def get_info(ticker: str) -> dict:
    """Company/asset info dict from Yahoo (fundamentals, sector, etc.)."""
    try:
        return yf.Ticker(ticker).info or {}
    except Exception:
        return {}


@ttl_cache(3600 * 12)
def get_financials(ticker: str) -> dict[str, pd.DataFrame]:
    """Annual income statement, balance sheet and cash flow."""
    t = yf.Ticker(ticker)
    out = {}
    for name, attr in [("Income statement", "income_stmt"),
                       ("Balance sheet", "balance_sheet"),
                       ("Cash flow", "cashflow")]:
        try:
            out[name] = getattr(t, attr)
        except Exception:
            out[name] = pd.DataFrame()
    return out


@ttl_cache(3600 * 24)
def get_fund_sectors(ticker: str) -> dict:
    """Sector weights published for a fund/ETF ({} if Yahoo has none, e.g. most NZX funds)."""
    try:
        return dict(yf.Ticker(ticker).funds_data.sector_weightings or {})
    except Exception:
        return {}


@ttl_cache(3600)
def search(query: str, max_results: int = 10) -> list[dict]:
    """Search Yahoo by company name or ticker. Returns [{symbol, name, exchange, type}]."""
    query = query.strip()
    if not query:
        return []
    try:
        quotes = yf.Search(query, max_results=max_results, news_count=0, lists_count=0,
                           recommended=0, enable_fuzzy_query=True, raise_errors=False).quotes
    except Exception:
        return []
    out = []
    for q in quotes:
        if not q.get("symbol") or "quoteType" not in q:
            continue
        out.append({
            "symbol": q["symbol"],
            "name": q.get("longname") or q.get("shortname") or q["symbol"],
            "exchange": q.get("exchDisp") or q.get("exchange", ""),
            "type": QUOTE_TYPES.get(q["quoteType"], q.get("typeDisp") or q["quoteType"].title()),
        })
    return out


@ttl_cache(3600 * 24)
def get_currency(ticker: str) -> tuple[str, int]:
    """(major-unit currency, price divisor) - e.g. London stocks quoted in GBp -> ("GBP", 100)."""
    try:
        ccy = yf.Ticker(ticker).fast_info["currency"] or "USD"
    except Exception:
        ccy = get_info(ticker).get("currency") or "USD"
    return MINOR_CURRENCIES.get(ccy, ccy), (100 if ccy in MINOR_CURRENCIES else 1)


@ttl_cache(3600 * 6)
def get_meta(ticker: str) -> dict:
    """Name, asset type, exchange and currency for a ticker."""
    info = get_info(ticker)
    ccy, _ = get_currency(ticker)
    name = info.get("longName") or info.get("shortName") or ticker
    kind = QUOTE_TYPES.get(info.get("quoteType", ""), "Stock")
    if kind == "Stock" and " ETF" in f" {name.upper()}":     # NZX/ASX funds are often typed as equities
        kind = "ETF"
    return {
        "symbol": ticker,
        "name": name,
        "type": kind,
        "currency": ccy,
        "exchange": info.get("fullExchangeName") or info.get("exchange", ""),
    }


LIVE_WINDOW = pd.Timedelta(minutes=30)   # a trade this recent during trading hours counts as live


@ttl_cache(60)
def get_quote(ticker: str) -> dict | None:
    """Latest price plus when it's from and whether the market is trading now.

    Returns {price, prev, change_pct, spark, as_of (tz-aware Timestamp), live (bool), delay (minutes)}
    in the major-unit currency.
    """
    t = yf.Ticker(ticker)
    try:
        df = t.history(period="1mo", auto_adjust=False)
        meta = t.history_metadata or {}
    except Exception:
        return None
    df = df.dropna(subset=["Close"]) if not df.empty else df
    if df.empty:
        return None
    div = get_currency(ticker)[1]
    closes = df["Close"] / div
    price = (meta.get("regularMarketPrice") or closes.iloc[-1] * div) / div
    as_of = pd.Timestamp(meta.get("regularMarketTime") or df.index[-1])
    if as_of.tzinfo is None:
        as_of = as_of.tz_localize("UTC")
    # previous close = last daily bar before the one the latest price belongs to
    latest_day = as_of.tz_convert(df.index.tz).date() if df.index.tz else as_of.date()
    prior = closes[[d.date() < latest_day for d in df.index]]
    prev = prior.iloc[-1] if not prior.empty else closes.iloc[0]

    now = pd.Timestamp.now(tz="UTC")
    regular = (meta.get("currentTradingPeriod") or {}).get("regular") or {}
    start, end = regular.get("start"), regular.get("end")
    in_hours = start is not None and end is not None and pd.Timestamp(start) <= now <= pd.Timestamp(end)
    # Yahoo's usual data delays: crypto & FX real-time, futures 10 min, exchange-listed shares 15 min
    delay = {"CRYPTOCURRENCY": 0, "CURRENCY": 0, "FUTURE": 10}.get(meta.get("instrumentType"), 15)
    live = bool(in_hours and now - as_of <= LIVE_WINDOW + pd.Timedelta(minutes=delay))

    spark = closes.round(4).tolist()
    spark[-1] = round(float(price), 4)
    return {"price": float(price), "prev": float(prev), "change_pct": (price / prev - 1) * 100,
            "spark": spark, "as_of": as_of, "live": live, "delay": int(delay)}


def position_history(ticker: str, start: date) -> pd.DataFrame:
    """Split-adjusted daily prices from `start` (minus a buffer) plus a 'Factor' column.

    Factor(d) = product of stock splits after day d, so:
      price actually traded on day d = Close(d) * Factor(d)
      shares bought on day d are worth  shares * Factor(d) shares today.
    """
    df = get_history(ticker, period=None, start=str(start - timedelta(days=10)), auto_adjust=False)
    if df.empty:
        return df
    div = get_currency(ticker)[1]
    for col in ("Open", "High", "Low", "Close"):
        df[col] = df[col] / div
    splits = df.get("Stock Splits", pd.Series(0.0, index=df.index)).replace(0, 1.0).fillna(1.0)
    # product of splits strictly after each day
    df["Factor"] = splits[::-1].cumprod()[::-1].shift(-1).fillna(1.0)
    return df


def fx_series(frm: str, to: str, start: date) -> pd.Series | None:
    """Daily FX rate series converting 1 unit of `frm` into `to`. None if same currency."""
    if frm == to:
        return None
    df = get_history(f"{frm}{to}=X", period=None, start=str(start - timedelta(days=10)))
    if df.empty:
        return None
    return df["Close"]


def fx_rate(frm: str, to: str, on: date | None = None) -> float:
    """FX rate on a given day (latest if None). Falls back to 1.0 if unavailable."""
    if frm == to:
        return 1.0
    start = on or (date.today() - timedelta(days=10))
    s = fx_series(frm, to, start)
    if s is None or s.empty:
        return 1.0
    if on is None:
        return float(s.iloc[-1])
    val = s.asof(pd.Timestamp(on))
    return float(val) if pd.notna(val) else float(s.iloc[0])


def price_on(df: pd.DataFrame, day: date) -> tuple[date, float] | None:
    """(actual trading day, traded close) on `day` or the last trading day before it."""
    ts = pd.Timestamp(day)
    sub = df[df.index <= ts]
    if sub.empty:
        return None
    row = sub.iloc[-1]
    return sub.index[-1].date(), float(row["Close"] * row.get("Factor", 1.0))
