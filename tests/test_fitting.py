"""Tests for src/sfg_app2/processing/fitting.py -- pure-Python physics
and lmfit wiring for homodyne fitting, no Qt involved.

Run with:
    uv run pytest tests/test_fitting.py -v
"""
import numpy as np
import pytest

from sfg_app2.processing.fitting import (
    FitParam, PeakInstance, FitModelSpec, default_peak,
    evaluate_homodyne, evaluate_peak_component,
    fit_homodyne, compute_weights, get_lineshape, available_lineshapes,
    fit_model_spec_from_provenance_payload,
)

rng = np.random.default_rng(42)


# ── Lineshape registry ───────────────────────────────────────────────────────

def test_lorentzian_is_registered():
    assert any(ls.key == "lorentzian" for ls in available_lineshapes())


def test_lorentzian_has_amplitude_center_width_params():
    ls = get_lineshape("lorentzian")
    assert {p.name for p in ls.params} == {"amplitude", "center", "width"}


def test_unknown_lineshape_raises():
    with pytest.raises(KeyError):
        get_lineshape("does_not_exist")


# ── Lorentzian chi formula: gamma = width/2 convention ─────────────────────

def test_lorentzian_chi_matches_gamma_is_half_width():
    ls = get_lineshape("lorentzian")
    omega = np.array([3200.0, 3300.0, 3400.0])
    amplitude, center, width = 5.0, 3300.0, 20.0
    gamma = width / 2.0
    expected = amplitude / (omega - center + 1j * gamma)
    actual = ls.chi(omega, amplitude=amplitude, center=center, width=width)
    assert np.allclose(actual, expected)


def test_lorentzian_differs_from_naive_full_width_denominator():
    """Regression guard: using the full width directly (not gamma=width/2)
    in the denominator gives a different value at resonance -- this locks
    in the halving so it can't be silently dropped."""
    ls = get_lineshape("lorentzian")
    w0 = 3000.0
    chi_correct = ls.chi(np.array([w0]), amplitude=1.0, center=w0, width=10.0)
    chi_wrong = 1.0 / (1j * 10.0)
    assert not np.isclose(chi_correct[0], chi_wrong)


# ── Coherent sum happens before squaring ────────────────────────────────────

def test_coherent_sum_differs_from_incoherent_sum_of_squares():
    spec = FitModelSpec(
        nonresonant={"amplitude": FitParam(value=0.0, vary=False), "phase": FitParam(value=0.0, vary=False)},
        peaks=[
            PeakInstance("lorentzian", {"amplitude": FitParam(1.0, vary=False), "center": FitParam(3300.0, vary=False), "width": FitParam(20.0, vary=False)}),
            PeakInstance("lorentzian", {"amplitude": FitParam(1.0, vary=False), "center": FitParam(3310.0, vary=False), "width": FitParam(20.0, vary=False)}),
        ],
    )
    omega = np.linspace(3200, 3400, 50)
    coherent = evaluate_homodyne(omega, spec)
    incoherent = evaluate_peak_component(omega, spec.peaks[0]) + evaluate_peak_component(omega, spec.peaks[1])
    assert not np.allclose(coherent, incoherent), \
        "|sum|^2 should differ from sum(|.|^2) -- proves cross-interference terms are present"


# ── Ground-truth fit recovery ────────────────────────────────────────────────

def test_fit_homodyne_recovers_ground_truth_single_peak():
    true_spec = FitModelSpec(
        nonresonant={"amplitude": FitParam(value=2.0), "phase": FitParam(value=0.3)},
        peaks=[PeakInstance("lorentzian", {
            "amplitude": FitParam(value=8.0), "center": FitParam(value=3300.0), "width": FitParam(value=15.0),
        })],
    )
    omega = np.linspace(3200, 3400, 200)
    true_intensity = evaluate_homodyne(omega, true_spec)
    noisy_intensity = true_intensity + rng.normal(0, 0.02 * true_intensity.max(), size=omega.shape)

    guess_spec = FitModelSpec(
        nonresonant={"amplitude": FitParam(value=1.5, min=0.0), "phase": FitParam(value=0.0, min=-np.pi, max=np.pi)},
        peaks=[PeakInstance("lorentzian", {
            "amplitude": FitParam(value=6.0), "center": FitParam(value=3290.0), "width": FitParam(value=20.0, min=0.0),
        })],
    )
    result = fit_homodyne(omega, noisy_intensity, guess_spec)
    assert result.success
    fitted = result.spec.peaks[0].params
    assert abs(fitted["center"].value - 3300.0) < 2.0
    assert abs(fitted["amplitude"].value - 8.0) < 1.0
    assert abs(fitted["width"].value - 15.0) < 3.0
    assert result.r_squared > 0.9


