"""Signals: scan many stocks with the switched-on indicators and rank the best buys and sells."""
from datetime import datetime

import pandas as pd
import streamlit as st

from analyser import journal
from analyser import portfolio as pfm
from analyser import signals as sg
from analyser.universes import DEFAULT_SCAN, RUSSELL, UNIVERSES, russell_2000, tickers_for
from views.common import ANALYSE, TILE, go_analyse, tiles, when
from views.flipdeck import flip_deck
from views.signals_ui import badge, indicator_panel, side_word

SETUPS = {
    "Near support + RSI oversold": lambda c: c["support"]["flags"].get("near_support") and c["rsi"]["flags"].get("oversold"),
    "Testing EMA200 from above": lambda c: c["ema200"]["flags"].get("testing_ema200_from_above"),
    "In unfilled gap zone": lambda c: c["gaps"]["flags"].get("in_gap_zone"),
    "Recent golden / death cross": lambda c: (c["crossovers"]["flags"].get("golden_cross_recent")
                                              or c["crossovers"]["flags"].get("death_cross_recent")),
    "Lagging MAG7, no red flags": lambda c: c["relative"]["flags"].get("lagging_no_red_flags"),
}

with st.sidebar:
    cfg = indicator_panel()
weights = {k: (cfg["weights"][k] if cfg["enabled"][k] else 0.0) for k in sg.CHECKS}

st.title("Signals")
st.caption("Scans stocks with the indicators switched on in the sidebar and ranks the strongest buy and sell setups.")

# ---------- what to scan ----------
holdings = sorted({h["ticker"] for h in pfm.load()["holdings"] if h["kind"] == "security"})
groups = (["My holdings"] if holdings else []) + list(UNIVERSES) + [RUSSELL]
default = [g for g in DEFAULT_SCAN if g in groups]
chosen = st.pills("Stocks to scan", groups, selection_mode="multi", default=default, key="sig_groups")
extra = st.text_input("Extra tickers", placeholder="Add any others, e.g. PLTR, AIR.NZ", key="sig_extra",
                      label_visibility="collapsed")
tickers = tickers_for(chosen or [], holdings)
tickers = list(dict.fromkeys(tickers + [t.strip().upper() for t in extra.split(",") if t.strip()]))
if not tickers:
    st.info("Pick at least one list of stocks to scan.")
    st.stop()
if RUSSELL in (chosen or []) and not russell_2000():
    st.warning("Couldn't load the Russell 2000 list from Yahoo's screener right now - scanning the other lists.")

if st.button("Rescan now", icon=":material/refresh:", type="tertiary"):
    sg._run_checks_cached.cache_clear()

# ---------- scan (each ticker's checks are cached for 30 minutes) ----------
bar = st.progress(0.0, text=f"Scanning {len(tickers)} stocks...")
results = sg.scan(tickers, cfg["params"], on_done=lambda i, n: bar.progress(i / n, f"Scanning {i}/{n}..."))
bar.empty()
ok = [r for r in results if "error" not in r]
failed = [r["ticker"] for r in results if "error" in r]

rows = []
for r in ok:
    comp = sg.composite(r, weights)
    c = r["checks"]
    rows.append({"Ticker": r["ticker"], "Name": r["name"], "Score": round(comp["score"]), "Verdict": comp["verdict"],
                 "Why": comp["reasons"][0] if comp["reasons"] else "", "Reasons": comp["reasons"],
                 "Price": r["price"], "As of": r["as_of"],
                 **{label: (None if c[k]["score"] is None else round(c[k]["score"] * 100)) for k, label in sg.CHECKS.items()},
                 "checks": c})
table = pd.DataFrame(rows)
if table.empty:
    st.warning("No results - check your internet connection.")
    st.stop()

buys = table[table["Score"] > 0].sort_values("Score", ascending=False).head(10)
sells = table[table["Score"] < 0].sort_values("Score").head(10)
on = [k for k in sg.CHECKS if weights[k]]

# log today's strongest signals so we can see later what the stocks did next
added = journal.record([
    {"ticker": row["Ticker"], "name": row["Name"], "side": side, "score": int(row["Score"]),
     "verdict": row["Verdict"], "price": float(row["Price"]), "date": pd.Timestamp(row["As of"]).date().isoformat(),
     "reasons": row["Reasons"], "indicators": on}
    for side, df in (("buy", buys), ("sell", sells)) for _, row in df.iterrows()])
