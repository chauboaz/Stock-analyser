"""Your portfolio: overview, holdings (edit/remove) and adding positions."""
from datetime import date, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from analyser import data
from analyser import portfolio as pfm
from views import portfolio_diversification, portfolio_import
from views.common import TILE, TYPE_ICONS, go_analyse, hbar, primary_color, tiles

GREEN, RED = "#22c55e", "#ef4444"
OVERVIEW, HOLDINGS, DIVERSIFICATION, ADD = "📊 Overview", "📋 Holdings", "🎯 Diversification", "➕ Add position"
VIEWS = [OVERVIEW, HOLDINGS, DIVERSIFICATION, ADD]
KINDS = ["Stock / ETF / Crypto", "Physical gold / silver", "📸 Import from screenshot"]
MODES = {"date": "📅 I know the date I bought it",
         "today": "🟢 Start tracking from today",
         "price": "💲 I know the price I paid — help me find the date"}

pf = pfm.load()
today = date.today()


def fmt_qty(q: float) -> str:
    return f"{q:,.6f}".rstrip("0").rstrip(".")


def fmt_pct(v) -> str:
    return "—" if pd.isna(v) else f"{v:+.2f}%"


def fmt_period(p: dict) -> str:
    s, e = p["start"], p["end"]
    if s == e:
        return f"{s:%d %b %Y}"
    if s.year == e.year:
        return f"{s:%d %b} – {e:%d %b %Y}"
    return f"{s:%d %b %Y} – {e:%d %b %Y}"


def pl_color(v):
    if pd.isna(v) or v == 0:
        return ""
    return f"color: {GREEN if v > 0 else RED}"


def reset_add_form():
    for k in [k for k in st.session_state if str(k).startswith("add_")]:
        del st.session_state[k]


# ---------- header ----------
h1, h2 = st.columns([3, 1], vertical_alignment="bottom")
h1.title("💼 Your portfolio")
base = h2.selectbox("Currency", pfm.BASE_CURRENCIES,
                    index=pfm.BASE_CURRENCIES.index(pf["base_currency"]), key="pf_base")
if base != pf["base_currency"]:
    pf["base_currency"] = base
    pfm.save(pf)

if req := st.session_state.pop("pf_view_request", None):
    st.session_state.pf_view = req
st.session_state.setdefault("pf_view", OVERVIEW if pf["holdings"] else ADD)

vals = pd.DataFrame()
if pf["holdings"]:
    with st.spinner("Fetching latest prices..."):
        vals = pfm.value(pf["holdings"], base)
    total, cost = vals["Value"].sum(), vals["Cost"].sum()
    day = vals["Day change"].sum()
    with tiles():
        st.metric("Total value", pfm.money(total, base, None), border=True, width=TILE)
        st.metric("Invested", pfm.money(cost, base, None), border=True, width=TILE)
        st.metric("Total return", pfm.money(total - cost, base, None),
                  f"{(total / cost - 1) * 100:+.2f}%" if cost else None, border=True, width=TILE)
        st.metric("Today", pfm.money(day, base, None),
                  f"{day / (total - day) * 100:+.2f}%" if total - day else None, border=True, width=TILE)
    if vals["Value"].isna().any():
        st.warning("No price data for: " + ", ".join(vals.loc[vals["Value"].isna(), "Ticker"]))

view = st.segmented_control("View", VIEWS, key="pf_view", required=True, label_visibility="collapsed")


