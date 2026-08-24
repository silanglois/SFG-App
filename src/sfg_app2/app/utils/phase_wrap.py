from __future__ import annotations
import numpy as np


def wrap_phase_for_plot(y: np.ndarray, wrap: bool) -> np.ndarray:
    """Folds phase data (already the (-180, 180] principal value from
    arctan2) into the chosen display window -- [0, 360) if wrap else
    (-180, 180] -- and breaks the line (via NaN) only where the underlying
    continuous phase actually crosses *that window's* own seam.

    Folding on the raw wrapped values (e.g. a plain `np.mod(y, 360)`) heals
    the seam at one boundary but opens an equally large artificial one
    wherever the real phase happens to pass through the other window's
    boundary, since a modulo fold can't tell a genuine wrap from a value
    that just crossed 0. Reconstructing the continuous phase first, then
    folding it, means both windows get exactly the breaks they need and no
    others.
    """
    y = np.asarray(y, dtype=float)
    finite = np.isfinite(y)
    if finite.all():
        filled = y
    else:
        # np.unwrap cascades a single NaN into every following value, so
        # interpolate over gaps just for the unwrap step and restore them
        # as NaN afterward.
        filled = y.copy()
        idx = np.arange(len(y))
        if finite.any():
            filled[~finite] = np.interp(idx[~finite], idx[finite], y[finite])
        else:
            filled[:] = 0.0

    continuous = np.unwrap(filled, period=360.0)
    if wrap:
        folded = np.mod(continuous, 360.0)
    else:
        folded = np.mod(continuous + 180.0, 360.0) - 180.0

    # Number of full turns folded away at each point -- a change between
    # neighbors means the continuous phase crossed this window's seam
    # there, which is the only place a break belongs.
    turns = np.round((continuous - folded) / 360.0)
    breaks = np.diff(turns) != 0

    folded = folded.copy()
    folded[1:][breaks] = np.nan
    folded[~finite] = np.nan
    return folded
