"""App preferences (theme, signal settings) saved in user_data/settings.json."""
import json

from .portfolio import DATA_DIR

SETTINGS_FILE = DATA_DIR / "settings.json"


def get(key: str, default=None):
    try:
        return json.loads(SETTINGS_FILE.read_text(encoding="utf-8")).get(key, default)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def put(key: str, value) -> None:
    try:
        settings = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        settings = {}
    settings[key] = value
    SETTINGS_FILE.parent.mkdir(exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(settings, indent=2), encoding="utf-8")
