"""Rule-based trading signals.

Pure functions only (DataFrames / dicts in, dicts out, no Streamlit) so every check can be
backtested later. Each check returns:
    {"score": float in [-1, 1] (positive = bullish) or None if not applicable,
     "summary": one plain-English line, "flags": {...}, plus check-specific details}
run_checks() runs them all for a ticker; composite() turns the enabled checks into a
-100..100 score with a verdict and the reasons behind it.
"""
import copy
import json
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd

from . import data
from . import indicators as ind

MAG7 = ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA"]

CHECKS = {
    "gaps": "Gap fill",
    "ema200": "200-day EMA support",
    "crossovers": "MA crossovers",
    "rsi": "RSI overbought / oversold",
    "support": "Support levels",
    "relative": "Relative performance",
    "fundamentals": "Fundamentals check",
}

# Plain-English explanations: what each indicator measures, and why a reading counts as bullish/bearish.
MEANING = {
    "gaps": {
        "what": "A gap is a jump between one bar's close and the next bar's open (often after earnings or news) "
                "that leaves a price range nobody traded in. Prices often come back to 'fill' that empty zone "
                "later, so old gaps act like magnets and as support or resistance.",
        "bull": "Price has pulled back into the zone left by a gap up. Buyers stepped in hard at this level "
                "before, so it often acts as support - the idea is to buy the retest instead of chasing the jump.",
        "bear": "Price is either sitting under the zone left by a gap down (sellers took over there before, "
                "so it tends to act as resistance) or has fallen straight through an old gap-up zone, which "
                "means that support failed.",
        "neutral": "No gap zone is close enough to the current price to matter right now.",
    },
    "ema200": {
        "what": "The 200-day exponential moving average is the average price over roughly the last 10 months, "
                "weighted towards recent days. Big funds watch it as the line between a long-term uptrend and "
                "a downtrend.",
        "bull": "Price is above its 200-day average, i.e. in a long-term uptrend. A pullback to the average from "
                "above is a classic lower-risk entry because many buyers defend that line, and you have a clear "
                "exit if it closes below.",
        "bear": "Price has closed below its 200-day average. The long-term trend has turned down or support has "
                "just broken, and stocks under this line tend to keep underperforming until they reclaim it.",
        "neutral": "Price is around its 200-day average without a clear test or break.",
    },
    "crossovers": {
        "what": "Compares a fast moving average (recent trend) with a slow one (longer trend). When the fast one "
                "crosses above the slow one it's a 'golden cross'; crossing below is a 'death cross'. They confirm "
                "trends after they start - they don't predict them.",
        "bull": "The faster average is above the slower one (or just crossed above it), so recent prices are "
                "stronger than the longer-term average - momentum is pointing up.",
        "bear": "The faster average is below the slower one (or just crossed below it), so recent prices are "
                "weaker than the longer-term average - momentum is pointing down.",
        "neutral": "The averages are mixed or crossing back and forth (choppy), so there's no clear trend signal.",
    },
    "rsi": {
        "what": "The Relative Strength Index (0-100) measures how fast and far price has moved recently. Above "
                "70 means it has risen sharply (overbought); below 30 means it has fallen sharply (oversold).",
        "bull": "Selling has been heavy and fast, so the stock is stretched to the downside. Oversold stocks "
                "often bounce, especially in an uptrend - though in a downtrend RSI can stay low for a while.",
        "bear": "Buying has been heavy and fast, so the stock is stretched to the upside. Overbought stocks often "
                "pause or pull back before going higher.",
        "neutral": "RSI is in the normal 40-60 range - momentum isn't stretched either way.",
    },
    "support": {
        "what": "Support is a price level where the stock has repeatedly stopped falling and bounced (found here "
                "from weekly swing lows). The more times it has bounced there, the stronger the level.",
        "bull": "Price is just above a level where buyers have stepped in before, so the downside to that "
                "support is small - a good risk/reward spot, with a clear exit if it breaks.",
        "bear": "Price has broken below a support level that held before. Broken support often turns into "
                "resistance, and the people who bought there may sell on any bounce.",
        "neutral": "The nearest support level is far enough below that it doesn't matter yet.",
    },
    "relative": {
        "what": "Compares the stock's return over 1-12 months with the S&P 500 and an equal-weight basket of "
                "the 'Magnificent 7' tech giants. Leaders tend to keep leading (momentum).",
        "bull": "The stock is beating the market (momentum), or it has lagged its peers while its fundamentals "
                "still look healthy - which can mean it's cheap.",
        "bear": "The stock is trailing the market, or lagging its peers with fundamental red flags - which "
                "suggests it's falling behind for a reason.",
        "neutral": "Performing roughly in line with the market.",
    },
    "fundamentals": {
        "what": "A sanity check on the business itself: valuation (P/E now vs expected), growth, cash flow, debt, "
                "how many shares trade freely, and what analysts expect. It stops you buying a nice-looking "
                "chart of a shaky company.",
        "bull": "Earnings are expected to grow into the valuation (forward P/E below today's), analysts see "
                "upside to their price target, and there are no red flags.",
        "bear": "There are red flags such as losing cash while earnings shrink, very few tradable shares, missing "
                "financials or no analyst coverage - or the P/E is so high that a lot of success is already "
                "priced in.",
        "neutral": "Nothing stands out either way in the financials.",
    },
}


