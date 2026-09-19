"""Reading raw spectrum files of varying shape into one canonical frame.

Instruments export wildly different text: semicolons or tabs instead of
commas, decimal commas, a preamble of instrument settings before the
header, columns called "wavelength (nm)" or "counts". This module
absorbs all of that.

**The invariant that keeps it contained**: every reader returns a
DataFrame with exactly the canonical columns `Frame`, `Wavelength`,
`Intensity`. Those names are the pipeline's internal data contract --
they appear well over a hundred times across the codebase -- so
normalisation happens *here*, at the boundary, and nothing downstream
ever learns that a file called its wavelength column something else.

Readers are registered the same way lineshapes are in `fitting.py`, so
a new format is a `register_reader()` call and needs no UI change.
"""
from __future__ import annotations

import csv
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import pandas as pd

logger = logging.getLogger(__name__)

CANONICAL_COLUMNS = ("Frame", "Wavelength", "Intensity")


class UnrecognizedFormatError(ValueError):
    """Raised when a file can't be read into the canonical shape."""


@dataclass
class ReadOptions:
    """How to turn one file's bytes into a table.

    Defaults reproduce a plain `pd.read_csv(path)` exactly, so a file
    that loaded before still loads identically.
    """

    delimiter: str | None = None      # None = let pandas sniff it
    decimal: str = "."
    encoding: str = "utf-8"
    skiprows: int = 0
    # canonical name -> the column actually in the file. Only needed when
    # the file's own headers don't already match.
    columns: dict[str, str] = field(default_factory=dict)
    # Wide files only: which columns hold frames. Needed when a wide file
    # carries something that isn't a frame alongside them (a dark
    # reference, a timestamp), since otherwise every non-wavelength
    # column is taken to be one.
    frame_columns: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict | None) -> "ReadOptions":
        data = data or {}
        return cls(
            delimiter=data.get("delimiter") or None,
            decimal=data.get("decimal") or ".",
            encoding=data.get("encoding") or "utf-8",
            skiprows=int(data.get("skiprows") or 0),
            columns=dict(data.get("columns") or {}),
            frame_columns=list(data.get("frame_columns") or []),
        )

    def to_dict(self) -> dict:
        return {"delimiter": self.delimiter, "decimal": self.decimal,
                "encoding": self.encoding, "skiprows": self.skiprows,
                "columns": dict(self.columns),
                "frame_columns": list(self.frame_columns)}


@dataclass
class ReaderSpec:
    key: str
    display_name: str
    extensions: tuple[str, ...]
    read: Callable[[Path, ReadOptions], pd.DataFrame]


_REGISTRY: dict[str, ReaderSpec] = {}


def register_reader(spec: ReaderSpec) -> None:
    _REGISTRY[spec.key] = spec


def available_readers() -> list[ReaderSpec]:
    return list(_REGISTRY.values())


def supported_extensions() -> list[str]:
    return sorted({ext for spec in _REGISTRY.values() for ext in spec.extensions})


# ── Delimited text ────────────────────────────────────────────────────────

def _candidate_separators(options: ReadOptions) -> list[str | None]:
    """Separators to try, in order.

    An explicit choice is used alone -- second-guessing it would make
    the setting a lie. Otherwise comma comes first, which is exactly
    what this app did before and keeps the common path on pandas' fast
    C engine, followed by the other separators instruments actually
    emit. Each attempt is validated by the reshape step, so a wrong
    guess fails and moves on rather than producing a garbage frame.
    Sniffing (`None`) is only the last resort: csv.Sniffer is happy to
    return the wrong answer, or none at all, on short numeric files.
    """
    if options.delimiter:
        return [options.delimiter]
    return [",", ";", "\t", "|", None]


def _read_table(path: Path, options: ReadOptions,
                sep: str | None = ",") -> pd.DataFrame:
    """The raw table, before any reshaping."""
    kwargs: dict = {"sep": sep, "skiprows": options.skiprows,
                    "decimal": options.decimal, "encoding": options.encoding}
    if sep is None:
        kwargs["engine"] = "python"      # only it can sniff
    try:
        return pd.read_csv(path, **kwargs)
    except (pd.errors.ParserError, pd.errors.EmptyDataError,
            UnicodeDecodeError, LookupError, csv.Error) as e:
        # csv.Error is the sniffer giving up ("Could not determine
        # delimiter"), which pandas lets through unwrapped.
        raise UnrecognizedFormatError(f"{path.name}: could not be parsed ({e})") from e


def _apply_column_mapping(raw: pd.DataFrame, options: ReadOptions,
                          path: Path) -> pd.DataFrame:
    """Rename the user's chosen source columns to the canonical names."""
    if not options.columns:
        return raw
    renames = {}
    for canonical, source in options.columns.items():
        if not source or canonical == source:
            continue
        if source not in raw.columns:
            raise UnrecognizedFormatError(
                f"{path.name}: mapped column {source!r} isn't in the file. "
                f"Found: {list(raw.columns)}"
            )
        renames[source] = canonical
    return raw.rename(columns=renames)


def _frame_number(header: object) -> int | None:
    """The frame a wide-format column header denotes.

    Plain numbers are the classic case, but exports label frames
    "Frame 1", "scan1", "S1" just as often; the first run of digits is
    what identifies those. A header with no digits at all is *not*
    guessed at by position -- a wide file can carry a dark reference or
    a timestamp column alongside its frames, and silently importing
    that as frame 1 would be worse than saying so.
    """
    text = str(header).strip()
    try:
        return int(float(text))
    except ValueError:
        pass
    digits = re.search(r"\d+", text)
    return int(digits.group()) if digits else None


