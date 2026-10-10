"""Rate a portfolio's diversification (0-100) with a breakdown and plain-English suggestions.

Six factors, each scored 0-100 and weighted:
  holdings concentration (effective number of positions, ETFs counted as many positions),
  sector spread, geographic spread, asset-class mix, currency spread, and how correlated
  the holdings' daily returns are.
Funds are "looked through" where Yahoo publishes sector weights; otherwise their makeup is
estimated from the fund name and category.
"""
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd

from . import data

WEIGHTS = {"Holdings": 0.30, "Sectors": 0.20, "Geography": 0.20, "Asset classes": 0.10,
           "Currencies": 0.10, "Correlation": 0.10}
ETF_BREADTH = 30          # a broad fund counts as this many equal positions
NICHE_ETF_BREADTH = 10    # sector/theme funds

# Yahoo fund sector keys -> stock sector names
FUND_SECTORS = {"realestate": "Real Estate", "consumer_cyclical": "Consumer Cyclical",
                "basic_materials": "Basic Materials", "consumer_defensive": "Consumer Defensive",
                "technology": "Technology", "communication_services": "Communication Services",
                "financial_services": "Financial Services", "utilities": "Utilities",
                "industrials": "Industrials", "energy": "Energy", "healthcare": "Healthcare"}
# rough sector mix of a broad global/US index, used when a fund publishes nothing
BROAD_MARKET_SECTORS = {"Technology": .28, "Financial Services": .14, "Healthcare": .11,
                        "Consumer Cyclical": .10, "Industrials": .10, "Communication Services": .08,
                        "Consumer Defensive": .06, "Energy": .04, "Basic Materials": .03,
                        "Utilities": .03, "Real Estate": .03}
# rough country mix of a global (all-world) index fund
GLOBAL_REGIONS = {"United States": .62, "Europe": .15, "Japan": .05, "Emerging markets": .11,
                  "Other developed": .07}

SECTOR_KEYWORDS = {"technology": "Technology", "tech": "Technology", "semiconductor": "Technology",
                   "health": "Healthcare", "property": "Real Estate", "reit": "Real Estate",
                   "real estate": "Real Estate", "energy": "Energy", "oil": "Energy",
                   "financial": "Financial Services", "bank": "Financial Services",
                   "infrastructure": "Utilities", "utilities": "Utilities", "consumer": "Consumer Cyclical",
                   "materials": "Basic Materials", "mining": "Basic Materials", "gold miners": "Basic Materials"}
REGION_KEYWORDS = [  # checked in order; first match wins
    (("total world", "all world", "all-world", "global", "world", "acwi", "international", "all country"),
     "Global"),
    (("emerging",), "Emerging markets"),
    (("europe", "euro"), "Europe"),
    (("japan",), "Japan"), (("china",), "China"), (("asia",), "Asia"),
    (("new zealand", " nz ", "nz top", "nzx", "nz 50", "nz mid"), "New Zealand"),
    (("australia", "asx"), "Australia"),
    (("s&p 500", "us 500", "nasdaq", "total stock market", "u.s.", " us ", "america", "dow"), "United States"),
]
CURRENCY_HOME = {"NZD": "New Zealand", "AUD": "Australia", "USD": "United States", "GBP": "United Kingdom",
                 "EUR": "Europe", "CAD": "Canada", "JPY": "Japan"}
BOND_WORDS = ("bond", "fixed income", "treasury", "aggregate", "credit", "cash", "money market")


def _is_fund(info: dict, name: str) -> bool:
    if info.get("quoteType") in ("ETF", "MUTUALFUND"):
        return True
    n = f" {name.lower()} "
    return not info.get("sector") and any(w in n for w in (" etf", " fund", " index", " trust", " portfolio"))


