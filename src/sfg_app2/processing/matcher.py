from __future__ import annotations
import logging
from dataclasses import dataclass, field
from typing import Callable, Optional

import pandas as pd

from sfg_app2.processing.utils import DEFAULT_ROLE_SUFFIXES

logger = logging.getLogger(__name__)

# DEFAULT_EXACT_KEYS = ["polarization", "center_wavelength", "acquisition_time", "date"]
DEFAULT_REQUIRED_KEYS = ["center wavelength", "acquisition time"]
DEFAULT_OPTIONAL_KEYS = ["polarization", "date"]
DEFAULT_CLOSEST_KEYS = ["timestamp"]
DEFAULT_SAMPLE_KEY = "sample"


# ── Role detection ──────────────────────────────────────────────────────────

def make_role_fn(mode: str = "suffix", values: set[str] | None = None,
                  field: str | None = None) -> Callable:
    """Build a role_fn for DataFileMatcher.

    mode : "suffix" | "prefix" | "field"
        "suffix"/"prefix" — a file is "background" if the last/first
        `_`-separated token of its filename stem is in `values`.
        "field" — a file is "background" if its `field` metadata value is
        in `values`.
    values : the suffix/prefix tokens or field values (matched
        case-insensitively) that indicate a background file. Defaults to
        DEFAULT_ROLE_SUFFIXES.
    field : metadata key to check, only used when mode == "field".
    """
    values = {v.lower() for v in (values or DEFAULT_ROLE_SUFFIXES)}

    def role_fn(datafile) -> str:
        if mode == "field":
            val = str(datafile.metadata.get(field or "") or "").strip().lower()
            return "background" if val in values else "signal"

        # suffix/prefix: prefer the tag set at load time by load_datafiles/
        # load_individual_files; fall back to a direct filename check for
        # DataFiles constructed outside those helpers.
        if datafile.metadata.get("role") == "background":
            return "background"
        parts = datafile.path.stem.split("_")
        token = (parts[-1] if mode == "suffix" else parts[0]).lower()
        return "background" if token in values else "signal"

    return role_fn


default_role_fn = make_role_fn()


# ── Result container ─────────────────────────────────────────────────────────

@dataclass
class MatchedSet:
    """One complete experiment unit ready for the processing pipeline.

    signal              → the sample measurement
    background          → subtracted from signal
    reference           → used for normalization (e.g. gold, quartz)
    reference_background → subtracted from reference before normalization

    Any field can be None if no match was found — handle via .with_*() overrides.
    """
    signal:               Optional[object] = None
    background:           Optional[object] = None
    reference:            Optional[object] = None
    reference_background: Optional[object] = None
    spectrum_type:        str = "homodyne"   # "homodyne" | "heterodyne"

    def with_background(self, bg) -> "MatchedSet":
        from dataclasses import replace
        return replace(self, background=bg)

    def with_reference(self, ref) -> "MatchedSet":
        from dataclasses import replace
        return replace(self, reference=ref)

    def with_reference_background(self, ref_bg) -> "MatchedSet":
        from dataclasses import replace
        return replace(self, reference_background=ref_bg)

    def with_type(self, spectrum_type: str) -> "MatchedSet":
        from dataclasses import replace
        return replace(self, spectrum_type=spectrum_type)

    def is_complete(self) -> bool:
        return all([
            self.signal, self.background,
            self.reference, self.reference_background
        ])

    def __repr__(self) -> str:
        def name(f): return f.path.name if f else "None"
        return (
            f"MatchedSet(\n"
            f"  signal               = {name(self.signal)}\n"
            f"  background           = {name(self.background)}\n"
            f"  reference            = {name(self.reference)}\n"
            f"  reference_background = {name(self.reference_background)}\n"
            f"  spectrum_type        = {self.spectrum_type}\n"
            f")"
        )


# ── matching configuration ───────────────────────────────────────────────────