# ---------- Overview ----------
def overview():
    if vals.empty:
        st.info("Your portfolio is empty. Add your first position to get started.")
        return
    hist = pfm.history(pf["holdings"], base)
    st.subheader("Value over time")
    if hist.empty:
        st.info("Add a purchase date to your holdings to see how your portfolio value has changed over time.")
    else:
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=hist.index, y=hist["Value"], name="Portfolio value", fill="tozeroy",
                                 line=dict(color=primary_color(), width=2)))
        fig.add_trace(go.Scatter(x=hist.index, y=hist["Invested"], name="Amount invested",
                                 line=dict(color="gray", width=1.5, dash="dash"), line_shape="hv"))
        fig.update_layout(height=380, margin=dict(l=10, r=10, t=10, b=10), hovermode="x unified",
                          legend=dict(orientation="h", y=-0.12), yaxis_title=base,
                          xaxis=dict(rangeselector=dict(buttons=[
                              dict(count=1, label="1M", step="month", stepmode="backward"),
                              dict(count=6, label="6M", step="month", stepmode="backward"),
                              dict(count=1, label="YTD", step="year", stepmode="todate"),
                              dict(count=1, label="1Y", step="year", stepmode="backward"),
                              dict(step="all", label="All")])))
        st.plotly_chart(fig, width="stretch")
        undated = [h["ticker"] for h in pf["holdings"] if not h.get("date")]
        if undated:
            st.caption(f"Not in this chart (no purchase date): {', '.join(undated)}. "
                       "Add a date from the Holdings tab to include them.")

    live = vals.dropna(subset=["Value"])
    total_v = live["Value"].sum()
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("By asset type")
        by_type = live.groupby("Type")["Value"].sum() / total_v * 100
        by_type.index = [f"{TYPE_ICONS.get(t, '')} {t}" for t in by_type.index]
        st.plotly_chart(hbar(by_type, "{:.1f}%"), width="stretch")
    with c2:
        st.subheader("By holding")
        by_h = live.groupby("Ticker")["Value"].sum() / total_v * 100
        st.plotly_chart(hbar(by_h, "{:.1f}%", height_per_row=28), width="stretch")

    st.subheader("Return by holding")
    r = live.groupby("Ticker")[["Value", "Cost"]].sum()
    pct = (r["Value"] / r["Cost"] - 1) * 100
    # pad both ends so the "outside" labels of negative bars don't collide with the ticker names
    span = max(pct.max(), 0) - min(pct.min(), 0) or 1
    fig = hbar(pct, "{:+.1f}%", height_per_row=28, colors=lambda s: [GREEN if v >= 0 else RED for v in s],
               x_range=[min(pct.min(), 0) - 0.25 * span, max(pct.max(), 0) + 0.2 * span])
    fig.update_xaxes(visible=True, zeroline=True, showticklabels=False, showgrid=False)
    st.plotly_chart(fig, width="stretch")


