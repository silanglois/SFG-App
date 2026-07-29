from __future__ import annotations
import copy
import json
import logging
from pathlib import Path
from platformdirs import user_config_dir

from sfg_app2.processing.matcher import MatchingConfig, DEFAULT_SAMPLE_KEY
from sfg_app2.processing.utils import DEFAULT_ROLE_SUFFIXES
from sfg_app2.app.utils.preset_tree import new_leaf, iter_leaves

logger = logging.getLogger(__name__)

CONFIG_DIR = Path(user_config_dir("SFG-App"))
SETTINGS_FILE = CONFIG_DIR / "matching_settings.json"

DEFAULT_REFERENCE_NAMES = ["Au", "gold", "quartz"]
DEFAULT_BACKGROUND_REQUIRED_KEYS = ["polarization", "date"]
DEFAULT_BACKGROUND_OPTIONAL_KEYS = ["center_wavelength", "acquisition_time"]
DEFAULT_BACKGROUND_CLOSEST_KEYS = ["timestamp"]
DEFAULT_REFERENCE_REQUIRED_KEYS = ["polarization"]
DEFAULT_REFERENCE_OPTIONAL_KEYS = ["center_wavelength"]
DEFAULT_REFERENCE_CLOSEST_KEYS = ["timestamp"]
DEFAULT_TYPE_RULES: list[dict] = []
DEFAULT_BACKGROUND_ROLE_MODE = "suffix"
DEFAULT_BACKGROUND_ROLE_VALUES = sorted(DEFAULT_ROLE_SUFFIXES)
DEFAULT_BACKGROUND_ROLE_FIELD = ""

TYPE_RULE_TYPES = ("heterodyne", "homodyne")
TYPE_RULE_SCOPES = ("signal", "background", "both")
ROLE_MODES = ("suffix", "prefix", "field")

# (field name, default value) — shared by MatchingSettings.__init__,
# to_dict(), and from_dict() so all three always stay in sync.
_FIELDS = [
    ("reference_names", DEFAULT_REFERENCE_NAMES),
    ("background_required_keys", DEFAULT_BACKGROUND_REQUIRED_KEYS),
    ("background_optional_keys", DEFAULT_BACKGROUND_OPTIONAL_KEYS),
    ("background_closest_keys", DEFAULT_BACKGROUND_CLOSEST_KEYS),
    ("reference_required_keys", DEFAULT_REFERENCE_REQUIRED_KEYS),
    ("reference_optional_keys", DEFAULT_REFERENCE_OPTIONAL_KEYS),
    ("reference_closest_keys", DEFAULT_REFERENCE_CLOSEST_KEYS),
    ("type_rules", DEFAULT_TYPE_RULES),
    ("background_role_mode", DEFAULT_BACKGROUND_ROLE_MODE),
    ("background_role_values", DEFAULT_BACKGROUND_ROLE_VALUES),
    ("background_role_field", DEFAULT_BACKGROUND_ROLE_FIELD),
]


def type_rules_conflicts(type_rules: list[dict]) -> list[tuple[dict, dict]]:
    """Returns pairs of rules that contradict each other: same match
    criteria (mode + field/key), with scopes that overlap (any shared
    role), but a different forced type.
    """
    def scopes_overlap(a: str, b: str) -> bool:
        if a == "both" or b == "both":
            return True
        return a == b

    def identity(rule: dict):
        if rule.get("mode", "field") == "filename":
            return ("filename", None)
        return ("field", rule.get("field") or DEFAULT_SAMPLE_KEY)

    conflicts = []
    for i, rule_a in enumerate(type_rules):
        key_a = str(rule_a.get("key", "")).strip().lower()
        if not key_a:
            continue
        id_a = identity(rule_a)
        for rule_b in type_rules[i + 1:]:
            key_b = str(rule_b.get("key", "")).strip().lower()
            if key_a != key_b or identity(rule_b) != id_a:
                continue
            if rule_a.get("type") == rule_b.get("type"):
                continue
            if scopes_overlap(rule_a.get("scope", "both"), rule_b.get("scope", "both")):
                conflicts.append((rule_a, rule_b))
    return conflicts


