from __future__ import annotations
import json
import logging
from pathlib import Path
from platformdirs import user_config_dir

from sfg_app2.app.utils.preset_tree import iter_leaves, find_node, new_leaf
from sfg_app2.processing.data_file import FilenamePattern

logger = logging.getLogger(__name__)


CONFIG_DIR = Path(user_config_dir("SFG-App"))
PATTERNS_FILE = CONFIG_DIR / "patterns.json"


def _as_pattern(leaf: dict) -> FilenamePattern:
    pattern = FilenamePattern.coerce(leaf.get("data") or {})
    pattern.name = leaf.get("name", "")
    return pattern


def positional_length(leaf: dict) -> int | None:
    """Token count a positional pattern claims, or None for a regex one
    (which isn't selected by token count, so it can't conflict)."""
    pattern = _as_pattern(leaf)
    return None if pattern.mode == "regex" else len(pattern.fields)

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
    `preset_tree.py`) so they can be grouped into sub-categories.
    `leaf["active"]` marks it as one of possibly-several simultaneously
    active patterns (auto-selected per filename — see `active_patterns`).

    A leaf's payload (`leaf["data"]`) is whatever
    `FilenamePattern.coerce()` accepts. The historical `{"fields": [...]}`
    still means exactly what it always did — positional parsing on "_" —
    so stored patterns need no migration; richer leaves add
    `"delimiter"`, `"mode": "regex"` and `"regex"`.
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
        "active", "data": {...}}`."""
        return list(iter_leaves(self._tree))

    @property
    def active_patterns(self) -> list[FilenamePattern]:
        """Active patterns — ready to pass to load_datafiles(patterns=...)."""
        return [_as_pattern(p) for p in self.all_patterns if p.get("active")]

    def set_active(self, leaf_id: str, active: bool) -> str | None:
        """Activate/deactivate a pattern. Returns a warning message if a
        length conflict exists, None if the change was applied cleanly.
        """
        target = find_node(self._tree, leaf_id)
        if target is None:
            return None
        target_len = positional_length(target)
        if target_len is None:
            # Regex patterns are chosen by inspecting the filename, not
            # by token count, so they can never collide this way.
            target["active"] = active
            return None

        if active:
            for p in self.all_patterns:
                if (p["id"] != leaf_id and p.get("active")
                        and positional_length(p) == target_len):
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
        target_len = positional_length(target)
        for p in self.all_patterns:
            if (p["id"] != leaf_id and p.get("active")
                    and target_len is not None and positional_length(p) == target_len):
                p["active"] = False
        target["active"] = True

    def active_lengths(self) -> list[int]:
        lengths = (positional_length(p) for p in self.all_patterns if p.get("active"))
        return sorted(n for n in lengths if n is not None)
