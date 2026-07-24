from __future__ import annotations
import logging
from dataclasses import dataclass, field

import numpy as np
from scipy.interpolate import CubicSpline
from scipy.signal import savgol_filter

from .config import HDSFGConfig
from .windows import edge_window, fft_mask_window

logger = logging.getLogger(__name__)


# ── Data classes — one per pipeline stage ─────────────────────────────────────

@dataclass
class DeSpikeParams:
    window: int = 20
    threshold: float = 15.0

@dataclass
class DespikedData:
    """Raw frames with spikes removed. Direct output of step_despike."""
    signal:           object   # ProcessedSpectrum or DataFile
    background:       object
    reference:        object
    ref_background:   object


@dataclass
class AveragedData:
    """Per-component averaged intensities on a uniform wavenumber grid.
    Signal keeps per-frame arrays for error statistics at normalization.
    """
    wavenumber:       np.ndarray          # uniform grid, max→min (cm⁻¹)
    sig_frames:       list[np.ndarray]    # per-frame signal (interpolated, not smoothed)
    sig_avg:          np.ndarray          # mean across frames
    bg_avg:           np.ndarray
    ref_avg:          np.ndarray
    ref_bg_avg:       np.ndarray
    n_sig_frames:     int


@dataclass
class BGSubtractedData:
    """After background subtraction, SG smoothing, and edge window."""
    wavenumber:             np.ndarray
    edge_win:               np.ndarray    # edge window weights (for plotting)
    # smoothed components
    sig_sm:                 np.ndarray
    bg_sm:                  np.ndarray
    ref_sm:                 np.ndarray
    ref_bg_sm:              np.ndarray
    sig_frames_sm:          list[np.ndarray]
    # deltas (smoothed signal - smoothed bg)
    sig_delta:              np.ndarray    # before edge window
    sig_delta_windowed:     np.ndarray    # after edge window
    ref_delta:              np.ndarray
    ref_delta_windowed:     np.ndarray


@dataclass
class FFTFilterData:
    """FFT → mask → iFFT intermediate arrays.
    Step 5 (time domain view) and step 6 (wavenumber view) both use this.
    """
    wavenumber:         np.ndarray    # same grid as upstream
    time_axis:          np.ndarray    # for FFT time-domain plots
    fft_mask:           np.ndarray    # the filter window (real)
    # signal
    sig_fft:            np.ndarray    # complex, shifted to centre
    sig_fft_masked:     np.ndarray    # complex, after mask
    sig_ifft:           np.ndarray    # complex, in freq domain
    sig_ifft_frames:    list[np.ndarray]   # per-frame iFFT
    # reference
    ref_fft:            np.ndarray
    ref_fft_masked:     np.ndarray
    ref_ifft:           np.ndarray


# ── Internal helpers ──────────────────────────────────────────────────────────

def _to_wavenumber(wavelength_nm: np.ndarray, upconversion_nm: float) -> np.ndarray:
    return (1e7 / wavelength_nm) - (1e7 / upconversion_nm)


def _interpolate(wavenumber_raw: np.ndarray,
                 intensity: np.ndarray,
                 n_pts: int) -> tuple[np.ndarray, np.ndarray]:
    """Cubic spline interpolation to uniform wavenumber grid (max → min)."""
    wn_uniform = np.linspace(wavenumber_raw.max(), wavenumber_raw.min(), n_pts)
    # CubicSpline requires ascending x — flip, interpolate, result is already max→min
    cs = CubicSpline(wavenumber_raw[::-1], intensity[::-1])
    return wn_uniform, cs(wn_uniform)


def _smooth(y: np.ndarray, window: int, order: int) -> np.ndarray:
    if window <= 0 or order <= 0:
        return y
    if window % 2 == 0:
        window += 1
    return savgol_filter(y, window, order)


