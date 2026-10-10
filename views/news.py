"""News: headlines for your holdings, today's strongest signals, the market, or any search."""
import streamlit as st

from analyser import journal, news
from analyser import portfolio as pfm
from views.common import news_list

st.title("News")
st.caption("Latest headlines from Yahoo Finance. Click a headline to read the full article.")

holdings = sorted({h["ticker"] for h in pfm.load()["holdings"] if h["kind"] == "security"})
log = journal.load()
latest_day = max((e["date"] for e in log), default=None)
flagged = [e for e in log if e["date"] == latest_day]
signal_tickers = list(dict.fromkeys(e["ticker"] for e in sorted(flagged, key=lambda e: -abs(e["score"]))))[:10]

sources = ["My holdings", "Signal stocks", "Market", "Search"]
source = st.segmented_control("Show news for", sources, default=sources[0] if holdings else "Market",
                              key="news_source", required=True, label_visibility="collapsed")

if source == "My holdings":
    if not holdings:
        st.info("Add holdings on the Portfolio page to see news about them.")
        st.stop()
    only = st.pills("Filter", holdings, selection_mode="multi", key="news_filter")
    picks = only or holdings
    with st.spinner("Fetching headlines..."):
        items = news.many(picks)
    news_list(items, highlight=set(picks))
elif source == "Signal stocks":
    if not signal_tickers:
        st.info("Open the Signals page first - its strongest buys and sells show up here.")
        st.stop()
    sides = {e["ticker"]: e["side"] for e in flagged}
    st.caption(f"The strongest buy and sell signals from {latest_day}: "
               + ", ".join(f"{t} ({sides[t]})" for t in signal_tickers))
    with st.spinner("Fetching headlines..."):
        items = news.many(signal_tickers, per_ticker=4)
    news_list(items, highlight=set(signal_tickers))
elif source == "Market":
    with st.spinner("Fetching headlines..."):
        news_list(news.market_news())
else:
    q = st.text_input("Search news", placeholder="Ticker or company, e.g. NVDA, Fisher Paykel, gold price",
                      key="news_q", icon=":material/search:", label_visibility="collapsed")
    if q:
        with st.spinner("Searching..."):
            news_list(news.ticker_news(q.strip(), count=20))