def test_fit_homodyne_expr_constraint_ties_two_peak_widths():
    tied_spec = FitModelSpec(
        nonresonant={"amplitude": FitParam(value=0.5, min=0.0), "phase": FitParam(value=0.0, min=-np.pi, max=np.pi)},
        peaks=[
            PeakInstance("lorentzian", {
                "amplitude": FitParam(value=5.0), "center": FitParam(value=3280.0), "width": FitParam(value=15.0, min=0.0),
            }),
            PeakInstance("lorentzian", {
                "amplitude": FitParam(value=5.0), "center": FitParam(value=3340.0),
                "width": FitParam(value=15.0, min=0.0, expr="p0_width"),
            }),
        ],
    )
    two_peak_true = FitModelSpec(
        nonresonant={"amplitude": FitParam(value=1.0), "phase": FitParam(value=0.1)},
        peaks=[
            PeakInstance("lorentzian", {"amplitude": FitParam(6.0), "center": FitParam(3280.0), "width": FitParam(18.0)}),
            PeakInstance("lorentzian", {"amplitude": FitParam(4.0), "center": FitParam(3340.0), "width": FitParam(18.0)}),
        ],
    )
    omega = np.linspace(3200, 3400, 200)
    intensity = evaluate_homodyne(omega, two_peak_true) + rng.normal(0, 0.5, size=omega.shape)
    result = fit_homodyne(omega, intensity, tied_spec)
    w0 = result.spec.peaks[0].params["width"].value
    w1 = result.spec.peaks[1].params["width"].value
    assert abs(w0 - w1) < 1e-6


def test_fit_homodyne_flags_parameter_pinned_at_bound():
    true_spec = FitModelSpec(
        nonresonant={"amplitude": FitParam(value=2.0), "phase": FitParam(value=0.3)},
        peaks=[PeakInstance("lorentzian", {
            "amplitude": FitParam(value=8.0), "center": FitParam(value=3300.0), "width": FitParam(value=15.0),
        })],
    )
    omega = np.linspace(3200, 3400, 200)
    pinned_spec = FitModelSpec(
        nonresonant={"amplitude": FitParam(value=0.0, vary=False), "phase": FitParam(value=0.0, vary=False)},
        peaks=[PeakInstance("lorentzian", {
            "amplitude": FitParam(value=100.0, min=0.0, max=1.0),   # deliberately outside its own bound
            "center": FitParam(value=3300.0, vary=False),
            "width": FitParam(value=15.0, vary=False),
        })],
    )
    pinned_intensity = evaluate_homodyne(omega, true_spec)  # true amplitude ~8, will hit max=1.0
    result = fit_homodyne(omega, pinned_intensity, pinned_spec)
    assert result.param_results["p0_amplitude"].at_bound
    assert abs(result.param_results["p0_amplitude"].value - 1.0) < 1e-6


# ── Weighting modes ──────────────────────────────────────────────────────────

def test_compute_weights_modes():
    intensity = np.array([100.0, 400.0, 0.0])
    assert compute_weights("none", intensity) is None

    w_stat = compute_weights("statistical", intensity)
    assert np.allclose(w_stat[:2], 1.0 / np.sqrt(intensity[:2]))

    std = np.array([2.0, 4.0, 0.0])
    count = np.array([4, 4, 4])
    w_err = compute_weights("measurement_error", intensity, std, count)
    assert np.isclose(w_err[0], 1.0 / (2.0 / 2.0))

    with pytest.raises(ValueError):
        compute_weights("bogus", intensity)


# ── FitModelSpec <-> dict round trip (templates + provenance) ──────────────

def test_fit_model_spec_dict_round_trip_preserves_expr_and_values():
    tied_spec = FitModelSpec(
        nonresonant={"amplitude": FitParam(value=0.5), "phase": FitParam(value=0.0)},
        peaks=[
            PeakInstance("lorentzian", {"amplitude": FitParam(5.0), "center": FitParam(3280.0), "width": FitParam(15.0)}),
            PeakInstance("lorentzian", {"amplitude": FitParam(5.0), "center": FitParam(3340.0),
                                         "width": FitParam(15.0, expr="p0_width")}),
        ],
    )
    restored = FitModelSpec.from_dict(tied_spec.to_dict())
    assert len(restored.peaks) == len(tied_spec.peaks)
    assert restored.peaks[1].params["width"].expr == "p0_width"
    assert restored.peaks[0].params["amplitude"].value == tied_spec.peaks[0].params["amplitude"].value


def test_fit_model_spec_from_provenance_payload():
    tied_spec = FitModelSpec(
        nonresonant={"amplitude": FitParam(value=0.5), "phase": FitParam(value=0.0)},
        peaks=[
            PeakInstance("lorentzian", {"amplitude": FitParam(5.0), "center": FitParam(3280.0), "width": FitParam(15.0)}),
            PeakInstance("lorentzian", {"amplitude": FitParam(5.0), "center": FitParam(3340.0), "width": FitParam(15.0)}),
        ],
    )
    payload = {
        "model": tied_spec.to_dict(), "weighting": "none",
        "redchi": 1.0, "r_squared": 0.9, "aic": 1.0, "bic": 1.0,
    }
    from_payload = fit_model_spec_from_provenance_payload(payload)
    assert from_payload is not None
    assert len(from_payload.peaks) == 2

    assert fit_model_spec_from_provenance_payload(None) is None
    assert fit_model_spec_from_provenance_payload({}) is None


# ── default_peak() seeding helper ────────────────────────────────────────────

def test_default_peak_seeds_from_click_and_heuristic():
    seeded = default_peak("lorentzian", center=3350.0, amplitude=7.0, width=25.0)
    assert seeded.params["center"].value == 3350.0
    assert seeded.params["amplitude"].value == 7.0
    assert seeded.params["width"].value == 25.0


def test_default_peak_falls_back_to_lineshape_defaults():
    seeded = default_peak("lorentzian", center=3350.0)
    assert seeded.params["amplitude"].value == get_lineshape("lorentzian").params[0].default
