from __future__ import annotations
import json
import logging
from pathlib import Path
from platformdirs import user_config_dir

from sfg_app2.processing.matcher import MatchingConfig, DEFAULT_SAMPLE_KEY
from sfg_app2.processing.utils import DEFAULT_ROLE_SUFFIXES

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
    """Load, save, and expose the user's auto-matching rules: which sample
    names identify references, how background files are detected (filename
    suffix/prefix or a metadata field), which metadata keys must (required),
    may (optional), or should be matched to the nearest value (closest)
    between a signal and its background/reference candidates, and rules
    forcing a signal/background pair to homodyne or heterodyne processing.
    Used by LoadMatchTab's "Auto-match Files" button.
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
        self.load()

    def load(self):
        try:
            if SETTINGS_FILE.exists():
                data = json.loads(SETTINGS_FILE.read_text())
                self.reference_names = data.get("reference_names", DEFAULT_REFERENCE_NAMES)
                self.background_required_keys = data.get(
                    "background_required_keys", DEFAULT_BACKGROUND_REQUIRED_KEYS)
                self.background_optional_keys = data.get(
                    "background_optional_keys", DEFAULT_BACKGROUND_OPTIONAL_KEYS)
                self.background_closest_keys = data.get(
                    "background_closest_keys", DEFAULT_BACKGROUND_CLOSEST_KEYS)
                self.reference_required_keys = data.get(
                    "reference_required_keys", DEFAULT_REFERENCE_REQUIRED_KEYS)
                self.reference_optional_keys = data.get(
                    "reference_optional_keys", DEFAULT_REFERENCE_OPTIONAL_KEYS)
                self.reference_closest_keys = data.get(
                    "reference_closest_keys", DEFAULT_REFERENCE_CLOSEST_KEYS)
                self.type_rules = data.get("type_rules", DEFAULT_TYPE_RULES)
                self.background_role_mode = data.get(
                    "background_role_mode", DEFAULT_BACKGROUND_ROLE_MODE)
                self.background_role_values = data.get(
                    "background_role_values", DEFAULT_BACKGROUND_ROLE_VALUES)
                self.background_role_field = data.get(
                    "background_role_field", DEFAULT_BACKGROUND_ROLE_FIELD)
                logger.info("Loaded matching settings from %s.", SETTINGS_FILE)
            else:
                logger.info("No matching settings file found — using defaults.")
        except Exception as e:
            logger.warning("Failed to load matching settings: %s — using defaults.", e)

    def save(self):
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            SETTINGS_FILE.write_text(json.dumps({
                "reference_names": self.reference_names,
                "background_required_keys": self.background_required_keys,
                "background_optional_keys": self.background_optional_keys,
                "background_closest_keys": self.background_closest_keys,
                "reference_required_keys": self.reference_required_keys,
                "reference_optional_keys": self.reference_optional_keys,
                "reference_closest_keys": self.reference_closest_keys,
                "type_rules": self.type_rules,
                "background_role_mode": self.background_role_mode,
                "background_role_values": self.background_role_values,
                "background_role_field": self.background_role_field,
            }, indent=2))
            logger.info("Matching settings saved to %s.", SETTINGS_FILE)
        except Exception as e:
            logger.error("Failed to save matching settings: %s", e)

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
