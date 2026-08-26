import numpy as np
import pandas as pd

def remove_outliers_movmedian(
    values: np.ndarray,
    window: int,
    threshold_factor: float = 500.0,
) -> np.ndarray:
    """Python equivalent of MATLAB's filloutliers(..., "linear", "movmedian", window, ThresholdFactor=tf)."""
    s = pd.Series(values)

    local_median = s.rolling(window, center=True, min_periods=1).median()
    abs_dev = (s - local_median).abs()
    local_mad = abs_dev.rolling(window, center=True, min_periods=1).median() * 1.4826

    is_outlier = abs_dev > threshold_factor * local_mad

    cleaned = s.copy()
    cleaned[is_outlier] = np.nan
    cleaned = cleaned.interpolate(method="linear", limit_direction="both")

    return cleaned.to_numpy()