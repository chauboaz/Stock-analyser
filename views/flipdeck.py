"""Flip-through deck for the Top 10 buys / sells.

Each stock is a full-height card: its 1-year price line runs across a dark background with the
details on top. Scrolling stacks the next card over the current one; the covered card sinks back,
drifts and tilts slightly from its top-right corner, dims, then fades away - and the new card's
text rises into place. Wheel scrolling is smoothed and settles on whole cards. "Open full chart"
sends the ticker back to Python.
"""
import pandas as pd
import streamlit as st

from analyser import data
from analyser import signals as sg

CSS = r"""
:host { display: block; }
.deck { position: relative; height: min(76vh, 700px); min-height: 520px; border-radius: 16px; overflow: hidden;
        background: #010403; container-type: inline-size; outline: none; }
.scroller { position: absolute; inset: 0; overflow-y: auto; scrollbar-width: none; }
.scroller::-webkit-scrollbar { display: none; }
.card { position: sticky; top: 0; height: 100%; overflow: hidden; border-radius: 16px 16px 0 0;
        transform-origin: right top; will-change: transform, opacity; backface-visibility: hidden; }
.card::after { content: ""; position: absolute; inset: 0; background: #000; opacity: var(--shade, 0);
               pointer-events: none; }
.card.buy  { background: linear-gradient(180deg, #010503 0%, #03140b 45%, #0a3a22 100%); --line: #4ade80; --glow: rgba(74,222,128,.20); }
.card.sell { background: linear-gradient(180deg, #050102 0%, #1c0710 45%, #4a0e1f 100%); --line: #ff8fa3; --glow: rgba(255,143,163,.20); }
.chart { position: absolute; left: 0; right: 0; bottom: 7%; height: 42%; width: 100%; pointer-events: none; }
.chart path.line { fill: none; stroke: var(--line); stroke-width: 2; vector-effect: non-scaling-stroke; }
.content { position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; text-align: center;
           padding: 6% 48px 0; color: #f5f8fb; gap: 10px; }
/* text rises into place when the card arrives (time-based, staggered) */
.content > * { opacity: 0; transform: translateY(40px);
               transition: opacity 1s cubic-bezier(.2,.7,.2,1), transform 1.3s cubic-bezier(.2,.7,.2,1); }
.card.inview .content > * { opacity: 1; transform: none; }
.card.inview .content > :nth-child(2) { transition-delay: 0.10s; }
.card.inview .content > :nth-child(3) { transition-delay: 0.19s; }
.card.inview .content > :nth-child(4) { transition-delay: 0.29s; }
.card.inview .content > :nth-child(5) { transition-delay: 0.38s; }
.card.inview .content > :nth-child(6) { transition-delay: 0.48s; }
.eyebrow { font-size: 12px; letter-spacing: .18em; text-transform: uppercase; color: rgba(245,248,251,.62); }
.ticker { font-size: clamp(38px, 9cqi, 68px); font-weight: 800; line-height: 1; letter-spacing: -.02em; margin: 2px 0 0; }
.name { font-size: clamp(14px, 2.6cqi, 19px); color: rgba(245,248,251,.75); font-weight: 300; }
.facts { display: flex; flex-wrap: wrap; gap: 8px; justify-content: center; margin-top: 4px; }
.pill { font-size: 13px; padding: 5px 12px; border-radius: 999px; background: rgba(255,255,255,.08); color: #f5f8fb;
        border: 1px solid rgba(255,255,255,.12); white-space: nowrap; }
.pill.verdict.buy { background: rgba(34,197,94,.2); border-color: rgba(34,197,94,.55); color: #c6f6d5; }
.pill.verdict.sell { background: rgba(239,68,68,.2); border-color: rgba(239,68,68,.55); color: #ffd0d0; }
.reasons { list-style: none; margin: 8px 0 0; padding: 0; max-width: 720px; display: grid; gap: 6px; }
.reasons li { font-size: 13.5px; line-height: 1.45; color: rgba(245,248,251,.86); background: rgba(1,4,3,.72);
              border-radius: 10px; padding: 7px 12px; }
.reasons b { color: #fff; font-weight: 600; }
.actions { display: flex; gap: 10px; margin-top: 10px; flex-wrap: wrap; justify-content: center; }
.btn { font: inherit; font-size: 14px; font-weight: 600; padding: 9px 18px; border-radius: 999px; cursor: pointer;
       border: 1px solid rgba(255,255,255,.35); background: #f5f8fb; color: #03140b; text-decoration: none; }
.btn.ghost { background: transparent; color: #f5f8fb; }
.btn:hover { filter: brightness(1.08); }
.btn:focus-visible, .dot:focus-visible { outline: 2px solid var(--line); outline-offset: 3px; }
.foot { position: absolute; left: 20px; right: 20px; bottom: 14px; display: flex; justify-content: space-between; gap: 12px;
        font-size: 11.5px; color: rgba(245,248,251,.55); pointer-events: none; }
.rail { position: absolute; right: 10px; top: 50%; transform: translateY(-50%); display: grid; gap: 6px; z-index: 50; }
.dot { width: 24px; height: 20px; border-radius: 6px; border: 0; cursor: pointer; font: inherit; font-size: 10.5px;
       background: rgba(255,255,255,.08); color: rgba(255,255,255,.55); transition: background .3s, color .3s; }
.dot.on { background: rgba(255,255,255,.9); color: #03140b; font-weight: 700; }
/* half-width decks (buys and sells side by side) */
@container (max-width: 620px) {
  .content { padding: 7% 40px 0; gap: 8px; }
  .reasons li { font-size: 12.5px; padding: 6px 10px; }
  .reasons li:nth-child(n+3) { display: none; }
  .foot .graph { display: none; }
}
@media (prefers-reduced-motion: reduce) {
  .card { transform: none !important; } .content > * { transition: none; opacity: 1; transform: none; }
}
"""

