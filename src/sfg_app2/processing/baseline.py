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


def subtract_background(
    signal,                  # DataFile or ProcessedSpectrum
    background,             # DataFile or ProcessedSpectrum
    offset: OffsetSpec = None,
) -> ProcessedSpectrum:
    """Subtract a (possibly offset) background from each frame of the signal.

    The background is averaged across its own frames first, regardless of
    how many frames it has relative to the signal, since a single reference
    background is what's physically being subtracted.
    """
    bg_avg = background.average_spectrum().frame(1)  # wavelength, intensity, ...
    bg_wavelength = bg_avg["Wavelength"].to_numpy()
    bg_intensity = bg_avg["Intensity"].to_numpy()

    offset_values = _resolve_offset(bg_wavelength, offset)
    bg_adjusted = bg_intensity + offset_values

    bg_lookup = pd.Series(bg_adjusted, index=bg_wavelength)

    corrected_frames = []
    for frame_id, group in signal.data.groupby("Frame"):
        group = group.sort_values("Wavelength").copy()
        # exact-axis match assumed; .loc raises clearly if a wavelength is missing
        group["Intensity"] = group["Intensity"].to_numpy() - bg_lookup.loc[group["Wavelength"]].to_numpy()
        corrected_frames.append(group)

    corrected_df = pd.concat(corrected_frames, ignore_index=True)

    return ProcessedSpectrum(
        corrected_df,
        metadata=signal.metadata,
        history=signal.history + ["subtract_background"],
    )