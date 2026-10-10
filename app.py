"""Stock Analyser - Streamlit dashboard.

Run with:  .venv\\Scripts\\streamlit run app.py   (or double-click run.bat)
"""
import streamlit as st

from analyser import themes, warmup
from views.common import ANALYSE, HOME, NEWS, PORTFOLIO, SIGNALS

st.set_page_config(page_title="Stock Analyser", page_icon=":material/monitoring:", layout="wide")


@st.cache_resource
def start_warmup():
    """Once per server: keep data caches warm in the background so pages load instantly."""
    warmup.start()
    return True


start_warmup()
# less empty space above each page's title
st.html("<style>[data-testid='stMainBlockContainer']{padding-top:2.5rem}</style>")

pg = st.navigation([
    st.Page(HOME, title="Home", icon=":material/home:", default=True),
    st.Page(ANALYSE, title="Analyse", icon=":material/candlestick_chart:"),
    st.Page(PORTFOLIO, title="Portfolio", icon=":material/account_balance_wallet:"),
    st.Page(SIGNALS, title="Signals", icon=":material/radar:"),
    st.Page(NEWS, title="News", icon=":material/newspaper:"),
])

with st.sidebar:
    themes.picker()
    st.caption("Data: Yahoo Finance (may be delayed). Not financial advice.")

# buttons on one page can ask to open another (see views.common.go_analyse / go_add)
if nav := st.session_state.pop("_nav", None):
    st.switch_page(nav)

pg.run()
