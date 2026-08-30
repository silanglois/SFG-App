import numpy as np
import pandas as pd

def remove_outliers_movmedian(
    values: np.ndarray,
    window: int,
    threshold_factor: float = 500.0,
    return_mask: bool = False,
):
    """Python equivalent of MATLAB's filloutliers(..., "linear", "movmedian", window, ThresholdFactor=tf).

    If `return_mask` is True, also returns the boolean array of points
    that were flagged as outliers (before interpolation) -- for
    previewing which points would be removed, without changing the
    return shape for existing callers.
    """
    s = pd.Series(values)

    local_median = s.rolling(window, center=True, min_periods=1).median()
    abs_dev = (s - local_median).abs()
    local_mad = abs_dev.rolling(window, center=True, min_periods=1).median() * 1.4826

    is_outlier = abs_dev > threshold_factor * local_mad

    cleaned = s.copy()
    cleaned[is_outlier] = np.nan
    cleaned = cleaned.interpolate(method="linear", limit_direction="both")

    if return_mask:
        return cleaned.to_numpy(), is_outlier.to_numpy()
    return cleaned.to_numpy()