class MatchingSettings:
    """The auto-matching rules for one profile: which sample names identify
    references, how background files are detected (filename suffix/prefix
    or a metadata field), which metadata keys must (required), may
    (optional), or should be matched to the nearest value (closest) between
    a signal and its background/reference candidates, and rules forcing a
    signal/background pair to homodyne or heterodyne processing.

    Persistence lives in `MatchingProfileManager` (multiple named profiles,
    organized in a tree) — this class just holds one profile's fields, with
    `to_dict()`/`from_dict()` for (de)serializing into/out of a profile
    leaf's payload.
    """

    def __init__(self):
        self.reference_names: list[str] = list(DEFAULT_REFERENCE_NAMES)
        self.background_required_keys: list[str] = list(DEFAULT_BACKGROUND_REQUIRED_KEYS)
        self.background_optional_keys: list[str] = list(DEFAULT_BACKGROUND_OPTIONAL_KEYS)
        self.background_closest_keys: list[str] = list(DEFAULT_BACKGROUND_CLOSEST_KEYS)
        self.reference_required_keys: list[str] = list(DEFAULT_REFERENCE_REQUIRED_KEYS)
        self.reference_optional_keys: list[str] = list(DEFAULT_REFERENCE_OPTIONAL_KEYS)
        self.reference_closest_keys: list[str] = list(DEFAULT_REFERENCE_CLOSEST_KEYS)
        self.type_rules: list[dict] = list(DEFAULT_TYPE_RULES)
        self.background_role_mode: str = DEFAULT_BACKGROUND_ROLE_MODE
        self.background_role_values: list[str] = list(DEFAULT_BACKGROUND_ROLE_VALUES)
        self.background_role_field: str = DEFAULT_BACKGROUND_ROLE_FIELD

    def to_dict(self) -> dict:
        return {name: getattr(self, name) for name, _ in _FIELDS}

    @classmethod
    def from_dict(cls, data: dict) -> "MatchingSettings":
        obj = cls()
        for name, default in _FIELDS:
            fallback = list(default) if isinstance(default, list) else default
            setattr(obj, name, data.get(name, fallback))
        return obj

    def background_config(self) -> MatchingConfig:
        return MatchingConfig(
            required_keys=list(self.background_required_keys),
            optional_keys=list(self.background_optional_keys),
            closest_keys=list(self.background_closest_keys),
        )

    def reference_config(self) -> MatchingConfig:
        return MatchingConfig(
            required_keys=list(self.reference_required_keys),
            optional_keys=list(self.reference_optional_keys),
            closest_keys=list(self.reference_closest_keys),
        )

    def role_kwargs(self) -> dict:
        """kwargs for processing.utils.load_datafiles(**settings.role_kwargs())."""
        return {
            "role_mode": self.background_role_mode,
            "role_values": set(self.background_role_values),
            "role_field": self.background_role_field,
        }


DEFAULT_PROFILE_TREE = [new_leaf("Default", MatchingSettings().to_dict(), active=True)]


class MatchingProfileManager:
    """Load, save, and expose multiple named auto-matching profiles,
    organized as a tree (folders + leaves — see `preset_tree.py`). Exactly
    one profile is active at a time: unlike metadata patterns (which can
    have several simultaneously active, auto-selected by filename part
    count), there's no equivalent "pick by count" concept here — activating
    a profile simply deactivates any other.
    """

    def __init__(self):
        self._tree: list[dict] = []
        self.load()

    def load(self):
        try:
            if SETTINGS_FILE.exists():
                raw = json.loads(SETTINGS_FILE.read_text())
                if "tree" in raw:
                    self._tree = raw["tree"]
                else:
                    # legacy flat single-profile format — migrate to one
                    # active "Default" leaf, preserving all existing settings
                    self._tree = [new_leaf("Default", raw, active=True)]
                    logger.info("Migrated legacy matching_settings.json to profile tree format.")
                    self.save()
                logger.info(
                    "Loaded %d auto-matching profile(s) from %s.",
                    len(self.leaves()), SETTINGS_FILE,
                )
            else:
                self._tree = copy.deepcopy(DEFAULT_PROFILE_TREE)
                logger.info("No matching settings file found — using defaults.")
        except Exception as e:
            logger.warning("Failed to load matching settings: %s — using defaults.", e)
            self._tree = copy.deepcopy(DEFAULT_PROFILE_TREE)

    def save(self):
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            SETTINGS_FILE.write_text(json.dumps({"tree": self._tree}, indent=2))
            logger.info("Matching profiles saved to %s.", SETTINGS_FILE)
        except Exception as e:
            logger.error("Failed to save matching settings: %s", e)

    @property
    def tree(self) -> list[dict]:
        return self._tree

    def leaves(self) -> list[dict]:
        return list(iter_leaves(self._tree))

    def active_leaf(self) -> dict | None:
        for leaf in self.leaves():
            if leaf.get("active"):
                return leaf
        return None

    def active_settings(self) -> MatchingSettings:
        leaf = self.active_leaf()
        if leaf is None:
            return MatchingSettings()
        return MatchingSettings.from_dict(leaf["data"])

    def set_active(self, leaf_id: str):
        """Exactly one active profile — clears every other leaf's flag."""
        for leaf in self.leaves():
            leaf["active"] = (leaf["id"] == leaf_id)
