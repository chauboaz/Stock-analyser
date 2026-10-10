"""Portfolio > Diversification: score, factor breakdown, exposures and suggestions."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from analyser import diversification as dv
from views.common import hbar

GRADE_TEXT = {"A": "Well diversified", "B": "Good, with a few gaps", "C": "Moderately diversified",
              "D": "Concentrated", "F": "Highly concentrated"}
FACTOR_HELP = {
    "Holdings": "How many positions you effectively own, weighted by size. A broad ETF counts as many.",
    "Sectors": "How spread your shares are across industries (looking inside ETFs where possible).",
    "Geography": "How spread your shares are across countries/regions.",
    "Asset classes": "Mix of shares, bonds/cash, precious metals and crypto. Heavy crypto is penalised.",
    "Currencies": "How many currencies your holdings are priced in.",
    "Correlation": "How differently your holdings move day to day over the past year (lower is better).",
}
LEVEL = {"warning": (st.warning, ":material/warning:"), "info": (st.info, ":material/lightbulb:"),
         "success": (st.success, ":material/check_circle:")}


def render(pf: dict, vals: pd.DataFrame) -> None:
    if vals.empty:
        st.info("Add some holdings to get a diversification rating.")
        return
    with st.spinner("Analysing sectors, regions and correlations..."):
        r = dv.analyse(pf["holdings"], vals)
    if not r:
        st.warning("Couldn't value any holdings, so there's nothing to rate yet.")
        return

    # ---- headline ----
    c1, c2 = st.columns([1, 2], gap="large")
    with c1, st.container(border=True):
        st.metric("Diversification score", f"{r['score']:.0f} / 100", border=False)
        st.markdown(f"### Grade {r['grade']}")
        st.caption(GRADE_TEXT[r["grade"]] + f" · ~{r['n_eff']:.0f} effective positions")
    with c2:
        scores = pd.Series({k: v for k, v in r["scores"].items() if v is not None})
        fig = hbar(scores, "{:.0f}", x_range=[0, 115])
        fig.update_traces(customdata=[FACTOR_HELP[k] for k in scores.sort_values().index],
                          hovertemplate="<b>%{y}</b>: %{x:.0f}/100<br>%{customdata}<extra></extra>")
        st.markdown("**Score by factor** (0–100, hover for what each means)")
        st.plotly_chart(fig, width="stretch")

    st.subheader("Suggestions")
    for level, msg in r["suggestions"]:
        fn, icon = LEVEL[level]
        fn(msg, icon=icon)

    # ---- exposures ----
    st.subheader("Where your money is")
    e1, e2 = st.columns(2)
    with e1:
        st.markdown("**Asset classes** (whole portfolio)")
        st.plotly_chart(hbar(pd.Series(r["classes"]) * 100, "{:.0f}%"), width="stretch")
        st.markdown("**Currencies** (whole portfolio)")
        st.plotly_chart(hbar(pd.Series(r["currencies"]) * 100, "{:.0f}%"), width="stretch")
    with e2:
        if r["sectors"]:
            st.markdown("**Sectors** (shares & ETFs, looking inside funds)")
            st.plotly_chart(hbar(pd.Series(r["sectors"]) * 100, "{:.0f}%"), width="stretch")
        if r["regions"]:
            st.markdown("**Regions** (shares & ETFs)")
            st.plotly_chart(hbar(pd.Series(r["regions"]) * 100, "{:.0f}%"), width="stretch")

    corr = r["corr"]
    if not corr.empty and len(corr) >= 2:
        with st.expander(f"Correlation between holdings (weighted average {r['avg_corr']:.2f})"):
            st.caption("Daily return correlation over the past year: 1 = always move together, 0 = unrelated, "
                       "−1 = move opposite. Lower numbers between big holdings mean better diversification.")
            fig = go.Figure(go.Heatmap(
                z=corr.values, x=corr.columns, y=corr.index, zmin=-1, zmax=1, zmid=0,
                colorscale=[[0, "#2166ac"], [0.5, "#9e9e9e"], [1, "#b2182b"]],
                text=corr.round(2).values, texttemplate="%{text}", xgap=2, ygap=2,
                hovertemplate="%{y} vs %{x}: %{z:.2f}<extra></extra>", colorbar=dict(title="corr")))
            fig.update_layout(height=max(260, 45 * len(corr) + 80), margin=dict(l=10, r=10, t=10, b=10),
                              yaxis=dict(autorange="reversed"))
            st.plotly_chart(fig, width="stretch")

    with st.expander("How the score works"):
        st.markdown("\n".join(f"- **{k}** ({dv.WEIGHTS[k]:.0%} of the score) — {FACTOR_HELP[k]}"
                              for k in dv.WEIGHTS))
        st.markdown(f"ETFs and index funds count as {dv.ETF_BREADTH} equal positions "
                    f"({dv.NICHE_ETF_BREADTH} for sector/theme funds). Grades: A ≥ 85, B ≥ 70, C ≥ 55, D ≥ 40.")
    if r["estimated"]:
        st.caption("Sector/region mix estimated from the fund name for: " + ", ".join(r["estimated"]) +
                   " (Yahoo doesn't publish their breakdown).")
    st.caption("General information to help you think about risk — not financial advice.")
