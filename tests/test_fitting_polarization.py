"""Polarization sets: per-spectrum amplitude seeding, the seeded joint fit,
and per-polarization amplitude sign rules (processing/fitting.py)."""
import numpy as np
import pytest

from sfg_app2.processing.fitting import (
    BatchDataset, FitModelSpec, PeakInstance, apply_sign_constraints, default_peak,
    evaluate_chi, fit_global_batch, fit_independent_batch, fit_one_dataset,
    fit_polarization_set, fit_sequential_batch, restore_amplitude_bounds, seed_amplitudes,
)

_OMEGA = np.arange(2800.0, 3000.0, 1.0)
_CENTERS = [2850.0, 2880.0, 2940.0]
_WIDTHS = [10.0, 12.0, 15.0]
# Amplitudes differ in size and sign across polarizations, and one peak
# nearly vanishes in sps.
_TRUE = {
    "ssp": ([3.0, 5.0, 2.0], 0.5),
    "ppp": ([-1.0, 0.5, 4.0], 0.2),
    "sps": ([0.8, -0.3, 0.05], 0.1),
}


def _spec(amps, nr, centers=_CENTERS, widths=_WIDTHS, phase_vary=False):
    spec = FitModelSpec.empty()
    spec.nonresonant["amplitude"].value = nr
    spec.nonresonant["phase"].vary = phase_vary
    for a, c, w in zip(amps, centers, widths):
        spec.peaks.append(default_peak("lorentzian", c, amplitude=a, width=w))
    return spec


def _datasets(kind, truth=_TRUE, centers=_CENTERS, widths=_WIDTHS, noise=0.0, rng=None):
    rng = rng or np.random.default_rng(1)
    out = []
    for pol, (amps, nr) in truth.items():
        chi = evaluate_chi(_OMEGA, _spec(amps, nr, centers, widths))
        if kind == "heterodyne":
            out.append(BatchDataset(pol, kind, _OMEGA,
                                    real=chi.real + noise * rng.normal(size=_OMEGA.size),
                                    imag=chi.imag + noise * rng.normal(size=_OMEGA.size),
                                    polarization=pol))
        else:
            intensity = np.abs(chi) ** 2
            out.append(BatchDataset(pol, kind, _OMEGA,
                                    intensity=intensity + noise * intensity.max() * rng.normal(size=_OMEGA.size),
                                    polarization=pol))
    return out


def _shared_shapes(spec):
    for peak in spec.peaks:
        peak.params["center"].shared = True
        peak.params["width"].shared = True
    return spec


def _amplitudes(spec):
    return np.array([p.params["amplitude"].value for p in spec.peaks])


# ── seed_amplitudes ───────────────────────────────────────────────────────

def test_heterodyne_seed_recovers_amplitudes_exactly_from_wrong_ones():
    template = _shared_shapes(_spec([1.0, 1.0, 1.0], 0.3, phase_vary=True))
    for ds in _datasets("heterodyne"):
        seeded = seed_amplitudes(ds, template)
        amps, nr = _TRUE[ds.label]
        np.testing.assert_allclose(_amplitudes(seeded), amps, atol=1e-8)
        assert seeded.nonresonant["amplitude"].value == pytest.approx(nr, abs=1e-8)
        assert seeded.nonresonant["phase"].value == pytest.approx(0.0, abs=1e-8)


def test_seed_changes_values_only():
    template = _shared_shapes(_spec([1.0, 1.0, 1.0], 0.3, phase_vary=True))
    template.peaks[0].params["amplitude"].min = -50.0
    seeded = seed_amplitudes(_datasets("heterodyne")[0], template)
    for t_peak, s_peak in zip(template.peaks, seeded.peaks):
        for name, fp in t_peak.params.items():
            sp = s_peak.params[name]
            assert (sp.vary, sp.min, sp.max, sp.shared) == (fp.vary, fp.min, fp.max, fp.shared)
        assert s_peak.params["center"].value == t_peak.params["center"].value


def test_homodyne_seed_recovers_amplitudes_up_to_global_sign():
    template = _shared_shapes(_spec([1.0, 1.0, 1.0], 0.3))
    for ds in _datasets("homodyne"):
        seeded = seed_amplitudes(ds, template)
        amps, nr = _TRUE[ds.label]
        sign = np.sign(seeded.nonresonant["amplitude"].value)
        np.testing.assert_allclose(sign * _amplitudes(seeded), amps, atol=1e-3)
        assert abs(seeded.nonresonant["amplitude"].value) == pytest.approx(nr, abs=1e-3)


# ── fit_polarization_set ──────────────────────────────────────────────────

