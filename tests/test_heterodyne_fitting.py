"""Tests for heterodyne (HD-SFG) fitting in src/sfg_app2/processing/fitting.py
-- pure-Python physics and lmfit wiring, no Qt involved.

Run with:
    uv run pytest tests/test_heterodyne_fitting.py -v
"""
import numpy as np
import pytest

from sfg_app2.processing.fitting import (
    FitModelSpec, FitParam, PeakInstance,
    fit_heterodyne, compute_heterodyne_weights, evaluate_chi,
)


def _truth_and_guess():
    truth = FitModelSpec(
        nonresonant={"amplitude": FitParam(value=2.0), "phase": FitParam(value=0.3, vary=True, min=-np.pi, max=np.pi)},
        peaks=[PeakInstance("lorentzian", {
            "amplitude": FitParam(value=8.0), "center": FitParam(value=3300.0), "width": FitParam(value=15.0),
        })],
    )
    guess = FitModelSpec(
        nonresonant={"amplitude": FitParam(value=1.0), "phase": FitParam(value=0.0, vary=True, min=-np.pi, max=np.pi)},
        peaks=[PeakInstance("lorentzian", {
            "amplitude": FitParam(value=5.0), "center": FitParam(value=3295.0), "width": FitParam(value=10.0),
        })],
    )
    return truth, guess


def test_fit_heterodyne_recovers_ground_truth():
    np.random.seed(0)
    omega = np.linspace(3200, 3400, 400)
    truth, guess = _truth_and_guess()
    chi_true = evaluate_chi(omega, truth)
    real, imag = chi_true.real, chi_true.imag

    result = fit_heterodyne(omega, real, imag, guess)
    assert result.success
    assert abs(result.param_results["nr_amplitude"].value - 2.0) < 1e-3
    assert abs(result.param_results["nr_phase"].value - 0.3) < 1e-3
    assert abs(result.param_results["p0_center"].value - 3300.0) < 1e-2
    assert abs(result.param_results["p0_amplitude"].value - 8.0) < 1e-2
    assert abs(result.param_results["p0_width"].value - 15.0) < 1e-2
    assert result.r_squared > 0.999


def test_fit_heterodyne_noisy_weighted_still_converges():
    np.random.seed(0)
    omega = np.linspace(3200, 3400, 400)
    truth, guess = _truth_and_guess()
    chi_true = evaluate_chi(omega, truth)
    real, imag = chi_true.real, chi_true.imag

    noise_scale = 0.05
    real_noisy = real + np.random.normal(0, noise_scale, real.shape)
    imag_noisy = imag + np.random.normal(0, noise_scale, imag.shape)
    real_err = np.full_like(omega, 1.96 * noise_scale)   # 95% CI convention
    imag_err = np.full_like(omega, 1.96 * noise_scale)

    w_real, w_imag = compute_heterodyne_weights("measurement_error", real_noisy, imag_noisy, real_err, imag_err)
    assert w_real is not None
    assert w_imag is not None
    assert abs(w_real[0] - 1.0 / noise_scale) < 1e-6

    result = fit_heterodyne(omega, real_noisy, imag_noisy, guess, weights_real=w_real, weights_imag=w_imag)
    assert abs(result.param_results["p0_center"].value - 3300.0) < 0.5


def test_compute_heterodyne_weights_modes():
    omega = np.linspace(3200, 3400, 400)
    real = np.cos(omega / 100)
    imag = np.sin(omega / 100)

    assert compute_heterodyne_weights("none", real, imag) == (None, None)
    assert compute_heterodyne_weights("measurement_error", real, imag, None, None) == (None, None)

    with pytest.raises(ValueError):
        compute_heterodyne_weights("bogus", real, imag)


def test_compute_heterodyne_weights_zero_error_gets_positive_median_fallback():
    omega = np.linspace(3200, 3400, 400)
    real = np.cos(omega / 100)
    imag = np.sin(omega / 100)
    err = np.full_like(omega, 1.96 * 0.1)
    err[5] = 0.0
    w_r, w_i = compute_heterodyne_weights("measurement_error", real, imag, err, err)
    assert np.isfinite(w_r[5])
