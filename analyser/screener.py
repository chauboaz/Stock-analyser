"""Scan a watchlist and compute a snapshot of indicators per ticker."""
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd

from . import indicators as ind
from .data import get_history

DEFAULT_WATCHLISTS = {
    "US large caps": "AAPL, MSFT, NVDA, AMZN, GOOGL, META, TSLA, JPM, V, UNH, XOM, JNJ, WMT, PG, AMD",
    "NZX": "FPH.NZ, AIR.NZ, SPK.NZ, MEL.NZ, CEN.NZ, IFT.NZ, AIA.NZ, FBU.NZ, MFT.NZ, EBO.NZ, CNU.NZ, ATM.NZ",
    "ASX": "BHP.AX, CBA.AX, CSL.AX, NAB.AX, WBC.AX, ANZ.AX, WES.AX, MQG.AX, FMG.AX, WOW.AX, TLS.AX, RIO.AX",
    "Crypto": "BTC-USD, ETH-USD, SOL-USD, XRP-USD, BNB-USD, ADA-USD, DOGE-USD, AVAX-USD, LINK-USD, DOT-USD",
}


def snapshot(ticker: str) -> dict | None:
    df = get_history(ticker, period="1y")
    if len(df) < 60:
        return None
    d = ind.add_all(df)
    last = d.iloc[-1]
    c = d["Close"]

    def chg(n):
        return (c.iloc[-1] / c.iloc[-n - 1] - 1) * 100 if len(c) > n else np.nan

    return {
        "Ticker": ticker,
        "Price": last["Close"],
        "1D %": chg(1),
        "1M %": chg(21),
        "3M %": chg(63),
        "RSI": last["RSI"],
        "vs SMA50 %": (last["Close"] / last["SMA50"] - 1) * 100,
        "vs SMA200 %": (last["Close"] / last["SMA200"] - 1) * 100 if not np.isnan(last["SMA200"]) else np.nan,
        "MACD bullish": bool(last["MACD"] > last["Signal"]),
        "Golden cross": bool(last["SMA50"] > last["SMA200"]) if not np.isnan(last["SMA200"]) else None,
        "Vol ratio": last["Volume"] / last["Vol_SMA20"] if last["Vol_SMA20"] else np.nan,
        "ATR %": last["ATR"] / last["Close"] * 100,
        "52W high %": (last["Close"] / c.max() - 1) * 100,
    }


def scan(tickers: list[str], workers: int = 8) -> pd.DataFrame:
    with ThreadPoolExecutor(workers) as pool:
        rows = [r for r in pool.map(_safe_snapshot, tickers) if r]
    return pd.DataFrame(rows)


def _safe_snapshot(t: str):
    try:
        return snapshot(t)
    except Exception:
        return None
