from __future__ import annotations
from typing import Callable, Union
import logging
from pathlib import Path
import numpy as np

from .data_file import DataFile, FilenamePattern, UnrecognizedFormatError

OffsetSpec = Union[None, float, list[float], Callable[[np.ndarray], np.ndarray]]

logger = logging.getLogger(__name__)

# suffixes that indicate file role but are not metadata fields
DEFAULT_ROLE_SUFFIXES = {"bg", "bkg", "background", "darkbg", "irbg", "irbkg"}


def _strip_role_token(stem: str, mode: str, values: set[str]) -> tuple[str, str | None]:
    """Remove a role-indicating token from a filename stem if present.
    mode: "suffix" (checks the last '_'-part) or "prefix" (checks the first).
    Returns (cleaned_stem, token_found_or_None).

    e.g. _strip_role_token("sample_ssp_2024_bg", "suffix", {"bg"})
         -> ("sample_ssp_2024", "bg")
         _strip_role_token("bg_sample_ssp_2024", "prefix", {"bg"})
         -> ("sample_ssp_2024", "bg")
    """
    parts = stem.split("_")
    if not parts:
        return stem, None
    if mode == "prefix":
        if parts[0].lower() in values:
            return "_".join(parts[1:]), parts[0].lower()
        return stem, None
    if parts[-1].lower() in values:
        return "_".join(parts[:-1]), parts[-1].lower()
    return stem, None


def resolve_role(stem: str, mode: str, values: set[str]) -> tuple[str, bool, str | None]:
    """Resolve (clean_stem, is_background, role_token) for a filename stem
    given a role detection mode ("suffix" | "prefix" | "field"). For "field"
    mode, role is decided from metadata (not the filename), so stem is
    returned unchanged, is_background is always False, and role_token is
    None here — callers must check the relevant metadata field themselves
    once it's available.
    """
    if mode == "field":
        return stem, False, None
    clean_stem, token = _strip_role_token(stem, mode, values)
    return clean_stem, token is not None, token


def select_pattern(clean_stem: str, patterns: list) -> FilenamePattern | None:
    """The first pattern that applies to `clean_stem`, or None.

    Regex patterns are tried first, in order, since they can actually
    inspect the text; positional ones then match on token count. Order
    within each group is the order given (i.e. the pattern tree's), so
    two patterns that could both apply resolve predictably to the first
    rather than to whichever happened to be built last.
    """
    coerced = [FilenamePattern.coerce(p) for p in patterns]
    for pattern in sorted(coerced, key=lambda p: p.mode != "regex"):
        if pattern.match(clean_stem) is not None:
            return pattern
    return None


def load_datafiles(
    folder: str | Path,
    patterns: list | None = None,
    glob: str = "*.csv",
    role_mode: str = "suffix",
    role_values: set[str] = None,
    role_field: str | None = None,
) -> list:
    if role_values is None:
        role_values = DEFAULT_ROLE_SUFFIXES
    role_values = {v.lower() for v in role_values}

    files = []
    skipped = []

    for path in sorted(Path(folder).glob(glob)):
        clean_stem, matched, role_token = resolve_role(path.stem, role_mode, role_values)
        fields = select_pattern(clean_stem, patterns) if patterns else None

        if patterns and fields is None:
            logger.warning(
                "%s: no active pattern applies to %r. Loading without "
                "filename metadata.", path.name, clean_stem,
            )

        extra_metadata = {"role": "background", "role_token": role_token} if matched else {}

        try:
            files.append(DataFile(path, filename_fields=fields,
                                  metadata=extra_metadata, parse_stem=clean_stem))
        except UnrecognizedFormatError as e:
            logger.warning("Skipping %s: %s", path.name, e)
            skipped.append(path.name)
        except Exception as e:
            logger.warning("Skipping %s due to unexpected error: %s", path.name, e)
            skipped.append(path.name)

    logger.info(
        "Loaded %d files from %s (%d skipped).",
        len(files), Path(folder).name, len(skipped),
    )
    if skipped:
        logger.warning("Skipped files: %s", skipped)

    return files