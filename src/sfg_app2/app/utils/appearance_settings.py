from __future__ import annotations
import json
import logging
from pathlib import Path
from platformdirs import user_config_dir

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication

logger = logging.getLogger(__name__)

CONFIG_DIR = Path(user_config_dir("SFG-App"))
SETTINGS_FILE = CONFIG_DIR / "appearance_settings.json"

THEMES = ("light", "dark", "system")
DEFAULT_THEME = "system"

_COLOR_SCHEME = {
    "light": Qt.ColorScheme.Light,
    "dark": Qt.ColorScheme.Dark,
    "system": Qt.ColorScheme.Unknown,
}


class AppearanceSettings:
    """Load, save, and apply the user's chosen Qt widget color scheme
    (Light / Dark / follow the OS)."""

    def __init__(self):
        self._theme: str = DEFAULT_THEME
        self.load()

    def load(self):
        try:
            if SETTINGS_FILE.exists():
                data = json.loads(SETTINGS_FILE.read_text())
                theme = data.get("theme", DEFAULT_THEME)
                self._theme = theme if theme in THEMES else DEFAULT_THEME
                logger.info("Loaded appearance theme '%s' from %s.", self._theme, SETTINGS_FILE)
            else:
                self._theme = DEFAULT_THEME
                logger.info("No appearance settings file found — using default '%s'.", DEFAULT_THEME)
        except Exception as e:
            logger.warning("Failed to load appearance settings: %s — using default.", e)
            self._theme = DEFAULT_THEME

    def save(self) -> bool:
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            SETTINGS_FILE.write_text(json.dumps({"theme": self._theme}, indent=2))
            logger.info("Appearance settings saved to %s.", SETTINGS_FILE)
            return True
        except Exception as e:
            logger.error("Failed to save appearance settings: %s", e)
            return False

    @property
    def theme(self) -> str:
        return self._theme

    def apply_current(self):
        app = QGuiApplication.instance()
        if app is not None:
            app.styleHints().setColorScheme(_COLOR_SCHEME[self._theme])

    def set_theme(self, theme: str) -> bool:
        self._theme = theme
        saved = self.save()
        self.apply_current()
        return saved
