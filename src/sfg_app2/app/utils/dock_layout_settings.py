from __future__ import annotations
import base64
import json
import logging
from pathlib import Path
from platformdirs import user_config_dir

logger = logging.getLogger(__name__)

CONFIG_DIR = Path(user_config_dir("SFG-App"))
SETTINGS_FILE = CONFIG_DIR / "dock_layout_settings.json"


class DockLayoutSettings:
    """Load, save, and expose per-panel QMainWindow.saveState() blobs
    (base64-encoded for JSON), keyed by an arbitrary panel name (e.g.
    "homodyne", "hd_sfg"). QMainWindow.restoreState() silently ignores
    dock object names it doesn't recognize, so a saved layout stays valid
    even after docks are added/removed/renamed in a later version.
    """

    def __init__(self):
        self._layouts: dict[str, str] = {}
        self.load()

    def load(self):
        try:
            if SETTINGS_FILE.exists():
                data = json.loads(SETTINGS_FILE.read_text())
                self._layouts = data.get("layouts", {})
                logger.info(
                    "Loaded %d dock layout(s) from %s.", len(self._layouts), SETTINGS_FILE,
                )
            else:
                self._layouts = {}
                logger.info("No dock layout settings file found — using defaults.")
        except Exception as e:
            logger.warning("Failed to load dock layout settings: %s — using defaults.", e)
            self._layouts = {}

    def save(self) -> bool:
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            SETTINGS_FILE.write_text(json.dumps({"layouts": self._layouts}, indent=2))
            logger.info("Dock layout settings saved to %s.", SETTINGS_FILE)
            return True
        except Exception as e:
            logger.error("Failed to save dock layout settings: %s", e)
            return False

    def get(self, key: str) -> bytes | None:
        encoded = self._layouts.get(key)
        if not encoded:
            return None
        try:
            return base64.b64decode(encoded)
        except Exception as e:
            logger.warning("Could not decode dock layout '%s': %s", key, e)
            return None

    def set(self, key: str, state: bytes):
        self._layouts[key] = base64.b64encode(state).decode("ascii")
