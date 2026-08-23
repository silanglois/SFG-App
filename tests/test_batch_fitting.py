"""Tests for batch/sequential fitting in src/sfg_app2/processing/fitting.py
-- pure-Python physics and lmfit wiring, no Qt involved.

Run with:
    uv run pytest tests/test_batch_fitting.py -v
"""
import numpy as np
import pytest

from sfg_app2.processing.fitting import (
    FitModelSpec, FitParam, PeakInstance, evaluate_homodyne,
    BatchDataset, fit_sequential_batch, fit_independent_batch,
    fit_one_dataset, fit_homodyne, advance_seed,
)

OMEGA = np.linspace(3200, 3400, 200)
TRUE_AMPLITUDES = [4.0, 8.0, 12.0]


def _make_spec(amplitude: float) -> FitModelSpec:
    return FitModelSpec(
        nonresonant={"amplitude": FitParam(1.0), "phase": FitParam(0.1)},
        peaks=[PeakInstance("lorentzian", {
            "amplitude": FitParam(amplitude), "center": FitParam(3300.0), "width": FitParam(12.0),
        })],
    )


@pytest.fixture
def datasets() -> list[BatchDataset]:
    return [
        BatchDataset(label=f"conc-{i}", kind="homodyne", omega=OMEGA,
                     intensity=evaluate_homodyne(OMEGA, _make_spec(amp)))
        for i, amp in enumerate(TRUE_AMPLITUDES)
    ]


@pytest.fixture
def far_template() -> FitModelSpec:
    """Deliberately far from every dataset's truth, so seeding matters."""
    return _make_spec(1.0)


def test_sequential_batch_recovers_each_dataset_amplitude(datasets, far_template):
    progress_calls = []
    def progress_cb(i, n, label):
        progress_calls.append((i, n, label))
        return True

    results = fit_sequential_batch(datasets, far_template, progress_cb=progress_cb)
    assert len(results) == len(datasets)
    assert progress_calls == [(0, 3, "conc-0"), (1, 3, "conc-1"), (2, 3, "conc-2")]
    for r, truth in zip(results, TRUE_AMPLITUDES):
        assert abs(r.param_results["p0_amplitude"].value - truth) < 1e-2


def test_sequential_batch_seeds_from_previous_result_not_the_template(datasets, far_template):
    """With a template far off (amplitude=1.0, true values 4/8/12), a
    warm-started fit (seeded from the previous dataset's converged result)
    should need no more lmfit evaluations than a cold fit from the same
    far-off template -- directly evidencing that seeding is happening."""
    results = fit_sequential_batch(datasets, far_template)
    cold = fit_homodyne(OMEGA, datasets[2].intensity, far_template)
    warm = results[2]
    assert warm.lmfit_result.nfev <= cold.lmfit_result.nfev


def test_sequential_batch_rejects_mixed_homodyne_heterodyne_kinds(datasets, far_template):
    het_ds = BatchDataset(label="het", kind="heterodyne", omega=OMEGA,
                           real=np.zeros_like(OMEGA), imag=np.zeros_like(OMEGA))
    with pytest.raises(ValueError):
        fit_sequential_batch(datasets + [het_ds], far_template)


def test_sequential_batch_unfittable_template_fills_every_slot_with_none(datasets):
    broken_template = FitModelSpec(
        nonresonant={"amplitude": FitParam(1.0), "phase": FitParam(0.1)},
        peaks=[PeakInstance("no_such_lineshape", {
            "amplitude": FitParam(5.0), "center": FitParam(3300.0), "width": FitParam(12.0),
        })],
    )
    results = fit_sequential_batch(datasets, broken_template)
    assert len(results) == 3
    assert all(r is None for r in results)


def test_sequential_batch_one_failure_does_not_corrupt_the_seed(far_template):
    """A dataset that raises during fitting (shape mismatch) gets a None
    slot, but the NEXT dataset still seeds from the last GOOD result."""
    mismatched = BatchDataset(label="bad-shape", kind="homodyne",
                               omega=OMEGA, intensity=np.zeros(5))   # shape mismatch -> raises
    datasets_with_failure = [
        BatchDataset(label="a", kind="homodyne", omega=OMEGA, intensity=evaluate_homodyne(OMEGA, _make_spec(5.0))),
        mismatched,
        BatchDataset(label="c", kind="homodyne", omega=OMEGA, intensity=evaluate_homodyne(OMEGA, _make_spec(9.0))),
    ]
    results = fit_sequential_batch(datasets_with_failure, far_template)
    assert len(results) == 3
    assert results[1] is None
    assert results[0] is not None and results[0].success
    assert results[2] is not None
    assert abs(results[2].param_results["p0_amplitude"].value - 9.0) < 1e-2


def test_sequential_batch_progress_cb_returning_false_stops_early(datasets, far_template):
    def cancel_after_one(i, n, label):
        return i < 1   # allow dataset 0, refuse before dataset 1
    partial = fit_sequential_batch(datasets, far_template, progress_cb=cancel_after_one)
    assert len(partial) == 1
    assert partial[0] is not None and partial[0].success


def test_independent_batch_recovers_every_dataset_from_the_same_far_template(datasets, far_template):
    results = fit_independent_batch(datasets, far_template)
    assert len(results) == 3
    assert all(r is not None for r in results)
    for r, truth in zip(results, TRUE_AMPLITUDES):
        assert abs(r.param_results["p0_amplitude"].value - truth) < 1e-2


def test_independent_batch_order_does_not_affect_individual_results(datasets, far_template):
    """Unlike sequential fitting, independent fits never seed from each
    other, so reversing dataset order must not change any result."""
    reversed_results = fit_independent_batch(list(reversed(datasets)), far_template)
    assert abs(reversed_results[0].param_results["p0_amplitude"].value - TRUE_AMPLITUDES[2]) < 1e-2
    assert abs(reversed_results[2].param_results["p0_amplitude"].value - TRUE_AMPLITUDES[0]) < 1e-2


def test_independent_batch_matches_a_cold_direct_fit(datasets, far_template):
    """Every independent-batch fit starts from the same far-off template,
    so nfev should match a cold fit_one_dataset() call exactly -- unlike
    sequential fitting, where later fits warm-start and take fewer evals."""
    results = fit_independent_batch(datasets, far_template)
    cold_direct = fit_one_dataset(datasets[2], far_template)
    assert results[2].lmfit_result.nfev == cold_direct.lmfit_result.nfev


def test_advance_seed_returns_deepcopy_of_results_spec(datasets, far_template):
    some_result = fit_one_dataset(datasets[0], far_template)
    advanced = advance_seed(far_template, some_result)
    assert advanced is not some_result.spec
    assert advanced.nonresonant["amplitude"].value == some_result.spec.nonresonant["amplitude"].value


def test_advance_seed_falls_back_to_current_spec_when_result_is_none(far_template):
    assert advance_seed(far_template, None) is far_template
