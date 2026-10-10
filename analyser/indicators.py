"""Technical indicators implemented with pandas (no extra TA library needed)."""
import numpy as np
import pandas as pd


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n).mean()


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def rsi(s: pd.Series, n: int = 14) -> pd.Series:
    """Wilder's RSI."""
    delta = s.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(100)


def macd(s: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    line = ema(s, fast) - ema(s, slow)
    sig = ema(line, signal)
    return pd.DataFrame({"MACD": line, "Signal": sig, "Hist": line - sig})


def bollinger(s: pd.Series, n: int = 20, k: float = 2.0) -> pd.DataFrame:
    mid = sma(s, n)
    sd = s.rolling(n).std()
    return pd.DataFrame({"BB_mid": mid, "BB_upper": mid + k * sd, "BB_lower": mid - k * sd})


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    prev_close = df["Close"].shift()
    tr = pd.concat([df["High"] - df["Low"],
                    (df["High"] - prev_close).abs(),
                    (df["Low"] - prev_close).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def add_all(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of an OHLCV frame with the standard indicator columns added."""
    out = df.copy()
    c = out["Close"]
    for n in (20, 50, 200):
        out[f"SMA{n}"] = sma(c, n)
    out["EMA12"] = ema(c, 12)
    out["EMA26"] = ema(c, 26)
    out["RSI"] = rsi(c)
    out = out.join(macd(c)).join(bollinger(c))
    out["ATR"] = atr(out)
    out["Vol_SMA20"] = sma(out["Volume"], 20)
    return out


def signal_summary(df: pd.DataFrame) -> list[tuple[str, str, str]]:
    """Plain-English read of the latest bar: list of (indicator, reading, bias)."""
    last, prev = df.iloc[-1], df.iloc[-2]
    rows = []

    r = last["RSI"]
    rows.append(("RSI(14)", f"{r:.1f}",
                 "Oversold (bullish)" if r < 30 else "Overbought (bearish)" if r > 70 else "Neutral"))

    if not np.isnan(last["SMA50"]) and not np.isnan(last["SMA200"]):
        trend = "Bullish" if last["SMA50"] > last["SMA200"] else "Bearish"
        cross = ""
        if prev["SMA50"] <= prev["SMA200"] < last["SMA50"] or prev["SMA50"] < prev["SMA200"] <= last["SMA50"]:
            cross = " - Golden cross today"
        elif prev["SMA50"] >= prev["SMA200"] > last["SMA50"]:
            cross = " - Death cross today"
        rows.append(("SMA50 vs SMA200", f"{last['SMA50']:.2f} / {last['SMA200']:.2f}", trend + cross))

    if not np.isnan(last["SMA200"]):
        rows.append(("Price vs SMA200", f"{(last['Close'] / last['SMA200'] - 1) * 100:+.1f}%",
                     "Above (bullish)" if last["Close"] > last["SMA200"] else "Below (bearish)"))

    rows.append(("MACD", f"{last['MACD']:.3f} vs signal {last['Signal']:.3f}",
                 "Bullish" if last["MACD"] > last["Signal"] else "Bearish"))

    bb_pos = (last["Close"] - last["BB_lower"]) / (last["BB_upper"] - last["BB_lower"])
    rows.append(("Bollinger %B", f"{bb_pos:.2f}",
                 "Near lower band" if bb_pos < 0.1 else "Near upper band" if bb_pos > 0.9 else "Inside bands"))

    if last["Vol_SMA20"]:
        vr = last["Volume"] / last["Vol_SMA20"]
        rows.append(("Volume vs 20d avg", f"{vr:.2f}x", "High volume" if vr > 1.5 else "Normal"))

    rows.append(("ATR(14)", f"{last['ATR']:.2f} ({last['ATR'] / last['Close'] * 100:.1f}% of price)",
                 "Volatility"))
    return rows
