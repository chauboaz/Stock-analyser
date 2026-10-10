"""Financial news headlines from Yahoo Finance (via its search endpoint)."""
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import yfinance as yf

from .data import get_info, ttl_cache


@ttl_cache(900)
def _search_news(query: str, count: int) -> list[dict]:
    try:
        raw = yf.Search(query, news_count=count, max_results=1, raise_errors=False).news or []
    except Exception:
        return []
    out = []
    for n in raw:
        if not n.get("title") or not n.get("link"):
            continue
        thumbs = (n.get("thumbnail") or {}).get("resolutions") or []
        small = next((t["url"] for t in thumbs if t.get("tag") == "140x140"), thumbs[0]["url"] if thumbs else None)
        out.append({"id": n.get("uuid") or n["link"], "title": n["title"], "publisher": n.get("publisher", ""),
                    "url": n["link"], "thumbnail": small,
                    "published": pd.Timestamp(n.get("providerPublishTime", 0), unit="s", tz="UTC"),
                    "tickers": [t for t in n.get("relatedTickers") or [] if not t.endswith(".PVT")]})
    return out


def ticker_news(ticker: str, count: int = 10) -> list[dict]:
    """Headlines about one ticker. Falls back to the company name for small/non-US listings."""
    items = _search_news(ticker, count)
    if len(items) < 3:
        name = get_info(ticker).get("shortName")
        if name:
            items += _search_news(name, count)
    return dedupe([{**it, "about": ticker} for it in items])     # copies: don't mutate cached items


def market_news(count: int = 15) -> list[dict]:
    items = _search_news("stock market", count) + _search_news("economy markets", count)
    return dedupe(items)


def many(tickers: list[str], per_ticker: int = 6) -> list[dict]:
    """Merged, de-duplicated, newest-first headlines for several tickers. Each item gets 'about' = the
    tickers it was found for."""
    with ThreadPoolExecutor(8) as ex:
        lists = list(ex.map(lambda t: [{**it, "about": t} for it in ticker_news(t, per_ticker)], tickers))
    merged: dict[str, dict] = {}
    for items in lists:
        for it in items:
            if it["id"] in merged:
                merged[it["id"]]["abouts"].add(it["about"])
            else:
                merged[it["id"]] = {**it, "abouts": {it["about"]}}
    return sorted(merged.values(), key=lambda it: it["published"], reverse=True)


def dedupe(items: list[dict]) -> list[dict]:
    seen, out = set(), []
    for it in sorted(items, key=lambda it: it["published"], reverse=True):
        if it["id"] not in seen:
            seen.add(it["id"])
            out.append(it)
    return out
