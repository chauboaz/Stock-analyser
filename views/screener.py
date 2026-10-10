"""Scan a watchlist and filter by technical criteria."""
import streamlit as st

from analyser import screener
from views.common import go_analyse


@st.cache_data(ttl=900, show_spinner=False)
def scan(tickers):
    return screener.scan(list(tickers))


st.title("🔎 Screener")
wl_name = st.selectbox("Watchlist preset", list(screener.DEFAULT_WATCHLISTS) + ["Custom"])
default = screener.DEFAULT_WATCHLISTS.get(wl_name, "")
tickers_txt = st.text_area("Tickers (comma-separated, full Yahoo symbols)", default, height=80)
tickers = tuple(t.strip().upper() for t in tickers_txt.replace("\n", ",").split(",") if t.strip())

f1, f2, f3, f4 = st.columns(4)
rsi_range = f1.slider("RSI range", 0, 100, (0, 100))
above200 = f2.selectbox("vs SMA200", ["Any", "Above", "Below"])
macd_f = f3.selectbox("MACD", ["Any", "Bullish", "Bearish"])
min_vol = f4.number_input("Min volume ratio", 0.0, 10.0, 0.0, 0.1)

if st.button("Run scan", type="primary") or "scan_done" in st.session_state:
    st.session_state["scan_done"] = True
    with st.spinner(f"Scanning {len(tickers)} tickers..."):
        res = scan(tickers)
    if res.empty:
        st.warning("No data returned.")
    else:
        f = res[res["RSI"].between(*rsi_range)]
        if above200 != "Any":
            f = f[(f["vs SMA200 %"] > 0) == (above200 == "Above")]
        if macd_f != "Any":
            f = f[f["MACD bullish"] == (macd_f == "Bullish")]
        f = f[f["Vol ratio"].fillna(0) >= min_vol].reset_index(drop=True)
        st.write(f"**{len(f)}** of {len(res)} match · select a row to analyse it")
        num_cols = [c for c in f.columns if f[c].dtype.kind == "f"]
        event = st.dataframe(
            f.style.format({c: "{:.2f}" for c in num_cols})
             .background_gradient(subset=["1D %", "1M %", "3M %"], cmap="RdYlGn", vmin=-15, vmax=15)
             .background_gradient(subset=["RSI"], cmap="RdYlGn_r", vmin=20, vmax=80),
            hide_index=True, width="stretch", height=min(600, 40 + 35 * len(f)),
            on_select="rerun", selection_mode="single-row", key="scr_table")
        if event.selection.rows:
            sym = f.iloc[event.selection.rows[0]]["Ticker"]
            st.button(f"📊 Analyse {sym}", type="primary", on_click=go_analyse, args=(sym,))
        missing = set(tickers) - set(res["Ticker"])
        if missing:
            st.caption("No data for: " + ", ".join(sorted(missing)))