def explain(key: str, score: float | None) -> str:
    """Why the current reading of `key` counts as bullish / bearish / neutral."""
    if score is None:
        return "Not applicable to this asset (or not enough history)."
    m = MEANING[key]
    return m["bull"] if score >= 0.15 else m["bear"] if score <= -0.15 else m["neutral"]


DEFAULT_PARAMS = {
    "gaps": {"min_gap_daily": 1.0, "min_gap_weekly": 2.0, "overshoot": 5.0, "min_dollar_volume": 1e6},
    "ema200": {"days_above": 20, "band": 2.0},
    "crossovers": {"pairs": [[50, 200], [10, 50]], "recent_bars": 20, "noise_window": 120, "noise_crosses": 4},
    "rsi": {"period": 14, "oversold": 30, "overbought": 70},
    "support": {"swing_n": 5, "cluster": 2.0, "near": 3.0},
    "relative": {"benchmark": "SPY", "lag": 15.0},
    "fundamentals": {"small_float_m": 20},
}

VERDICTS = [(40, "Strong buy"), (15, "Buy"), (-15, "Neutral"), (-40, "Sell")]   # else "Strong sell"
WINDOWS = {"1M": 21, "3M": 63, "6M": 126, "1Y": 252}


def merged_params(params: dict | None) -> dict:
    """DEFAULT_PARAMS with any user overrides applied."""
    out = copy.deepcopy(DEFAULT_PARAMS)
    for k, v in (params or {}).items():
        out.setdefault(k, {}).update(v)
    return out


def _clip(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return float(max(lo, min(hi, x)))


def _touches(n) -> str:
    return f"{int(n)} touch" + ("" if int(n) == 1 else "es")


def _fmt(x: float) -> str:
    return f"{x:,.2f}" if abs(x) < 1000 else f"{x:,.0f}"


def weekly(df: pd.DataFrame) -> pd.DataFrame:
    """Daily OHLCV -> weekly bars ending Friday."""
    return df.resample("W-FRI").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last",
                                      "Volume": "sum"}).dropna(subset=["Close"])


# ---------- 1. gaps ----------
def find_gaps(df: pd.DataFrame, min_pct: float, overshoot_pct: float) -> pd.DataFrame:
    """Every gap of at least min_pct %. Gap up: low[t] > high[t-1], zone (high[t-1], low[t]).
    Gap down: high[t] < low[t-1], zone (high[t], low[t-1]). A gap is filled once price trades
    back through the whole zone; overshoot = after filling, price went > overshoot_pct % beyond it."""
    hi, lo, op = df["High"].values, df["Low"].values, df["Open"].values
    rows = []
    for t in range(1, len(df)):
        if op[t] > hi[t - 1] and lo[t] > hi[t - 1]:
            direction, z_lo, z_hi = "up", hi[t - 1], lo[t]
        elif op[t] < lo[t - 1] and hi[t] < lo[t - 1]:
            direction, z_lo, z_hi = "down", hi[t], lo[t - 1]
        else:
            continue
        size = (z_hi / z_lo - 1) * 100
        if size < min_pct:
            continue
        after_lo, after_hi = lo[t + 1:], hi[t + 1:]
        hit = after_lo <= z_lo if direction == "up" else after_hi >= z_hi
        filled = bool(hit.any())
        fill_i = t + 1 + int(np.argmax(hit)) if filled else None
        over = False
        if filled:
            if direction == "up":
                over = bool(lo[fill_i:].min() < z_lo * (1 - overshoot_pct / 100))
            else:
                over = bool(hi[fill_i:].max() > z_hi * (1 + overshoot_pct / 100))
        rows.append({"date": df.index[t], "direction": direction, "zone_low": float(z_lo), "zone_high": float(z_hi),
                     "size_pct": float(size), "filled": filled,
                     "fill_date": df.index[fill_i] if filled else pd.NaT, "overshoot": over})
    return pd.DataFrame(rows, columns=["date", "direction", "zone_low", "zone_high", "size_pct", "filled",
                                       "fill_date", "overshoot"])


