"""Where the Anthropic API key comes from.

Order: ANTHROPIC_API_KEY environment variable, then a key saved from the app. Saved keys live in
the Windows user folder (~/.stock_analyser), NOT the project folder - the project sits in OneDrive,
which would sync the key to the cloud.
"""
import os
from pathlib import Path

KEY_FILE = Path.home() / ".stock_analyser" / "anthropic_api_key"


def api_key() -> str | None:
    if os.environ.get("ANTHROPIC_API_KEY"):
        return os.environ["ANTHROPIC_API_KEY"]
    try:
        return KEY_FILE.read_text(encoding="utf-8").strip() or None
    except FileNotFoundError:
        return None


def key_source() -> str | None:
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "environment variable"
    return "saved key" if KEY_FILE.exists() else None


def save_key(key: str) -> None:
    KEY_FILE.parent.mkdir(exist_ok=True)
    KEY_FILE.write_text(key.strip(), encoding="utf-8")


def forget_key() -> None:
    KEY_FILE.unlink(missing_ok=True)
