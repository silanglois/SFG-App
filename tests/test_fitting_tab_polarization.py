"""FittingTab's polarization-set controls: Share peak shapes, Polarization
from, sign constraints, and the seeded batch run."""
import numpy as np
import pandas as pd
import pytest

from sfg_app2.app.dialogs.sign_constraints_dialog import SignConstraintsDialog
from sfg_app2.app.tabs.fitting_tab import (
    FittingTab, _COL_PARAM, _FileLoadedEntry, _make_list_item,
)
from sfg_app2.processing.fitting import FitModelSpec, default_peak, evaluate_chi
from sfg_app2.processing.processed_spectrum import ProcessedSpectrum

_OMEGA = np.arange(2800.0, 3000.0, 1.0)
_CENTERS, _WIDTHS = [2850.0, 2880.0], [10.0, 12.0]
_TRUE = {"ssp": [3.0, 5.0], "ppp": [-1.0, 4.0], "sps": [0.8, -0.3]}


@pytest.fixture
def fitting_tab(qtbot):
    tab = FittingTab()
    qtbot.addWidget(tab)
    return tab


def _spec(amps):
    spec = FitModelSpec.empty()
    spec.nonresonant["amplitude"].value = 0.3
    for a, c, w in zip(amps, _CENTERS, _WIDTHS):
        spec.peaks.append(default_peak("lorentzian", c, amplitude=a, width=w))
    return spec


def _entry(pol, amps, extra_metadata=None):
    intensity = np.abs(evaluate_chi(_OMEGA, _spec(amps))) ** 2
    df = pd.DataFrame({"Wavenumber": _OMEGA, "Intensity": intensity})
    metadata = {"polarization": pol, "sample": "A", **(extra_metadata or {})}
    spectrum = ProcessedSpectrum(df, metadata=metadata, history=[], provenance={})
    return _FileLoadedEntry(label=f"A_{pol}", spectrum=spectrum, kind="conventional")


def _load_polarization_set(tab):
    entries = [_entry(pol, amps) for pol, amps in _TRUE.items()]
    for entry in entries:
        tab._batch_file_entries.append(entry)
        tab._batch_list.addItem(_make_list_item(entry, checkable=False))
    tab._refresh_batch_controls()
    # The reference spectrum (ssp) in the single-spectrum workspace.
    tab._load_from_processed_spectrum(entries[0].spectrum, entries[0].label, kind="conventional")
    for center in _CENTERS:
        tab._add_peak_at(center)
    return entries


# ── Share peak shapes ─────────────────────────────────────────────────────

def test_share_peak_shapes_marks_shapes_shared_and_undoes_in_one_step(fitting_tab):
    _load_polarization_set(fitting_tab)
    spec = fitting_tab._model_spec
    spec.nonresonant["amplitude"].shared = True   # should be cleared
    count_before = fitting_tab.undo_stack.count()

    fitting_tab._on_share_peak_shapes()

    spec = fitting_tab._model_spec
    assert fitting_tab.undo_stack.count() == count_before + 1
    for peak in spec.peaks:
        assert peak.params["center"].shared and peak.params["width"].shared
        assert not peak.params["amplitude"].shared
    assert not spec.nonresonant["amplitude"].shared
    assert sorted(fitting_tab._shared_param_keys(spec)) == ["p0_center", "p0_width", "p1_center", "p1_width"]

    fitting_tab.undo_stack.undo()
    assert fitting_tab._model_spec.nonresonant["amplitude"].shared
    assert not fitting_tab._model_spec.peaks[0].params["center"].shared


def test_share_peak_shapes_twice_pushes_nothing_the_second_time(fitting_tab):
    _load_polarization_set(fitting_tab)
    fitting_tab._on_share_peak_shapes()
    count = fitting_tab.undo_stack.count()
    fitting_tab._on_share_peak_shapes()
    assert fitting_tab.undo_stack.count() == count


# ── Polarization from ─────────────────────────────────────────────────────

def test_polarization_field_is_offered_and_preselected(fitting_tab):
    _load_polarization_set(fitting_tab)
    combo = fitting_tab._polarization_combo
    keys = [combo.itemData(i) for i in range(combo.count())]
    assert keys == [None, "polarization", "sample"]
    assert combo.currentData() == "polarization"
    assert fitting_tab._sign_rules_btn.isEnabled()
    assert fitting_tab._batch_polarization_values() == ["ssp", "ppp", "sps"]


