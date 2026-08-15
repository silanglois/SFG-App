from __future__ import annotations
import numpy as np


def wrap_phase_for_plot(y: np.ndarray, wrap: bool) -> np.ndarray:
    """Returns y unchanged if wrap is False. If True, wraps to [0, 360)
    and breaks the line (via NaN) at every crossing so matplotlib doesn't
    draw a near-vertical connector where the branch cut used to be.
    """
    if not wrap:
        return y
    y = np.mod(np.asarray(y, dtype=float), 360.0).copy()
    jumps = np.abs(np.diff(y)) > 180.0
    y[1:][jumps] = np.nan
    return y
