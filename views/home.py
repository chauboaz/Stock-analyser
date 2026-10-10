"""Home: search, portfolio snapshot and market overview."""
from concurrent.futures import ThreadPoolExecutor

import streamlit as st

from analyser import data
from analyser import portfolio as pfm
from views.common import PORTFOLIO, TILE, search_box, tiles

MARKETS = [("S&P 500", "^GSPC"), ("Nasdaq", "^IXIC"), ("NZX 50", "^NZ50"), ("ASX 200", "^AXJO"),
           ("Bitcoin", "BTC-USD"), ("Ethereum", "ETH-USD"), ("Gold (USD/oz)", "GC=F"), ("NZD / USD", "NZDUSD=X")]

st.title("📈 Stock Analyser")
st.caption("Search any stock, ETF or crypto — US, NZX, ASX and more — then analyse it or add it to your portfolio.")
search_box("home_q")

# ---------- portfolio snapshot ----------
st.subheader("Your portfolio")
pf = pfm.load()
if not pf["holdings"]:
    with st.container(border=True):
        st.write("You haven't added any holdings yet. Track your stocks, ETFs, crypto and physical gold "
                 "in one place.")
        st.page_link(PORTFOLIO, label="Set up your portfolio", icon="💼")
else:
    base = pf["base_currency"]
    with st.spinner("Valuing portfolio..."):
        vals = pfm.value(pf["holdings"], base)
        hist = pfm.history(pf["holdings"], base)
    total, cost = vals["Value"].sum(), vals["Cost"].sum()
    day = vals["Day change"].sum()
    spark = hist["Value"].iloc[-90:].round(2).tolist() if not hist.empty else None
    with tiles():
        st.metric("Total value", pfm.money(total, base, None), f"{pfm.money(day, base, None)} today",
                  chart_data=spark, chart_type="area", border=True, width=TILE)
        st.metric("Total return", pfm.money(total - cost, base, None),
                  f"{(total / cost - 1) * 100:+.2f}%" if cost else None, border=True, width=TILE)
        st.metric("Holdings", len(vals), f"{vals['Type'].nunique()} asset types", delta_color="off", delta_arrow="off",
                  border=True, width=TILE)
    st.page_link(PORTFOLIO, label="Open portfolio", icon="💼")

# ---------- market overview ----------
st.subheader("Markets")
with st.spinner("Loading markets..."):
    with ThreadPoolExecutor(8) as ex:
        quotes = list(ex.map(lambda m: data.get_quote(m[1]), MARKETS))
with tiles():
    for (label, sym), q in zip(MARKETS, quotes):
        if q:
            fmt = f"{q['price']:,.4f}" if sym.endswith("=X") else f"{q['price']:,.2f}"
            st.metric(label, fmt, f"{q['change_pct']:+.2f}%", chart_data=q["spark"], border=True, width=TILE)
        else:
            st.metric(label, "—", border=True, width=TILE)
st.caption("Prices from Yahoo Finance, may be delayed. Sparklines show the last month. Not financial advice.")