def test_user_choice_of_none_survives_a_refresh(fitting_tab):
    _load_polarization_set(fitting_tab)
    combo = fitting_tab._polarization_combo
    combo.setCurrentIndex(combo.findData(None))
    fitting_tab._refresh_batch_controls()
    assert combo.currentData() is None
    assert not fitting_tab._sign_rules_btn.isEnabled()


def test_batch_datasets_carry_polarization(fitting_tab):
    entries = _load_polarization_set(fitting_tab)
    datasets = fitting_tab._build_batch_datasets(entries)
    assert [ds.polarization for ds in datasets] == ["ssp", "ppp", "sps"]


# ── Sign constraints ──────────────────────────────────────────────────────

def test_sign_constraints_dialog_round_trip(fitting_tab, qtbot):
    _load_polarization_set(fitting_tab)
    spec = fitting_tab._model_spec
    spec.peaks[0].amplitude_signs = {"old-pol": "+"}   # not a column: must survive
    dialog = SignConstraintsDialog(spec, ["ssp", "ppp", "sps"], "polarization")
    qtbot.addWidget(dialog)
    dialog.set_rule(0, "ssp", "+")
    dialog.set_rule(0, "ppp", "-")
    dialog.set_rule(1, "sps", "-")
    assert dialog.rules() == [{"old-pol": "+", "ssp": "+", "ppp": "-"}, {"sps": "-"}]


def test_apply_sign_rules_is_undoable_and_shown_in_parameter_table(fitting_tab):
    _load_polarization_set(fitting_tab)
    fitting_tab._apply_sign_rules([{"ssp": "+", "ppp": "-"}, {}])
    assert fitting_tab._model_spec.peaks[0].amplitude_signs == {"ssp": "+", "ppp": "-"}

    table = fitting_tab._param_table
    amplitude_row = fitting_tab._param_row_keys.index(("peak", 0, "amplitude"))
    assert table.item(amplitude_row, _COL_PARAM).text() == "Amplitude (ppp −, ssp +)"

    fitting_tab.undo_stack.undo()
    assert fitting_tab._model_spec.peaks[0].amplitude_signs == {}
    assert table.item(amplitude_row, _COL_PARAM).text() == "Amplitude"


def test_run_fit_respects_the_loaded_spectrums_rule(fitting_tab):
    """ssp truth is (+3, +5). Conventional only sees |chi|^2, so a "-" rule on
    peak 1 picks the mirror solution (-3, -5, flipped background) rather
    than fighting the data: the rule holds and the relative sign survives."""
    _load_polarization_set(fitting_tab)
    for peak in fitting_tab._model_spec.peaks:
        peak.params["center"].vary = peak.params["width"].vary = False
    fitting_tab._apply_sign_rules([{"ssp": "-"}, {}])

    fitting_tab._on_run_fit()

    spec = fitting_tab._model_spec
    a0, a1 = (p.params["amplitude"].value for p in spec.peaks)
    assert a0 < 0.0 and a1 < 0.0
    assert spec.nonresonant["amplitude"].value < 0.0
    assert spec.peaks[0].params["amplitude"].max == np.inf   # narrowed bound not kept on the model
    assert fitting_tab._last_result.param_results["p0_amplitude"].max == 0.0


# ── Seeded batch run ──────────────────────────────────────────────────────

def test_seeded_batch_run_fits_every_polarization_and_is_one_undo_step(fitting_tab):
    _load_polarization_set(fitting_tab)
    fitting_tab._on_share_peak_shapes()
    assert fitting_tab._seed_amplitudes_check.isChecked()
    count_before = fitting_tab.undo_stack.count()

    fitting_tab._on_run_batch_fit()

    assert len(fitting_tab._batch_rows) == 3
    assert fitting_tab._batch_global_result is not None
    assert fitting_tab.undo_stack.count() == count_before + 1
    for (entry, _ds, result), pol in zip(fitting_tab._batch_rows, _TRUE):
        sign = np.sign(result.spec.nonresonant["amplitude"].value)
        amps = [sign * p.params["amplitude"].value for p in result.spec.peaks]
        np.testing.assert_allclose(amps, _TRUE[pol], atol=0.05)

    fitting_tab.undo_stack.undo()
    assert fitting_tab._batch_rows == []
