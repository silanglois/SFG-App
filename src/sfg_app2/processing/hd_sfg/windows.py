from __future__ import annotations
import numpy as np
from .config import HDSFGConfig


def edge_window(n: int, left_smooth: int, right_smooth: int) -> np.ndarray:
    """Hann-Genzel edge smoothing window applied to delta before FFT.
    Tapers the signal at both ends to avoid spectral leakage from
    edge discontinuities.

    Values:
        - Left taper:  Hann-Genzel over first `left_smooth` points
        - Middle:      1.0
        - Right taper: Hann-Genzel over last `right_smooth` points
    """
    w = np.ones(n, dtype=np.float64)
    for i in range(n):
        if i < left_smooth:
            w[i] = 0.54 + 0.46 * np.cos(np.pi * (i - left_smooth) / left_smooth)
        elif n - right_smooth <= i:
            w[i] = 0.54 + 0.46 * np.cos(
                np.pi * ((n - right_smooth) - i) / right_smooth
            )
    return w


def fft_mask_window(n: int, config: HDSFGConfig) -> np.ndarray:
    """FFT-domain mask window. Selects the resonant signal in time domain
    and suppresses non-resonant background.

    The window is centered at n//2 (DC after roll), with the passband
    region defined by [n//2 + fft_start, n//2 + fft_end].

    Window types:
        1: Box-Car — hard edges
        2: Box-Car + left Happ-Genzel — soft left edge
        3: Double Happ-Genzel — soft both edges
        4: Masking Happ-Genzel — attenuated region within passband
    """
    w = np.zeros(n, dtype=np.float64)
    c = n // 2
    st  = config.fft_start
    end = config.fft_end
    hg1 = config.hg_left
    hg2 = config.hg_right

    if config.window_type == 1:
        for i in range(n):
            if c + st < i < c + end:
                w[i] = 1.0

    elif config.window_type == 2:
        for i in range(n):
            if i <= c + st:
                w[i] = 0.0
            elif c + st < i <= c + st + hg1:
                w[i] = 0.54 + 0.46 * np.cos(
                    np.pi * (i - (c + st + hg1)) / hg1
                )
            elif c + st + hg1 < i <= c + end:
                w[i] = 1.0
            else:
                w[i] = 0.0

    elif config.window_type == 3:
        for i in range(n):
            if i <= c + st:
                w[i] = 0.0
            elif c + st < i <= c + st + hg1:
                w[i] = 0.54 + 0.46 * np.cos(
                    np.pi * (i - (c + st + hg1)) / hg1
                )
            elif c + st + hg1 < i <= c + end - hg2:
                w[i] = 1.0
            elif c + end - hg2 < i <= c + end:
                w[i] = 0.54 + 0.46 * np.cos(
                    np.pi * ((c + end - hg2) - i) / hg2
                )
            else:
                w[i] = 0.0

    elif config.window_type == 4:
        lx_st = config.mask_start
        lx_ed = config.mask_end
        lmask = config.mask_transition
        lfact = config.mask_factor
        for i in range(n):
            if i <= c + st:
                w[i] = 0.0
            elif c + st < i <= c + st + hg1:
                w[i] = 0.54 + 0.46 * np.cos(
                    np.pi * (i - (c + st + hg1)) / hg1
                )
            elif c + st + hg1 < i <= c + lx_st - lmask:
                w[i] = 1.0
            elif c + lx_st - lmask < i <= c + lx_st:
                w[i] = 0.54 + 0.46 * np.cos(
                    np.pi * (i - (c + lx_st + lmask)) / lmask
                )
            elif c + lx_st < i <= c + lx_ed:
                w[i] = lfact
            elif c + lx_ed < i <= c + lx_ed + lmask:
                w[i] = 0.54 + 0.46 * np.cos(
                    np.pi * ((c + lx_ed + lmask) - i) / lmask
                )
            elif c + lx_ed + lmask < i <= c + end:
                w[i] = 1.0
            else:
                w[i] = 0.0
    else:
        raise ValueError(f"Unknown window_type {config.window_type}. Must be 1–4.")

    return w