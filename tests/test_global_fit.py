"""Tests for global (shared-parameter) batch fitting in
src/sfg_app2/processing/fitting.py -- pure-Python physics and lmfit
wiring, no Qt involved.

Run with:
    uv run pytest tests/test_global_fit.py -v
"""
import numpy as np
import pytest

from sfg_app2.processing.fitting import (
    FitModelSpec, FitParam, PeakInstance, evaluate_homodyne,
    BatchDataset, fit_global_batch, fit_independent_batch, build_global_params,
)

OMEGA = np.linspace(3200, 3400, 200)
TRUE_WIDTH = 12.0
TRUE_AMPLITUDES = [4.0, 8.0, 12.0]


def _true_spec(amplitude: float) -> FitModelSpec:
    return FitModelSpec(
        nonresonant={"amplitude": FitParam(1.0), "phase": FitParam(0.1)},
        peaks=[PeakInstance("lorentzian", {
            "amplitude": FitParam(amplitude), "center": FitParam(3300.0), "width": FitParam(TRUE_WIDTH),
        })],
    )


@pytest.fixture
def datasets() -> list[BatchDataset]:
    """Three datasets that all share the true width but differ in
    amplitude -- exactly the shape a global fit with a shared width
    parameter should be able to recover exactly (noiseless, so recovery
    should be tight)."""
    return [
        BatchDataset(label=f"conc-{i}", kind="homodyne", omega=OMEGA,
                     intensity=evaluate_homodyne(OMEGA, _true_spec(amp)))
        for i, amp in enumerate(TRUE_AMPLITUDES)
    ]


def _template(width_shared: bool, width_guess: float = 5.0, amplitude_guess: float = 1.0) -> FitModelSpec:
    """Deliberately far from every dataset's truth, so a correct fit
    demonstrates real convergence, not a lucky starting point."""
    return FitModelSpec(
        nonresonant={"amplitude": FitParam(1.0), "phase": FitParam(0.1)},
        peaks=[PeakInstance("lorentzian", {
            "amplitude": FitParam(amplitude_guess),
            "center": FitParam(3300.0, vary=False),
            "width": FitParam(width_guess, shared=width_shared),
        })],
    )


def test_global_fit_recovers_shared_width_and_per_dataset_amplitudes(datasets):
    template = _template(width_shared=True)
    result = fit_global_batch(datasets, template)

    assert result.shared_keys == ["p0_width"]
    assert len(result.per_dataset) == 3

    widths = [r.param_results["p0_width"].value for r in result.per_dataset]
    # every dataset's view of the shared parameter is literally the same
    # lmfit Parameter, so these must agree exactly, not just approximately
    assert widths[0] == widths[1] == widths[2]
    assert abs(widths[0] - TRUE_WIDTH) < 1e-2

    for r, truth in zip(result.per_dataset, TRUE_AMPLITUDES):
        assert abs(r.param_results["p0_amplitude"].value - truth) < 1e-2
        assert r.r_squared > 0.999


def test_global_fit_forcing_a_genuinely_different_parameter_shared_hurts_fit_quality(datasets):
    """Amplitudes are NOT the same across these datasets (4/8/12) -- forcing
    amplitude to be shared should measurably worsen the fit relative to
    fitting each dataset independently, proving the constraint has real
    teeth rather than being a no-op."""
    # Everything except the (falsely) shared resonant amplitude is fixed
    # at the true value, so nothing else in the model can compensate for
    # the wrong shared amplitude -- isolates the effect of the false
    # sharing constraint instead of letting free nonresonant terms mask it.
    shared_amp_template = FitModelSpec(
        nonresonant={"amplitude": FitParam(1.0, vary=False), "phase": FitParam(0.1, vary=False)},
        peaks=[PeakInstance("lorentzian", {
            "amplitude": FitParam(1.0, shared=True),
            "center": FitParam(3300.0, vary=False),
            "width": FitParam(TRUE_WIDTH, vary=False),
        })],
    )
    forced = fit_global_batch(datasets, shared_amp_template)

    independent_template = _template(width_shared=False, width_guess=TRUE_WIDTH)
    independent = fit_independent_batch(datasets, independent_template)

    forced_r2 = [r.r_squared for r in forced.per_dataset]
    independent_r2 = [r.r_squared for r in independent]

    # every dataset does at least as well independently -- with the
    # false shared-amplitude constraint, not all three can be near 1.0
    assert min(independent_r2) > min(forced_r2)
    assert any(r2 < 0.99 for r2 in forced_r2)


def test_global_fit_per_dataset_error_fields_are_finite_and_nonnegative():
    datasets = [
        BatchDataset(label=f"conc-{i}", kind="homodyne", omega=OMEGA,
                     intensity=evaluate_homodyne(OMEGA, _true_spec(amp)))
        for i, amp in enumerate(TRUE_AMPLITUDES)
    ]
    result = fit_global_batch(datasets, _template(width_shared=True))
    assert np.isfinite(result.redchi)
    for r in result.per_dataset:
        assert np.isfinite(r.redchi) and r.redchi >= 0
        assert np.isnan(r.aic) and np.isnan(r.bic)   # only well-defined for the whole joint fit


def test_build_global_params_shared_key_added_once_independent_keys_per_dataset():
    datasets = [
        BatchDataset(label=f"d{i}", kind="homodyne", omega=OMEGA, intensity=np.zeros_like(OMEGA))
        for i in range(3)
    ]
    params = build_global_params(datasets, _template(width_shared=True))
    names = set(params.keys())
    assert "p0_width" in names   # shared -- one unprefixed entry
    assert "d0_p0_width" not in names and "d1_p0_width" not in names
    for i in range(3):
        assert f"d{i}_p0_amplitude" in names   # independent -- one per dataset
        assert f"d{i}_nr_amplitude" in names


def test_global_fit_rejects_mixed_homodyne_heterodyne_kinds(datasets):
    het_ds = BatchDataset(label="het", kind="heterodyne", omega=OMEGA,
                           real=np.zeros_like(OMEGA), imag=np.zeros_like(OMEGA))
    with pytest.raises(ValueError):
        fit_global_batch(datasets + [het_ds], _template(width_shared=True))


def test_fit_param_shared_round_trips_through_dict():
    fp = FitParam(value=12.0, shared=True)
    restored = FitParam.from_dict(fp.to_dict())
    assert restored.shared is True

    fp_default = FitParam(value=1.0)
    assert FitParam.from_dict(fp_default.to_dict()).shared is False
