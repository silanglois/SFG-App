from __future__ import annotations
import json
import logging
from pathlib import Path
from platformdirs import user_config_dir

logger = logging.getLogger(__name__)

CONFIG_DIR = Path(user_config_dir("SFG-App"))
SETTINGS_FILE = CONFIG_DIR / "recent_paths.json"

# Falls back to whichever folder was most recently used in ANY category --
# read only by get_last_dir() when the requested category has no history
# of its own yet, so the very first visit to a category defaults somewhere
# sensible instead of the bare OS default. Every remember_dir() call updates
# this alongside its own category.
_GLOBAL_KEY = "_global"


class RecentPathsSettings:
    """Remembers the last folder browsed to per file-dialog category.

    Deliberately machine/session state, not a portable preference --
    excluded from settings_bundle.PARTS for the same reason
    dock_layout_settings is (see that module's comment).
    """

    def __init__(self):
        self._dirs: dict[str, str] = {}
        self.load()

    def load(self):
        try:
            if SETTINGS_FILE.exists():
                data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
                self._dirs = {k: v for k, v in data.items() if isinstance(v, str)}
            else:
                self._dirs = {}
        except Exception as e:
            logger.warning("Failed to load recent paths: %s — starting empty.", e)
            self._dirs = {}

    def save(self) -> bool:
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            SETTINGS_FILE.write_text(json.dumps(self._dirs, indent=2), encoding="utf-8")
            return True
        except Exception as e:
            logger.error("Failed to save recent paths: %s", e)
            return False

    def get(self, category: str) -> str:
        for key in (category, _GLOBAL_KEY):
            candidate = self._dirs.get(key, "")
            if candidate and Path(candidate).is_dir():
                return candidate
        return ""

    def remember(self, category: str, path: str | Path) -> None:
        path = Path(path)
        directory = path if path.is_dir() else path.parent
        self._dirs[category] = str(directory)
        self._dirs[_GLOBAL_KEY] = str(directory)
        self.save()


def get_last_dir(category: str) -> str:
    """The remembered starting directory for this dialog category, or
    "" if none is known yet (Qt then falls back to its own default)."""
    return RecentPathsSettings().get(category)


def remember_dir(category: str, path: str | Path) -> None:
    """Call after a successful file/folder pick with the chosen path
    (a file or a directory -- either is resolved to its containing
    directory automatically)."""
    RecentPathsSettings().remember(category, path)