@pytest.mark.parametrize("kind", ["homodyne", "heterodyne"])
def test_polarization_set_recovers_shared_shapes_and_per_spectrum_amplitudes(kind):
    centers = [c + 3 for c in _CENTERS]
    widths = [w * 1.3 for w in _WIDTHS]
    template = _shared_shapes(_spec([1.0, 1.0, 1.0], 0.3, centers, widths, phase_vary=(kind == "heterodyne")))
    result = fit_polarization_set(_datasets(kind, noise=0.01), template)

    shared = result.per_dataset[0].spec
    np.testing.assert_allclose([p.params["center"].value for p in shared.peaks], _CENTERS, atol=0.5)
    np.testing.assert_allclose([p.params["width"].value for p in shared.peaks], _WIDTHS, rtol=0.05)
    for ds, fitted in zip(_datasets(kind), result.per_dataset):
        sign = np.sign(fitted.spec.nonresonant["amplitude"].value) if kind == "homodyne" else 1.0
        np.testing.assert_allclose(sign * _amplitudes(fitted.spec), _TRUE[ds.label][0], atol=0.1)


def test_polarization_set_rescues_a_joint_fit_that_fails_from_the_template():
    """Overlapping peaks, opposite signs between ssp and ppp, a strong ppp
    background and a rough shape guess: the plain joint fit started from
    ssp's amplitudes ends far off, the seeded one doesn't."""
    centers, widths = [2860.0, 2878.0, 2935.0, 2965.0], [14.0, 12.0, 16.0, 12.0]
    truth = {"ssp": ([4.0, 6.0, 2.0, 1.0], 0.6), "ppp": ([-3.0, 1.0, -6.0, 3.0], 3.0),
             "sps": ([0.5, -1.5, 0.1, -0.8], 0.15)}
    rng = np.random.default_rng(6)
    datasets = _datasets("homodyne", truth, centers, widths, noise=0.06, rng=rng)
    template = _shared_shapes(_spec(
        truth["ssp"][0], truth["ssp"][1],
        [c + rng.normal(0, 5) for c in centers], [w * rng.uniform(0.6, 1.6) for w in widths],
    ))

    def center_error(result):
        return max(abs(p.params["center"].value - c) for p, c in zip(result.per_dataset[0].spec.peaks, centers))

    plain = fit_global_batch(datasets, template)
    seeded = fit_polarization_set(datasets, template)
    assert center_error(plain) > 10.0
    assert center_error(seeded) < 2.0
    assert seeded.redchi < plain.redchi


def test_polarization_set_never_worse_than_plain_joint_fit():
    template = _shared_shapes(_spec([1.0, 1.0, 1.0], 0.3, [c + 3 for c in _CENTERS]))
    datasets = _datasets("homodyne", noise=0.02)
    assert fit_polarization_set(datasets, template).redchi <= fit_global_batch(datasets, template).redchi + 1e-12


def test_polarization_set_cancel_while_seeding_returns_none():
    template = _shared_shapes(_spec([1.0, 1.0, 1.0], 0.3))
    assert fit_polarization_set(_datasets("homodyne"), template, progress_cb=lambda *_: False) is None


def test_global_fit_without_seeds_unchanged():
    template = _shared_shapes(_spec([1.0, 1.0, 1.0], 0.3))
    datasets = _datasets("homodyne")
    a = fit_global_batch(datasets, template)
    b = fit_global_batch(datasets, template, seeds=None)
    assert a.redchi == b.redchi
    assert not a.seeded


# ── Sign rules ────────────────────────────────────────────────────────────

def _ruled(spec, rules):
    for peak, signs in zip(spec.peaks, rules):
        peak.amplitude_signs = dict(signs)
    return spec


def test_amplitude_signs_round_trip_and_old_dicts_load_empty():
    peak = default_peak("lorentzian", 2850.0)
    peak.amplitude_signs = {"ssp": "+", "ppp": "-"}
    assert PeakInstance.from_dict(peak.to_dict()).amplitude_signs == {"ssp": "+", "ppp": "-"}

    old = default_peak("lorentzian", 2850.0).to_dict()
    assert "amplitude_signs" not in old   # no rules -> serialized exactly as before
    assert PeakInstance.from_dict(old).amplitude_signs == {}


def test_apply_sign_constraints_narrows_bounds_and_flips_contradicting_start():
    spec = _ruled(_spec([1.0, 1.0, 1.0], 0.3), [{"ppp": "-"}, {"ppp": "+"}, {}])
    constrained = apply_sign_constraints(spec, "ppp")
    a0, a1, a2 = (p.params["amplitude"] for p in constrained.peaks)
    assert (a0.max, a0.value) == (0.0, -1.0)
    assert a1.min == 0.0
    assert (a2.min, a2.max) == (-np.inf, np.inf)
    assert spec.peaks[0].params["amplitude"].max == np.inf   # input untouched
    assert apply_sign_constraints(spec, "sps") is spec        # no rule -> no copy
    assert apply_sign_constraints(spec, None) is spec


