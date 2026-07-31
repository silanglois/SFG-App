from __future__ import annotations
import json
import logging
from pathlib import Path
from platformdirs import user_config_dir

logger = logging.getLogger(__name__)

CONFIG_DIR = Path(user_config_dir("SFG-App"))
SETTINGS_FILE = CONFIG_DIR / "color_coding_settings.json"

MODES = ("single", "multiple", "role")
SCOPES = ("file_list", "match_table", "both")


class ColorCodingSettings:
    """Load, save, and hold the user's filename color-coding preferences
    for the Load/Match tab. Off by default."""

    def __init__(self):
        self.enabled: bool = False
        self.mode: str = "single"
        self.fields: list[str] = []
        self.scope: str = "file_list"
        self.load()

    def load(self):
        try:
            if SETTINGS_FILE.exists():
                data = json.loads(SETTINGS_FILE.read_text())
                self.enabled = bool(data.get("enabled", False))
                mode = data.get("mode", "single")
                self.mode = mode if mode in MODES else "single"
                self.fields = list(data.get("fields", []))
                scope = data.get("scope", "file_list")
                self.scope = scope if scope in SCOPES else "file_list"
                logger.info("Loaded color-coding settings from %s.", SETTINGS_FILE)
            else:
                logger.info("No color-coding settings file found — using defaults (off).")
        except Exception as e:
            logger.warning("Failed to load color-coding settings: %s — using defaults.", e)
            self.enabled = False
            self.mode = "single"
            self.fields = []
            self.scope = "file_list"

    def save(self):
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            SETTINGS_FILE.write_text(json.dumps({
                "enabled": self.enabled,
                "mode": self.mode,
                "fields": self.fields,
                "scope": self.scope,
            }, indent=2))
            logger.info("Color-coding settings saved to %s.", SETTINGS_FILE)
        except Exception as e:
            logger.error("Failed to save color-coding settings: %s", e)