def _to_canonical(raw: pd.DataFrame, path: Path,
                  frame_columns: list[str] | None = None) -> pd.DataFrame:
    """Long as-is, or wide (Wavelength + one column per frame) melted."""
    missing_long = set(CANONICAL_COLUMNS) - set(raw.columns)
    if not missing_long:
        return raw

    if missing_long == {"Frame"}:
        # A single-spectrum file: wavelength and intensity, no frame
        # index. Common in its own right, and the normal outcome of
        # mapping columns by hand. Without this it would fall into the
        # wide branch below and try to melt an "Intensity" column into a
        # column of the same name.
        df = raw.copy()
        df.insert(0, "Frame", 1)
        return df[list(CANONICAL_COLUMNS)]

    if "Wavelength" not in raw.columns:
        raise UnrecognizedFormatError(
            f"{path.name}: columns don't match long format (missing "
            f"{missing_long}) or wide format (no 'Wavelength' column). "
            f"Found: {list(raw.columns)}"
        )

    df = raw.copy()

    first_row = df.iloc[0]
    if pd.to_numeric(first_row, errors="coerce").isna().any():
        df = df.iloc[1:].reset_index(drop=True)

    df = df.apply(pd.to_numeric, errors="coerce")

    if frame_columns:
        missing = [c for c in frame_columns if c not in df.columns]
        if missing:
            raise UnrecognizedFormatError(
                f"{path.name}: frame column(s) {missing} aren't in the file. "
                f"Found: {[c for c in raw.columns]}"
            )
        frame_cols = list(frame_columns)
    else:
        frame_cols = [c for c in df.columns if c != "Wavelength"]
    if not frame_cols:
        raise UnrecognizedFormatError(
            f"{path.name}: wide format detected but no frame columns "
            f"found alongside 'Wavelength'."
        )

    numbers = {c: _frame_number(c) for c in frame_cols}
    unnamed = [c for c, n in numbers.items() if n is None]
    if unnamed:
        raise UnrecognizedFormatError(
            f"{path.name}: can't tell which frame these column(s) are: "
            f"{unnamed}. Frame columns need a number in their header "
            f"(\"1\", \"Frame 1\", \"S1\"). If they aren't frames at all, "
            f"name the ones that are in the import options."
        )

    long_df = df.melt(
        id_vars="Wavelength",
        value_vars=frame_cols,
        var_name="Frame",
        value_name="Intensity",
    )
    long_df["Frame"] = long_df["Frame"].map(numbers).astype(int)
    long_df = long_df.dropna(subset=["Intensity"]).reset_index(drop=True)

    if long_df.empty:
        raise UnrecognizedFormatError(
            f"{path.name}: no usable numeric data found after parsing "
            f"as wide format."
        )

    return long_df[list(CANONICAL_COLUMNS)]


def _read_delimited(path: Path, options: ReadOptions) -> pd.DataFrame:
    errors = []
    for sep in _candidate_separators(options):
        try:
            raw = _read_table(path, options, sep)
            raw = _apply_column_mapping(raw, options, path)
            return _to_canonical(raw, path, options.frame_columns)
        except UnrecognizedFormatError as e:
            errors.append(str(e))
    # Report the first failure: that's the one against the separator the
    # user actually configured (or the default), so it's the one whose
    # message will make sense to them.
    raise UnrecognizedFormatError(errors[0])


register_reader(ReaderSpec(
    key="delimited",
    display_name="Delimited text (CSV/TSV/TXT)",
    extensions=(".csv", ".txt", ".dat", ".asc", ".tsv"),
    read=_read_delimited,
))


# ── Entry point ───────────────────────────────────────────────────────────

def read_spectrum(path: str | Path, options: ReadOptions | None = None) -> pd.DataFrame:
    """Read `path` into the canonical Frame/Wavelength/Intensity frame.

    Readers are chosen by extension; an unknown extension still falls
    back to trying every reader, since instruments label plain text with
    all sorts of suffixes and refusing on the name alone would be worse
    than attempting the parse.
    """
    path = Path(path)
    options = options or ReadOptions()
    suffix = path.suffix.lower()

    candidates = [s for s in _REGISTRY.values() if suffix in s.extensions]
    if not candidates:
        candidates = list(_REGISTRY.values())

    errors = []
    for spec in candidates:
        try:
            return spec.read(path, options)
        except UnrecognizedFormatError as e:
            errors.append(str(e))
    raise UnrecognizedFormatError("; ".join(errors)
                                  or f"{path.name}: no reader could parse this file.")


def peek_columns(path: str | Path, options: ReadOptions | None = None) -> list[str]:
    """The file's own column headers, for offering a mapping.

    Deliberately does not reshape or validate -- it's what you show a
    user whose file failed to load so they can say which column is
    which.
    """
    options = options or ReadOptions()
    for sep in _candidate_separators(options):
        try:
            raw = _read_table(Path(path), options, sep)
        except UnrecognizedFormatError:
            continue
        if len(raw.columns) > 1 or options.delimiter:
            return [str(c) for c in raw.columns]
    return []
