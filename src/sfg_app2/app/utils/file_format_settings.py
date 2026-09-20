from __future__ import annotations
import json
import logging
from pathlib import Path
from platformdirs import user_config_dir

from sfg_app2.processing.readers import ReadOptions

logger = logging.getLogger(__name__)

CONFIG_DIR = Path(user_config_dir("SFG-App"))
SETTINGS_FILE = CONFIG_DIR / "file_format_settings.json"


class FileFormatSettings:
    """How raw files should be read: separator, decimal mark, encoding,
    lines to skip, and which columns mean what.

    Persisted so an instrument that needs, say, semicolons and a decimal
    comma is configured once rather than per session. The stored
    defaults are `ReadOptions()`'s, which reproduce a plain
    `pd.read_csv(path)` — so a user who never opens the dialog sees the
    behaviour this app always had.
    """

    def __init__(self):
        self._options = ReadOptions()
        self.load()

    def load(self):
        try:
            if SETTINGS_FILE.exists():
                self._options = ReadOptions.from_dict(json.loads(SETTINGS_FILE.read_text()))
                logger.info("Loaded file-format settings from %s.", SETTINGS_FILE)
            else:
                self._options = ReadOptions()
                logger.info("No file-format settings file found — using defaults.")
        except Exception as e:
            logger.warning("Failed to load file-format settings: %s — using defaults.", e)
            self._options = ReadOptions()

    def save(self) -> bool:
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            SETTINGS_FILE.write_text(json.dumps(self._options.to_dict(), indent=2))
            logger.info("File-format settings saved to %s.", SETTINGS_FILE)
            return True
        except Exception as e:
            logger.error("Failed to save file-format settings: %s", e)
            return False

    @property
    def options(self) -> ReadOptions:
        return self._options

    def set_options(self, options: ReadOptions) -> bool:
        self._options = options
        return self.save()

    def is_default(self) -> bool:
        return self._options.to_dict() == ReadOptions().to_dict()