if added:
    st.toast(f"Logged {added} new signals to your track record", icon=":material/history:")


def score_color(v):
    if pd.isna(v) or v == 0:
        return ""
    return f"color: {'#16a34a' if v > 0 else '#dc2626'}"


def ranked(df: pd.DataFrame, key: str):
    """Numbered cards: clickable ticker, verdict badge, main reason, and a per-indicator 'why' breakdown."""
    for i, (_, row) in enumerate(df.iterrows(), 1):
        with st.container(border=True, gap="small"):
            c1, c2 = st.columns([3, 1.4], vertical_alignment="center")
            c1.button(f"{i}. **{row['Ticker']}** · {row['Name']}", key=f"{key}_{row['Ticker']}", type="tertiary",
                      on_click=go_analyse, args=(row["Ticker"],), help="Open in Analyse")
            color = "green" if row["Score"] > 0 else "red"
            c2.markdown(f":{color}-badge[{row['Verdict']} {row['Score']:+d}]")
            if row["Why"]:
                st.caption(row["Why"])
            with st.expander("Why? Every indicator explained"):
                checks = row["checks"]
                order = sorted(on, key=lambda k: -abs((checks[k]["score"] or 0) * weights[k]))
                for k in order:
                    c = checks[k]
                    st.markdown(f"**{sg.CHECKS[k]}** &nbsp; {badge(c['score'])}", help=sg.MEANING[k]["what"])
                    st.caption(c["summary"])
                    if c["score"] is not None:
                        st.markdown(f"**Why it's {side_word(c['score'])}:** {sg.explain(k, c['score'])}")


tab_rank, tab_track = st.tabs(["Rankings", "Track record"])

# ---------- rankings ----------
with tab_rank:
    st.caption(f"Scanned {len(ok)} stocks at {when(datetime.now().astimezone())} using daily prices to the latest "
               f"close · indicators on: {', '.join(sg.CHECKS[k] for k in on) or 'none'}"
               + (f" · no data for {', '.join(failed)}" if failed else ""))
    view = st.segmented_control("View", ["Flip-through", "List"], default="Flip-through", key="sig_view",
                                required=True, label_visibility="collapsed")
    col_buy, col_sell = st.columns(2, gap="medium")
    for col, df, side_name, title in ((col_buy, buys, "buy", "Top 10 buys"), (col_sell, sells, "sell", "Top 10 sells")):
        with col:
            st.subheader(title)
            if df.empty:
                st.caption(f"No {side_name} signals right now.")
                continue
            if side_name == "buy" and df["Score"].max() < 15:
                st.caption("None reach a Buy signal (+15) right now - these are just the strongest.")
            elif side_name == "sell" and df["Score"].min() > -15:
                st.caption("None reach a Sell signal (−15) right now - these are just the weakest.")
            else:
                st.caption("&nbsp;")                     # keeps both decks lined up
            if view == "Flip-through":
                opened = flip_deck(df, side_name, on, weights, key=f"deck_{side_name}")
                if opened:
                    st.session_state.ticker = opened
                    st.switch_page(ANALYSE)
            else:
                ranked(df, f"sig_{side_name}s")
    if view == "Flip-through":
        st.caption("Scroll, swipe or use ↑ ↓ on either deck to turn its pages · the numbers jump to a stock.")

    st.subheader("Setups")
    picked = st.pills("Show stocks matching", list(SETUPS), selection_mode="multi", key="sig_setups")
    if picked:
        match = table[[all(bool(SETUPS[p](c)) for p in picked) for c in table["checks"]]]
        if match.empty:
            st.caption("Nothing matches all of these right now.")
        else:
            detail = pd.DataFrame({
                "Ticker": match["Ticker"], "Score": match["Score"], "Verdict": match["Verdict"],
                "RSI": [round(c["rsi"]["rsi"]) for c in match["checks"]],
                "vs EMA200 %": [round(c["ema200"].get("pct_from_ema200", float("nan")), 1) for c in match["checks"]],
                "Gaps": [c["gaps"]["summary"] for c in match["checks"]],
                "Support": [c["support"]["summary"] for c in match["checks"]],
            }).sort_values("Score", ascending=False)
            st.dataframe(detail.style.map(score_color, subset=["Score"]).format({"Score": "{:+d}"}),
                         hide_index=True, width="stretch")

    with st.expander(f"All {len(table)} results, score per indicator"):
        cols = ["Ticker", "Score", "Verdict", *sg.CHECKS.values()]
        full = table[cols].sort_values("Score", ascending=False)
        st.dataframe(full.style.map(score_color, subset=["Score", *sg.CHECKS.values()])
                     .format({c: lambda v: "—" if pd.isna(v) else f"{v:+.0f}" for c in ["Score", *sg.CHECKS.values()]}),
                     hide_index=True, width="stretch")
        st.caption("Each indicator scores −100 (strongly bearish) to +100 (strongly bullish); the overall score is "
                   "their weighted average. Switched-off indicators don't count. — = not applicable.")

