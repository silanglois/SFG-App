# processor.py — now a thin wrapper over steps.py
from __future__ import annotations
from .config import HDSFGConfig
from .result import HDSFGResult
from .steps import (
    step_despike, step_average, step_bg_smooth,
    step_fft_filter, step_normalize,
)


def process_hd_sfg(
    matched_set,
    config: HDSFGConfig,
    return_diagnostics: bool = False,
) -> HDSFGResult:
    """Full HD-SFG pipeline in one call.
    return_diagnostics kept for notebook compatibility but now returns
    the step data classes directly rather than a separate Diagnostics object.
    """
    despiked  = step_despike(matched_set,
                             config.despike_window if config.despike else 0,
                             config.despike_threshold)
    averaged  = step_average(despiked, config)
    bg_sub    = step_bg_smooth(averaged, config)
    fft_data  = step_fft_filter(bg_sub, config)
    result    = step_normalize(fft_data, config)

    result.metadata   = matched_set.signal.metadata.copy()
    result.history    = ["hd_sfg_processing"]
    result.provenance = {"config": config.__dict__,
                         "signal": matched_set.signal.path.name}

    if return_diagnostics:
        # return step data as a named tuple for notebook compatibility
        from collections import namedtuple
        Steps = namedtuple("Steps", ["despiked", "averaged", "bg_sub", "fft_data"])
        return result, Steps(despiked, averaged, bg_sub, fft_data)

    return result