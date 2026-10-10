"""Background cache warm-up, so pages are ready before you open them.

Started once when the server starts (see app.py). Every 25 minutes it loads what the pages need
most: your portfolio's prices, the home page market tiles, and a Signals scan of the default lists
with your saved indicator settings. Only expired data is re-downloaded.
"""
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from . import data, settings
from . import portfolio as pfm
from . import signals as sg
from .universes import DEFAULT_SCAN, MARKETS, tickers_for

INTERVAL = 25 * 60


def warm_once() -> None:
    pf = pfm.load()
    if pf["holdings"]:
        pfm.value(pf["holdings"], pf["base_currency"])
        pfm.history(pf["holdings"], pf["base_currency"])
    with ThreadPoolExecutor(8) as ex:
        list(ex.map(lambda m: data.get_quote(m[1]), MARKETS))
    holdings = sorted({h["ticker"] for h in pf["holdings"] if h["kind"] == "security"})
    params = (settings.get("signals", {}) or {}).get("params")
    sg.scan(tickers_for(DEFAULT_SCAN, holdings), params)


def _loop() -> None:
    while True:
        try:
            warm_once()
        except Exception:
            pass                     # network hiccup: try again next round
        time.sleep(INTERVAL)


def start() -> None:
    threading.Thread(target=_loop, name="cache-warmup", daemon=True).start()