# ---------- track record ----------
with tab_track:
    st.caption("Every scan logs its top 10 buys and sells (once per stock per day) with that day's closing price. "
               f"This shows what those stocks did next, compared with the S&P 500 ({journal.BENCHMARK}).")
    entries = journal.load()
    if not entries:
        st.info("Nothing logged yet - signals are recorded automatically each time you open this page.")
    else:
        c1, c2 = st.columns([1, 2], vertical_alignment="center")
        side = c1.segmented_control("Show", ["Sells", "Buys"], default="Sells", key="trk_side", required=True)
        strong = c2.toggle("Only real signals (score beyond ±15)", key="trk_strong")
        with st.spinner("Checking what happened next..."):
            out = journal.outcomes(entries)
        if strong:
            out = out[out["Score"].abs() >= 15]
        mine = out[out["Side"] == side[:-1]]
        if mine.empty:
            st.caption(f"No {side.lower()} logged" + (" with a score beyond ±15." if strong else "."))
        else:
            summ = journal.summary(out, side[:-1])
            verb = "fell" if side == "Sells" else "rose"
            vs = f"Avg vs {journal.BENCHMARK} (pts)"
            with tiles():
                for _, h in summ.iterrows():
                    if h["Signals"]:
                        st.metric(h["Horizon"], f"{h['Hit rate %']:.0f}% {verb}",
                                  f"avg {h['Avg move %']:+.1f}% ({h[vs]:+.1f} vs {journal.BENCHMARK})",
                                  delta_color="inverse" if side == "Sells" else "normal",
                                  delta_description=f"{int(h['Signals'])} measured", border=True, width=TILE)
                    else:
                        st.metric(h["Horizon"], "Pending", f"{int(h['Pending'])} waiting", delta_color="off",
                                  delta_arrow="off", border=True, width=TILE)
            st.caption(f"Hit rate = share of {side.lower()} whose price {verb} over that period. A good sell signal "
                       "should fall, or at least lag SPY. Results fill in as time passes; small samples can mislead.")
            pct_cols = ["Since", *journal.HORIZONS]
            show = mine[["Date", "Ticker", "Score", "Verdict", "Price then", *pct_cols, "Reason"]].sort_values(
                "Date", ascending=False)
            st.dataframe(
                show.style.map(score_color, subset=pct_cols + ["Score"])
                .format({**{c: (lambda v: "…" if pd.isna(v) else f"{v:+.1f}%") for c in pct_cols},
                         "Score": "{:+d}", "Price then": "{:,.2f}", "Date": lambda d: f"{d:%d %b %Y}"},
                        na_rep="…"),
                hide_index=True, width="stretch",
                column_config={"Reason": st.column_config.TextColumn(width="large")})
            st.caption("… = not enough trading days have passed yet. 'Since' = change from the signal day to now.")
        with st.popover("Clear track record", icon=":material/delete:"):
            st.write("Delete every logged signal? This can't be undone.")
            if st.button("Yes, clear it", type="primary", key="trk_clear"):
                journal.clear()
                st.rerun()

st.caption("Rule-based signals for research, not financial advice. Indicators lag and can be wrong; "
           "test a strategy (Analyse → Backtest) before trusting it.")