JS = r"""
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const clamp = (v, lo, hi) => Math.min(Math.max(v, lo), hi);

function linePath(values) {
  const n = values.length, lo = Math.min(...values), hi = Math.max(...values), span = (hi - lo) || 1;
  return values.map((v, i) => `${i ? "L" : "M"}${(i / (n - 1) * 1000).toFixed(1)},${(380 - (v - lo) / span * 360).toFixed(1)}`).join("");
}

function card(s, i, n, side) {
  const path = linePath(s.closes);
  const reasons = s.reasons.map(r => `<li><b>${esc(r.label)}:</b> ${esc(r.summary)}</li>`).join("");
  const chg = s.change_1y == null ? "" : `<span class="pill">1Y ${s.change_1y >= 0 ? "+" : ""}${s.change_1y.toFixed(1)}%</span>`;
  return `
  <section class="card ${side}">
    <svg class="chart" viewBox="0 0 1000 400" preserveAspectRatio="none" aria-hidden="true">
      <defs><linearGradient id="g${side}${i}" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" style="stop-color: var(--glow)"/><stop offset="1" style="stop-color: transparent"/></linearGradient></defs>
      <path d="${path}L1000,400L0,400Z" fill="url(#g${side}${i})"/>
      <path class="line" d="${path}"/>
    </svg>
    <div class="content">
      <div class="eyebrow">Top ${side} &middot; ${String(i + 1).padStart(2, "0")} / ${String(n).padStart(2, "0")}</div>
      <h2 class="ticker">${esc(s.ticker)}</h2>
      <div class="name">${esc(s.name)}</div>
      <div class="facts">
        <span class="pill verdict ${side}">${esc(s.verdict)} ${s.score > 0 ? "+" : ""}${s.score}</span>
        <span class="pill">${esc(s.price)}</span>${chg}
      </div>
      <ul class="reasons">${reasons}</ul>
      <div class="actions">
        <button class="btn" data-open="${esc(s.ticker)}">Open full chart &rarr;</button>
        <a class="btn ghost" href="https://finance.yahoo.com/quote/${encodeURIComponent(s.ticker)}/chart" target="_blank" rel="noopener">Yahoo &#8599;</a>
      </div>
    </div>
    <div class="foot">
      <span>${i < n - 1 ? "Scroll to turn the page &darr;" : "End of the top " + n}</span>
      <span class="graph">Graph: ${esc(s.ticker)} daily close, last 12 months</span>
    </div>
  </section>`;
}

export default function (component) {
  const { data, parentElement, setTriggerValue } = component;
  const root = parentElement.querySelector(".deck");
  const stocks = data.stocks || [], side = data.side, n = stocks.length;
  const memo = parentElement.__deck || (parentElement.__deck = {});
  const sig = side + stocks.map(s => s.ticker + s.score).join();
  if (memo.sig === sig) return;                       // same deck as last render: keep position
  memo.sig = sig;
  if (memo.stop) memo.stop();

  root.innerHTML = `<div class="scroller">${stocks.map((s, i) => card(s, i, n, side)).join("")}</div>
    <nav class="rail" aria-label="Pages">${stocks.map((s, i) =>
      `<button class="dot" data-go="${i}" title="${esc(s.ticker)}" aria-label="Go to ${esc(s.ticker)}">${i + 1}</button>`).join("")}</nav>`;
  const scroller = root.querySelector(".scroller");
  const cards = [...root.querySelectorAll(".card")];
  const dots = [...root.querySelectorAll(".dot")];
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const H = () => scroller.clientHeight;

  // The card being covered (progress p: 0 -> 1 as the next card slides over it) sinks back, drifts
  // down-right and tilts ~2deg from its top-right corner, dims by up to 10%, and only starts to fade
  // in the last third of the turn - so the stack reads like pages being laid down.
  function paint() {
    const h = H(), y = scroller.scrollTop;
    cards.forEach((c, i) => {
      const p = clamp((y - i * h) / h, 0, 1);
      if (!reduce && i < n - 1) {
        c.style.transform = `perspective(400px) translate3d(${20 * p}px, ${70 * p}px, ${-50 * p}px) rotate(${2 * p}deg)`;
        c.style.opacity = String(p >= 1 ? 0 : 1 - Math.max(0, p - .65) * .6 / .35);
        c.style.setProperty("--shade", (p * .1).toFixed(3));
      }
      const visible = (i * h - y) < h * .5 && p < 1;  // at least half on screen
      c.classList.toggle("inview", visible);
    });
    const active = clamp(Math.round(y / h), 0, n - 1);
    dots.forEach((d, i) => d.classList.toggle("on", i === active));
  }

  // smooth (eased) wheel scrolling that settles on whole cards; hands the wheel back to the page
  // at either end of the deck so you can keep scrolling past it
  let target = scroller.scrollTop, raf = 0, idle = 0, alive = true, page = Math.round(target / H());
  const maxY = () => (n - 1) * H();
  function tick() {
    const cur = scroller.scrollTop, next = cur + (target - cur) * .055;   // lower = slower glide
    scroller.scrollTop = Math.abs(target - next) < .5 ? target : next;
    paint();
    raf = alive && Math.abs(scroller.scrollTop - target) > .5 ? requestAnimationFrame(tick) : 0;
  }
  const go = (y) => { target = clamp(y, 0, maxY()); if (!raf) raf = requestAnimationFrame(tick); };
  const goPage = (i) => { page = clamp(i, 0, n - 1); go(page * H()); };
  // a deliberate scroll (>15% of a card) turns the page in that direction, like flicking a book
  function settle() {
    const moved = target / H() - page;
    goPage(Math.abs(moved) < .15 ? page : page + Math.sign(moved) * Math.max(1, Math.round(Math.abs(moved))));
  }

  scroller.addEventListener("wheel", (e) => {
    const atStart = target <= 0 && e.deltaY < 0, atEnd = target >= maxY() - 1 && e.deltaY > 0;
    if (atStart || atEnd) return;                     // let the page scroll
    e.preventDefault();
    go(target + e.deltaY * (e.deltaMode === 1 ? 40 : 1));
    clearTimeout(idle); idle = setTimeout(settle, 260);
  }, { passive: false });
  // touch / scrollbar / keyboard scrolling: follow it, then settle on a card
  scroller.addEventListener("scroll", () => {
    if (!raf) { target = scroller.scrollTop; requestAnimationFrame(paint); clearTimeout(idle); idle = setTimeout(settle, 160); }
  }, { passive: true });
  root.addEventListener("click", (e) => {
    const d = e.target.closest("[data-go]"), open = e.target.closest("[data-open]");
    if (d) goPage(+d.dataset.go);
    if (open) setTriggerValue("open", open.dataset.open);
  });
  root.tabIndex = 0;
  root.addEventListener("keydown", (e) => {
    const step = { ArrowDown: 1, PageDown: 1, ArrowUp: -1, PageUp: -1 }[e.key];
    if (step) { e.preventDefault(); goPage(page + step); }
  });
  memo.stop = () => { alive = false; cancelAnimationFrame(raf); clearTimeout(idle); };
  paint();
}
"""

