"""Signal settings panel and result display, shared by the Signals and Analyse pages."""
import copy

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from analyser import settings
from analyser import signals as sg

WEIGHTS = [0.5, 1.0, 1.5, 2.0, 3.0]
PAIR_OPTIONS = ["5/20", "10/50", "20/50", "20/100", "50/200"]


def load_config() -> dict:
    """{"enabled": {key: bool}, "weights": {key: float}, "params": {...}} - saved settings over defaults."""
    saved = settings.get("signals", {}) or {}
    return {"enabled": {k: saved.get("enabled", {}).get(k, True) for k in sg.CHECKS},
            "weights": {k: float(saved.get("weights", {}).get(k, 1.0)) for k in sg.CHECKS},
            "params": sg.merged_params(saved.get("params"))}


def effective_weights(cfg: dict) -> dict:
    return {k: (cfg["weights"][k] if cfg["enabled"][k] else 0.0) for k in sg.CHECKS}


def _param_widgets(key: str, p: dict) -> dict:
    p = copy.deepcopy(p)
    k = f"sig_{key}_"
    if key == "gaps":
        p["min_gap_daily"] = st.number_input("Min daily gap %", 0.2, 10.0, float(p["min_gap_daily"]), 0.1, key=k + "d")
        p["min_gap_weekly"] = st.number_input("Min weekly gap %", 0.5, 15.0, float(p["min_gap_weekly"]), 0.5,
                                              key=k + "w")
        p["overshoot"] = st.number_input("Overshoot beyond gap %", 1.0, 20.0, float(p["overshoot"]), 0.5, key=k + "o")
    elif key == "ema200":
        p["days_above"] = st.number_input("Days above before the test", 5, 120, int(p["days_above"]), key=k + "n")
        p["band"] = st.number_input("Counts as testing within ±%", 0.5, 10.0, float(p["band"]), 0.5, key=k + "b")
    elif key == "crossovers":
        current = [f"{a}/{b}" for a, b in p["pairs"]]
        chosen = st.multiselect("Fast / slow pairs", PAIR_OPTIONS, default=[c for c in current if c in PAIR_OPTIONS],
                                key=k + "p") or ["50/200"]
        p["pairs"] = [[int(x) for x in c.split("/")] for c in chosen]
        p["recent_bars"] = st.number_input("Cross counts as recent within (days)", 5, 120, int(p["recent_bars"]),
                                           key=k + "r")
    elif key == "rsi":
        p["period"] = st.number_input("Period", 5, 30, int(p["period"]), key=k + "p")
        p["oversold"] = st.number_input("Oversold below", 10, 45, int(p["oversold"]), key=k + "lo")
        p["overbought"] = st.number_input("Overbought above", 55, 90, int(p["overbought"]), key=k + "hi")
    elif key == "support":
        p["swing_n"] = st.number_input("Swing-low window (± weeks)", 2, 12, int(p["swing_n"]), key=k + "n")
        p["cluster"] = st.number_input("Group lows within %", 0.5, 6.0, float(p["cluster"]), 0.5, key=k + "c")
        p["near"] = st.number_input("Near support within %", 0.5, 10.0, float(p["near"]), 0.5, key=k + "near")
    elif key == "relative":
        p["benchmark"] = st.selectbox("Benchmark", ["SPY", "VOO", "QQQ", "VT"],
                                      index=["SPY", "VOO", "QQQ", "VT"].index(p["benchmark"]), key=k + "b")
        p["lag"] = st.number_input("Lagging MAG7 by at least (pts, 6M)", 5.0, 50.0, float(p["lag"]), 1.0, key=k + "l")
    elif key == "fundamentals":
        p["small_float_m"] = st.number_input("Small float below (million shares)", 1, 500, int(p["small_float_m"]),
                                             key=k + "f")
    return p


def indicator_panel() -> dict:
    """Toggle + weight + settings for each indicator. Saves changes; returns the config."""
    cfg = load_config()
    new = copy.deepcopy(cfg)
    st.markdown("**Indicators**")
    for key, label in sg.CHECKS.items():
        c1, c2 = st.columns([4, 1], vertical_alignment="center")
        new["enabled"][key] = c1.toggle(label, value=cfg["enabled"][key], key=f"sig_on_{key}", help=sg.MEANING[key]["what"])
        with c2.popover("", icon=":material/tune:", help=f"{label} settings"):
            st.caption(sg.MEANING[key]["what"])
            new["weights"][key] = st.select_slider("Weight in the score", WEIGHTS, value=cfg["weights"][key],
                                                   key=f"sig_w_{key}")
            new["params"][key] = _param_widgets(key, cfg["params"][key])
    if new != cfg:
        settings.put("signals", new)
    if st.button("Reset to defaults", key="sig_reset", type="tertiary"):
        settings.put("signals", {})
        for k in [k for k in st.session_state if str(k).startswith("sig_")]:
            del st.session_state[k]
        st.rerun()
    return new


