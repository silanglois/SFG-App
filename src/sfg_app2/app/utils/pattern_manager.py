from __future__ import annotations
import json
import logging
from pathlib import Path
from platformdirs import user_config_dir

logger = logging.getLogger(__name__)

CONFIG_DIR = Path(user_config_dir("SFG-App"))
PATTERNS_FILE = CONFIG_DIR / "patterns.json"

DEFAULT_PATTERNS = [
    {
        "name": "6-field standard",
        "fields": ["sample", "polarization", "center_wavelength",
                   "acquisition_time", "timestamp", "date"],
        "active": True,
    },
    {
        "name": "8-field with concentration and potential",
        "fields": ["sample", "concentration", "potential", "polarization",
                   "center_wavelength", "acquisition_time", "timestamp", "date"],
        "active": False,
    },
]


class PatternManager:
    """Load, save, and validate metadata patterns from persistent config."""

    def __init__(self):
        self._patterns: list[dict] = []
        self.load()

    def load(self):
        try:
            if PATTERNS_FILE.exists():
                self._patterns = json.loads(PATTERNS_FILE.read_text())["patterns"]
                logger.info("Loaded %d patterns from %s.", len(self._patterns), PATTERNS_FILE)
            else:
                self._patterns = DEFAULT_PATTERNS
                logger.info("No patterns file found — using defaults.")
        except Exception as e:
            logger.warning("Failed to load patterns: %s — using defaults.", e)
            self._patterns = DEFAULT_PATTERNS

    def save(self):
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            PATTERNS_FILE.write_text(json.dumps({"patterns": self._patterns}, indent=2))
            logger.info("Patterns saved to %s.", PATTERNS_FILE)
        except Exception as e:
            logger.error("Failed to save patterns: %s", e)

    @property
    def all_patterns(self) -> list[dict]:
        return self._patterns

    @property
    def active_patterns(self) -> list[list[str]]:
        """Returns active field lists — ready to pass to load_datafiles(patterns=...)."""
        return [p["fields"] for p in self._patterns if p.get("active")]

    def set_active(self, index: int, active: bool) -> str | None:
        """Activate/deactivate a pattern. Returns a warning message if a
        length conflict exists, None if the change was applied cleanly.
        """
        target = self._patterns[index]
        target_len = len(target["fields"])

        if active:
            # check for length conflict with other active patterns
            for i, p in enumerate(self._patterns):
                if i != index and p.get("active") and len(p["fields"]) == target_len:
                    return (
                        f"Pattern \"{p['name']}\" is already active with "
                        f"{target_len} fields. Activating this will replace it."
                    )

        self._patterns[index]["active"] = active
        return None

    def resolve_conflict(self, index: int):
        """Force-activate pattern at index, deactivating any conflicting pattern."""
        target_len = len(self._patterns[index]["fields"])
        for i, p in enumerate(self._patterns):
            if i != index and p.get("active") and len(p["fields"]) == target_len:
                p["active"] = False
        self._patterns[index]["active"] = True

    def active_lengths(self) -> list[int]:
        return sorted(len(p["fields"]) for p in self._patterns if p.get("active"))