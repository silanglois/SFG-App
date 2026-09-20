"""Tests for src/sfg_app2/processing/fitting.py -- pure-Python physics
and lmfit wiring for homodyne fitting, no Qt involved.

Run with:
    uv run pytest tests/test_fitting.py -v
"""
import numpy as np
import pytest

from sfg_app2.processing.fitting import (
    FitParam, PeakInstance, FitModelSpec, default_peak, estimate_peak_seed,
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


def test_unknown_lineshape_error_names_what_is_available():
    """The message ends up in a dialog when a fit from a newer build is
    opened, so it has to say what this build actually has."""
    from sfg_app2.processing.fitting import UnknownLineshapeError

    with pytest.raises(UnknownLineshapeError) as excinfo:
        get_lineshape("does_not_exist")
    assert "lorentzian" in excinfo.value.message


def test_gaussian_and_voigt_are_registered():
    keys = {ls.key for ls in available_lineshapes()}
    assert {"lorentzian", "gaussian", "voigt"} <= keys


# ── Gaussian-broadened lineshapes ──────────────────────────────────────────

def test_voigt_reduces_to_lorentzian_as_gaussian_width_vanishes():
    """This is what pins down the Faddeeva prefactor -- get the sign or
    the normalisation wrong and the two stop agreeing."""
    omega = np.linspace(3100.0, 3500.0, 401)
    amplitude, center, width = 5.0, 3300.0, 20.0

    lorentzian = get_lineshape("lorentzian").chi(
        omega, amplitude=amplitude, center=center, width=width)
    voigt = get_lineshape("voigt").chi(
        omega, amplitude=amplitude, center=center, width=width,
        gauss_width=1e-9)

    assert np.allclose(voigt, lorentzian, rtol=1e-6, atol=1e-9)


def test_voigt_with_zero_gaussian_width_is_exactly_lorentzian():
    """The sigma <= 0 branch, which also guards a division by zero."""
    omega = np.linspace(3100.0, 3500.0, 51)
    kwargs = dict(amplitude=2.0, center=3300.0, width=15.0)
    assert np.allclose(
        get_lineshape("voigt").chi(omega, gauss_width=0.0, **kwargs),
        get_lineshape("lorentzian").chi(omega, **kwargs),
    )


def test_gaussian_absorption_has_the_right_full_width():
    """`width` means FWHM for every lineshape, so Im(chi) must drop to
    half its peak exactly width/2 away from centre."""
    center, width = 3300.0, 24.0
    omega = np.linspace(center - 200.0, center + 200.0, 40001)
    absorption = np.abs(get_lineshape("gaussian").chi(
        omega, amplitude=1.0, center=center, width=width).imag)

    peak = absorption.max()
    half_idx = np.argmin(np.abs(absorption[omega >= center] - peak / 2.0))
    half_offset = omega[omega >= center][half_idx] - center
    assert half_offset == pytest.approx(width / 2.0, rel=0.02)


def test_gaussian_absorption_decays_faster_than_lorentzian_in_the_wings():
    """The physical point of offering it: no heavy absorption tails."""
    omega = np.array([3300.0 + 200.0])
    kwargs = dict(amplitude=1.0, center=3300.0, width=20.0)
    gaussian = get_lineshape("gaussian").chi(omega, **kwargs)[0]
    lorentzian = get_lineshape("lorentzian").chi(omega, **kwargs)[0]
    assert abs(gaussian.imag) < abs(lorentzian.imag) / 1000.0


def test_gaussian_keeps_a_dispersive_tail_like_the_lorentzian():
    """Deliberately pinning down a counter-intuitive property, because
    it looks like a bug and invites a wrong "fix".

    Only the *absorption* (imaginary) part of a Gaussian line collapses
    in the wings; the dispersive (real) part is its Kramers-Kronig
    partner, a Dawson function, which decays as ~1/x just like the
    Lorentzian's. So |chi| far from resonance is essentially the same
    for both -- that is correct, not a normalisation error.
    """
    omega = np.array([3300.0 + 200.0])
    kwargs = dict(amplitude=1.0, center=3300.0, width=20.0)
    gaussian = get_lineshape("gaussian").chi(omega, **kwargs)[0]
    lorentzian = get_lineshape("lorentzian").chi(omega, **kwargs)[0]
    assert abs(gaussian.real) == pytest.approx(abs(lorentzian.real), rel=0.05)


def test_voigt_is_broader_than_either_component_alone():
    omega = np.linspace(3200.0, 3400.0, 20001)
    kwargs = dict(amplitude=1.0, center=3300.0)

    def fwhm(chi):
        y = np.abs(chi.imag)
        above = omega[y >= y.max() / 2.0]
        return above.max() - above.min()

    lorentzian = fwhm(get_lineshape("lorentzian").chi(omega, width=10.0, **kwargs))
    voigt = fwhm(get_lineshape("voigt").chi(omega, width=10.0, gauss_width=10.0, **kwargs))
    assert voigt > lorentzian


@pytest.mark.parametrize("key, kwargs", [
    ("lorentzian", {"width": 20.0}),
    ("gaussian", {"width": 20.0}),
    ("voigt", {"width": 10.0, "gauss_width": 15.0}),
])
def test_every_lineshape_is_a_complex_response_function(key, kwargs):
    """All three must be the same *kind* of object as the original
    complex Lorentzian, since they're summed coherently before squaring.
    A real-valued "Gaussian bump" would break that sum: it's the
    dispersive real part that makes interference between modes come out
    right. Re is odd about the centre, Im is even, Re vanishes on
    resonance -- the signature of a causal response function.
    """
    center = 3000.0
    omega = np.linspace(center - 400.0, center + 400.0, 20001)
    chi = get_lineshape(key).chi(omega, amplitude=1.0, center=center, **kwargs)

    assert np.iscomplexobj(chi)
    assert np.max(np.abs(chi.real + chi.real[::-1])) < 1e-9 * np.max(np.abs(chi.real))
    assert np.max(np.abs(chi.imag - chi.imag[::-1])) < 1e-9 * np.max(np.abs(chi.imag))
    assert chi.real[len(omega) // 2] == pytest.approx(0.0, abs=1e-12)
    assert chi.imag[len(omega) // 2] < 0.0


def test_voigt_really_is_the_complex_lorentzian_convolved_with_a_gaussian():
    """The defining property, checked against a numerical convolution
    rather than restated from the formula -- and checked on *both*
    parts, since convolving only the absorption would leave the
    dispersive part inconsistent with it."""
    from scipy.signal import fftconvolve
    from sfg_app2.processing.fitting import _FWHM_PER_SIGMA

    center, width, gauss_width, step = 3000.0, 10.0, 15.0, 0.02
    omega = np.arange(center - 800.0, center + 800.0, step)
    lorentzian = get_lineshape("lorentzian").chi(
        omega, amplitude=1.0, center=center, width=width)

    sigma = gauss_width / _FWHM_PER_SIGMA
    offsets = np.arange(-200.0, 200.0, step)
    kernel = np.exp(-offsets**2 / (2 * sigma**2))
    kernel /= kernel.sum()
    convolved = fftconvolve(lorentzian, kernel, mode="same")

    voigt = get_lineshape("voigt").chi(
        omega, amplitude=1.0, center=center, width=width, gauss_width=gauss_width)

    core = np.abs(omega - center) < 80.0
    scale = np.max(np.abs(voigt[core]))
    assert np.max(np.abs(convolved[core].real - voigt[core].real)) < 0.01 * scale
    assert np.max(np.abs(convolved[core].imag - voigt[core].imag)) < 0.01 * scale


# ── Click-to-place seeding for non-Lorentzian parameter names ──────────────

def test_voigt_seed_splits_the_measured_width_across_both_mechanisms():
    """Without the seed hook, gauss_width would silently take its
    ParamSpec default and ignore the click entirely."""
    peak = default_peak("voigt", center=3300.0, amplitude=4.0, width=30.0)
    assert peak.params["center"].value == 3300.0
    assert peak.params["amplitude"].value == 4.0
    assert peak.params["width"].value < 30.0
    assert peak.params["gauss_width"].value == peak.params["width"].value


def test_voigt_seed_recovers_roughly_the_measured_width():
    measured = 30.0
    peak = default_peak("voigt", center=3300.0, amplitude=1.0, width=measured)
    f_l = peak.params["width"].value
    f_g = peak.params["gauss_width"].value
    # The usual Voigt width approximation.
    combined = 0.5346 * f_l + np.sqrt(0.2166 * f_l**2 + f_g**2)
    assert combined == pytest.approx(measured, rel=0.1)


def test_lorentzian_seeding_is_unchanged_by_the_seed_hook():
    """Regression guard: the hook is opt-in, so the default lineshape
    must behave exactly as before."""
    peak = default_peak("lorentzian", center=3300.0, amplitude=4.0, width=30.0)
    assert peak.params["width"].value == 30.0
    assert peak.params["amplitude"].value == 4.0
    assert peak.params["center"].value == 3300.0


# ── The new lineshapes actually fit ────────────────────────────────────────
# Formula tests alone would pass even if the parameters were unidentifiable
# in practice, so recover known truth through the real optimizer.

@pytest.mark.parametrize("key, truth", [
    ("gaussian", {"amplitude": 30.0, "center": 2900.0, "width": 14.0}),
    ("voigt", {"amplitude": 30.0, "center": 2900.0, "width": 8.0,
               "gauss_width": 12.0}),
])
def test_new_lineshapes_recover_known_parameters(key, truth):
    omega = np.linspace(2800.0, 3000.0, 400)

    spec = FitModelSpec.empty()
    spec.peaks = [default_peak(key, center=truth["center"])]
    for name, value in truth.items():
        spec.peaks[0].params[name] = FitParam(value=value)
    clean = evaluate_homodyne(omega, spec)
    noisy = clean + rng.normal(0.0, 0.002 * clean.max(), omega.size)

    start = FitModelSpec.empty()
    start.peaks = [default_peak(key, center=truth["center"] - 2.0,
                                amplitude=truth["amplitude"] * 0.7,
                                width=truth["width"] * 1.5)]
    fitted = fit_homodyne(omega, noisy, start).spec.peaks[0].params

    for name, value in truth.items():
        assert fitted[name].value == pytest.approx(value, rel=0.05), name


def test_voigt_widths_are_separately_identifiable():
    """The two widths trading off against each other would still fit the
    data well, so check they land individually, not just jointly."""
    omega = np.linspace(2800.0, 3000.0, 400)
    spec = FitModelSpec.empty()
    spec.peaks = [default_peak("voigt", center=2900.0)]
    spec.peaks[0].params["amplitude"] = FitParam(value=30.0)
    spec.peaks[0].params["width"] = FitParam(value=6.0)
    spec.peaks[0].params["gauss_width"] = FitParam(value=18.0)
    y = evaluate_homodyne(omega, spec)

    start = FitModelSpec.empty()
    start.peaks = [default_peak("voigt", center=2900.0, amplitude=30.0, width=12.0)]
    fitted = fit_homodyne(omega, y, start).spec.peaks[0].params
    assert fitted["width"].value == pytest.approx(6.0, rel=0.1)
    assert fitted["gauss_width"].value == pytest.approx(18.0, rel=0.1)


# ── Saved fits from a build with different lineshapes ──────────────────────

def test_saved_voigt_fit_round_trips_through_provenance():
    from sfg_app2.processing import provenance

    spec = FitModelSpec.empty()
    spec.peaks = [default_peak("voigt", center=2900.0, amplitude=3.0, width=10.0)]
    lines = provenance.format_fit_section(
        spec.to_dict(), weighting="none", redchi=1.0, r_squared=0.99,
        aic=1.0, bic=1.0, kind="homodyne",
    )
    fit_json = next(l for l in lines if "Fit json:" in l).split("Fit json:", 1)[1].strip()
    restored = fit_model_spec_from_provenance_payload(
        provenance.parse_fit_json({"fit_json": fit_json})
    )
    assert restored is not None
    assert restored.peaks[0].lineshape_key == "voigt"
    assert set(restored.peaks[0].params) == {"amplitude", "center", "width", "gauss_width"}


def test_a_fit_using_an_unregistered_lineshape_is_declined_not_crashed():
    """A CSV written by a newer build can name a lineshape this one has
    never heard of. Every caller already handles None; raising out of a
    later table rebuild is what we're avoiding."""
    payload = {"model": {
        "nonresonant": {"amplitude": {"value": 0.0}, "phase": {"value": 0.0}},
        "peaks": [{"lineshape_key": "from_the_future",
                   "params": {"amplitude": {"value": 1.0}}}],
    }}
    assert fit_model_spec_from_provenance_payload(payload) is None


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


# ── estimate_peak_seed() -- data-driven click-to-add-peak guess ────────────

def test_estimate_peak_seed_recovers_known_lorentzian():
    ls = get_lineshape("lorentzian")
    omega = np.linspace(3200.0, 3400.0, 400)
    true_amplitude, true_center, true_width = 5.0, 3300.0, 15.0
    chi = ls.chi(omega, amplitude=true_amplitude, center=true_center, width=true_width)
    intensity = np.abs(chi) ** 2

    idx = int(np.argmin(np.abs(omega - true_center)))
    amplitude, width = estimate_peak_seed(omega, intensity, idx, squared=True)

    assert width == pytest.approx(true_width, rel=0.5)
    assert amplitude == pytest.approx(true_amplitude, rel=0.75)


def test_estimate_peak_seed_ignores_flanking_peak_when_residual_subtracted():
    ls = get_lineshape("lorentzian")
    omega = np.linspace(3200.0, 3400.0, 400)
    # Close enough together (15 cm^-1 apart, width 10-15) that the first
    # peak's tail meaningfully distorts the raw combined intensity around
    # the second peak's center.
    peak1 = dict(amplitude=8.0, center=3285.0, width=15.0)
    peak2 = dict(amplitude=3.0, center=3300.0, width=10.0)
    combined = np.abs(ls.chi(omega, **peak1) + ls.chi(omega, **peak2)) ** 2
    peak1_only = np.abs(ls.chi(omega, **peak1)) ** 2

    idx = int(np.argmin(np.abs(omega - peak2["center"])))

    raw_amplitude, raw_width = estimate_peak_seed(omega, combined, idx, squared=True)
    residual = combined - peak1_only
    resid_amplitude, resid_width = estimate_peak_seed(omega, residual, idx, squared=True)

    assert abs(resid_amplitude - peak2["amplitude"]) < abs(raw_amplitude - peak2["amplitude"])
    assert abs(resid_width - peak2["width"]) <= abs(raw_width - peak2["width"])


def test_estimate_peak_seed_handles_flat_data():
    omega = np.linspace(3200.0, 3400.0, 200)
    flat = np.full_like(omega, 2.0)
    amplitude, width = estimate_peak_seed(omega, flat, idx=100, squared=True)
    assert np.isfinite(amplitude) and amplitude > 0
    assert np.isfinite(width) and width > 0


@pytest.mark.parametrize("idx", [0, -1])
def test_estimate_peak_seed_handles_edge_click(idx):
    ls = get_lineshape("lorentzian")
    omega = np.linspace(3200.0, 3400.0, 200)
    intensity = np.abs(ls.chi(omega, amplitude=5.0, center=3300.0, width=15.0)) ** 2
    amplitude, width = estimate_peak_seed(omega, intensity, idx, squared=True)
    assert np.isfinite(amplitude) and amplitude > 0
    assert np.isfinite(width) and width > 0


def test_estimate_peak_seed_heterodyne_linear_relation():
    ls = get_lineshape("lorentzian")
    omega = np.linspace(3200.0, 3400.0, 400)
    true_amplitude, true_center, true_width = 4.0, 3300.0, 12.0
    chi = ls.chi(omega, amplitude=true_amplitude, center=true_center, width=true_width)
    magnitude = np.abs(chi)

    idx = int(np.argmin(np.abs(omega - true_center)))
    amplitude, width = estimate_peak_seed(omega, magnitude, idx, squared=False)

    assert width == pytest.approx(true_width, rel=0.5)
    assert amplitude == pytest.approx(true_amplitude, rel=0.75)
