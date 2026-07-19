from __future__ import annotations
from typing import Callable, Union
import logging
from pathlib import Path
import numpy as np

from .data_file import DataFile

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
    patterns: list[list[str]],
    glob: str = "*.csv",
    role_suffixes: set[str] = None,
) -> list[DataFile]:
    """Load all matching files from a folder, picking the filename_fields
    pattern that best fits each file's metadata part count.

    Role suffixes (e.g. 'bg', 'ref') are stripped before part counting
    so they don't interfere with pattern matching, and stored separately
    under metadata['role'].

    Parameters
    ----------
    folder : str or Path
        Folder to search.
    patterns : list of list[str]
        filename_fields lists to try, matched by part count — first match wins.
        e.g. [["sample", "polarization", "date"],
               ["sample", "potential", "polarization", "date"]]
    glob : str
        Glob pattern for file discovery. Default: "*.csv".
    role_suffixes : set[str], optional
        Suffixes to strip before part counting. Defaults to {"bg", "ref"}.
    """
    if role_suffixes is None:
        role_suffixes = DEFAULT_ROLE_SUFFIXES

    pattern_map = {len(p): p for p in patterns}
    files = []

    for path in sorted(Path(folder).glob(glob)):
        clean_stem, role = _strip_role_suffix(path.stem, role_suffixes)
        n_parts = len(clean_stem.split("_"))
        fields = pattern_map.get(n_parts)

        if fields is None:
            logger.warning(
                "%s has %d metadata parts after stripping role suffix — "
                "no pattern matched %s. Loading without filename_fields.",
                path.name, n_parts, list(pattern_map.keys()),
            )

        # store role in manual metadata so matcher can use it later
        extra_metadata = {"role": role} if role else {}

        files.append(DataFile(path, filename_fields=fields, metadata=extra_metadata))

    logger.info(
        "Loaded %d files from %s (%d backgrounds, %d with no pattern match).",
        len(files),
        Path(folder).name,
        sum(1 for f in files if f.metadata.get("role") == "bg"),
        sum(1 for f in files if f.metadata.get("filename_parts") is not None
            and pattern_map.get(len(f.metadata.get("filename_parts", []))) is None),
    )

    return files