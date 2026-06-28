from __future__ import annotations
from typing import Callable, Union

import numpy as np
import pandas as pd

from .processed_spectrum import ProcessedSpectrum

OffsetSpec = Union[None, float, list[float], Callable[[np.ndarray], np.ndarray]]


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