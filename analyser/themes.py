"""Colour themes, applied live by rewriting Streamlit's theme config and rerunning."""
import streamlit as st
from streamlit import config

from . import settings

THEMES = {
    "Light": dict(base="light", primaryColor="#2563eb", backgroundColor="#ffffff",
                  secondaryBackgroundColor="#f4f6fa", textColor="#0f172a", font="sans-serif",
                  sidebar_bg="#f8fafc", borderColor="#e5e7eb"),
    "Dark": dict(base="dark", primaryColor="#60a5fa", backgroundColor="#0e1117",
                 secondaryBackgroundColor="#1a1f2b", textColor="#e6e8ec", font="sans-serif",
                 sidebar_bg="#141821"),
    "Midnight": dict(base="dark", primaryColor="#38bdf8", backgroundColor="#0b1426",
                     secondaryBackgroundColor="#14223f", textColor="#dbe7ff", font="sans-serif",
                     sidebar_bg="#0f1b33"),
    "Terminal": dict(base="dark", primaryColor="#ffb000", backgroundColor="#000000",
                     secondaryBackgroundColor="#141414", textColor="#e8e8e8", font="monospace",
                     sidebar_bg="#0a0a0a", greenColor="#00d26a", redColor="#ff4d4d", baseRadius="none",
                     metricValueFontSize="1.75rem"),   # monospace digits are wide
    "Emerald": dict(base="dark", primaryColor="#34d399", backgroundColor="#0b1a17",
                    secondaryBackgroundColor="#12302a", textColor="#e3f5ef", font="sans-serif",
                    sidebar_bg="#0f231f"),
    "Paper": dict(base="light", primaryColor="#b45309", backgroundColor="#faf7f2",
                  secondaryBackgroundColor="#efe8dc", textColor="#2d2a26", font="serif",
                  sidebar_bg="#f3eee5"),
    "Rose": dict(base="light", primaryColor="#e11d48", backgroundColor="#fff8f9",
                 secondaryBackgroundColor="#fde7ec", textColor="#3b0a17", font="sans-serif",
                 sidebar_bg="#fff0f3", baseRadius="large"),
}
DEFAULT_THEME = "Dark"

# every option any theme sets - reset to None when a theme doesn't use it
_KEYS = ["base", "primaryColor", "backgroundColor", "secondaryBackgroundColor", "textColor", "font",
         "greenColor", "redColor", "baseRadius", "metricValueFontSize", "borderColor"]


def _options(name: str) -> dict:
    t = THEMES[name]
    opts = {f"theme.{k}": t.get(k) for k in _KEYS}
    opts["theme.sidebar.backgroundColor"] = t.get("sidebar_bg")
    return opts


def saved_theme() -> str:
    name = settings.get("theme")
    if name and name not in THEMES:          # older saves used emoji names, e.g. "☀️ Light"
        name = name.split()[-1]
    return name if name in THEMES else DEFAULT_THEME


def apply(name: str) -> None:
    """Make `name` the active theme. Streamlit sends the theme at the start of each run, so if
    the config changes we rerun once for the browser to pick it up."""
    opts = _options(name)
    if any(config.get_option(k) != v for k, v in opts.items()):
        for k, v in opts.items():
            config.set_option(k, v)
        st.rerun()


def is_dark(name: str) -> bool:
    return THEMES[name]["base"] == "dark"


def picker() -> str:
    """Sidebar theme selector. Returns the active theme name."""
    if "theme" not in st.session_state:
        st.session_state.theme = saved_theme()
    name = st.selectbox("Theme", list(THEMES), key="theme",
                        on_change=lambda: settings.put("theme", st.session_state.theme))
    apply(name)
    return name