_deck = st.components.v2.component("signal_flip_deck", html='<div class="deck"></div>', css=CSS, js=JS)


def _stock_payload(row: pd.Series, enabled: list[str], weights: dict) -> dict:
    daily = data.get_history(row["Ticker"], "5y")
    closes = daily["Close"].tail(252)
    ccy = data.get_currency(row["Ticker"])[0]
    checks = row["checks"]
    top = sorted((k for k in enabled if checks[k]["score"] is not None),
                 key=lambda k: -abs(checks[k]["score"] * weights[k]))
    side_sign = 1 if row["Score"] > 0 else -1
    reasons = [{"label": sg.CHECKS[k], "summary": checks[k]["summary"]}
               for k in top if checks[k]["score"] * side_sign > 0][:3] or \
              [{"label": sg.CHECKS[k], "summary": checks[k]["summary"]} for k in top[:2]]
    return {"ticker": row["Ticker"], "name": row["Name"], "score": int(row["Score"]), "verdict": row["Verdict"],
            "price": f"{row['Price']:,.2f} {ccy}",
            "change_1y": float((closes.iloc[-1] / closes.iloc[0] - 1) * 100) if len(closes) > 20 else None,
            "closes": [round(float(v), 4) for v in closes.values], "reasons": reasons}


def flip_deck(df: pd.DataFrame, side: str, enabled: list[str], weights: dict, key: str) -> str | None:
    """Render the deck for 'buy' or 'sell'. Returns the ticker whose 'Open full chart' was clicked."""
    stocks = [_stock_payload(row, enabled, weights) for _, row in df.iterrows()]
    result = _deck(data={"side": side, "stocks": stocks}, key=key, on_open_change=lambda: None)
    return result.open if result else None
