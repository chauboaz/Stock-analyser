"""UI helpers shared by the pages."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from streamlit import config

from analyser import data

HOME, ANALYSE, PORTFOLIO, SCREENER = ("views/home.py", "views/analyse.py",
                                      "views/portfolio.py", "views/screener.py")
TYPE_ICONS = {"Stock": "🏢", "ETF": "🧺", "Crypto": "🪙", "Fund": "💼", "Index": "📊",
              "Future": "📦", "Currency": "💱", "Gold": "🥇", "Silver": "🥈"}


def primary_color() -> str:
    return config.get_option("theme.primaryColor") or "#2563eb"


TILE = 200          # metric tile width (px): tiles wrap onto new rows instead of truncating numbers
SMALL_TILE = 150


def tiles(**kwargs):
    """Row container whose children wrap on narrow screens."""
    return st.container(horizontal=True, gap="small", **kwargs)


def hbar(series: pd.Series, fmt: str, height_per_row: int = 34, x_range=None, colors=None) -> go.Figure:
    """Horizontal bars, largest on top, value labelled at the bar end. Single hue unless `colors` given."""
    s = series.sort_values()
    fig = go.Figure(go.Bar(
        x=s.values, y=s.index, orientation="h",
        marker=dict(color=colors(s) if colors else primary_color(), cornerradius=4),
        text=[fmt.format(v) for v in s.values], textposition="outside", cliponaxis=False,
        hovertemplate="%{y}: " + fmt.replace("{:", "%{x:") + "<extra></extra>"))
    fig.update_layout(height=max(140, height_per_row * len(s) + 40), margin=dict(l=10, r=60, t=10, b=10),
                      xaxis=dict(visible=False, range=x_range), yaxis=dict(showgrid=False), bargap=0.35)
    return fig


def go_analyse(symbol: str, query_key: str | None = None):
    """Button callback: open the Analyse page on `symbol`."""
    st.session_state.ticker = symbol
    st.session_state._nav = ANALYSE
    if query_key:
        st.session_state[query_key] = ""


def go_add(result: dict, query_key: str | None = None):
    """Button callback: open the Portfolio 'Add position' form pre-filled with `result`."""
    st.session_state.add_sel = result
    st.session_state.add_kind_request = "Stock / ETF / Crypto"
    st.session_state.pf_view_request = "➕ Add position"
    st.session_state._nav = PORTFOLIO
    if query_key:
        st.session_state[query_key] = ""


def search_box(key: str, placeholder: str = "Search by company name or ticker — e.g. Fisher Paykel, AAPL, "
                                            "Vanguard S&P 500, bitcoin") -> None:
    """Search input plus result rows, each with Analyse and Add-to-portfolio buttons."""
    q = st.text_input("Search", key=key, placeholder=placeholder, label_visibility="collapsed",
                      icon=":material/search:")
    if not q:
        return
    with st.spinner("Searching..."):
        results = data.search(q)
    if not results:
        st.info(f"No matches for **{q}**. Try the company name or the full ticker (e.g. FPH.NZ, BHP.AX).")
        return
    with st.container(border=True):
        for i, r in enumerate(results):
            c1, c2, c3, c4 = st.columns([5, 3, 1.4, 1.6], vertical_alignment="center")
            c1.markdown(f"**{r['symbol']}** &nbsp; {r['name']}")
            c2.caption(f"{TYPE_ICONS.get(r['type'], '•')} {r['type']} · {r['exchange']}")
            c3.button("Analyse", key=f"{key}_a_{i}", on_click=go_analyse, args=(r["symbol"], key),
                      width="stretch")
            c4.button("＋ Portfolio", key=f"{key}_p_{i}", on_click=go_add, args=(r, key),
                      type="primary", width="stretch")