# ---------- Holdings ----------
def holdings():
    if vals.empty:
        st.info("No holdings yet.")
        return
    disp = pd.DataFrame({
        "Ticker": vals["Ticker"],
        "Name": vals["Name"],
        "Type": [f"{TYPE_ICONS.get(t, '')} {t}" for t in vals["Type"]],
        "Quantity": [f"{fmt_qty(q)} {u if u not in ('units', 'shares') else ''}".strip()
                     for q, u in zip(vals["Quantity"], vals["Unit"])],
        "Buy price": [f"{p:,.2f} {c}" for p, c in zip(vals["Buy price"], vals["Cost currency"])],
        "Price now": [f"{p:,.2f} {c}" if pd.notna(p) else "—" for p, c in zip(vals["Price"], vals["Currency"])],
        f"Value ({base})": vals["Value"],
        f"Cost ({base})": vals["Cost"],
        "P/L": vals["P/L"],
        "P/L %": vals["P/L %"],
        "Today": vals["Day change"],
        "Bought": [d.strftime("%d %b %Y") if d else "Unknown" for d in vals["Bought"]],
        "Ann. %": vals["Ann. %"],
    })
    money_cols = [f"Value ({base})", f"Cost ({base})", "P/L", "Today"]
    # one .format call: in pandas 3 a second call resets the first call's formatters
    styled = (disp.style
              .format({**{c: lambda v: pfm.money(v, base) for c in money_cols}, "P/L %": fmt_pct, "Ann. %": fmt_pct})
              .map(pl_color, subset=["P/L", "P/L %", "Today", "Ann. %"]))
    st.caption("Select a row to edit, remove or analyse it.")
    event = st.dataframe(styled, hide_index=True, width="stretch", on_select="rerun",
                         selection_mode="single-row", key="pf_table")
    st.download_button("⬇️ Export CSV", vals.drop(columns="id").to_csv(index=False), "portfolio.csv",
                       "text/csv")

    if not event.selection.rows:
        return
    h = next(x for x in pf["holdings"] if x["id"] == vals.iloc[event.selection.rows[0]]["id"])
    is_metal = h["kind"] == "metal"
    uf = pfm.UNITS.get(h.get("display_unit"), 1.0) if is_metal else 1.0
    k = h["id"]
    with st.container(border=True):
        st.markdown(f"#### ✏️ {h['name']}" + ("" if is_metal else f" ({h['ticker']})"))
        c1, c2, c3 = st.columns(3)
        qty = c1.number_input(f"Quantity ({h['display_unit']})", min_value=0.0, value=float(h["quantity"] / uf),
                              format="%g", key=f"ed_q_{k}")
        price = c2.number_input(f"Price paid per {h['display_unit'].rstrip('s') if is_metal else 'unit'} "
                                f"({h['cost_currency']})", min_value=0.0, value=float(h["price"] * uf),
                                format="%.4f", key=f"ed_p_{k}")
        known = c3.toggle("I know the purchase date", value=bool(h.get("date")), key=f"ed_k_{k}")
        d = c3.date_input("Purchase date", value=date.fromisoformat(h["date"]) if h.get("date") else today,
                          max_value=today, disabled=not known, format="DD/MM/YYYY", key=f"ed_d_{k}")
        notes = st.text_input("Notes", h.get("notes", ""), key=f"ed_n_{k}")
        b1, b2, b3, _ = st.columns([1, 1, 1.3, 3])
        if b1.button("💾 Save", type="primary", key=f"ed_s_{k}"):
            if qty <= 0:
                st.error("Quantity must be more than zero.")
            else:
                h.update(quantity=qty * uf, price=price / uf, date=d.isoformat() if known else None, notes=notes)
                pfm.save(pf)
                st.toast("Saved", icon="✅")
                st.rerun()
        with b2.popover("🗑️ Remove"):
            st.write(f"Remove **{h['ticker']}** from your portfolio?")
            if st.button("Yes, remove", type="primary", key=f"ed_x_{k}"):
                pf["holdings"] = [x for x in pf["holdings"] if x["id"] != k]
                pfm.save(pf)
                st.toast(f"Removed {h['ticker']}", icon="🗑️")
                st.rerun()
        if not is_metal:
            b3.button("📊 Analyse", key=f"ed_a_{k}", on_click=go_analyse, args=(h["ticker"],))


