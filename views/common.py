"""UI helpers shared by the pages."""
from datetime import datetime, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from streamlit import config

from analyser import data

HOME, ANALYSE, PORTFOLIO, SIGNALS, NEWS = ("views/home.py", "views/analyse.py", "views/portfolio.py",
                                           "views/signals.py", "views/news.py")


def primary_color() -> str:
    return config.get_option("theme.primaryColor") or "#2563eb"


TILE = 200          # metric tile width (px): tiles wrap onto new rows instead of truncating numbers
SMALL_TILE = 150


def when(ts, short: bool = False) -> str:
    """A timestamp in the viewer's local time, e.g. '4:00 pm today' / '4:00 pm Fri 10 Oct'.
    short=True gives '4:00 pm' for today and 'Fri 4:00 pm' within the last week (fits in tiles)."""
    now = datetime.now().astimezone()
    t = pd.Timestamp(ts).tz_convert(now.tzinfo)
    clock = t.strftime("%I:%M %p").lstrip("0").lower()
    if short:
        if t.date() == now.date():
            return clock
        return f"{t:%a} {clock}" if (now - t).days < 6 else f"{t.day} {t:%b}"
    if t.date() == now.date():
        return f"{clock} today"
    if t.date() == (now - timedelta(days=1)).date():
        return f"{clock} yesterday"
    return f"{clock} {t:%a} {t.day} {t:%b}"


def status(q: dict, compact: bool = False) -> str:
    """Markdown badge: live (market open) or closed, plus the exchange's data delay unless compact."""
    if q["live"]:
        return ":green[● Live]" + (f" :gray[({q['delay']} min delay)]" if q["delay"] and not compact else "")
    return ":gray[● Closed]"


def ago(ts) -> str:
    """'5 min ago' / '3 h ago' / '2 days ago' / '12 Sep'."""
    secs = (pd.Timestamp.now(tz="UTC") - pd.Timestamp(ts)).total_seconds()
    if secs < 3600:
        return f"{max(1, int(secs // 60))} min ago"
    if secs < 86400:
        return f"{int(secs // 3600)} h ago"
    if secs < 7 * 86400:
        days = int(secs // 86400)
        return f"{days} day{'s' if days > 1 else ''} ago"
    return f"{pd.Timestamp(ts).day} {pd.Timestamp(ts):%b}"


def news_list(items: list[dict], limit: int = 30, highlight: set[str] | None = None) -> None:
    """Headline cards: thumbnail, linked title, publisher, age and the tickers it mentions."""
    if not items:
        st.info("No recent headlines found.")
        return
    for it in items[:limit]:
        with st.container(border=True):
            c1, c2 = st.columns([1, 6], vertical_alignment="center")
            if it.get("thumbnail"):
                c1.image(it["thumbnail"], width=90)
            title = it["title"].replace("$", r"\$")        # "$100 ... $7B" would otherwise render as maths
            c2.markdown(f"**[{title}]({it['url']})**")
            tickers = sorted(set(it.get("tickers", [])) | set(it.get("abouts", [])))
            tags = " ".join(f":blue-badge[{t}]" if highlight and t in highlight else f":gray-badge[{t}]"
                            for t in tickers[:6])
            c2.caption(f"{it['publisher']} · {ago(it['published'])}")
            if tags:
                c2.markdown(tags)


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
    st.session_state.pf_view_request = "Add position"
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
            c2.caption(f"{r['type']} · {r['exchange']}")
            c3.button("Analyse", key=f"{key}_a_{i}", on_click=go_analyse, args=(r["symbol"], key),
                      width="stretch")
            c4.button("Add", icon=":material/add:", key=f"{key}_p_{i}", on_click=go_add, args=(r, key),
                      type="primary", width="stretch")