def _fft_pipeline(delta_windowed: np.ndarray,
                  fft_mask: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Returns (fft_shifted, fft_masked, ifft)."""
    n = len(delta_windowed)
    fft_sh = np.roll(np.fft.fft(delta_windowed), n // 2)
    fft_masked = fft_sh * fft_mask
    return fft_sh, fft_masked, np.fft.ifft(fft_masked)


def _phase_degrees(z: np.ndarray) -> np.ndarray:
    phase = np.degrees(np.arctan2(z.imag, z.real))
    return np.where(phase < 0, 360 + phase, phase)


def _normalize_chi(sig_ifft: np.ndarray,
                   ref_ifft: np.ndarray,
                   sample_exp: float,
                   ref_exp: float,
                   phase_corr_deg: float) -> np.ndarray:
    phi = np.deg2rad(phase_corr_deg)
    phase_factor = 1j * (np.cos(phi) + 1j * np.sin(phi))
    return (sig_ifft / ref_ifft) * (ref_exp / sample_exp) * phase_factor


# ── Step functions ────────────────────────────────────────────────────────────

def step_despike(
    matched_set,
    sig_params:    DeSpikeParams,
    bg_params:     DeSpikeParams,
    ref_params:    DeSpikeParams,
    ref_bg_params: DeSpikeParams,
) -> DespikedData:
    """Step 1 — remove cosmic rays from each component independently."""
    return DespikedData(
        signal         = matched_set.signal.remove_cosmic_rays(
                             sig_params.window, sig_params.threshold),
        background     = matched_set.background.remove_cosmic_rays(
                             bg_params.window, bg_params.threshold),
        reference      = matched_set.reference.remove_cosmic_rays(
                             ref_params.window, ref_params.threshold),
        ref_background = matched_set.reference_background.remove_cosmic_rays(
                             ref_bg_params.window, ref_bg_params.threshold),
    )


def step_average(
    despiked: DespikedData,
    config: HDSFGConfig,
) -> AveragedData:
    """Step 2 — average frames and interpolate to uniform wavenumber grid.
    Signal keeps per-frame arrays for downstream error statistics.
    """
    # wavenumber axis from signal's first frame
    sig_df = despiked.signal
    wl_nm = sig_df.frame(sig_df.data["Frame"].iloc[0])["Wavelength"].to_numpy()
    wn_raw = _to_wavenumber(wl_nm, config.upconversion_wavelength)
    n_pts = config.n_interpolation_points or len(wn_raw)

    # per-frame signal
    sig_frames = []
    for fid in sig_df.data["Frame"].unique():
        intensity = sig_df.frame(fid)["Intensity"].to_numpy()
        wn_uniform, interp = _interpolate(wn_raw, intensity, n_pts)
        sig_frames.append(interp)

    sig_avg = np.mean(sig_frames, axis=0) if sig_frames else np.zeros(n_pts)

    def avg_component(comp) -> np.ndarray:
        intensity = comp.average_spectrum().frame(1)["Intensity"].to_numpy()
        _, interp = _interpolate(wn_raw, intensity, n_pts)
        return interp

    wn_uniform, _ = _interpolate(wn_raw, sig_df.frame(
        sig_df.data["Frame"].iloc[0])["Intensity"].to_numpy(), n_pts)

    return AveragedData(
        wavenumber   = wn_uniform,
        sig_frames   = sig_frames,
        sig_avg      = sig_avg,
        bg_avg       = avg_component(despiked.background),
        ref_avg      = avg_component(despiked.reference),
        ref_bg_avg   = avg_component(despiked.ref_background),
        n_sig_frames = len(sig_frames),
    )


def step_bg_smooth(
    averaged: AveragedData,
    config: HDSFGConfig,
) -> BGSubtractedData:
    """Step 3 — smooth all components (Savitzky-Golay), subtract backgrounds,
    apply edge window to deltas.
    """
    n = len(averaged.wavenumber)
    e_win = edge_window(n, config.edge_left, config.edge_right)

    bg_sm     = _smooth(averaged.bg_avg,     config.bg_smoothing_window,  config.bg_smoothing_order)
    ref_bg_sm = _smooth(averaged.ref_bg_avg, config.bg_smoothing_window,  config.bg_smoothing_order)
    sig_sm    = _smooth(averaged.sig_avg,    config.sig_smoothing_window, config.sig_smoothing_order)
    ref_sm    = _smooth(averaged.ref_avg,    config.sig_smoothing_window, config.sig_smoothing_order)

    sig_frames_sm = [
        _smooth(f, config.sig_smoothing_window, config.sig_smoothing_order)
        for f in averaged.sig_frames
    ]

    # deltas — add bg_offset to sample background
    bg_offset = config.bg_offset
    sig_delta          = sig_sm - (bg_sm + bg_offset)
    sig_delta_windowed = sig_delta * e_win
    ref_delta          = ref_sm - ref_bg_sm
    ref_delta_windowed = ref_delta * e_win

    return BGSubtractedData(
        wavenumber          = averaged.wavenumber,
        edge_win            = e_win,
        sig_sm              = sig_sm,
        bg_sm               = bg_sm + bg_offset,
        ref_sm              = ref_sm,
        ref_bg_sm           = ref_bg_sm,
        sig_frames_sm       = sig_frames_sm,
        sig_delta           = sig_delta,
        sig_delta_windowed  = sig_delta_windowed,
        ref_delta           = ref_delta,
        ref_delta_windowed  = ref_delta_windowed,
    )


def step_fft_filter(
    bg_sub: BGSubtractedData,
    config: HDSFGConfig,
) -> FFTFilterData:
    """Step 4 — FFT each delta, apply frequency-domain mask, iFFT.
    Both the time-domain view (step 5) and wavenumber view (step 6)
    use the arrays produced here.
    """
    n = len(bg_sub.wavenumber)
    f_mask = fft_mask_window(n, config)

    # time axis
    delta_wn = (bg_sub.wavenumber.max() - bg_sub.wavenumber.min()) / (n - 1) * 3e10
    time_axis = np.linspace(-0.5 / delta_wn, 0.5 / delta_wn, n)

    sig_fft,     sig_fft_masked,     sig_ifft     = _fft_pipeline(bg_sub.sig_delta_windowed, f_mask)
    ref_fft,     ref_fft_masked,     ref_ifft     = _fft_pipeline(bg_sub.ref_delta_windowed, f_mask)

    # per-frame iFFT for signal (error statistics at normalization)
    sig_ifft_frames = []
    for frame_sm in bg_sub.sig_frames_sm:
        frame_delta = (frame_sm - bg_sub.bg_sm) * bg_sub.edge_win
        _, _, frame_ifft = _fft_pipeline(frame_delta, f_mask)
        sig_ifft_frames.append(frame_ifft)

    return FFTFilterData(
        wavenumber       = bg_sub.wavenumber,
        time_axis        = time_axis,
        fft_mask         = f_mask,
        sig_fft          = sig_fft,
        sig_fft_masked   = sig_fft_masked,
        sig_ifft         = sig_ifft,
        sig_ifft_frames  = sig_ifft_frames,
        ref_fft          = ref_fft,
        ref_fft_masked   = ref_fft_masked,
        ref_ifft         = ref_ifft,
    )


def step_normalize(
    fft_data: FFTFilterData,
    config: HDSFGConfig,
) -> "HDSFGResult":
    """Step 5 — normalize sample by reference, compute per-frame statistics."""
    from .result import HDSFGResult

    chi_from_avg = _normalize_chi(
        fft_data.sig_ifft, fft_data.ref_ifft,
        config.sample_exposure, config.reference_exposure,
        config.phase_correction_deg,
    )

    # per-frame normalization for error statistics
    per_frame = [
        _normalize_chi(
            f, fft_data.ref_ifft,
            config.sample_exposure, config.reference_exposure,
            config.phase_correction_deg,
        )
        for f in fft_data.sig_ifft_frames
    ]

    n_frames = len(per_frame)
    stack = np.array(per_frame)
    chi_avg = stack.mean(axis=0)

    if n_frames > 1:
        factor    = 1.96 / np.sqrt(n_frames)
        real_err  = stack.real.std(axis=0) * factor
        imag_err  = stack.imag.std(axis=0) * factor
        phases    = np.array([_phase_degrees(f) for f in per_frame])
        homodyne  = np.array([f.real**2 + f.imag**2 for f in per_frame])
        phase_avg = phases.mean(axis=0)
        phase_err = phases.std(axis=0) * factor
        homo_avg  = homodyne.mean(axis=0)
        homo_err  = homodyne.std(axis=0) * factor
    else:
        zeros     = np.zeros(len(fft_data.wavenumber))
        real_err  = imag_err = phase_err = homo_err = zeros
        phase_avg = _phase_degrees(chi_avg)
        homo_avg  = chi_avg.real**2 + chi_avg.imag**2

    return HDSFGResult(
        wavenumber      = fft_data.wavenumber,
        complex_chi     = chi_from_avg,
        phase           = _phase_degrees(chi_from_avg),
        homodyne        = chi_from_avg.real**2 + chi_from_avg.imag**2,
        complex_chi_avg = chi_avg,
        real_err        = real_err,
        imag_err        = imag_err,
        phase_avg       = phase_avg,
        phase_err       = phase_err,
        homodyne_avg    = homo_avg,
        homodyne_err    = homo_err,
        n_frames        = n_frames,
    )