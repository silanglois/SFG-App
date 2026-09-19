from __future__ import annotations
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from sfg_app2.processing.despike import remove_outliers_movmedian
from .spectrum_data import SpectrumDataMixin
from .processed_spectrum import ProcessedSpectrum
from .readers import (
    CANONICAL_COLUMNS, ReadOptions, UnrecognizedFormatError, read_spectrum,
)

logger = logging.getLogger(__name__)

# Re-exported: this was defined here historically and is caught by name
# all over the app and the tests. It now lives with the readers, since
# that's what raises it.
__all__ = ["DataFile", "FilenamePattern", "UnrecognizedFormatError"]


@dataclass
class FilenamePattern:
    """How to pull metadata fields out of a filename stem.

    "positional" splits the stem on `delimiter` and maps the parts onto
    `fields` in order -- historically the only mode, so a bare list of
    field names still coerces to exactly that, with the same delimiter.

    "regex" matches `regex` against the stem and takes its **named
    groups** as the fields. This is the escape hatch for layouts
    positional parsing can't tell apart: pattern selection is otherwise
    by token count, so two layouts with the same number of tokens are
    indistinguishable no matter how their fields are named.

    `match()` is strict and answers "does this pattern apply?" (used to
    choose between patterns); `extract()` is lenient and always returns
    something (used once a pattern has been chosen, so a near-miss still
    keeps the raw parts rather than losing them).
    """

    fields: list[str] = field(default_factory=list)
    delimiter: str = "_"
    mode: str = "positional"        # "positional" | "regex"
    regex: str = ""
    name: str = ""                  # for log/UI messages only

    @classmethod
    def coerce(cls, value) -> "FilenamePattern | None":
        """Accept None, a bare list of field names (the historical
        shape, still used by callers and tests), an already-built
        pattern, or a stored dict."""
        if value is None or isinstance(value, cls):
            return value
        if isinstance(value, (list, tuple)):
            return cls(fields=list(value))
        if isinstance(value, dict):
            return cls(
                fields=list(value.get("fields") or []),
                delimiter=value.get("delimiter") or "_",
                mode=value.get("mode") or "positional",
                regex=value.get("regex") or "",
                name=value.get("name") or "",
            )
        raise TypeError(f"Can't read {value!r} as a filename pattern")

    def to_dict(self) -> dict:
        return {"fields": list(self.fields), "delimiter": self.delimiter,
                "mode": self.mode, "regex": self.regex}

    def _compiled(self):
        try:
            return re.compile(self.regex)
        except re.error as e:
            logger.warning("Pattern %r has an invalid regex (%s).", self.name or self.regex, e)
            return None

    def field_names(self) -> list[str]:
        """The fields this pattern can produce -- its named groups in
        regex mode, its positional field list otherwise."""
        if self.mode == "regex":
            compiled = self._compiled()
            return list(compiled.groupindex) if compiled else []
        return list(self.fields)

    def match(self, stem: str) -> dict | None:
        """Extracted fields, or None if this pattern doesn't apply."""
        if self.mode == "regex":
            compiled = self._compiled()
            if compiled is None:
                return None
            found = compiled.search(stem)
            # Unanchored on purpose: a partial pattern is useful, and
            # anyone wanting the whole stem can write ^...$.
            return dict(found.groupdict()) if found else None
        if not self.fields:
            return None
        parts = stem.split(self.delimiter)
        if len(parts) != len(self.fields):
            return None
        return dict(zip(self.fields, parts))

    def extract(self, stem: str) -> dict:
        """Best-effort fields once this pattern has been chosen. Never
        raises and never drops information: leftovers are kept under
        `extra_filename_parts`, and a regex that fails to match falls
        back to the raw split."""
        exact = self.match(stem)
        if exact is not None:
            return exact
        parts = stem.split(self.delimiter)
        if self.mode == "regex" or not self.fields:
            return {"filename_parts": parts}
        out = {name: (parts[i] if i < len(parts) else None)
               for i, name in enumerate(self.fields)}
        if len(parts) > len(self.fields):
            out["extra_filename_parts"] = parts[len(self.fields):]
        return out

