"""Portfolio > Add position > Import from screenshot."""
import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import anthropic
import pandas as pd
import streamlit as st

from analyser import credentials, data, scanner
from analyser import portfolio as pfm

METAL_UNITS = {"oz": "troy oz", "g": "grams", "kg": "kilograms"}


def key_setup() -> bool:
    """Show API key status / entry. Returns True when a key is available."""
    source = credentials.key_source()
    if source:
        with st.expander(f"Anthropic API key: using {source}", icon=":material/key:"):
            st.caption("Screenshots are sent to Anthropic's API (model: Claude Opus 5) to read them; "
                       "each scan typically costs a few cents.")
            if source == "saved key" and st.button("Forget saved key", key="imp_forget"):
                credentials.forget_key()
                st.rerun()
        return True
    st.info("Screenshot import uses Claude to read your broker screenshots. It needs an **Anthropic API "
            "key** — create one at [console.anthropic.com](https://console.anthropic.com/settings/keys). "
            "Each scan typically costs a few cents.")
    c1, c2 = st.columns([4, 1], vertical_alignment="bottom")
    key = c1.text_input("API key", type="password", placeholder="sk-ant-...", key="imp_key_input")
    if c2.button("Save key", type="primary", disabled=not key, width="stretch"):
        credentials.save_key(key)
        st.toast("Key saved", icon=":material/key:")
        st.rerun()
    st.caption(f"Saved to {credentials.KEY_FILE} (your Windows user folder, outside OneDrive). "
               "Or set the ANTHROPIC_API_KEY environment variable instead.")
    return False


def _match(h: dict, existing: set[str]) -> dict:
    """One review-table row for an extracted holding."""
    is_metal = h["asset_type"] in ("gold", "silver")
    row = {"Add": True, "Symbol": "", "Name": h["name"], "Type": h["asset_type"].title(),
           "Quantity": h["quantity"], "Unit": "", "Avg price": h["average_price"],
           "Currency": (h["currency"] or "").upper() or None, "Bought on": None, "Status": ""}
    if h["average_price"] is None and h["total_cost"] and h["quantity"]:
        row["Avg price"] = h["total_cost"] / h["quantity"]
    if is_metal:
        metal = h["asset_type"].title()
        row.update(Symbol=metal, Unit=METAL_UNITS.get((h["quantity_unit"] or "oz").lower(), "troy oz"),
                   Status=f"✓ physical {metal.lower()}")
        row["Currency"] = row["Currency"] or "NZD"
    else:
        hit = scanner.resolve_symbol(h)
        if hit:
            q = data.get_quote(hit["symbol"])
            ccy = data.get_currency(hit["symbol"])[0]
            row.update(Symbol=hit["symbol"], Type=hit["type"], Unit="units" if hit["type"] == "Crypto" else "shares",
                       Status=f"✓ {hit['name']} · now {q['price']:,.2f} {ccy}")
            row["Currency"] = row["Currency"] or ccy
            if hit["guess"]:
                row.update(Add=False, Status=f"? best guess from name search: {hit['name']} - check, then tick")
            elif hit["symbol"] in existing:
                row.update(Add=False, Status=row["Status"] + " · already in your portfolio")
        else:
            row.update(Add=False, Status="⚠ couldn't find this on Yahoo Finance - type the symbol")
    if not row["Quantity"]:
        row.update(Add=False, Status=row["Status"] + " · ⚠ quantity missing")
    return row


def build_holding(row: pd.Series, base: str) -> tuple[dict | None, str | None]:
    """Turn a reviewed row into a holding. Returns (holding, error)."""
    sym, qty = (row["Symbol"] or "").strip(), row["Quantity"]
    if not sym or not qty or qty <= 0:
        return None, f"{row['Name']}: needs a symbol and quantity"
    bought = None if pd.isna(row["Bought on"]) else pd.Timestamp(row["Bought on"]).date()
    price = None if pd.isna(row["Avg price"]) else float(row["Avg price"])

    if sym in ("Gold", "Silver"):
        ticker, unit = pfm.METALS[sym], row["Unit"] or "troy oz"
        uf = pfm.UNITS.get(unit, 1.0)
        ccy, market_ccy, name, kind, asset_type = row["Currency"] or base, "USD", f"Physical {sym.lower()}", "metal", sym
    else:
        sym = sym.upper()
        if not data.get_quote(sym):
            return None, f"{row['Name']}: no prices found for symbol {sym}"
        meta = data.get_meta(sym)
        market_ccy = meta["currency"]
        ccy = (row["Currency"] or market_ccy).upper()
        ticker, uf, unit, name, kind, asset_type = sym, 1.0, row["Unit"] or "shares", meta["name"], "security", meta["type"]

    if price is None and bought:                       # date but no price: use that day's close
        ref = pfm.reference_price(ticker, bought, ccy, market_ccy, uf)
        price = ref[1] if ref else None
    if price is None:                                  # nothing known: start tracking today
        price, bought, tracking = pfm.current_price(ticker, ccy, market_ccy, uf), date.today(), "today"
    else:
        tracking = "date" if bought else "price"
    if not price:
        return None, f"{row['Name']}: couldn't get a price"
    return pfm.new_holding(kind=kind, ticker=ticker, name=name, asset_type=asset_type, currency=market_ccy,
                           quantity=qty * uf, price=price / uf, cost_currency=ccy, buy_date=bought,
                           tracking=tracking, display_unit=unit, notes="Imported from screenshot"), None


