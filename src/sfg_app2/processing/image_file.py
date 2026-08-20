from __future__ import annotations
from pathlib import Path

import numpy as np
import pandas as pd


class UnrecognizedImageFormatError(ValueError):
    """Raised when a file matches none of the known CCD image CSV formats."""


class CCDImage:
    """A single CCD image: a 2D pixel-intensity grid plus its row/column
    axis coordinates (taken from the CSV's own index/header rather than
    assumed to be 0..N-1, in case a format calibrates them to something
    other than plain pixel numbers)."""

    def __init__(self, path: Path, data: np.ndarray, rows: np.ndarray, cols: np.ndarray):
        self.path = path
        self.data = data
        self.rows = rows
        self.cols = cols

    def __repr__(self) -> str:
        return f"CCDImage({self.path.name}, shape={self.data.shape})"


def _parse_indexed_grid(path: Path) -> CCDImage:
    """Format 1: first column is the row-pixel index, the header row is
    the column-pixel index — i.e. `pd.read_csv(path, index_col=0)` gives
    a fully numeric 2D grid directly."""
    try:
        df = pd.read_csv(path, index_col=0)
    except (pd.errors.ParserError, pd.errors.EmptyDataError, UnicodeDecodeError) as e:
        raise UnrecognizedImageFormatError(f"{path.name}: could not be parsed as CSV ({e})") from e

    if df.shape[0] < 2 or df.shape[1] < 2:
        raise UnrecognizedImageFormatError(
            f"{path.name}: too small to be an image grid (shape {df.shape})"
        )

    cols = pd.to_numeric(pd.Series(df.columns), errors="coerce").to_numpy()
    if np.isnan(cols).any():
        raise UnrecognizedImageFormatError(
            f"{path.name}: column headers aren't all numeric pixel indices"
        )

    data = df.apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float)
    if np.isnan(data).any():
        raise UnrecognizedImageFormatError(
            f"{path.name}: grid contains non-numeric values"
        )

    rows = pd.to_numeric(df.index.to_series(), errors="coerce").to_numpy()
    if np.isnan(rows).any():
        raise UnrecognizedImageFormatError(
            f"{path.name}: row index isn't all numeric pixel indices"
        )

    return CCDImage(path, data, rows, cols)


# Tried in order; the first parser that doesn't raise wins. Add future
# image CSV formats as additional functions here — nothing else needs
# to change.
_FORMAT_PARSERS = [_parse_indexed_grid]


def load_image_csv(path: str | Path) -> CCDImage:
    path = Path(path)
    errors = []
    for parser in _FORMAT_PARSERS:
        try:
            return parser(path)
        except UnrecognizedImageFormatError as e:
            errors.append(str(e))
    raise UnrecognizedImageFormatError(
        f"{path.name}: did not match any known image CSV format. " + "; ".join(errors)
    )