class DataFile(SpectrumDataMixin):
    """A single SFG spectroscopy data file: raw frame data + metadata.

    Holds Frame/Wavelength/Intensity — the canonical columns every
    reader in `readers.py` normalises to, whatever the file itself
    called them. Metadata is parsed best-effort from the filename and
    can be supplemented or corrected manually.
    """

    REQUIRED_COLUMNS = CANONICAL_COLUMNS

    def __init__(
        self,
        path: str | Path,
        filename_fields: Optional[list[str]] = None,
        metadata: Optional[dict] = None,
        parse_stem: Optional[str] = None,
        read_options: Optional[ReadOptions] = None,
    ):
        self.path = Path(path)
        self._raw_df = read_spectrum(self.path, read_options)
        # `parse_stem` is the stem a pattern is matched against, which the
        # loader passes already stripped of its role token ("..._bg"). The
        # same text has to be used for choosing a pattern and for applying
        # it, or an anchored regex matches during selection and then fails
        # during extraction.
        self._parse_stem = parse_stem if parse_stem is not None else self.path.stem
        # Parsed and manual metadata are kept apart so the filename can be
        # re-parsed under a different pattern without discarding values the
        # user set by hand (or the role the loader detected). `metadata` is
        # the merged view everything else reads.
        self._parsed_metadata = self._parse_filename_metadata(
            self.path, filename_fields, self._parse_stem)
        self._manual_metadata: dict = dict(metadata or {})
        self.metadata = {**self._parsed_metadata, **self._manual_metadata}
        self.history: list[str] = []

    def set_manual_metadata(self, key: str, value) -> None:
        """Record a user-supplied value, which then survives re-parsing."""
        self._manual_metadata[key] = value
        self.metadata[key] = value

    def reparse_filename_metadata(self, pattern, parse_stem: Optional[str] = None) -> None:
        """Re-derive the filename-parsed half under a different pattern.

        Manual values win, as does the role the loader stamped on — that
        comes from role-stripping rather than the pattern, so a pattern
        change must not drop it.
        """
        if parse_stem is not None:
            self._parse_stem = parse_stem
        self._parsed_metadata = self._parse_filename_metadata(
            self.path, pattern, self._parse_stem)
        self.metadata = {**self._parsed_metadata, **self._manual_metadata}


    # ---- batch loading -------------------------------------------------

    @classmethod
    def load_many(
        cls,
        paths: list[str | Path],
        filename_fields: Optional[list[str]] = None,
        metadata: Optional[dict] = None,
    ) -> list["DataFile"]:
        """Load multiple files, skipping (and logging a warning for) any
        that don't match a recognized format instead of raising.
        """
        loaded = []
        for p in paths:
            p = Path(p)
            try:
                loaded.append(cls(p, filename_fields=filename_fields, metadata=metadata))
            except UnrecognizedFormatError as e:
                logger.warning("Skipping %s: %s", p.name, e)
            except Exception as e:
                logger.warning("Skipping %s due to unexpected error: %s", p.name, e)
        return loaded
    
    # ---- filename parsing -------------------------------------------

    @staticmethod
    def _parse_filename_metadata(path: Path, pattern, stem: Optional[str] = None) -> dict:
        """Best-effort metadata from a filename.

        `pattern` is a FilenamePattern, or any of the shapes its
        `coerce()` accepts — notably a bare list of field names, which
        means positional parsing on "_", the historical behaviour.
        Without one, nothing is lost: the raw parts are kept under a
        fallback key. `stem` defaults to the filename's own but is
        normally the role-stripped one (see __init__).
        """
        pattern = FilenamePattern.coerce(pattern)
        stem = path.stem if stem is None else stem
        metadata: dict = {"source_filename": path.name}
        if pattern is None:
            metadata["filename_parts"] = stem.split("_")
        else:
            metadata.update(pattern.extract(stem))
        return metadata

    # ------------------------------------------
    
    def remove_cosmic_rays(self, window: int = 5, threshold_factor: float = 3.0) -> ProcessedSpectrum:
        cleaned_frames = []
        for frame_id, group in self._raw_df.groupby("Frame"):
            group = group.sort_values("Wavelength").copy()
            group["Intensity"] = remove_outliers_movmedian(
                group["Intensity"].to_numpy(), window, threshold_factor
            )
            cleaned_frames.append(group)
        cleaned_df = pd.concat(cleaned_frames, ignore_index=True)
        return ProcessedSpectrum(
            cleaned_df, metadata=self.metadata, history=self.history + ["remove_cosmic_rays"]
        )

    def flag_cosmic_rays(self, window: int = 5, threshold_factor: float = 3.0) -> dict:
        """Same detection as remove_cosmic_rays, but returns per-frame
        boolean outlier masks (aligned to each frame's Wavelength-sorted
        order, same as `.frame(frame_id)`) instead of cleaned data --
        for previewing which points are currently being flagged, without
        touching/interpolating the data itself."""
        masks = {}
        for frame_id, group in self._raw_df.groupby("Frame"):
            group = group.sort_values("Wavelength")
            _, mask = remove_outliers_movmedian(
                group["Intensity"].to_numpy(), window, threshold_factor, return_mask=True
            )
            masks[frame_id] = mask
        return masks

    def __repr__(self) -> str:
        return f"DataFile({self.path.name}, n_frames={self.n_frames}, metadata={self.metadata})"