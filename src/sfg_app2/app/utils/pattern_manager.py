from __future__ import annotations
import json
import logging
from pathlib import Path
from platformdirs import user_config_dir

from sfg_app2.app.utils.preset_tree import iter_leaves, find_node, new_leaf

logger = logging.getLogger(__name__)

CONFIG_DIR = Path(user_config_dir("SFG-App"))
PATTERNS_FILE = CONFIG_DIR / "patterns.json"

DEFAULT_TREE = [
    new_leaf(
        "6-field standard",
        {"fields": ["sample", "polarization", "center_wavelength",
                    "acquisition_time", "timestamp", "date"]},
        active=True,
    ),
    new_leaf(
        "8-field with concentration and potential",
        {"fields": ["sample", "concentration", "potential", "polarization",
                    "center_wavelength", "acquisition_time", "timestamp", "date"]},
        active=False,
    ),
]


class PatternManager:
    """Load, save, and validate metadata patterns from persistent config.

    Patterns are organized as a tree (folders + leaves, see
    `preset_tree.py`) so they can be grouped into sub-categories. Each
    leaf's payload (`leaf["data"]`) holds `{"fields": [...]}`; `leaf["active"]`
    marks it as one of possibly-several simultaneously active patterns
    (auto-selected by filename part count — see `active_patterns`).
    """

    def __init__(self):
        self._tree: list[dict] = []
        self.load()

    def load(self):
        try:
            if PATTERNS_FILE.exists():
                raw = json.loads(PATTERNS_FILE.read_text())
                if "tree" in raw:
                    self._tree = raw["tree"]
                else:
                    # legacy flat {"patterns": [...]} format — migrate to a
                    # root-level leaf per pattern, preserving name/fields/active
                    self._tree = [
                        new_leaf(p["name"], {"fields": p["fields"]}, active=p.get("active", False))
                        for p in raw.get("patterns", [])
                    ]
                    logger.info("Migrated legacy patterns.json to tree format.")
                    self.save()
                logger.info("Loaded %d pattern(s) from %s.", len(self.all_patterns), PATTERNS_FILE)
            else:
                self._tree = DEFAULT_TREE
                logger.info("No patterns file found — using defaults.")
        except Exception as e:
            logger.warning("Failed to load patterns: %s — using defaults.", e)
            self._tree = DEFAULT_TREE

    def save(self) -> bool:
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            PATTERNS_FILE.write_text(json.dumps({"tree": self._tree}, indent=2))
            logger.info("Patterns saved to %s.", PATTERNS_FILE)
            return True
        except Exception as e:
            logger.error("Failed to save patterns: %s", e)
            return False

    @property
    def tree(self) -> list[dict]:
        return self._tree

    @property
    def all_patterns(self) -> list[dict]:
        """Flattened leaves, regardless of folder — each `{"id", "name",
        "active", "data": {"fields": [...]}}`."""
        return list(iter_leaves(self._tree))

    @property
    def active_patterns(self) -> list[list[str]]:
        """Returns active field lists — ready to pass to load_datafiles(patterns=...)."""
        return [p["data"]["fields"] for p in self.all_patterns if p.get("active")]

    def set_active(self, leaf_id: str, active: bool) -> str | None:
        """Activate/deactivate a pattern. Returns a warning message if a
        length conflict exists, None if the change was applied cleanly.
        """
        target = find_node(self._tree, leaf_id)
        if target is None:
            return None
        target_len = len(target["data"]["fields"])

        if active:
            for p in self.all_patterns:
                if p["id"] != leaf_id and p.get("active") and len(p["data"]["fields"]) == target_len:
                    return (
                        f"Pattern \"{p['name']}\" is already active with "
                        f"{target_len} fields. Activating this will replace it."
                    )

        target["active"] = active
        return None

    def resolve_conflict(self, leaf_id: str):
        """Force-activate the pattern at leaf_id, deactivating any conflicting pattern."""
        target = find_node(self._tree, leaf_id)
        if target is None:
            return
        target_len = len(target["data"]["fields"])
        for p in self.all_patterns:
            if p["id"] != leaf_id and p.get("active") and len(p["data"]["fields"]) == target_len:
                p["active"] = False
        target["active"] = True

    def active_lengths(self) -> list[int]:
        return sorted(len(p["data"]["fields"]) for p in self.all_patterns if p.get("active"))
