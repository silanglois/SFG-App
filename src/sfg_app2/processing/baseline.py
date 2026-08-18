from __future__ import annotations
from typing import Callable, Union

import numpy as np
import pandas as pd

from .processed_spectrum import ProcessedSpectrum
from .utils import OffsetSpec


def _resolve_offset(wavelength: np.ndarray, offset: OffsetSpec) -> np.ndarray:
    """Turn an offset spec into an array matching wavelength.

    offset can be:
      - None            -> no offset (zeros)
      - float            -> constant offset
      - list/array        -> polynomial coefficients, highest degree first
                             (e.g. [0.001, 0.5] -> 0.001*w + 0.5, a line)
      - callable           -> offset(wavelength) -> array, for anything custom
    """
    if offset is None:
        return np.zeros_like(wavelength, dtype=float)
    if callable(offset):
        return offset(wavelength)
    if np.isscalar(offset):
        return np.full_like(wavelength, float(offset), dtype=float)
    # list/array of polynomial coefficients
    return np.polyval(offset, wavelength)


def fit_offset_from_markers(
    markers: list[tuple[float, float]], style: str, degree: int,
    bg_wavelength: np.ndarray, bg_intensity: np.ndarray,
) -> OffsetSpec:
    """Least-squares fits an offset curve of the given style through
    user-placed (x, y) markers, so that bg_intensity + fitted(x) passes as
    close as possible through every marker.

    style : 'constant' | 'linear' | 'polynomial'
    degree : polynomial degree (only used when style == 'polynomial')

    The fit is computed on the *residual* (marker_y - bg_at(marker_x),
    bg interpolated at each marker's x) rather than the marker y-values
    directly, since the offset is what gets added to bg_intensity — this
    is what makes the same markers produce a different offset curve for
    each matched set's own (differently shaped) background.

    Returns None if there are no markers, a float for a constant fit, or a
    list of polynomial coefficients (highest degree first) otherwise —
    exactly the OffsetSpec shapes _resolve_offset() already understands.
    """
    if not markers:
        return None
    xs = np.array([m[0] for m in markers], dtype=float)
    ys = np.array([m[1] for m in markers], dtype=float)
    bg_wavelength = np.asarray(bg_wavelength, dtype=float)
    bg_intensity = np.asarray(bg_intensity, dtype=float)
    order = np.argsort(bg_wavelength)
    bg_at_marker = np.interp(xs, bg_wavelength[order], bg_intensity[order])
    residual = ys - bg_at_marker

    deg = {"constant": 0, "linear": 1, "polynomial": degree}[style]
    deg = max(0, min(deg, len(markers) - 1))
    coeffs = np.polyfit(xs, residual, deg)
    return float(coeffs[0]) if deg == 0 else list(coeffs)


def apply_offset(background, offset: OffsetSpec = None) -> ProcessedSpectrum:
    """Apply an offset to a background spectrum and return it as a
    plottable ProcessedSpectrum, without subtracting from anything.
    Useful for visually checking the offset before calling subtract_background.
    """
    bg_avg = background.average_spectrum().frame(1)
    bg_wavelength = bg_avg["Wavelength"].to_numpy()
    bg_intensity = bg_avg["Intensity"].to_numpy()

    offset_values = _resolve_offset(bg_wavelength, offset)
    adjusted = bg_intensity + offset_values

    df = pd.DataFrame({
        "Frame": 1,
        "Wavelength": bg_wavelength,
        "Intensity": adjusted,
    })

    return ProcessedSpectrum(
        df,
        metadata=background.metadata,
        history=background.history + [f"apply_offset(offset={offset})"],
    )


def subtract_background(signal, background, offset: OffsetSpec = None) -> ProcessedSpectrum:
    bg_adjusted = apply_offset(background, offset)
    bg_lookup = pd.Series(
        bg_adjusted.data["Intensity"].to_numpy(),
        index=bg_adjusted.data["Wavelength"].to_numpy(),
    )

    corrected_frames = []
    for frame_id, group in signal.data.groupby("Frame"):
        group = group.sort_values("Wavelength").copy()
        group["Intensity"] = group["Intensity"].to_numpy() - bg_lookup.loc[group["Wavelength"]].to_numpy()
        corrected_frames.append(group)

    corrected_df = pd.concat(corrected_frames, ignore_index=True)
    return ProcessedSpectrum(
        corrected_df, metadata=signal.metadata, history=signal.history + ["subtract_background"]
    )