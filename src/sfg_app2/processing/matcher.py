from __future__ import annotations
import logging
from dataclasses import dataclass, field
from typing import Callable, Optional

import pandas as pd

logger = logging.getLogger(__name__)

# DEFAULT_EXACT_KEYS = ["polarization", "center_wavelength", "acquisition_time", "date"]
DEFAULT_REQUIRED_KEYS = ["center wavelength", "acquisition time"]
DEFAULT_OPTIONAL_KEYS = ["polarization", "date"]
DEFAULT_TIMESTAMP_KEY = "timestamp"
DEFAULT_SAMPLE_KEY = "sample"


# ── Role detection ──────────────────────────────────────────────────────────

def default_role_fn(datafile) -> str:
    """Check metadata['role'] first (set by load_datafiles),
    fall back to filename stem check for files loaded manually."""
    role = datafile.metadata.get("role")
    if role == "bg":
        return "background"
    if role == "ref":
        return "reference"
    # fallback for files not loaded via load_datafiles
    return "background" if "bg" in datafile.path.stem.lower() else "signal"


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
    optional_keys : compared only if both files have a real value
    """
    required_keys: list[str] = field(default_factory=lambda: ["sample","polarization"])
    optional_keys: list[str] = field(default_factory=lambda: ["center wavelength", "acquisition time"])


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
    *outdated* exact_keys : list[str], optional
        Metadata keys that must match exactly. Defaults to
        ["polarization", "center_wavelength", "acquisition_time", "date"].
    timestamp_key : str
        Metadata key holding the timestamp, used for closest-match tiebreaking.
    sample_key : str
        Metadata key holding the sample name, used for reference identification.
    """

    def __init__(
        self,
        files: list,
        role_fn: Callable = None,
        reference_names: list[str] = None,
        background_config: MatchingConfig = None,
        reference_config: MatchingConfig = None,
        timestamp_key: str = DEFAULT_TIMESTAMP_KEY,
        sample_key: str = DEFAULT_SAMPLE_KEY,
    ):
        self.files = files
        self.role_fn = role_fn or default_role_fn
        self.reference_names = [n.lower() for n in (reference_names or [])]
        self.background_config = background_config or MatchingConfig()
        self.reference_config = reference_config or MatchingConfig(
            required_keys=["polarization"],      # references are rarer,
            optional_keys=["center wavelength"]  # so loosen the match
        )
        self.timestamp_key = timestamp_key
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

    def _is_compatible(self, target, candidate, config: MatchingConfig) -> bool:
        def normalize(val):
            return str(val).strip().lower() if val is not None else None

        for key in config.required_keys:
            t_val = normalize(target.metadata.get(key))
            c_val = normalize(candidate.metadata.get(key))
            if t_val != c_val:
                return False

        for key in config.optional_keys:
            t_val = normalize(target.metadata.get(key))
            c_val = normalize(candidate.metadata.get(key))
            if t_val and c_val and t_val != c_val:
                return False

        return True

    def _parse_timestamp(self, datafile):
        ts = datafile.metadata.get(self.timestamp_key)
        if ts is None:
            return None
        try:
            return pd.Timestamp(ts)
        except Exception:
            logger.warning(
                "Could not parse timestamp '%s' from %s — "
                "timestamp matching will be skipped for this file.",
                ts, datafile.path.name,
            )
            return None

    def _find_closest(self, target, candidates: list, config: MatchingConfig):
        if target is None:
            return None

        compatible = [c for c in candidates if self._is_compatible(target, c, config)]

        if not compatible:
            return None

        target_ts = self._parse_timestamp(target)
        if target_ts is None:
            if len(compatible) > 1:
                logger.warning(
                    "Multiple compatible matches for %s but no parseable timestamp "
                    "to disambiguate — using first: %s. "
                    "Use .with_background()/.with_reference() to override manually.",
                    target.path.name, compatible[0].path.name,
                )
            return compatible[0]

        def ts_distance(candidate):
            c_ts = self._parse_timestamp(candidate)
            return abs((target_ts - c_ts).total_seconds()) if c_ts else float("inf")

        return min(compatible, key=ts_distance)

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

            results.append(MatchedSet(
                signal=signal,
                background=bg,
                reference=ref,
                reference_background=ref_bg
                ))

        return results