def check_gaps(daily: pd.DataFrame, wk: pd.DataFrame, p: dict) -> dict:
    price = float(daily["Close"].iloc[-1])
    dollar_vol = float((daily["Close"] * daily["Volume"]).tail(50).mean())
    gd = find_gaps(daily, p["min_gap_daily"], p["overshoot"]).assign(timeframe="daily")
    gw = find_gaps(wk, p["min_gap_weekly"], p["overshoot"]).assign(timeframe="weekly")
    gaps = pd.concat([gw, gd], ignore_index=True).astype({"filled": bool, "overshoot": bool})
    gaps["fill_date"] = pd.to_datetime(gaps["fill_date"])
    fill_rate = {tf: (float(g["filled"].mean()) if len(g) else None) for tf, g in (("daily", gd), ("weekly", gw))}
    out = {"gaps": gaps, "fill_rate": fill_rate, "flags": {}, "score": 0.0}
    if dollar_vol < p["min_dollar_volume"]:
        out.update(score=None, summary=f"Thinly traded (~${dollar_vol:,.0f}/day) - gaps aren't meaningful here.")
        out["flags"]["illiquid"] = True
        return out

    unfilled = gaps[~gaps["filled"]]
    inside = unfilled[(unfilled["zone_low"] <= price) & (price <= unfilled["zone_high"])]
    recent_cut = daily.index[-60] if len(daily) > 60 else daily.index[0]
    recent_over = gaps[gaps["overshoot"] & (gaps["fill_date"] >= recent_cut)]
    rate_txt = " / ".join(f"{tf} {r:.0%}" for tf, r in fill_rate.items() if r is not None) or "no history"
    out["flags"].update(in_gap_zone=not inside.empty, overshoot=not recent_over.empty)

    if not inside.empty:
        g = inside.sort_values(["timeframe", "date"], ascending=[False, False]).iloc[0]   # prefer weekly, newest
        rng = f"{_fmt(g['zone_low'])}–{_fmt(g['zone_high'])}"
        if g["direction"] == "up":
            out["score"] = 0.6
            out["summary"] = (f"Inside unfilled {g['timeframe']} gap-up zone {rng} from {g['date']:%d %b %Y} - "
                              f"the classic gap-fill buy area (fill rate {rate_txt}). A zone, not a floor.")
        else:
            out["score"] = -0.5
            out["summary"] = (f"Inside unfilled {g['timeframe']} gap-down zone {rng} from {g['date']:%d %b %Y} - "
                              f"overhead resistance (fill rate {rate_txt}).")
        out["active_gap"] = g.to_dict()
    elif not recent_over.empty:
        g = recent_over.iloc[-1]
        zone = f"{g['timeframe']} gap {_fmt(g['zone_low'])}–{_fmt(g['zone_high'])}"
        if g["direction"] == "up":      # fell through an up-gap: the support zone failed
            out["score"] = -0.3
            out["summary"] = (f"Filled the {zone} on {g['fill_date']:%d %b} and kept falling - the gap didn't act "
                              f"as support (fill rate {rate_txt}).")
        else:                           # rallied through a down-gap: resistance broken
            out["score"] = 0.3
            out["summary"] = (f"Rallied through the {zone} on {g['fill_date']:%d %b} and kept going - overhead "
                              f"resistance cleared (fill rate {rate_txt}).")
    else:
        below = unfilled[(unfilled["direction"] == "up") & (unfilled["zone_high"] < price)]
        near = below[below["zone_high"] >= price * 0.95]
        if not near.empty:
            g = near.sort_values("zone_high").iloc[-1]
            out["score"] = 0.15
            out["summary"] = (f"Approaching unfilled {g['timeframe']} gap {_fmt(g['zone_low'])}–"
                              f"{_fmt(g['zone_high'])}, {(price / g['zone_high'] - 1) * 100:.1f}% below "
                              f"(fill rate {rate_txt}).")
        else:
            out["summary"] = f"No active gap setup · {len(unfilled)} unfilled gaps · fill rate {rate_txt}."
    return out