def render(pf: dict, base: str) -> None:
    st.markdown("**Import holdings from screenshots**")
    st.caption("Upload screenshots of your holdings from Sharesies, Hatch, Stake, CommSec, a crypto exchange "
               "or anywhere else. Claude reads them, you check the results, then add them in one go.")
    if not key_setup():
        return

    files = st.file_uploader("Screenshots", type=["png", "jpg", "jpeg", "webp"], accept_multiple_files=True,
                             key="imp_files", label_visibility="collapsed")
    if not files:
        return
    cols = st.columns(min(len(files), 4))
    for i, f in enumerate(files):
        cols[i % 4].image(f, width=220)

    images = [f.getvalue() for f in files]
    digest = hashlib.sha256(b"".join(images)).hexdigest()
    if st.session_state.get("imp_digest") != digest:
        if not st.button(f"Scan {len(files)} screenshot{'s' if len(files) > 1 else ''}", type="primary"):
            return
        try:
            with st.spinner("Claude is reading your screenshots... (usually 10–40 seconds)"):
                result = scanner.scan(images, scanner.make_client(credentials.api_key()))
        except anthropic.AuthenticationError:
            st.error("Anthropic rejected the API key. Check it at console.anthropic.com, then save it again.")
            return
        except anthropic.PermissionDeniedError:
            st.error("This API key isn't allowed to use Claude Opus 5 - check your Anthropic console.")
            return
        except anthropic.RateLimitError:
            st.error("Rate limited by Anthropic - wait a minute and try again.")
            return
        except anthropic.APIStatusError as e:
            st.error(f"Anthropic API error ({e.status_code}): {e.message}")
            return
        except anthropic.APIConnectionError:
            st.error("Couldn't reach Anthropic - check your internet connection.")
            return
        except scanner.ScanError as e:
            st.error(str(e))
            return
        existing = {h["ticker"] for h in pf["holdings"]}
        with st.spinner("Matching holdings to market data..."):
            with ThreadPoolExecutor(8) as ex:
                rows = list(ex.map(lambda h: _match(h, existing), result["holdings"]))
        st.session_state.update(imp_digest=digest, imp_rows=rows, imp_broker=result["broker"],
                                imp_warnings=result["warnings"])

    rows = st.session_state.get("imp_rows", [])
    if not rows:
        st.warning("No holdings found in these screenshots. Try a screenshot of your portfolio/holdings list.")
        return
    broker = st.session_state.get("imp_broker")
    st.success(f"Found **{len(rows)}** holding{'s' if len(rows) != 1 else ''}"
               + (f" in your **{broker}** screenshot" if broker else "") + ". Check them below — you can edit "
               "any cell, untick rows to skip them, and add purchase dates if you know them.")
    for w in st.session_state.get("imp_warnings", []):
        st.warning(w, icon=":material/warning:")

    edited = st.data_editor(
        pd.DataFrame(rows), hide_index=True, width="stretch", key=f"imp_editor_{digest[:8]}",
        column_config={
            "Add": st.column_config.CheckboxColumn(width="small"),
            "Symbol": st.column_config.TextColumn(help="Yahoo Finance symbol, e.g. FPH.NZ, BHP.AX, AAPL, "
                                                       "BTC-USD - or Gold / Silver for bullion"),
            "Name": st.column_config.TextColumn(disabled=True),
            "Type": st.column_config.TextColumn(disabled=True, width="small"),
            "Quantity": st.column_config.NumberColumn(format="%g"),
            "Unit": st.column_config.SelectboxColumn(options=["shares", "units", *pfm.UNITS], width="small"),
            "Avg price": st.column_config.NumberColumn(format="%.4f", help="Average price paid per unit. "
                                                       "Leave empty to start tracking from today's price."),
            "Currency": st.column_config.SelectboxColumn(options=sorted({*pfm.BASE_CURRENCIES, "CAD", "JPY"}),
                                                         width="small"),
            "Bought on": st.column_config.DateColumn(format="DD/MM/YYYY", max_value=date.today(),
                                                     help="Optional - enables the value-over-time chart"),
            "Status": st.column_config.TextColumn(disabled=True),
        })
    st.caption("No avg price → tracked from today's price. Avg price but no date → returns measured from "
               "your price. Date but no price → that day's closing price is used.")

    chosen = edited[edited["Add"]]
    c1, c2 = st.columns([1, 4])
    if c1.button(f"Add {len(chosen)} holding{'s' if len(chosen) != 1 else ''}", type="primary",
                 disabled=chosen.empty):
        new, errors = [], []
        with st.spinner("Adding..."):
            for _, row in chosen.iterrows():
                h, err = build_holding(row, base)
                if err:
                    errors.append(err)
                else:
                    new.append(h)
        if errors:
            st.error("Fix these rows (nothing was added yet):\n\n" + "\n".join(f"- {e}" for e in errors))
            return
        pf["holdings"].extend(new)
        pfm.save(pf)
        for k in [k for k in st.session_state if str(k).startswith("imp_") and k != "imp_key_input"]:
            del st.session_state[k]
        st.session_state.pf_view_request = "Holdings"
        st.toast(f"Added {len(new)} holdings from your screenshots", icon=":material/check_circle:")
        st.rerun()
    if c2.button("Start over", key="imp_reset"):
        for k in [k for k in st.session_state if str(k).startswith("imp_")]:
            del st.session_state[k]
        st.rerun()