@dataclass
class MatchingConfig:
    """Matching rules for one role (background or reference).

    required_keys : must match exactly — mismatch disqualifies the candidate
    optional_keys : soft preference — candidates whose value matches the
                    target's are preferred over ones that don't, but a key
                    is skipped (behaves like ignored) if no candidate has a
                    matching value at all
    closest_keys  : tiebreakers, in priority order — among the remaining
                    candidates, narrow to whichever has the numerically/
                    temporally closest value for each key in turn. A key
                    with no comparable value on any candidate is skipped.
    """
    required_keys: list[str] = field(default_factory=lambda: ["sample", "polarization"])
    optional_keys: list[str] = field(default_factory=lambda: ["center wavelength", "acquisition time"])
    closest_keys: list[str] = field(default_factory=lambda: list(DEFAULT_CLOSEST_KEYS))


# ── Matcher ──────────────────────────────────────────────────────────────────

class DataFileMatcher:
    """Match a flat list of DataFile objects into MatchedSets.

    Parameters
    ----------
    files : list[DataFile]
        All files to match — can come from any folder(s).
    role_fn : callable(DataFile) -> str, optional
        Returns one of: "signal", "background". Defaults to checking for "bg"
        in the filename stem. Override this to support different naming schemes.
    reference_names : list[str], optional
        Sample names (matched case-insensitively) that identify a file as a
        reference (e.g. ["Au", "gold", "quartz"]). A reference with role
        "background" becomes a reference_background.
    type_rules : list[dict], optional
        Rules forcing spectrum_type based on a metadata value or a filename
        substring, e.g.
        {"mode": "field", "field": "sample", "key": "PS-hetero", "type": "heterodyne", "scope": "signal"}
        or
        {"mode": "filename", "key": "hetero", "type": "heterodyne", "scope": "signal"}.
        `mode` defaults to "field" if omitted (backward compatible with
        older saved rules). For "field" mode, `field` defaults to
        `sample_key` if omitted, and `key` must equal the field's value. For
        "filename" mode, `key` is matched as a substring anywhere in the
        file's name. scope is one of "signal", "background", "both" — which
        file is checked. The first matching rule (in list order) wins; sets
        matching no rule default to "homodyne".
    sample_key : str
        Metadata key holding the sample name, used for reference identification
        and as the default field for type_rules matching.
    """

    def __init__(
        self,
        files: list,
        role_fn: Callable = None,
        reference_names: list[str] = None,
        type_rules: list[dict] = None,
        background_config: MatchingConfig = None,
        reference_config: MatchingConfig = None,
        sample_key: str = DEFAULT_SAMPLE_KEY,
    ):
        self.files = files
        self.role_fn = role_fn or default_role_fn
        self.reference_names = [n.lower() for n in (reference_names or [])]
        self.type_rules = type_rules or []
        self.background_config = background_config or MatchingConfig()
        self.reference_config = reference_config or MatchingConfig(
            required_keys=["polarization"],      # references are rarer,
            optional_keys=["center wavelength"]  # so loosen the match
        )
        self.sample_key = sample_key
        self._unmatched: list = []

    @property
    def unmatched(self) -> list:
        """Files for which no match was found — populated after .match() is called."""
        return self._unmatched

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _is_reference(self, datafile) -> bool:
        sample = str(datafile.metadata.get(self.sample_key) or "").lower()
        return sample in self.reference_names

    def _classify(self) -> tuple[list, list, list, list]:
        signals, backgrounds, references, ref_backgrounds = [], [], [], []
        for f in self.files:
            role = self.role_fn(f)
            is_ref = self._is_reference(f)
            if role == "background" and is_ref:
                ref_backgrounds.append(f)
            elif role == "background":
                backgrounds.append(f)
            elif is_ref:
                references.append(f)
            else:
                signals.append(f)
        return signals, backgrounds, references, ref_backgrounds

    @staticmethod
    def _normalize(val):
        return str(val).strip().lower() if val is not None else None

    def _required_match(self, target, candidate, required_keys: list[str]) -> bool:
        for key in required_keys:
            t_val = self._normalize(target.metadata.get(key))
            c_val = self._normalize(candidate.metadata.get(key))
            if t_val != c_val:
                return False
        return True

    def _values_match(self, target, candidate, key: str) -> bool:
        t_val = self._normalize(target.metadata.get(key))
        c_val = self._normalize(candidate.metadata.get(key))
        return t_val is not None and c_val is not None and t_val == c_val

    @staticmethod
    def _parse_comparable(value):
        """Parse a metadata value into a float distance-comparable form —
        tries a plain number first, then a timestamp (as ns since epoch)."""
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            pass
        try:
            return float(pd.Timestamp(value).value)
        except (TypeError, ValueError):
            return None

    def _narrow_by_closest(self, target, candidates: list, key: str) -> list:
        t_val = self._parse_comparable(target.metadata.get(key))
        if t_val is None or not candidates:
            return candidates  # nothing to compare against — behaves like ignore

        scored = []
        for c in candidates:
            c_val = self._parse_comparable(c.metadata.get(key))
            if c_val is not None:
                scored.append((abs(t_val - c_val), c))

        if not scored:
            return candidates  # no candidate has a comparable value — ignore this key

        min_dist = min(d for d, _ in scored)
        return [c for d, c in scored if d == min_dist]

    def _find_closest(self, target, candidates: list, config: MatchingConfig):
        if target is None:
            return None

        eligible = [c for c in candidates if self._required_match(target, c, config.required_keys)]
        if not eligible:
            return None

        # cascading optional-key preference: prefer candidates that match,
        # but skip the key entirely (no-op) if none of them do
        for key in config.optional_keys:
            matching = [c for c in eligible if self._values_match(target, c, key)]
            if matching:
                eligible = matching

        # cascading closest-key tiebreak, in priority order
        for key in config.closest_keys:
            eligible = self._narrow_by_closest(target, eligible, key)

        if len(eligible) > 1:
            logger.warning(
                "%d equally good matches for %s — using first: %s. "
                "Use .with_background()/.with_reference() to override manually.",
                len(eligible), target.path.name, eligible[0].path.name,
            )

        return eligible[0]

    def _forced_type(self, signal, background) -> Optional[str]:
        def rule_matches(f, rule, key: str) -> bool:
            if f is None:
                return False
            if rule.get("mode", "field") == "filename":
                return key in f.path.stem.lower()
            field = rule.get("field") or self.sample_key
            return str(f.metadata.get(field) or "").strip().lower() == key

        for rule in self.type_rules:
            key = str(rule.get("key", "")).strip().lower()
            if not key:
                continue
            scope = rule.get("scope", "both")
            applies = (
                (scope in ("signal", "both") and rule_matches(signal, rule, key)) or
                (scope in ("background", "both") and rule_matches(background, rule, key))
            )
            if applies:
                return rule.get("type")
        return None

    # ── Public API ───────────────────────────────────────────────────────────

    def match(self) -> list[MatchedSet]:
        """Classify and match all files. Returns a list of MatchedSet objects.
        Files with no match found are logged as warnings and accessible via .unmatched.
        """
        self._unmatched = []
        signals, backgrounds, references, ref_backgrounds = self._classify()

        logger.info(
            "Classified %d signals, %d backgrounds, %d references, %d reference backgrounds.",
            len(signals), len(backgrounds), len(references), len(ref_backgrounds),
        )

        results = []
        for signal in signals:
            bg = self._find_closest(signal, backgrounds, self.background_config)
            ref = self._find_closest(signal, references, self.reference_config)
            ref_bg = self._find_closest(ref, ref_backgrounds, self.background_config) if ref else None

            if bg is None:
                logger.warning(
                    "No background match found for %s. "
                    "Use .with_background() to set one manually.",
                    signal.path.name,
                )
                self._unmatched.append(signal)

            if ref is None:
                logger.warning(
                    "No reference match found for %s. "
                    "Use .with_reference() to set one manually.",
                    signal.path.name,
                )

            if ref is not None and ref_bg is None:
                logger.warning(
                    "Reference %s has no matching background. "
                    "Use .with_reference_background() to set one manually.",
                    ref.path.name,
                )

            spectrum_type = self._forced_type(signal, bg) or "homodyne"

            results.append(MatchedSet(
                signal=signal,
                background=bg,
                reference=ref,
                reference_background=ref_bg,
                spectrum_type=spectrum_type,
                ))

        return results