def test_homodyne_start_mirrors_instead_of_flipping_one_amplitude():
    """Negating the whole homodyne model fits equally well, so a start
    that breaks a rule is mirrored as a whole, keeping relative signs."""
    spec = _ruled(_spec([3.0, 5.0, 2.0], 0.5), [{"ssp": "-"}, {}, {}])
    mirrored = apply_sign_constraints(spec, "ssp", mirror_ok=True)
    np.testing.assert_allclose(_amplitudes(mirrored), [-3.0, -5.0, -2.0])
    assert mirrored.nonresonant["amplitude"].value == -0.5

    flipped = apply_sign_constraints(spec, "ssp")   # heterodyne: no symmetry to use
    np.testing.assert_allclose(_amplitudes(flipped), [-3.0, 5.0, 2.0])

    spec.peaks[2].params["amplitude"].vary = False   # pinned -> mirror would change the model
    np.testing.assert_allclose(_amplitudes(apply_sign_constraints(spec, "ssp", mirror_ok=True)), [-3.0, 5.0, 2.0])


def test_sign_rules_fix_homodyne_signs_outright():
    """With the true signs given as rules, homodyne seeding has no global
    sign ambiguity left."""
    rules = [{pol: ("+" if amps[i] > 0 else "-") for pol, (amps, _nr) in _TRUE.items()} for i in range(3)]
    template = _ruled(_shared_shapes(_spec([1.0, 1.0, 1.0], 0.3)), rules)
    for ds in _datasets("homodyne"):
        np.testing.assert_allclose(_amplitudes(seed_amplitudes(ds, template)), _TRUE[ds.label][0], atol=1e-3)


def test_contradicting_rule_pins_amplitude_at_zero_and_flags_at_bound():
    ds = _datasets("heterodyne")[0]                                   # ssp: peak 2 is +5
    spec = _ruled(_spec([3.0, 5.0, 2.0], 0.5, phase_vary=True), [{}, {"ssp": "-"}, {}])
    # Shapes held fixed, as in a polarization set: with them free, the fit
    # escapes a wrong-signed rule by deforming the peak instead.
    for peak in spec.peaks:
        peak.params["center"].vary = peak.params["width"].vary = False
    result = fit_one_dataset(ds, spec)
    assert result.spec.peaks[1].params["amplitude"].value == pytest.approx(0.0, abs=1e-6)
    assert result.param_results["p1_amplitude"].at_bound
    # The narrowed bound stays out of the spec the user keeps editing.
    assert result.spec.peaks[1].params["amplitude"].max == np.inf
    assert result.spec.peaks[1].amplitude_signs == {"ssp": "-"}


def test_sign_rules_respected_in_every_batch_mode():
    datasets = _datasets("heterodyne", noise=0.01)
    rules = [{"ppp": "+"}, {}, {}]   # truth for ppp peak 1 is -1
    template = _ruled(_spec([1.0, 1.0, 1.0], 0.3, phase_vary=True), rules)

    independent = fit_independent_batch(datasets, template)
    sequential = fit_sequential_batch(datasets, template)
    seeded = fit_polarization_set(datasets, _shared_shapes(template))
    plain_global = fit_global_batch(datasets, _shared_shapes(template))
    for results in (independent, sequential, seeded.per_dataset, plain_global.per_dataset):
        ppp = results[1]
        assert ppp.spec.peaks[0].params["amplitude"].value >= 0.0
        assert ppp.param_results["p0_amplitude"].at_bound
        # Other polarizations are free to keep their own sign.
        assert results[2].spec.peaks[1].params["amplitude"].value < 0.0


def test_restore_amplitude_bounds_is_inverse_of_constraints():
    spec = _ruled(_spec([1.0, 1.0, 1.0], 0.3), [{"ssp": "+"}, {}, {}])
    constrained = apply_sign_constraints(spec, "ssp")
    restore_amplitude_bounds(constrained, spec)
    assert constrained.peaks[0].params["amplitude"].min == -np.inf


def test_single_fit_keeps_shared_flags_and_rules():
    """_spec_from_param_results used to drop the Shared flag, so a plain
    Run fit after "Share peak shapes" silently un-shared everything."""
    spec = _ruled(_shared_shapes(_spec([3.0, 5.0, 2.0], 0.5, phase_vary=True)), [{"ssp": "+"}, {}, {}])
    result = fit_one_dataset(_datasets("heterodyne")[0], spec)
    assert all(p.params["center"].shared and p.params["width"].shared for p in result.spec.peaks)
    assert result.spec.peaks[0].amplitude_signs == {"ssp": "+"}
