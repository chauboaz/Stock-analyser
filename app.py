"""Stock Analyser - Streamlit dashboard.

Run with:  .venv\\Scripts\\streamlit run app.py   (or double-click run.bat)
"""
import streamlit as st

from analyser import themes
from views.common import ANALYSE, HOME, PORTFOLIO, SCREENER

st.set_page_config(page_title="Stock Analyser", page_icon="📈", layout="wide")

pg = st.navigation([
    st.Page(HOME, title="Home", icon="🏠", default=True),
    st.Page(ANALYSE, title="Analyse", icon="📊"),
    st.Page(PORTFOLIO, title="Portfolio", icon="💼"),
    st.Page(SCREENER, title="Screener", icon="🔎"),
])

with st.sidebar:
    themes.picker()
    st.caption("Data: Yahoo Finance (may be delayed). Not financial advice.")

# buttons on one page can ask to open another (see views.common.go_analyse / go_add)
if nav := st.session_state.pop("_nav", None):
    st.switch_page(nav)

pg.run()
