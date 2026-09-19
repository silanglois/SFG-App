"""Finding the upconversion wavelength from a known reference.

The measured axis is a detected wavelength; what the experiment cares
about is the IR wavenumber probed, and the two are related by

    nu = 1e7/lambda - 1e7/lambda_upconversion

so calibration is the job of pinning down that single scalar
`lambda_upconversion`. Two ways to do it, both scans over candidate
values scored against something known:

- **against a reference curve** -- correlate the measured ratio with a
  material's tabulated absorption. This is what polystyrene calibration
  always did here; it just isn't specific to polystyrene.
- **against known line positions** -- find peaks in the measured ratio
  and line them up with a list of literature wavenumbers. Useful when
  there's no tabulated curve for the reference in hand, only published
  peak positions.

Qt-free, so all of it is testable without a GUI; the dialog only
supplies inputs and draws results.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Upconversion sources in common use (515/532/800/1030 nm) all sit well
# inside this, but the scan isn't restricted to them.
DEFAULT_CANDIDATES = (400.0, 1400.0, 0.25)
DEFAULT_WINDOW = (2750.0, 3150.0)     # the C-H stretch region

# Polystyrene's coordinates in the refractiveindex.info database. Kept
# as the default because it's the reference this lab already used, not
# because the method needs it.
POLYSTYRENE = ("organic", "polystyrene", "Myers")


def to_wavenumber(wavelength_nm: np.ndarray, upconversion_nm: float) -> np.ndarray:
    return (1e7 / np.asarray(wavelength_nm, dtype=float)) - (1e7 / upconversion_nm)


def default_candidates() -> np.ndarray:
    start, stop, step = DEFAULT_CANDIDATES
    return np.arange(start, stop, step)


# ── Reference sources ─────────────────────────────────────────────────────
# Anything with a `name` and `sample(wavenumber) -> values` will do.

@dataclass
class CurveReference:
    """A reference absorption curve, tabulated on its own wavenumber grid.

    Covers both a file the user supplies and anything else already in
    memory. Values outside the tabulated range come back NaN rather than
    being clamped: clamping would invent a flat shoulder that the
    correlation would happily score against.
    """

    wavenumber: np.ndarray
    value: np.ndarray
    name: str = "reference curve"

    def sample(self, wavenumber: np.ndarray) -> np.ndarray:
        wavenumber = np.asarray(wavenumber, dtype=float)
        order = np.argsort(self.wavenumber)
        known_x = np.asarray(self.wavenumber, dtype=float)[order]
        known_y = np.asarray(self.value, dtype=float)[order]
        out = np.interp(wavenumber, known_x, known_y, left=np.nan, right=np.nan)
        return out


class MaterialReference:
    """A material from the refractiveindex.info database.

    Constructed lazily and cached per (shelf, book, page): the first use
    may trigger a one-time download of the database, and the dialog asks
    for the same material repeatedly while replotting.
    """

    _cache: dict[tuple[str, str, str], object] = {}

    def __init__(self, shelf: str, book: str, page: str, name: str | None = None):
        self.shelf, self.book, self.page = shelf, book, page
        self.name = name or f"{book} ({page})"

    def _material(self):
        key = (self.shelf, self.book, self.page)
        if key not in self._cache:
            from refractiveindex import RefractiveIndexMaterial
            self._cache[key] = RefractiveIndexMaterial(
                shelf=self.shelf, book=self.book, page=self.page)
        return self._cache[key]

    def sample(self, wavenumber: np.ndarray) -> np.ndarray:
        return self._material().get_extinction_coefficient(
            np.asarray(wavenumber, dtype=float), unit="cm-1")


def polystyrene_reference() -> MaterialReference:
    return MaterialReference(*POLYSTYRENE, name="Polystyrene (Myers)")


def load_reference_csv(path: str | Path) -> CurveReference:
    """A two-column reference curve: wavenumber, then value.

    Deliberately forgiving about the header, since these come from
    published data and spreadsheets rather than from this app: the
    first two numeric columns are used, whatever they're called.
    """
    from .readers import read_raw_table

    path = Path(path)
    # Same separator/encoding tolerance the data readers have: these
    # files come from other people's spreadsheets too.
    frame = read_raw_table(path)
    numeric = frame.apply(pd.to_numeric, errors="coerce").dropna(axis=1, how="all")
    if numeric.shape[1] < 2:
        raise ValueError(
            f"{path.name}: need two numeric columns (wavenumber, value); "
            f"found {list(frame.columns)}"
        )
    pair = numeric.iloc[:, :2].dropna()
    if pair.empty:
        raise ValueError(f"{path.name}: no usable numeric rows.")
    return CurveReference(
        wavenumber=pair.iloc[:, 0].to_numpy(),
        value=pair.iloc[:, 1].to_numpy(),
        name=path.stem,
    )


# ── Scans ─────────────────────────────────────────────────────────────────

def find_best_upconversion_wavelength(
    ratio_wavelength: np.ndarray,
    ratio_intensity: np.ndarray,
    reference,
    wn_min: float = DEFAULT_WINDOW[0],
    wn_max: float = DEFAULT_WINDOW[1],
    candidates: np.ndarray | None = None,
) -> tuple[float | None, float]:
    """Best (wavelength, correlation) against a reference curve.

    `reference` is anything exposing `sample(wavenumber) -> values` --
    a MaterialReference, a CurveReference, or a stand-in in tests.
    Returns (None, -inf) if nothing scored.
    """
    if candidates is None:
        candidates = default_candidates()

    ratio_wavelength = np.asarray(ratio_wavelength, dtype=float)
    ratio_intensity = np.asarray(ratio_intensity, dtype=float)

    best_wl, best_score = None, -np.inf
    for wl in candidates:
        wavenumber = to_wavenumber(ratio_wavelength, wl)
        mask = ((wavenumber >= wn_min) & (wavenumber <= wn_max)
                & np.isfinite(ratio_intensity))
        if mask.sum() < 5:
            continue
        try:
            expected = np.asarray(reference.sample(wavenumber[mask]), dtype=float)
        except Exception:
            continue
        measured = ratio_intensity[mask]
        usable = np.isfinite(expected) & np.isfinite(measured)
        if usable.sum() < 5:
            continue
        measured, expected = measured[usable], expected[usable]
        if np.std(measured) == 0 or np.std(expected) == 0:
            continue
        score = np.corrcoef(measured, expected)[0, 1]
        if np.isfinite(score) and score > best_score:
            best_score, best_wl = score, float(wl)

    return best_wl, best_score


def detect_peaks(wavenumber: np.ndarray, intensity: np.ndarray,
                 prominence: float | None = None) -> np.ndarray:
    """Wavenumbers of peaks in a measured curve, strongest first."""
    from scipy.signal import find_peaks

    intensity = np.asarray(intensity, dtype=float)
    finite = np.isfinite(intensity)
    if finite.sum() < 5:
        return np.empty(0)

    values = np.where(finite, intensity, np.nanmin(intensity[finite]))
    if prominence is None:
        spread = np.nanmax(values) - np.nanmin(values)
        prominence = 0.05 * spread if spread > 0 else None

    found, properties = find_peaks(values, prominence=prominence)
    if found.size == 0:
        return np.empty(0)
    order = np.argsort(properties["prominences"])[::-1]
    return np.asarray(wavenumber, dtype=float)[found[order]]


def find_upconversion_from_lines(
    ratio_wavelength: np.ndarray,
    ratio_intensity: np.ndarray,
    line_positions: list[float],
    wn_min: float = DEFAULT_WINDOW[0],
    wn_max: float = DEFAULT_WINDOW[1],
    candidates: np.ndarray | None = None,
    prominence: float | None = None,
) -> tuple[float | None, float]:
    """Best (wavelength, rms error) lining measured peaks up with known lines.

    A genuinely different method from the correlation scan above: it
    needs only a list of literature positions, not a tabulated curve.
    Scored as the RMS distance from each known line to the nearest
    detected peak, so **lower is better** -- and it returns
    (None, inf), not (None, -inf), when nothing scores.

    Matching is done line-to-nearest-peak rather than the reverse
    because the measurement usually shows extra peaks the reference
    list doesn't mention; penalising those would fight the fit.
    """
    lines = np.asarray(sorted(float(v) for v in line_positions), dtype=float)
    if lines.size == 0:
        return None, np.inf
    if candidates is None:
        candidates = default_candidates()

    ratio_wavelength = np.asarray(ratio_wavelength, dtype=float)
    best_wl, best_error = None, np.inf

    for wl in candidates:
        wavenumber = to_wavenumber(ratio_wavelength, wl)
        window = (wavenumber >= wn_min) & (wavenumber <= wn_max)
        if window.sum() < 5:
            continue
        peaks = detect_peaks(wavenumber[window],
                             np.asarray(ratio_intensity, dtype=float)[window],
                             prominence)
        if peaks.size == 0:
            continue
        distances = np.abs(lines[:, None] - peaks[None, :]).min(axis=1)
        error = float(np.sqrt(np.mean(distances ** 2)))
        if error < best_error:
            best_error, best_wl = error, float(wl)

    return best_wl, best_error
