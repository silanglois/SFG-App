from __future__ import annotations
from typing import Callable, Union
import logging
from pathlib import Path
import numpy as np

from .data_file import DataFile, UnrecognizedFormatError

OffsetSpec = Union[None, float, list[float], Callable[[np.ndarray], np.ndarray]]

logger = logging.getLogger(__name__)

# suffixes that indicate file role but are not metadata fields
DEFAULT_ROLE_SUFFIXES = {"bg", "bkg", "background", "darkbg", "irbg", "irbkg"}


def _strip_role_suffix(stem: str, role_suffixes: set[str]) -> tuple[str, str | None]:
    """Remove a trailing role suffix from a filename stem if present.
    Returns (cleaned_stem, role_suffix_found_or_None).

    e.g. "sample_ssp_2024_bg" -> ("sample_ssp_2024", "bg")
         "sample_ssp_2024"    -> ("sample_ssp_2024", None)
    """
    parts = stem.split("_")
    if parts[-1].lower() in role_suffixes:
        return "_".join(parts[:-1]), parts[-1].lower()
    return stem, None


def load_datafiles(
    folder: str | Path,
    patterns: list[list[str]] | None = None,
    glob: str = "*.csv",
    role_suffixes: set[str] = None,
) -> list:
    if role_suffixes is None:
        role_suffixes = DEFAULT_ROLE_SUFFIXES

    pattern_map = {len(p): p for p in patterns} if patterns else {}
    files = []
    skipped = []

    for path in sorted(Path(folder).glob(glob)):
        clean_stem, role = _strip_role_suffix(path.stem, role_suffixes)
        n_parts = len(clean_stem.split("_"))
        fields = pattern_map.get(n_parts) if pattern_map else None

        if pattern_map and fields is None:
            logger.warning(
                "%s has %d metadata parts — no pattern matched %s. "
                "Loading without filename_fields.",
                path.name, n_parts, list(pattern_map.keys()),
            )

        extra_metadata = {"role": role} if role else {}

        try:
            files.append(DataFile(path, filename_fields=fields, metadata=extra_metadata))
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