def badge(score) -> str:
    if score is None:
        return ":gray-badge[n/a]"
    if score >= 0.15:
        return f":green-badge[Bullish {score * 100:+.0f}]"
    if score <= -0.15:
        return f":red-badge[Bearish {score * 100:+.0f}]"
    return f":gray-badge[Neutral {score * 100:+.0f}]"


def side_word(score) -> str:
    return "bullish" if score >= 0.15 else "bearish" if score <= -0.15 else "neutral"


def explanation(key: str, c: dict) -> None:
    """The reading, why it's bullish/bearish, and (collapsed) what the indicator measures."""
    st.caption(c["summary"])
    if c.get("score") is not None:
        st.markdown(f"**Why it's {side_word(c['score'])}:** {sg.explain(key, c['score'])}")
    with st.expander("What does this indicator mean?"):
        st.write(sg.MEANING[key]["what"])


def check_cards(result: dict, cfg: dict) -> None:
    """One bordered card per check: name, bullish/bearish badge, the reading and why it matters."""
    for key, label in sg.CHECKS.items():
        c = result["checks"][key]
        with st.container(border=True):
            on = cfg["enabled"][key]
            st.markdown(f"**{label}** &nbsp; {badge(c.get('score')) if on else ':gray-badge[Off]'}")
            explanation(key, c)


def signal_chart(daily: pd.DataFrame, result: dict, years: int = 3) -> go.Figure:
    """Weekly candles with EMA200, unfilled gap zones and the strongest support zones."""
    wk = sg.weekly(daily)
    start = wk.index[-1] - pd.DateOffset(years=years)
    wk = wk[wk.index >= start]
    ema = daily["Close"].ewm(span=200, adjust=False).mean()
    ema = ema[ema.index >= start]
    fig = go.Figure(go.Candlestick(x=wk.index, open=wk["Open"], high=wk["High"], low=wk["Low"], close=wk["Close"],
                                   name="Weekly price"))
    fig.add_trace(go.Scatter(x=ema.index, y=ema.values, name="EMA200", line=dict(color="#f59e0b", width=1.5)))
    end = wk.index[-1] + pd.Timedelta(days=7)
    gaps = result["checks"]["gaps"].get("gaps")
    if gaps is not None and not gaps.empty:
        open_gaps = gaps[~gaps["filled"] & (gaps["date"] >= start)]
        for _, g in open_gaps.iterrows():
            color = "rgba(34,197,94,0.18)" if g["direction"] == "up" else "rgba(239,68,68,0.18)"
            fig.add_shape(type="rect", x0=g["date"], x1=end, y0=g["zone_low"], y1=g["zone_high"],
                          fillcolor=color, line_width=0, layer="below")
    zones = result["checks"]["support"].get("zones")
    if zones is not None and not zones.empty:
        lo, hi = wk["Low"].min() * 0.9, wk["High"].max() * 1.05
        labelled = []
        for _, z in zones[(zones["level"] > lo) & (zones["level"] < hi)].nlargest(5, "touches").iterrows():
            fig.add_shape(type="rect", x0=start, x1=end, y0=z["zone_low"] * 0.997, y1=z["zone_high"] * 1.003,
                          fillcolor="rgba(100,116,139,0.25)", line_width=0, layer="below")
            if all(abs(z["level"] / y - 1) > 0.04 for y in labelled):     # skip labels that would overlap
                labelled.append(z["level"])
                fig.add_annotation(x=start, y=z["level"], text=f"support ×{int(z['touches'])}", showarrow=False,
                                   xanchor="left", yanchor="bottom", font=dict(size=10, color="#64748b"))
    fig.update_layout(height=460, xaxis_rangeslider_visible=False, margin=dict(l=10, r=10, t=10, b=10),
                      legend=dict(orientation="h", y=-0.12))
    return fig
