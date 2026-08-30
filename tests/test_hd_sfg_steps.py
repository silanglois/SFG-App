"""Tests for src/sfg_app2/processing/hd_sfg/steps.py::step_normalize --
pure-Python physics, no Qt involved.

Run with:
    uv run pytest tests/test_hd_sfg_steps.py -v
"""
import numpy as np

from sfg_app2.processing.hd_sfg.steps import step_normalize, FFTFilterData, _normalize_chi
from sfg_app2.processing.hd_sfg.config import HDSFGConfig


def _make_fft_data(sig_ifft_frames, ref_ifft, wavenumber):
    """Minimal synthetic FFTFilterData -- step_normalize only reads
    wavenumber/ref_ifft/sig_ifft_frames; the rest of the dataclass's
    fields (from earlier pipeline stages) are irrelevant here, so they
    get harmless placeholder values."""
    n = len(wavenumber)
    dummy_complex = np.zeros(n, dtype=complex)
    dummy_real = np.zeros(n)
    return FFTFilterData(
        wavenumber=wavenumber,
        time_axis=dummy_real,
        fft_mask=dummy_real,
        sig_fft=dummy_complex,
        sig_fft_masked=dummy_complex,
        sig_ifft=np.mean(sig_ifft_frames, axis=0),
        sig_ifft_frames=sig_ifft_frames,
        ref_fft=dummy_complex,
        ref_fft_masked=dummy_complex,
        ref_ifft=ref_ifft,
    )


def test_step_normalize_single_frame_has_zero_error():
    wavenumber = np.linspace(2800, 3400, 50)
    ref_ifft = np.full(50, 2.0 + 0j)
    frame = np.full(50, 1.0 + 0.5j)
    fft_data = _make_fft_data([frame], ref_ifft, wavenumber)
    config = HDSFGConfig()

    result = step_normalize(fft_data, config)

    assert result.n_frames == 1
    np.testing.assert_array_equal(result.real_err, 0.0)
    np.testing.assert_array_equal(result.imag_err, 0.0)
    np.testing.assert_array_equal(result.phase_err, 0.0)
    np.testing.assert_array_equal(result.homodyne_err, 0.0)
    assert np.all(np.isfinite(result.complex_chi))
    assert np.all(np.isfinite(result.phase))
    assert np.all(np.isfinite(result.homodyne))


def test_step_normalize_matches_direct_per_frame_average():
    """complex_chi should be exactly the mean of each frame's own
    normalized chi (this is the whole point of the consolidation --
    there's only one central-value convention now)."""
    rng = np.random.default_rng(1)
    n = 40
    wavenumber = np.linspace(2800, 3400, n)
    ref_ifft = np.full(n, 3.0 + 0j)
    config = HDSFGConfig(sample_exposure=2.0, reference_exposure=5.0, phase_correction_deg=15.0)

    frames = [rng.normal(0, 1, n) + 1j * rng.normal(0, 1, n) for _ in range(8)]
    fft_data = _make_fft_data(frames, ref_ifft, wavenumber)

    result = step_normalize(fft_data, config)

    per_frame_chi = [
        _normalize_chi(f, ref_ifft, config.sample_exposure,
                       config.reference_exposure, config.phase_correction_deg)
        for f in frames
    ]
    expected_chi = np.mean(per_frame_chi, axis=0)

    np.testing.assert_allclose(result.complex_chi, expected_chi)
    np.testing.assert_allclose(result.phase, np.degrees(np.arctan2(expected_chi.imag, expected_chi.real)))
    np.testing.assert_allclose(result.homodyne, expected_chi.real**2 + expected_chi.imag**2)


def test_step_normalize_homodyne_avoids_incoherent_averaging_bias():
    """homodyne (|mean(chi)|^2) must be <= the naive per-frame-averaged
    |chi_i|^2 for noisy frames -- Jensen's inequality
    (E[|X|^2] >= |E[X]|^2), and strictly less on average whenever
    there's real frame-to-frame noise. This is exactly the systematic
    upward bias the old (removed) homodyne_avg field used to have."""
    rng = np.random.default_rng(0)
    n = 60
    wavenumber = np.linspace(2800, 3400, n)
    ref_ifft = np.full(n, 3.0 + 0j)
    config = HDSFGConfig(sample_exposure=1.0, reference_exposure=1.0, phase_correction_deg=0.0)

    n_frames = 20
    frames = [
        np.full(n, 4.0 + 2.0j) + rng.normal(0, 2.0, n) + 1j * rng.normal(0, 2.0, n)
        for _ in range(n_frames)
    ]
    fft_data = _make_fft_data(frames, ref_ifft, wavenumber)

    result = step_normalize(fft_data, config)

    per_frame_chi = [
        _normalize_chi(f, ref_ifft, config.sample_exposure,
                       config.reference_exposure, config.phase_correction_deg)
        for f in frames
    ]
    naive_homodyne_avg = np.mean([np.abs(c)**2 for c in per_frame_chi], axis=0)

    assert np.all(result.homodyne <= naive_homodyne_avg + 1e-9)
    assert np.mean(result.homodyne) < np.mean(naive_homodyne_avg)

    assert result.n_frames == n_frames
    assert np.all(result.real_err >= 0) and np.all(np.isfinite(result.real_err))
    assert np.all(result.imag_err >= 0) and np.all(np.isfinite(result.imag_err))
    assert np.all(result.phase_err >= 0) and np.all(np.isfinite(result.phase_err))
    assert np.all(result.homodyne_err >= 0) and np.all(np.isfinite(result.homodyne_err))