# ---------- 2. EMA200 ----------
def check_ema200(daily: pd.DataFrame, p: dict) -> dict:
    close = daily["Close"]
    if len(close) < 250:
        return {"score": None, "summary": "Not enough history (needs 200+ days to warm up).", "flags": {}}
    ema = close.ewm(span=200, adjust=False).mean()
    pct = float((close.iloc[-1] - ema.iloc[-1]) / ema.iloc[-1] * 100)
    n, band = int(p["days_above"]), p["band"]
    prior_above = float((close.iloc[-n - 1:-1] > ema.iloc[-n - 1:-1]).mean())
    below_days = int((close.iloc[::-1] < ema.iloc[::-1]).cumprod().sum())     # consecutive closes below
    testing = abs(pct) <= band and prior_above >= 0.9
    below = close.iloc[-1] < ema.iloc[-1]
    flags = {"testing_ema200_from_above": bool(testing), "below_ema200": bool(below)}
    lvl = _fmt(float(ema.iloc[-1]))
    if testing:
        score, s = 0.7, f"Testing the EMA200 ({lvl}) from above, {pct:+.1f}% - long-term support being retested."
    elif below and below_days <= 10:
        score, s = -0.6, f"Closed below the EMA200 ({lvl}) {below_days} day(s) ago - support broke."
    elif below:
        score, s = -0.4, f"{pct:+.1f}% vs EMA200 ({lvl}), below it for {below_days} days - long-term downtrend."
    else:
        score, s = (0.3 if pct < 15 else 0.1), f"{pct:+.1f}% above the EMA200 ({lvl}) - long-term uptrend."
    return {"score": score, "summary": s, "flags": flags, "pct_from_ema200": pct, "ema200": float(ema.iloc[-1])}


# ---------- 3. MA crossovers ----------
def crossover(close: pd.Series, fast: int, slow: int, recent: int, window: int, noisy_n: int) -> dict:
    f, s = close.rolling(fast).mean(), close.rolling(slow).mean()
    valid = f.notna() & s.notna()
    state = (f > s)[valid]
    if len(state) < 2:
        return {}
    flips = state.astype(int).diff().fillna(0)
    crosses = flips[flips != 0]
    last = crosses.index[-1] if len(crosses) else None
    bars_since = int(len(state) - 1 - state.index.get_loc(last)) if last is not None else None
    n_recent = int((flips.iloc[-window:] != 0).sum())
    return {"pair": f"{fast}/{slow}", "fast_above": bool(state.iloc[-1]),
            "last_cross": ("golden" if crosses.iloc[-1] > 0 else "death") if last is not None else None,
            "last_cross_date": last, "bars_since": bars_since, "recent_crosses": n_recent,
            "noisy": n_recent >= noisy_n, "fresh": bars_since is not None and bars_since <= recent}


def check_crossovers(daily: pd.DataFrame, p: dict) -> dict:
    pairs = [crossover(daily["Close"], int(a), int(b), p["recent_bars"], p["noise_window"], p["noise_crosses"])
             for a, b in p["pairs"]]
    pairs = [x for x in pairs if x]
    if not pairs:
        return {"score": None, "summary": "Not enough history for these moving averages.", "flags": {}}
    scores, parts = [], []
    for x in pairs:
        if x["fresh"]:
            sc = 0.7 if x["last_cross"] == "golden" else -0.7
            txt = f"{x['pair']}: {x['last_cross']} cross {x['bars_since']}d ago"
        else:
            sc = 0.3 if x["fast_above"] else -0.3
            txt = f"{x['pair']}: fast {'above' if x['fast_above'] else 'below'} slow"
            if x["last_cross"]:
                txt += f" (last {x['last_cross']} cross {x['bars_since']}d ago)"
        if x["noisy"]:
            sc *= 0.5
            txt += f", choppy ({x['recent_crosses']} crosses lately)"
        scores.append(sc)
        parts.append(txt)
    flags = {"golden_cross_recent": any(x["fresh"] and x["last_cross"] == "golden" for x in pairs),
             "death_cross_recent": any(x["fresh"] and x["last_cross"] == "death" for x in pairs)}
    return {"score": float(np.mean(scores)), "summary": "; ".join(parts) + ".", "flags": flags, "pairs": pairs}


