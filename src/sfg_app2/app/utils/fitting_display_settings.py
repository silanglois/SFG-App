from __future__ import annotations
import json
import logging
from pathlib import Path
from platformdirs import user_config_dir

logger = logging.getLogger(__name__)

CONFIG_DIR = Path(user_config_dir("SFG-App"))
SETTINGS_FILE = CONFIG_DIR / "fitting_display_settings.json"


class FittingDisplaySettings:
    """Load, save, and hold the user's Fitting-tab display preferences.
    Off by default."""

    def __init__(self):
        self.color_parameter_table_by_peak: bool = False
        self.load()

    def load(self):
        try:
            if SETTINGS_FILE.exists():
                data = json.loads(SETTINGS_FILE.read_text())
                self.color_parameter_table_by_peak = bool(
                    data.get("color_parameter_table_by_peak", False)
                )
                logger.info("Loaded fitting display settings from %s.", SETTINGS_FILE)
            else:
                logger.info("No fitting display settings file found — using defaults (off).")
        except Exception as e:
            logger.warning("Failed to load fitting display settings: %s — using defaults.", e)
            self.color_parameter_table_by_peak = False

    def save(self) -> bool:
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            SETTINGS_FILE.write_text(json.dumps({
                "color_parameter_table_by_peak": self.color_parameter_table_by_peak,
            }, indent=2))
            logger.info("Fitting display settings saved to %s.", SETTINGS_FILE)
            return True
        except Exception as e:
            logger.error("Failed to save fitting display settings: %s", e)
            return False