# ---------- Add position ----------
def add_position():
    if req := st.session_state.pop("add_kind_request", None):
        st.session_state.add_kind = req
    st.session_state.setdefault("add_kind", KINDS[0])
    kind = st.segmented_control("What are you adding?", KINDS, key="add_kind", required=True)
    if kind == KINDS[2]:
        with st.container(border=True):
            portfolio_import.render(pf, base)
        return

    with st.container(border=True):
        # ---- 1. what ----
        if kind == KINDS[0]:
            st.markdown("**1. Find the stock, ETF or crypto**")
            q = st.text_input("Search", key="add_q", icon=":material/search:", label_visibility="collapsed",
                              placeholder="Company name or ticker, e.g. Fisher Paykel, VOO, BHP, bitcoin")
            if q:
                results = data.search(q)
                if not results:
                    st.info(f"No matches for **{q}**.")
                else:
                    labels = [f"**{r['symbol']}** — {r['name']}  ·  {r['type']}, {r['exchange']}" for r in results]
                    pick = st.radio("Pick one", range(len(results)), format_func=lambda i: labels[i], index=None,
                                    key=f"add_pick_{q}")
                    if pick is not None:
                        st.session_state.add_sel = results[pick]
            sel = st.session_state.get("add_sel")
            if not sel:
                return
            ticker, name, asset_type = sel["symbol"], sel["name"], sel["type"]
            market_ccy = price_ccy = data.get_currency(ticker)[0]
            unit, uf = ("units" if asset_type == "Crypto" else "shares"), 1.0
            quote = data.get_quote(ticker)
            if not quote:
                st.error(f"Couldn't get prices for {ticker}.")
                return
            st.success(f"**{ticker}** — {name} · {asset_type} · last price **{quote['price']:,.2f} {market_ccy}**")
            qty = st.number_input(f"**2. How many {unit}?**", min_value=0.0, value=None, format="%g",
                                  key="add_qty", placeholder="e.g. 10")
            h_kind, display_unit = "security", unit
        else:
            st.markdown("**1. What metal?**")
            c1, c2, c3 = st.columns(3)
            metal = c1.selectbox("Metal", list(pfm.METALS), key="add_metal")
            unit = c2.selectbox("Unit", list(pfm.UNITS), key="add_unit")
            price_ccy = c3.selectbox("Currency you paid in", pfm.BASE_CURRENCIES,
                                     index=pfm.BASE_CURRENCIES.index(base), key="add_mccy")
            ticker, name, asset_type, market_ccy = pfm.METALS[metal], f"Physical {metal.lower()}", metal, "USD"
            uf = pfm.UNITS[unit]
            spot = pfm.current_price(ticker, price_ccy, market_ccy, uf)
            if spot:
                st.caption(f"{metal} spot ≈ **{spot:,.2f} {price_ccy} per {unit.rstrip('s')}** "
                           "(COMEX futures price; physical coins/bars usually cost a premium above spot)")
            qty = st.number_input(f"**2. How much {metal.lower()}? ({unit})**", min_value=0.0, value=None,
                                  format="%g", key="add_qty", placeholder="e.g. 1")
            h_kind, display_unit = "metal", unit
        is_metal = h_kind == "metal"
        per = unit.rstrip("s") if is_metal else ("unit" if unit == "units" else "share")

        def price_input(default, key):
            """Metals: ask the total paid (what receipts show). Securities: price per share."""
            if is_metal:
                total = st.number_input(f"Total paid ({price_ccy})", min_value=0.0, format="%.2f", key=key,
                                        value=round(default * qty, 2) if default and qty else None,
                                        help="Including any dealer premium")
                return total / qty if total and qty else None
            return st.number_input(f"Price paid per {per} ({price_ccy})", min_value=0.0, format="%.4f", key=key,
                                   value=round(default, 4) if default else None,
                                   help="Defaults to that day's close — change it to your actual price")

        # ---- 3. how to track ----
        mode = st.radio("**3. How should we track it?**", list(MODES), format_func=MODES.get, key="add_mode")
        buy_date, ppu = None, None
        if mode == "date":
            d = st.date_input("Purchase date", value=today - timedelta(days=365), max_value=today,
                              min_value=date(1970, 1, 1), format="DD/MM/YYYY", key="add_date")
            ref = pfm.reference_price(ticker, d, price_ccy, market_ccy, uf)
            if ref:
                rd, rpx = ref
                note = "" if rd == d else f" (last trading day before {d:%d %b})"
                st.caption(f"Closing price on {rd:%d %b %Y}{note}: **{rpx:,.2f} {price_ccy}** per {per}")
            else:
                st.warning("No price data for that date — enter what you paid.")
            # metals default the *total* from the quantity, so re-default when it changes
            ppu = price_input(ref[1] if ref else None, f"add_px_{ticker}_{d}_{unit}" + (f"_{qty}" if is_metal else ""))
            buy_date = d
        elif mode == "today":
            ppu = pfm.current_price(ticker, price_ccy, market_ccy, uf)
            buy_date = today
            if ppu:
                st.caption(f"We'll record today's price, **{ppu:,.2f} {price_ccy}** per {per}, and track "
                           "gains and losses from now on.")
        else:
            ppu = price_input(None, f"add_pp_{ticker}_{unit}")
            if ppu:
                buy_date = when_did_you_buy(ticker, ppu, price_ccy, market_ccy, uf, per)

        notes = st.text_input("Notes (optional)", key="add_notes", placeholder="e.g. bought through Sharesies")

        # ---- preview + add ----
        if not qty or not ppu:
            return
        h = pfm.new_holding(kind=h_kind, ticker=ticker, name=name, asset_type=asset_type, currency=market_ccy,
                            quantity=qty * uf, price=ppu / uf, cost_currency=price_ccy, buy_date=buy_date,
                            tracking=mode, display_unit=display_unit, notes=notes)
        pv = pfm.value([h], base).iloc[0]
        when = f"on {buy_date:%d %b %Y}" if buy_date else "(date unknown)"
        line = (f"**{fmt_qty(qty)} {unit} of {name.lower() if is_metal else ticker}** at {ppu:,.2f} {price_ccy} per {per} {when} — "
                f"cost **{pfm.money(pv['Cost'], base)}**")
        if pd.notna(pv["Value"]) and mode != "today":
            line += (f", worth **{pfm.money(pv['Value'], base)}** today "
                     f"(:{'green' if pv['P/L'] >= 0 else 'red'}[{pv['P/L %']:+.2f}%])")
        st.info(line)
        if st.button("＋ Add to portfolio", type="primary", key="add_go"):
            pf["holdings"].append(h)
            pfm.save(pf)
            reset_add_form()
            st.session_state.pf_view_request = OVERVIEW
            st.toast(f"Added {name if is_metal else ticker} to your portfolio", icon="✅")
            st.rerun()