# ---------- 4. RSI ----------
def check_rsi(daily: pd.DataFrame, p: dict, below_ema200: bool) -> dict:
    r = float(ind.rsi(daily["Close"], int(p["period"])).iloc[-1])
    lo, hi = p["oversold"], p["overbought"]
    flags = {"oversold": r < lo, "overbought": r > hi}
    if r < lo:
        score, s = 0.7, f"RSI {r:.0f} - oversold."
        if below_ema200:
            score, s = 0.35, s + " But it's in a downtrend (below EMA200), where RSI can stay oversold."
    elif r > hi:
        score, s = -0.7, f"RSI {r:.0f} - overbought."
    elif r < lo + 10:
        score, s = 0.2, f"RSI {r:.0f} - leaning oversold."
    elif r > hi - 10:
        score, s = -0.2, f"RSI {r:.0f} - leaning overbought."
    else:
        score, s = 0.0, f"RSI {r:.0f} - neutral."
    return {"score": score, "summary": s, "flags": flags, "rsi": r}


# ---------- 5. support ----------
def support_zones(wk: pd.DataFrame, n: int, cluster_pct: float) -> pd.DataFrame:
    """Weekly swing lows (lowest low within ±n bars) clustered into zones, ranked by touches."""
    lows = wk["Low"]
    swing = lows[lows == lows.rolling(2 * n + 1, center=True).min()].dropna()
    zones = []
    for d, v in swing.sort_values().items():
        if zones and v <= zones[-1]["level"] * (1 + cluster_pct / 100):
            z = zones[-1]
            z["lows"].append(v)
            z["dates"].append(d)
            z["level"] = float(np.mean(z["lows"]))
        else:
            zones.append({"level": float(v), "lows": [v], "dates": [d]})
    rows = [{"zone_low": float(min(z["lows"])), "zone_high": float(max(z["lows"])), "level": z["level"],
             "touches": len(z["lows"]), "last_touch": max(z["dates"])} for z in zones]
    return pd.DataFrame(rows, columns=["zone_low", "zone_high", "level", "touches", "last_touch"])


def round_level_below(price: float) -> float:
    step = 5 * 10 ** (np.floor(np.log10(price)) - 1) if price > 0 else 1
    return float(np.floor(price / step) * step)


def check_support(daily: pd.DataFrame, wk: pd.DataFrame, p: dict) -> dict:
    price = float(daily["Close"].iloc[-1])
    zones = support_zones(wk, int(p["swing_n"]), p["cluster"])
    low_52w = float(daily["Low"].tail(252).min())
    rnd = round_level_below(price)
    out = {"zones": zones, "low_52w": low_52w, "round_level": rnd, "flags": {"near_support": False}, "score": 0.0}
    extras = f"52-week low {_fmt(low_52w)} · round number {_fmt(rnd)}"
    below = zones[zones["zone_low"] <= price]
    if below.empty:
        out["summary"] = f"No swing-low support below the price yet. {extras}."
        return out
    z = below.sort_values("zone_high").iloc[-1]
    dist = max(0.0, (price / z["zone_high"] - 1) * 100)
    strength = "major" if z["touches"] >= 3 else "minor"
    rng = f"{_fmt(z['zone_low'])}–{_fmt(z['zone_high'])}"
    out["nearest"] = z.to_dict()
    # broken: a support zone (2+ touches) that price was above a month ago and is now >2% below
    month_ago = float(daily["Close"].iloc[-21]) if len(daily) > 21 else price
    broken = zones[(zones["touches"] >= 2) & (zones["zone_low"] < month_ago) & (price < zones["zone_low"] * 0.98)]
    if dist <= p["near"]:
        out["flags"]["near_support"] = True
        out["score"] = 0.3 + 0.1 * min(int(z["touches"]), 5)
        out["summary"] = (f"{dist:.1f}% above {strength} support {rng} ({_touches(z['touches'])}). {extras}.")
    elif not broken.empty:
        b = broken.sort_values("zone_low").iloc[-1]
        out["score"] = -0.5
        out["summary"] = (f"Broke below support {_fmt(b['zone_low'])}–{_fmt(b['zone_high'])} "
                          f"({_touches(b['touches'])}) in the last month. {extras}.")
        out["flags"]["broke_support"] = True
    else:
        out["summary"] = f"Nearest support {rng} ({strength}, {_touches(z['touches'])}), {dist:.1f}% below. {extras}."
    return out