def profile(h: dict) -> dict:
    """Exposure profile of one holding: asset class, sector & region weights, breadth."""
    if h["kind"] == "metal":
        return {"class": "Precious metals", "sectors": {}, "regions": {}, "breadth": 1, "estimated": False}
    if h["asset_type"] == "Crypto":
        return {"class": "Crypto", "sectors": {}, "regions": {}, "breadth": 1, "estimated": False}
    info = data.get_info(h["ticker"])
    name = info.get("longName") or info.get("shortName") or h["name"]
    home = CURRENCY_HOME.get(h["currency"], "Other")

    if not _is_fund(info, name):
        sector = info.get("sector") or "Unknown"
        return {"class": "Shares", "sectors": {sector: 1.0},
                "regions": {info.get("country") or home: 1.0}, "breadth": 1, "estimated": False}

    text = f" {name} {info.get('category') or ''} ".lower()
    if any(w in text for w in BOND_WORDS):
        return {"class": "Bonds & cash", "sectors": {}, "regions": {}, "breadth": ETF_BREADTH, "estimated": True}

    estimated, breadth = False, ETF_BREADTH
    sectors = {}
    try:
        sw = data.get_fund_sectors(h["ticker"])
        sectors = {FUND_SECTORS.get(k, k.title()): v for k, v in sw.items() if v > 0}
    except Exception:
        pass
    if not sectors:
        estimated = True
        niche = next((s for k, s in SECTOR_KEYWORDS.items() if k in text), None)
        sectors, breadth = ({niche: 1.0}, NICHE_ETF_BREADTH) if niche else (BROAD_MARKET_SECTORS, ETF_BREADTH)

    region = next((r for words, r in REGION_KEYWORDS if any(w in text for w in words)), None)
    if region is None:
        region, estimated = home, True
    regions = GLOBAL_REGIONS if region == "Global" else {region: 1.0}
    return {"class": "Shares", "sectors": sectors, "regions": regions, "breadth": breadth, "estimated": estimated}


def _spread(weights: dict) -> float:
    """1 - Herfindahl index of normalised weights (0 = all in one bucket)."""
    w = np.array([v for v in weights.values() if v > 0], dtype=float)
    if w.sum() == 0:
        return 0.0
    w = w / w.sum()
    return float(1 - (w ** 2).sum())


def _clamp(x: float) -> float:
    return float(max(0.0, min(100.0, x)))


def _add(target: dict, mix: dict, weight: float):
    total = sum(mix.values()) or 1.0
    for k, v in mix.items():
        target[k] = target.get(k, 0.0) + weight * v / total


def correlation(tickers: list[str], weights: list[float]) -> tuple[float | None, pd.DataFrame]:
    """Value-weighted average pairwise correlation of daily returns over the last year."""
    uniq = list(dict.fromkeys(tickers))
    if len(uniq) < 2:
        return None, pd.DataFrame()
    closes = {}
    for t in uniq:
        df = data.get_history(t, "1y")
        if not df.empty:
            closes[t] = df["Close"]
    if len(closes) < 2:
        return None, pd.DataFrame()
    px = pd.DataFrame(closes)
    px = px[px.index.dayofweek < 5].ffill()        # align 24/7 assets (crypto) to trading days
    corr = px.pct_change().dropna(how="all").corr(min_periods=60)
    w = pd.Series(weights, index=tickers).groupby(level=0).sum().reindex(corr.index).fillna(0)
    num = den = 0.0
    for i, a in enumerate(corr.index):
        for b in corr.index[i + 1:]:
            c = corr.at[a, b]
            if pd.notna(c):
                num += w[a] * w[b] * c
                den += w[a] * w[b]
    return (num / den if den else None), corr