def when_did_you_buy(ticker, ppu, price_ccy, market_ccy, uf, per):
    """Ask when a purchase at `ppu` happened, suggesting periods when it traded at that price."""
    st.markdown("**📆 When did you buy it?**")
    with st.spinner("Looking for when it traded at that price..."):
        sug = pfm.suggest_dates(ticker, ppu, price_ccy, market_ccy, uf)
    if sug["periods"]:
        more = sug["total_periods"] - len(sug["periods"])
        st.caption(f"{ticker} traded at **{ppu:,.2f} {price_ccy}** during these periods in the last 5 years "
                   f"(most recent first{f', {more} older ones not shown' if more > 0 else ''}). "
                   "Was it one of these?")
    elif sug["closest"]:
        cd, cpx = sug["closest"]
        st.caption(f"{ticker} hasn't traded at {ppu:,.2f} {price_ccy} per {per} in the last 5 years "
                   f"(range {sug['min']:,.2f}–{sug['max']:,.2f}). The closest close was {cpx:,.2f} on "
                   f"{cd:%d %b %Y}. Pick the date yourself, or choose 'I don't remember'.")
    options = [("period", p) for p in sug["periods"]] + [("pick", None), ("unknown", None)]
    labels = {"pick": "🗓️ I'll pick the date myself", "unknown": "🤷 I don't remember"}
    choice = st.radio("When", range(len(options)), label_visibility="collapsed", key=f"add_when_{ticker}_{ppu}",
                      format_func=lambda i: labels.get(options[i][0]) or
                      f"{fmt_period(options[i][1])}  ·  traded {options[i][1]['low']:,.2f} – "
                      f"{options[i][1]['high']:,.2f}")
    kind, p = options[choice]
    if kind == "period":
        if p["start"] == p["end"]:
            return p["start"]
        return st.date_input("Narrow it down (optional)", value=p["best"], min_value=p["start"],
                             max_value=p["end"], format="DD/MM/YYYY", key=f"add_ref_{ticker}_{ppu}_{choice}",
                             help="Pre-set to the day the close was nearest your price")
    if kind == "pick":
        default = sug["closest"][0] if sug["closest"] else today
        return st.date_input("Purchase date", value=default, max_value=today, min_value=date(1970, 1, 1),
                             format="DD/MM/YYYY", key=f"add_pick_date_{ticker}")
    st.caption("No problem — returns will be measured from your price. Without a date this holding won't "
               "appear on the value-over-time chart and can't be annualised. You can add the date later "
               "from the Holdings tab.")
    return None


{OVERVIEW: overview, HOLDINGS: holdings, ADD: add_position,
 DIVERSIFICATION: lambda: portfolio_diversification.render(pf, vals)}[view]()
