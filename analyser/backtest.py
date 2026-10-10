"""Simple long-only, vectorised strategy backtester.

Each strategy returns a position series (1 = long, 0 = flat) computed from data up to
and including the bar. The position is shifted one bar so trades execute on the next
bar's close - no look-ahead bias.
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import indicators as ind


def sma_crossover(df: pd.DataFrame, fast: int = 50, slow: int = 200) -> pd.Series:
    return (ind.sma(df["Close"], fast) > ind.sma(df["Close"], slow)).astype(int)


def rsi_reversion(df: pd.DataFrame, buy_below: float = 30, sell_above: float = 70) -> pd.Series:
    r = ind.rsi(df["Close"])
    pos = pd.Series(np.nan, index=df.index)
    pos[r < buy_below] = 1
    pos[r > sell_above] = 0
    return pos.ffill().fillna(0).astype(int)


def macd_cross(df: pd.DataFrame) -> pd.Series:
    m = ind.macd(df["Close"])
    return (m["MACD"] > m["Signal"]).astype(int)


def bollinger_reversion(df: pd.DataFrame, n: int = 20, k: float = 2.0) -> pd.Series:
    bb = ind.bollinger(df["Close"], n, k)
    pos = pd.Series(np.nan, index=df.index)
    pos[df["Close"] < bb["BB_lower"]] = 1
    pos[df["Close"] > bb["BB_mid"]] = 0
    return pos.ffill().fillna(0).astype(int)


STRATEGIES = {
    "SMA crossover": sma_crossover,
    "RSI mean reversion": rsi_reversion,
    "MACD crossover": macd_cross,
    "Bollinger mean reversion": bollinger_reversion,
}


@dataclass
class BacktestResult:
    equity: pd.DataFrame      # columns: Strategy, Buy & Hold
    trades: pd.DataFrame      # one row per closed/open trade
    stats: dict


def run(df: pd.DataFrame, position: pd.Series, capital: float = 10_000,
        fee_pct: float = 0.1, periods_per_year: int = 252) -> BacktestResult:
    """Backtest a 0/1 position series. fee_pct is charged on each entry and exit."""
    pos = position.shift(1).fillna(0)          # act on next bar
    rets = df["Close"].pct_change().fillna(0)
    trades_flag = pos.diff().abs().fillna(pos.iloc[0])
    strat_rets = pos * rets - trades_flag * fee_pct / 100

    equity = pd.DataFrame({
        "Strategy": capital * (1 + strat_rets).cumprod(),
        "Buy & Hold": capital * (1 + rets).cumprod(),
    })

    # Trade list. pos[t] = 1 means we held over bar t, i.e. bought at close t-1.
    trades = []
    entry_date = entry_px = None
    close, prev_close = df["Close"].values, df["Close"].shift(1).values
    prev_pos = pos.shift(1).fillna(0).values
    for i, date in enumerate(pos.index):
        if pos.iloc[i] == 1 and prev_pos[i] == 0:
            entry_date, entry_px = df.index[i - 1], prev_close[i]
        elif pos.iloc[i] == 0 and prev_pos[i] == 1 and entry_date is not None:
            trades.append((entry_date, entry_px, df.index[i - 1], prev_close[i]))
            entry_date = None
    if entry_date is not None:
        trades.append((entry_date, entry_px, None, close[-1]))
    trades = pd.DataFrame(trades, columns=["Entry date", "Entry price", "Exit date", "Exit price"])
    if not trades.empty:
        trades["Return %"] = (trades["Exit price"] / trades["Entry price"] - 1) * 100 - 2 * fee_pct

    stats = {"Strategy": _stats(equity["Strategy"], strat_rets, capital, periods_per_year),
             "Buy & Hold": _stats(equity["Buy & Hold"], rets, capital, periods_per_year)}
    closed = trades.dropna(subset=["Exit date"]) if not trades.empty else trades
    stats["Strategy"]["Trades"] = len(trades)
    stats["Strategy"]["Win rate %"] = (
        (closed["Return %"] > 0).mean() * 100 if len(closed) else float("nan"))
    stats["Strategy"]["Time in market %"] = pos.mean() * 100
    return BacktestResult(equity, trades, stats)


def _stats(equity: pd.Series, rets: pd.Series, capital: float, ppy: int) -> dict:
    years = max(len(equity) / ppy, 1e-9)
    total = equity.iloc[-1] / capital - 1
    cagr = (1 + total) ** (1 / years) - 1 if total > -1 else -1
    vol = rets.std() * np.sqrt(ppy)
    sharpe = rets.mean() / rets.std() * np.sqrt(ppy) if rets.std() > 0 else float("nan")
    dd = (equity / equity.cummax() - 1).min()
    return {"Total return %": total * 100, "CAGR %": cagr * 100, "Volatility %": vol * 100,
            "Sharpe": sharpe, "Max drawdown %": dd * 100}