def analyse(holdings: list[dict], vals: pd.DataFrame) -> dict:
    """Score the portfolio. `vals` is portfolio.value() output (same order as holdings)."""
    live = [(h, v) for h, v in zip(holdings, vals["Value"]) if pd.notna(v) and v > 0]
    if not live:
        return {}
    total = sum(v for _, v in live)
    with ThreadPoolExecutor(8) as ex:
        profiles = list(ex.map(lambda hv: profile(hv[0]), live))

    classes, sectors, regions, currencies, bets = {}, {}, {}, {}, {}
    equity_w = 0.0
    for (h, v), p in zip(live, profiles):
        w = v / total
        classes[p["class"]] = classes.get(p["class"], 0) + w
        currencies[h["currency"]] = currencies.get(h["currency"], 0) + w
        label = h["name"] if h["kind"] == "metal" else h["ticker"]
        prev_w = bets.get(label, (0.0, 0))[0]           # several lots of the same ticker = one position
        bets[label] = (prev_w + w, p["breadth"])
        if p["class"] == "Shares":
            equity_w += w
            _add(sectors, p["sectors"], w)
            _add(regions, p["regions"], w)

    # effective number of positions: 1 / sum(w_i^2), with a fund split into `breadth` equal parts
    n_eff = 1 / sum(w ** 2 / b for w, b in bets.values())
    avg_corr, corr = correlation([h["ticker"] for h, _ in live], [v / total for _, v in live])

    scores = {
        "Holdings": _clamp(100 * np.log(max(n_eff, 1)) / np.log(25)),
        "Sectors": _clamp(_spread(sectors) / 0.80 * 100) if sectors else 0.0,
        "Geography": _clamp(_spread(regions) / 0.50 * 100) if regions else 0.0,
        "Asset classes": _clamp(_spread(classes) / 0.40 * 100 - max(0, classes.get("Crypto", 0) - 0.2) * 200),
        "Currencies": _clamp(_spread(currencies) / 0.50 * 100),
        "Correlation": _clamp((0.85 - avg_corr) / 0.60 * 100) if avg_corr is not None else None,
    }
    used = {k: WEIGHTS[k] for k, s in scores.items() if s is not None}
    overall = sum(scores[k] * w for k, w in used.items()) / sum(used.values())

    return {
        "score": overall, "grade": grade(overall), "scores": scores, "n_eff": n_eff,
        "n_positions": len(bets), "classes": classes,
        "sectors": {k: v / equity_w for k, v in sectors.items()} if equity_w else {},
        "regions": {k: v / equity_w for k, v in regions.items()} if equity_w else {},
        "currencies": currencies, "avg_corr": avg_corr, "corr": corr,
        "positions": {k: w for k, (w, _) in bets.items()},
        "estimated": [h["ticker"] for (h, _), p in zip(live, profiles) if p["estimated"]],
        "suggestions": suggestions(bets, classes, sectors, regions, currencies, equity_w, avg_corr, n_eff),
    }


def grade(score: float) -> str:
    for cutoff, g in ((85, "A"), (70, "B"), (55, "C"), (40, "D")):
        if score >= cutoff:
            return g
    return "F"


def suggestions(bets, classes, sectors, regions, currencies, equity_w, avg_corr, n_eff) -> list[tuple[str, str]]:
    """(level, message) pairs - level is 'warning', 'info' or 'success'."""
    out = []
    top_name, (top_w, top_b) = max(bets.items(), key=lambda kv: kv[1][0] / kv[1][1])
    if top_b == 1 and top_w > 0.25:
        out.append(("warning", f"**{top_name}** is {top_w:.0%} of your portfolio. Any single holding "
                               "above ~20–25% means one bad stretch for it can hurt the whole portfolio."))
    if n_eff < 8 and not any(b > 1 for _, b in bets.values()):
        n = round(n_eff)
        out.append(("warning", f"You effectively hold about {n} position{'s' if n != 1 else ''}. A broad index ETF "
                               "(e.g. a total-market or world fund) adds hundreds of companies in one buy."))
    if equity_w and sectors:
        s, w = max(sectors.items(), key=lambda kv: kv[1])
        if w / equity_w > 0.40:
            out.append(("warning", f"**{s}** makes up {w / equity_w:.0%} of your shares. Sector downturns "
                                   "hit companies together - consider other sectors."))
    if equity_w and regions:
        r, w = max(regions.items(), key=lambda kv: kv[1])
        if w / equity_w > 0.70:
            out.append(("warning", f"{w / equity_w:.0%} of your shares are in **{r}**. Adding other markets "
                                   "(e.g. a global ETF) reduces exposure to one economy."))
    crypto = classes.get("Crypto", 0)
    if crypto > 0.20:
        out.append(("warning", f"Crypto is {crypto:.0%} of the portfolio. It's very volatile and tends to "
                               "fall together, so it adds risk faster than it adds diversification."))
    if "Bonds & cash" not in classes and "Precious metals" not in classes and len(classes) == 1:
        out.append(("info", "Everything is in growth assets. Bonds, cash or gold usually fall less in "
                            "share-market crashes - worth considering depending on your timeframe."))
    if len(currencies) == 1:
        out.append(("info", f"All holdings are priced in {next(iter(currencies))}. That's fine for spending "
                            "in that currency, but it means no protection if it weakens."))
    if avg_corr is not None and avg_corr > 0.6:
        out.append(("warning", f"Your holdings move together a lot (average correlation {avg_corr:.2f}). "
                               "Assets that behave differently cushion each other in bad periods."))
    if not out:
        out.append(("success", "Nicely diversified across positions, sectors and regions. Keep an eye on "
                               "position sizes as winners grow."))
    return out