# ---------- 6. relative performance ----------
def _returns(close: pd.Series) -> dict:
    return {k: (float(close.iloc[-1] / close.iloc[-n - 1] - 1) * 100 if len(close) > n else None)
            for k, n in WINDOWS.items()}


@data.ttl_cache(3600)
def benchmarks(benchmark: str = "SPY") -> dict:
    """Window returns for the benchmark ETF and an equal-weight MAG7 basket."""
    bench = _returns(data.get_history(benchmark, "5y")["Close"])
    members = [_returns(data.get_history(t, "5y")["Close"]) for t in MAG7]
    mag7 = {k: float(np.mean([m[k] for m in members if m[k] is not None])) for k in WINDOWS}
    return {benchmark: bench, "MAG7": mag7}


def check_relative(daily: pd.DataFrame, bench: dict, p: dict, red_flags: int | None) -> dict:
    mine = _returns(daily["Close"])
    excess = {name: {k: (mine[k] - r[k]) if mine[k] is not None and r[k] is not None else None
                     for k in WINDOWS} for name, r in bench.items()}
    b = p["benchmark"]
    vs_b, vs_m = excess[b]["6M"], excess["MAG7"]["6M"]
    lagging = vs_m is not None and vs_m <= -p["lag"]
    flags = {"lagging_peers": bool(lagging), "lagging_no_red_flags": bool(lagging and red_flags == 0)}
    if vs_b is None:
        return {"score": None, "summary": "Not enough history for 6-month comparison.", "flags": flags,
                "returns": mine, "excess": excess}
    txt = f"6M: {mine['6M']:+.1f}% ({vs_b:+.1f} pts vs {b}, {vs_m:+.1f} pts vs MAG7)"
    if lagging and red_flags == 0:
        score, s = 0.3, txt + " - lagging peers but fundamentals look clean: possibly cheap."
    elif lagging and red_flags:
        score, s = -0.5, txt + " - lagging peers with fundamental red flags: possibly broken."
    elif lagging:
        score, s = -0.2, txt + " - lagging peers (cheap or broken? check fundamentals)."
    else:
        score, s = _clip(vs_b / 40, -0.4, 0.4), txt + "."
    return {"score": score, "summary": s, "flags": flags, "returns": mine, "excess": excess}


# ---------- 7. fundamentals ----------
def check_fundamentals(info: dict, p: dict) -> dict:
    qtype = info.get("quoteType")
    if qtype and qtype != "EQUITY":
        return {"score": None, "summary": "Not applicable (fund / crypto / index).", "flags": {}, "red_flags": None}
    g = info.get
    fields = {k: g(k) for k in ("trailingPE", "forwardPE", "revenueGrowth", "earningsGrowth", "freeCashflow",
                                "profitMargins", "debtToEquity", "marketCap", "floatShares", "targetMeanPrice",
                                "targetHighPrice", "targetLowPrice", "recommendationKey", "numberOfAnalystOpinions")}
    price = g("currentPrice") or g("regularMarketPrice")
    tpe, fpe = fields["trailingPE"], fields["forwardPE"]
    compression = tpe / fpe if tpe and fpe and tpe > 0 and fpe > 0 else None
    red, warn = [], []
    if (fields["freeCashflow"] or 0) < 0 and (fields["earningsGrowth"] or 0) < 0:
        red.append("negative free cash flow and shrinking earnings")
    if fields["floatShares"] and fields["floatShares"] < p["small_float_m"] * 1e6:
        red.append(f"very small float ({fields['floatShares'] / 1e6:.1f}M shares)")
    if not any(fields[k] for k in ("revenueGrowth", "profitMargins", "marketCap")):
        red.append("missing financials")
    if not fields["numberOfAnalystOpinions"]:
        red.append("no analyst coverage")
    if tpe and tpe >= 100:
        warn.append(f"P/E {tpe:.0f} already prices in a lot of growth")
    upside = (fields["targetMeanPrice"] / price - 1) * 100 if fields["targetMeanPrice"] and price else None

    score = -0.3 * len(red)
    if compression and compression > 1.3 and (fields["earningsGrowth"] or 0) > 0:
        score += 0.2
    if upside is not None and upside > 15:
        score += 0.2
    if fields["recommendationKey"] in ("buy", "strong_buy"):
        score += 0.1
    if warn:
        score -= 0.2
    pe_txt = f"P/E {tpe:.0f}" if tpe else "P/E n/a"
    if fpe:
        pe_txt += f" → fwd {fpe:.0f}"
    bits = [pe_txt]
    if upside is not None:
        bits.append(f"analyst target {upside:+.0f}% ({fields['recommendationKey'] or 'n/a'}, "
                    f"{fields['numberOfAnalystOpinions'] or 0} analysts)")
    s = " · ".join(bits)
    s += (". Red flags: " + "; ".join(red) if red else ". No red flags") + ("; " + "; ".join(warn) if warn else "") + "."
    return {"score": round(_clip(score), 2) + 0.0, "summary": s, "flags": {"red_flags": bool(red)}, "red_flags": len(red),
            "red_flag_list": red, "warnings": warn, "fields": fields, "pe_compression": compression,
            "target_upside": upside}


