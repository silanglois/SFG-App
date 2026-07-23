from __future__ import annotations
import logging
import numpy as np
from scipy.interpolate import CubicSpline
from scipy.signal import savgol_filter

from .config import HDSFGConfig
from .result import HDSFGResult
from .windows import edge_window, fft_mask_window

logger = logging.getLogger(__name__)


# ── Low-level helpers ─────────────────────────────────────────────────────────

def _wavelength_to_wavenumber(
    wavelength_nm: np.ndarray,
    upconversion_nm: float,
) -> np.ndarray:
    """Convert SFG wavelength (nm) to resonant IR wavenumber (cm⁻¹)."""
    return (1e7 / wavelength_nm) - (1e7 / upconversion_nm)


def _interpolate_to_uniform_grid(
    wavenumber: np.ndarray,
    intensity: np.ndarray,
    n_points: int | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Interpolate intensity onto a uniform wavenumber grid using cubic spline.
    Grid runs from max → min wavenumber (matching original script convention).

    Returns (wavenumber_uniform, intensity_interpolated).
    """
    n = n_points or len(wavenumber)
    wn_uniform = np.linspace(wavenumber.max(), wavenumber.min(), n)
    cs = CubicSpline(wavenumber[::-1], intensity[::-1])   # CubicSpline needs ascending x
    return wn_uniform, cs(wn_uniform)


def _smooth(
    y: np.ndarray,
    window: int,
    order: int,
) -> np.ndarray:
    """Savitzky-Golay smoothing. Returns y unchanged if window <= 0 or order <= 0."""
    if window <= 0 or order <= 0:
        return y
    if window % 2 == 0:
        window += 1
    return savgol_filter(y, window, order)


def _phase_degrees(complex_arr: np.ndarray) -> np.ndarray:
    """Convert complex array to phase in [0, 360] degrees."""
    phase = np.degrees(np.arctan2(complex_arr.imag, complex_arr.real))
    return np.where(phase < 0, 360 + phase, phase)


def _apply_fft_pipeline(
    delta: np.ndarray,
    fft_mask: np.ndarray,
) -> np.ndarray:
    """FFT → roll to center → apply mask → iFFT → return complex result."""
    n = len(delta)
    fft = np.fft.fft(delta)
    fft_shifted = np.roll(fft, n // 2)
    fft_masked = fft_shifted * fft_mask
    return np.fft.ifft(fft_masked)


def _normalize_result(
    sample_ifft: np.ndarray,
    reference_ifft: np.ndarray,
    sample_exposure: float,
    reference_exposure: float,
    phase_correction_deg: float,
) -> np.ndarray:
    """Normalize sample by reference with exposure correction and phase rotation.

    Formula: (sample / reference) × (ref_exp / sample_exp) × i × e^(i×phase_corr)
    The leading (1j) is an inherent 90° shift from the heterodyne detection scheme.
    """
    phi = np.deg2rad(phase_correction_deg)
    phase_factor = 1j * (np.cos(phi) + 1j * np.sin(phi))
    return (
        (sample_ifft / reference_ifft)
        * (reference_exposure / sample_exposure)
        * phase_factor
    )


# ── Main pipeline ─────────────────────────────────────────────────────────────

def process_hd_sfg(
    matched_set,
    config: HDSFGConfig,
    return_diagnostics: bool = False,
) -> HDSFGResult | tuple[HDSFGResult, "HDSFGDiagnostics"]:
    """Full HD-SFG processing pipeline.
    If return_diagnostics=True, returns (HDSFGResult, HDSFGDiagnostics).
    """
    from .diagnostics import HDSFGDiagnostics

    sig_file = matched_set.signal
    bg_file  = matched_set.background
    ref_file = matched_set.reference
    rbg_file = matched_set.reference_background

    if not matched_set.is_complete():
        raise ValueError(
            "HD-SFG processing requires a complete MatchedSet."
        )

    # Step 1 — wavenumber axis
    wl_nm = sig_file.frame(sig_file.data["Frame"].iloc[0])["Wavelength"].to_numpy()
    wavenumber_raw = _wavelength_to_wavenumber(wl_nm, config.upconversion_wavelength)
    n_pts = config.n_interpolation_points or len(wavenumber_raw)

    # Step 2 — reference & reference background
    ref_avg  = ref_file.average_spectrum().frame(1)["Intensity"].to_numpy()
    rbg_avg  = rbg_file.average_spectrum().frame(1)["Intensity"].to_numpy()
    wn_uniform, ref_ip  = _interpolate_to_uniform_grid(wavenumber_raw, ref_avg, n_pts)
    _,           rbg_ip = _interpolate_to_uniform_grid(wavenumber_raw, rbg_avg, n_pts)
    ref_ip_sm  = _smooth(ref_ip,  config.sig_smoothing_window, config.sig_smoothing_order)
    rbg_ip_sm  = _smooth(rbg_ip,  config.bg_smoothing_window,  config.bg_smoothing_order)

    # Step 3 — sample background
    bg_avg = bg_file.average_spectrum().frame(1)["Intensity"].to_numpy() + config.bg_offset
    _, bg_ip = _interpolate_to_uniform_grid(wavenumber_raw, bg_avg, n_pts)
    bg_ip_sm = _smooth(bg_ip, config.bg_smoothing_window, config.bg_smoothing_order)

    # Step 4 — windows
    n = len(wn_uniform)
    e_win  = edge_window(n, config.edge_left, config.edge_right)
    f_mask = fft_mask_window(n, config)

    # Step 5 — reference FFT pipeline
    ref_delta          = ref_ip_sm - rbg_ip_sm
    ref_delta_windowed = ref_delta * e_win
    ref_fft_shifted    = np.roll(np.fft.fft(ref_delta_windowed), n // 2)
    ref_fft_masked     = ref_fft_shifted * f_mask
    ref_ifft           = np.fft.ifft(ref_fft_masked)

    # Step 6 — per-frame sample processing
    frame_ids = sig_file.data["Frame"].unique()
    per_frame_complex: list[np.ndarray] = []
    sig_frames_raw, sig_frames_sm = [], []

    for fid in frame_ids:
        sig_intensity = sig_file.frame(fid)["Intensity"].to_numpy()
        _, sig_ip = _interpolate_to_uniform_grid(wavenumber_raw, sig_intensity, n_pts)
        sig_ip_sm = _smooth(sig_ip, config.sig_smoothing_window, config.sig_smoothing_order)
        sig_frames_raw.append(sig_ip)
        sig_frames_sm.append(sig_ip_sm)
        sig_delta    = (sig_ip_sm - bg_ip_sm) * e_win
        sig_ifft_f   = _apply_fft_pipeline(sig_delta, f_mask)
        per_frame_complex.append(_normalize_result(
            sig_ifft_f, ref_ifft,
            config.sample_exposure, config.reference_exposure,
            config.phase_correction_deg,
        ))

    # Step 7 — per-frame statistics
    n_frames = len(per_frame_complex)
    stack    = np.array(per_frame_complex)
    chi_avg  = stack.mean(axis=0)
    if n_frames > 1:
        factor     = 1.96 / np.sqrt(n_frames)
        real_err   = stack.real.std(axis=0) * factor
        imag_err   = stack.imag.std(axis=0) * factor
        phases     = np.array([_phase_degrees(s) for s in stack])
        homomd     = np.array([s.real**2 + s.imag**2 for s in stack])
        phase_avg  = phases.mean(axis=0)
        phase_err  = phases.std(axis=0) * factor
        homo_avg   = homomd.mean(axis=0)
        homo_err   = homomd.std(axis=0) * factor
    else:
        zeros      = np.zeros(n_pts)
        real_err   = imag_err = phase_err = homo_err = zeros
        phase_avg  = _phase_degrees(chi_avg)
        homo_avg   = chi_avg.real**2 + chi_avg.imag**2

    # Step 8 — process averaged data
    sig_avg_intensity = sig_file.average_spectrum().frame(1)["Intensity"].to_numpy()
    _, sig_avg_ip      = _interpolate_to_uniform_grid(wavenumber_raw, sig_avg_intensity, n_pts)
    sig_avg_ip_sm      = _smooth(sig_avg_ip, config.sig_smoothing_window, config.sig_smoothing_order)
    sig_avg_delta      = sig_avg_ip_sm - bg_ip_sm
    sig_avg_delta_win  = sig_avg_delta * e_win
    sig_avg_fft_sh     = np.roll(np.fft.fft(sig_avg_delta_win), n // 2)
    sig_avg_fft_masked = sig_avg_fft_sh * f_mask
    sig_avg_ifft       = np.fft.ifft(sig_avg_fft_masked)
    chi_from_avg       = _normalize_result(
        sig_avg_ifft, ref_ifft,
        config.sample_exposure, config.reference_exposure,
        config.phase_correction_deg,
    )

    # time axis for FFT plots
    delta_wn = (wn_uniform.max() - wn_uniform.min()) / (n - 1) * 3e10
    time_axis = np.linspace(-0.5 / delta_wn, 0.5 / delta_wn, n)

    provenance = {
        "signal":               sig_file.path.name,
        "background":           bg_file.path.name,
        "reference":            ref_file.path.name,
        "reference_background": rbg_file.path.name,
        "config":               config.__dict__,
    }

    result = HDSFGResult(
        wavenumber      = wn_uniform,
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
        metadata        = sig_file.metadata.copy(),
        history         = ["hd_sfg_processing"],
        provenance      = provenance,
    )

    if not return_diagnostics:
        return result

    diagnostics = HDSFGDiagnostics(
        wavenumber          = wn_uniform,
        sig_frames_raw      = sig_frames_raw,
        sig_frames_sm       = sig_frames_sm,
        sig_avg_raw         = sig_avg_ip,
        sig_avg_sm          = sig_avg_ip_sm,
        bg_raw              = bg_ip,
        bg_sm               = bg_ip_sm,
        ref_raw             = ref_ip,
        ref_sm              = ref_ip_sm,
        ref_bg_raw          = rbg_ip,
        ref_bg_sm           = rbg_ip_sm,
        edge_window         = e_win,
        sig_delta           = sig_avg_delta,
        sig_delta_windowed  = sig_avg_delta_win,
        ref_delta           = ref_delta,
        ref_delta_windowed  = ref_delta_windowed,
        time_axis           = time_axis,
        fft_mask            = f_mask,
        sig_fft             = sig_avg_fft_sh,
        ref_fft             = ref_fft_shifted,
        sig_fft_masked      = sig_avg_fft_masked,
        ref_fft_masked      = ref_fft_masked,
        sig_ifft            = sig_avg_ifft,
        ref_ifft            = ref_ifft,
        chi_from_avg        = chi_from_avg,
    )

    return result, diagnostics