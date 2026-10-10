"""Analyse one ticker: chart & indicators, backtest, fundamentals."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from analyser import backtest as bt
from analyser import data, fundamentals, indicators
from analyser import news
from analyser import signals as sg
from views.common import SIGNALS, SMALL_TILE, TILE, go_add, news_list, search_box, status, tiles, when
from views.signals_ui import check_cards, effective_weights, load_config, signal_chart

ticker = st.session_state.setdefault("ticker", "AAPL")

search_box("analyse_q", placeholder="Search another stock, ETF or crypto...")

meta = data.get_meta(ticker)
quote = data.get_quote(ticker)
st.title(meta["name"])
st.caption(f"**{ticker}** · {meta['type']} · {meta['exchange']} · "
           f"{meta['currency']}")
with tiles(vertical_alignment="center"):
    if quote:
        st.metric(f"Last price &nbsp; {status(quote)}", f"{quote['price']:,.2f} {meta['currency']}",
                  f"{quote['change_pct']:+.2f}%", delta_description=f"as of {when(quote['as_of'])}",
                  width="content")
    st.button("Add to portfolio", icon=":material/add:", type="primary", on_click=go_add,
              args=({"symbol": ticker, "name": meta["name"], "type": meta["type"], "exchange": meta["exchange"]},))

period = st.segmented_control("History", ["6mo", "1y", "2y", "5y", "10y", "max"], default="2y",
                              key="an_period") or "2y"
ppy = 365 if meta["type"] == "Crypto" else 252

tab_chart, tab_sig, tab_news, tab_bt, tab_fund = st.tabs(["Chart & indicators", "Signals", "News", "Backtest",
                                                         "Fundamentals"])

# ---------- Chart & Indicators ----------
with tab_chart:
    df = data.get_history(ticker, period)
    if df.empty:
        st.error(f"No price data for **{ticker}**.")
    else:
        d = indicators.add_all(df)
        last, prev = d.iloc[-1], d.iloc[-2]
        with tiles():
            st.metric("Last close", f"{last['Close']:,.2f}", f"{(last['Close'] / prev['Close'] - 1) * 100:+.2f}%",
                      width=SMALL_TILE)
            st.metric("RSI(14)", f"{last['RSI']:.1f}", width=SMALL_TILE)
            st.metric("Period high", f"{d['High'].max():,.2f}", width=SMALL_TILE)
            st.metric("Period low", f"{d['Low'].min():,.2f}", width=SMALL_TILE)
            st.metric("Period return", f"{(last['Close'] / d['Close'].iloc[0] - 1) * 100:+.1f}%", width=SMALL_TILE)

        o1, o2 = st.columns(2)
        opts = o1.multiselect("Overlays", ["SMA20", "SMA50", "SMA200", "EMA12", "EMA26", "Bollinger Bands"],
                              default=["SMA50", "SMA200"])
        lower = o2.multiselect("Lower panels", ["Volume", "RSI", "MACD"], default=["Volume", "RSI", "MACD"])

        rows = 1 + len(lower)
        heights = [0.55] + [0.45 / len(lower)] * len(lower) if lower else [1]
        fig = make_subplots(rows=rows, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=heights)
        fig.add_trace(go.Candlestick(x=d.index, open=d["Open"], high=d["High"], low=d["Low"], close=d["Close"],
                                     name="Price"), 1, 1)
        colors = {"SMA20": "#f2a900", "SMA50": "#2e86de", "SMA200": "#c0392b", "EMA12": "#8e44ad", "EMA26": "#16a085"}
        for o in opts:
            if o == "Bollinger Bands":
                fig.add_trace(go.Scatter(x=d.index, y=d["BB_upper"], line=dict(width=1, color="gray"),
                                         name="BB upper"), 1, 1)
                fig.add_trace(go.Scatter(x=d.index, y=d["BB_lower"], line=dict(width=1, color="gray"),
                                         fill="tonexty", fillcolor="rgba(128,128,128,0.1)", name="BB lower"), 1, 1)
            else:
                fig.add_trace(go.Scatter(x=d.index, y=d[o], line=dict(width=1.5, color=colors[o]), name=o), 1, 1)

        for i, panel in enumerate(lower, start=2):
            if panel == "Volume":
                vcol = ["#26a69a" if c >= o else "#ef5350" for c, o in zip(d["Close"], d["Open"])]
                fig.add_trace(go.Bar(x=d.index, y=d["Volume"], marker_color=vcol, name="Volume"), i, 1)
            elif panel == "RSI":
                fig.add_trace(go.Scatter(x=d.index, y=d["RSI"], line=dict(color="#8e44ad"), name="RSI"), i, 1)
                for lvl in (30, 70):
                    fig.add_hline(y=lvl, line_dash="dot", line_color="gray", row=i, col=1)
                fig.update_yaxes(range=[0, 100], row=i, col=1)
            elif panel == "MACD":
                hcol = ["#26a69a" if h >= 0 else "#ef5350" for h in d["Hist"]]
                fig.add_trace(go.Bar(x=d.index, y=d["Hist"], marker_color=hcol, name="MACD hist"), i, 1)
                fig.add_trace(go.Scatter(x=d.index, y=d["MACD"], line=dict(color="#2e86de"), name="MACD"), i, 1)
                fig.add_trace(go.Scatter(x=d.index, y=d["Signal"], line=dict(color="#f2a900"), name="Signal"), i, 1)
            fig.update_yaxes(title_text=panel, row=i, col=1)

        if ppy == 252:   # hide weekends for exchange-traded assets
            fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])])
        fig.update_layout(height=750, xaxis_rangeslider_visible=False, showlegend=True,
                          legend=dict(orientation="h", y=1.02), margin=dict(l=10, r=10, t=30, b=10))
        st.plotly_chart(fig, width="stretch")

        st.subheader("Signal summary")
        st.dataframe(pd.DataFrame(indicators.signal_summary(d), columns=["Indicator", "Reading", "Bias"]),
                     hide_index=True, width="stretch")

# ---------- Signals ----------
with tab_sig:
    cfg = load_config()
    with st.spinner("Running signal checks..."):
        res = sg.run_checks(ticker, cfg["params"])
    if "error" in res:
        st.info(f"Signals unavailable for {ticker}: {res['error']}.")
    else:
        comp = sg.composite(res, effective_weights(cfg))
        with tiles(vertical_alignment="center"):
            st.metric("Signal score", f"{comp['score']:+.0f}", help="−100 strong sell … +100 strong buy",
                      border=True, width=TILE)
            st.metric("Verdict", comp["verdict"], border=True, width=TILE)
        st.caption("Uses the indicator switches, weights and settings from the Signals page.")
        st.page_link(SIGNALS, label="Change indicators", icon=":material/tune:")
        st.plotly_chart(signal_chart(data.get_history(ticker, "5y"), res), width="stretch")
        st.caption("Weekly candles · orange = EMA200 · green / red bands = unfilled gap-up / gap-down zones · "
                   "grey bands = strongest support zones (×touches).")
        check_cards(res, cfg)
        gaps = res["checks"]["gaps"].get("gaps")
        if gaps is not None and not gaps.empty:
            with st.expander(f"All {len(gaps)} gaps found"):
                st.dataframe(gaps.sort_values("date", ascending=False), hide_index=True, width="stretch",
                             column_config={"size_pct": st.column_config.NumberColumn("size %", format="%.1f")})
        st.caption("Rule-based signals for research, not financial advice.")

# ---------- News ----------
with tab_news:
    with st.spinner("Fetching headlines..."):
        news_list(news.ticker_news(ticker, count=15), highlight={ticker})

# ---------- Backtest ----------
with tab_bt:
    st.caption(f"Long-only backtest on **{ticker}** over **{period}**. "
               "Signals act on the next bar's close (no look-ahead).")
    b1, b2, b3 = st.columns(3)
    strat_name = b1.selectbox("Strategy", list(bt.STRATEGIES))
    capital = b2.number_input("Starting capital", 100.0, 1e9, 10_000.0, step=1000.0)
    fee = b3.number_input("Fee per trade (%)", 0.0, 5.0, 0.1, step=0.05)

    p1, p2 = st.columns(2)
    if strat_name == "SMA crossover":
        params = dict(fast=p1.number_input("Fast SMA", 2, 400, 50), slow=p2.number_input("Slow SMA", 3, 400, 200))
    elif strat_name == "RSI mean reversion":
        params = dict(buy_below=p1.slider("Buy when RSI below", 5, 50, 30),
                      sell_above=p2.slider("Sell when RSI above", 50, 95, 70))
    elif strat_name == "Bollinger mean reversion":
        params = dict(n=p1.number_input("Period", 5, 100, 20), k=p2.number_input("Std devs", 0.5, 4.0, 2.0, 0.1))
    else:
        params = {}

    df = data.get_history(ticker, period)
    if df.empty:
        st.error(f"No data for **{ticker}**.")
    else:
        res = bt.run(df, bt.STRATEGIES[strat_name](df, **params), capital, fee, ppy)
        s, bh = res.stats["Strategy"], res.stats["Buy & Hold"]
        with tiles():
            st.metric("Total return", f"{s['Total return %']:.1f}%",
                      f"{s['Total return %'] - bh['Total return %']:+.1f}% vs B&H", width=SMALL_TILE)
            st.metric("CAGR", f"{s['CAGR %']:.1f}%", width=SMALL_TILE)
            st.metric("Sharpe", f"{s['Sharpe']:.2f}", width=SMALL_TILE)
            st.metric("Max drawdown", f"{s['Max drawdown %']:.1f}%", width=SMALL_TILE)
            st.metric("Win rate", "—" if pd.isna(s["Win rate %"]) else f"{s['Win rate %']:.0f}%", width=SMALL_TILE)
            st.metric("Trades", s["Trades"], width=SMALL_TILE)

        fig = go.Figure()
        for col, colr in (("Strategy", "#2e86de"), ("Buy & Hold", "gray")):
            fig.add_trace(go.Scatter(x=res.equity.index, y=res.equity[col], name=col, line=dict(color=colr)))
        fig.update_layout(height=420, title="Equity curve", margin=dict(l=10, r=10, t=40, b=10),
                          legend=dict(orientation="h", y=1.08))
        st.plotly_chart(fig, width="stretch")

        cmp = pd.DataFrame(res.stats).T[["Total return %", "CAGR %", "Volatility %", "Sharpe", "Max drawdown %"]]
        st.dataframe(cmp.style.format("{:.2f}"), width="stretch")
        with st.expander(f"Trade list ({len(res.trades)})"):
            st.dataframe(res.trades.style.format({"Entry price": "{:.2f}", "Exit price": "{:.2f}",
                                                  "Return %": "{:+.2f}"}),
                         hide_index=True, width="stretch")
        st.caption("Past performance does not guarantee future results. Ignores slippage, taxes and dividends "
                   "beyond price adjustment.")

# ---------- Fundamentals ----------
with tab_fund:
    inf = data.get_info(ticker)
    if not inf:
        st.error(f"No fundamental data for **{ticker}**.")
    else:
        meta_line = [inf.get(k) for k in ("sector", "industry", "country", "currency", "exchange")]
        st.caption(" · ".join(str(x) for x in meta_line if x))

        groups = fundamentals.grouped(inf)
        cols = st.columns(3)
        for i, (g, items) in enumerate(groups.items()):
            with cols[i % 3]:
                st.markdown(f"**{g}**")
                st.dataframe(pd.DataFrame(items, columns=["Metric", "Value"]), hide_index=True, width="stretch")

        if inf.get("longBusinessSummary"):
            with st.expander("Business summary"):
                st.write(inf["longBusinessSummary"])

        if inf.get("quoteType") not in ("CRYPTOCURRENCY", "FUTURE", "CURRENCY", "INDEX"):
            st.markdown("### Financial statements (annual)")
            fins = data.get_financials(ticker)
            which = st.radio("Statement", list(fins), horizontal=True)
            fs = fins[which]
            if fs is None or fs.empty:
                st.info("Not available for this ticker.")
            else:
                fs = fs.copy()
                fs.columns = [c.strftime("%Y") if hasattr(c, "strftime") else str(c) for c in fs.columns]
                key_rows = [r for r in ["Total Revenue", "Gross Profit", "Operating Income", "Net Income",
                                        "EBITDA", "Diluted EPS", "Operating Cash Flow", "Free Cash Flow",
                                        "Capital Expenditure", "Total Assets",
                                        "Total Liabilities Net Minority Interest", "Stockholders Equity",
                                        "Total Debt", "Cash And Cash Equivalents"]
                            if r in fs.index]
                if key_rows:
                    chart_df = fs.loc[key_rows].T.iloc[::-1]
                    pick = st.multiselect("Chart rows", key_rows, default=key_rows[:2])
                    if pick:
                        fig = go.Figure([go.Bar(x=chart_df.index, y=chart_df[r], name=r) for r in pick])
                        fig.update_layout(barmode="group", height=350, margin=dict(l=10, r=10, t=10, b=10))
                        st.plotly_chart(fig, width="stretch")
                st.dataframe(fs.map(lambda v: fundamentals.fmt(v, "money") if isinstance(v, (int, float)) else v),
                             width="stretch")
