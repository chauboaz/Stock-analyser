"""Home: search, portfolio snapshot and market overview."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import streamlit as st

from analyser import data
from analyser import portfolio as pfm
from analyser.universes import MARKETS
from views.common import PORTFOLIO, TILE, search_box, status, tiles, when


st.title("Stock Analyser")
st.caption("Search any stock, ETF or crypto, then analyse it or add it to your portfolio.")
search_box("home_q")


@st.fragment(run_every="60s")
def portfolio_snapshot():
    st.subheader("Your portfolio")
    pf = pfm.load()
    if not pf["holdings"]:
        with st.container(border=True):
            st.write("You haven't added any holdings yet. Track your stocks, ETFs, crypto and physical gold "
                     "in one place.")
            st.page_link(PORTFOLIO, label="Set up your portfolio", icon=":material/arrow_forward:")
        return
    base = pf["base_currency"]
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
        st.metric("Holdings", len(vals), f"{vals['Type'].nunique()} asset types", delta_color="off",
                  delta_arrow="off", border=True, width=TILE)
    live = int(vals["Live"].sum())
    st.caption(f"{live} of {len(vals)} holdings' markets are open now · prices as of "
               f"{when(datetime.now().astimezone())}")
    st.page_link(PORTFOLIO, label="Open portfolio", icon=":material/arrow_forward:")


@st.fragment(run_every="60s")
def markets():
    st.subheader("Markets")
    with ThreadPoolExecutor(8) as ex:
        quotes = list(ex.map(lambda m: data.get_quote(m[1]), MARKETS))
    with tiles():
        for (label, sym), q in zip(MARKETS, quotes):
            if q:
                fmt = f"{q['price']:,.4f}" if sym.endswith("=X") else f"{q['price']:,.2f}"
                st.metric(f"{label} &nbsp; {status(q, compact=True)}", fmt, f"{q['change_pct']:+.2f}%",
                          delta_description=when(q["as_of"], short=True), chart_data=q["spark"],
                          border=True, width=TILE)
            else:
                st.metric(label, "—", border=True, width=TILE)
    st.caption(f"Updated {when(datetime.now().astimezone())} (your time) and every minute after. "
               "**Live** = the market is trading now; some exchanges' prices are delayed 10–20 min. "
               "**Closed** = last trade shown with its time. Sparklines show the last month.")


portfolio_snapshot()
markets()
