"""Undo/redo for FittingTab: peaks, parameter edits, template apply,
single fit, multi-spectrum runs."""
import numpy as np
import pandas as pd
import pytest

from sfg_app2.app.tabs.fitting_tab import FittingTab, _FileLoadedEntry, _COL_VALUE
from sfg_app2.processing.processed_spectrum import ProcessedSpectrum

_OMEGA = np.linspace(3200.0, 3400.0, 64)


@pytest.fixture
def fitting_tab(qtbot):
    tab = FittingTab()
    qtbot.addWidget(tab)
    return tab


def _load_conventional_data(tab, amplitude=1.0):
    df = pd.DataFrame({
        "Wavenumber": _OMEGA,
        "Intensity": amplitude * np.exp(-0.5 * ((_OMEGA - 3300.0) / 15.0) ** 2) + 0.05,
    })
    spectrum = ProcessedSpectrum(df, metadata={}, history=[], provenance={})
    tab._load_from_processed_spectrum(spectrum, "test-spectrum", kind="conventional")


def _load_batch_entries(tab, count=2):
    entries = []
    for i in range(count):
        df = pd.DataFrame({
            "Wavenumber": _OMEGA,
            "Intensity": np.exp(-0.5 * ((_OMEGA - 3300.0) / 15.0) ** 2) + 0.05 + 0.01 * i,
        })
        spectrum = ProcessedSpectrum(df, metadata={}, history=[], provenance={})
        entries.append(_FileLoadedEntry(label=f"batch-{i}", spectrum=spectrum, kind="conventional"))
    tab.add_entries_to_job(entries)


# ── Peaks ─────────────────────────────────────────────────────────────────

def test_add_peak_then_undo(fitting_tab):
    _load_conventional_data(fitting_tab)
    assert fitting_tab._model_spec.peaks == []

    fitting_tab._add_peak_at(3300.0)
    assert len(fitting_tab._model_spec.peaks) == 1

    fitting_tab.undo_stack.undo()
    assert fitting_tab._model_spec.peaks == []

    fitting_tab.undo_stack.redo()
    assert len(fitting_tab._model_spec.peaks) == 1


def test_remove_peak_then_undo_restores_peak_and_its_tuned_params(fitting_tab):
    _load_conventional_data(fitting_tab)
    fitting_tab._add_peak_at(3280.0)
    fitting_tab._add_peak_at(3320.0)
    assert len(fitting_tab._model_spec.peaks) == 2

    first_peak = fitting_tab._model_spec.peaks[0]
    first_peak.params["center"].value = 3280.5   # a hand-tuned value

    fitting_tab._on_remove_peak(0)
    assert len(fitting_tab._model_spec.peaks) == 1

    fitting_tab.undo_stack.undo()
    assert len(fitting_tab._model_spec.peaks) == 2
    assert fitting_tab._model_spec.peaks[0] is first_peak
    assert fitting_tab._model_spec.peaks[0].params["center"].value == 3280.5


# ── Apply template ────────────────────────────────────────────────────────

def test_apply_template_then_undo(fitting_tab):
    _load_conventional_data(fitting_tab)
    fitting_tab._add_peak_at(3300.0)
    fit_range = (fitting_tab._fit_min_spin.value(), fitting_tab._fit_max_spin.value())
    weighting = fitting_tab._weighting_combo.currentData()
    fitting_tab._template_manager.set("t1", fitting_tab._model_spec, fit_range, weighting)
    fitting_tab._refresh_template_combo()

    # Reset to an empty spec so applying the template is an observable change.
    from sfg_app2.processing.fitting import FitModelSpec
    fitting_tab._model_spec = FitModelSpec.empty()
    assert fitting_tab._model_spec.peaks == []

    fitting_tab._template_combo.setCurrentText("t1")
    fitting_tab._on_apply_template()
    assert len(fitting_tab._model_spec.peaks) == 1

    fitting_tab.undo_stack.undo()
    assert fitting_tab._model_spec.peaks == []

    fitting_tab.undo_stack.redo()
    assert len(fitting_tab._model_spec.peaks) == 1


# ── Run fit ───────────────────────────────────────────────────────────────

def test_run_fit_then_undo_reverts_table_and_result(fitting_tab):
    _load_conventional_data(fitting_tab)
    fitting_tab._add_peak_at(3300.0)
    assert fitting_tab._last_result is None

    fitting_tab._on_run_fit()
    assert fitting_tab._last_result is not None
    fitted_spec = fitting_tab._model_spec

    fitting_tab.undo_stack.undo()
    assert fitting_tab._last_result is None
    assert fitting_tab._model_spec is not fitted_spec
    assert len(fitting_tab._model_spec.peaks) == 1

    fitting_tab.undo_stack.redo()
    assert fitting_tab._last_result is not None


# ── Parameter edits ───────────────────────────────────────────────────────

def test_parameter_edits_are_undoable_and_merge_per_cell(fitting_tab):
    _load_conventional_data(fitting_tab)
    fitting_tab._add_peak_at(3300.0)
    key = ("peak", 0, "center")
    original = fitting_tab._param_at(key).value
    count = fitting_tab.undo_stack.count()

    for v in (3301.0, 3302.0, 3303.0):   # e.g. spinning the value
        fitting_tab._on_param_edit(key, "value", v)
    assert fitting_tab.undo_stack.count() == count + 1
    fitting_tab._on_param_edit(key, "vary", False)   # a different field: its own step
    assert fitting_tab.undo_stack.count() == count + 2

    fitting_tab.undo_stack.undo()
    assert fitting_tab._param_at(key).vary is True
    fitting_tab.undo_stack.undo()
    assert fitting_tab._param_at(key).value == original
    row = fitting_tab._param_row_keys.index(key)
    assert fitting_tab._param_table.cellWidget(row, _COL_VALUE).value() == original


# ── Multi-spectrum fit ────────────────────────────────────────────────────

def test_multi_spectrum_run_collapses_to_one_undo_step(fitting_tab):
    _load_conventional_data(fitting_tab)
    fitting_tab._add_peak_at(3300.0)
    _load_batch_entries(fitting_tab, count=2)

    count_before = fitting_tab.undo_stack.count()
    fitting_tab._on_fit_clicked()   # 3 spectra, Independent by default

    assert len(fitting_tab._batch_rows) == 3
    assert fitting_tab.undo_stack.count() == count_before + 1

    fitting_tab.undo_stack.undo()
    assert fitting_tab._batch_rows == []

    fitting_tab.undo_stack.redo()
    assert len(fitting_tab._batch_rows) == 3