# ---------- run everything ----------
def run_checks(ticker: str, params: dict | None = None) -> dict:
    """Every check for one ticker. Cached for 30 minutes per (ticker, params)."""
    return _run_checks_cached(ticker, json.dumps(merged_params(params), sort_keys=True))


@data.ttl_cache(1800)
def _run_checks_cached(ticker: str, params_json: str) -> dict:
    p = json.loads(params_json)
    daily = data.get_history(ticker, "5y")
    if len(daily) < 60:
        return {"ticker": ticker, "error": "not enough price history"}
    wk = weekly(daily)
    info = data.get_info(ticker)
    bench = benchmarks(p["relative"]["benchmark"])

    checks = {"gaps": check_gaps(daily, wk, p["gaps"]), "ema200": check_ema200(daily, p["ema200"]),
              "crossovers": check_crossovers(daily, p["crossovers"])}
    checks["rsi"] = check_rsi(daily, p["rsi"], checks["ema200"]["flags"].get("below_ema200", False))
    checks["support"] = check_support(daily, wk, p["support"])
    checks["fundamentals"] = check_fundamentals(info, p["fundamentals"])
    checks["relative"] = check_relative(daily, bench, p["relative"], checks["fundamentals"].get("red_flags"))
    return {"ticker": ticker, "name": info.get("longName") or info.get("shortName") or ticker,
            "type": info.get("quoteType"), "price": float(daily["Close"].iloc[-1]), "as_of": daily.index[-1],
            "checks": checks}


def composite(result: dict, weights: dict[str, float]) -> dict:
    """Weighted average of the enabled checks' scores -> {score (-100..100), verdict, reasons}.
    `weights` maps check key -> weight; leave a check out (or weight 0) to switch it off."""
    used = [(k, w, result["checks"][k]) for k, w in weights.items()
            if w and k in result.get("checks", {}) and result["checks"][k].get("score") is not None]
    if not used:
        return {"score": 0.0, "verdict": "Neutral", "reasons": []}
    score = 100 * sum(w * c["score"] for _, w, c in used) / sum(w for _, w, _ in used)
    verdict = next((v for cut, v in VERDICTS if score >= cut), "Strong sell")
    ranked = sorted(used, key=lambda x: abs(x[1] * x[2]["score"]), reverse=True)
    reasons = [c["summary"] for _, w, c in ranked if c["score"] * score > 0][:2]   # reasons on the winning side
    return {"score": score, "verdict": verdict, "reasons": reasons}


def scan(tickers: list[str], params: dict | None = None, workers: int = 8, on_done=None) -> list[dict]:
    """run_checks over many tickers in parallel. on_done(i, n) is called as each finishes."""
    p = merged_params(params)
    benchmarks(p["relative"]["benchmark"])           # warm once, before the threads all ask for it
    results = []
    with ThreadPoolExecutor(workers) as ex:
        futures = [ex.submit(_safe_run, t, p) for t in tickers]
        for i, f in enumerate(futures, 1):
            results.append(f.result())
            if on_done:
                on_done(i, len(tickers))
    return results


def _safe_run(ticker, p):
    try:
        return run_checks(ticker, p)
    except Exception as e:                      # one bad ticker shouldn't sink the scan
        return {"ticker": ticker, "error": str(e)}
