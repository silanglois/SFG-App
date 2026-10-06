"""Qt-layer tests for the Fitting tab: the job chips bar, the explicit
fit mode, viewing results without touching the starting model, refits,
paused sequences, and sending fits to the Spectra Library.

Run with:
    uv run pytest tests/test_fitting_tab.py -v
"""
import numpy as np
import pandas as pd
import pytest
from PySide6.QtWidgets import QMessageBox

from sfg_app2.app.tabs.fitting import job as jobmod
from sfg_app2.app.tabs.fitting_tab import FittingTab, _COL_SHARED, _FileLoadedEntry
from sfg_app2.processing.fitting import FitModelSpec, default_peak, evaluate_chi
from sfg_app2.processing.processed_spectrum import ProcessedSpectrum

_OMEGA = np.arange(2800.0, 3000.0, 1.0)


@pytest.fixture
def fitting_tab(qtbot):
    tab = FittingTab()
    qtbot.addWidget(tab)
    return tab


@pytest.fixture(autouse=True)
def _no_blocking_dialogs(monkeypatch):
    """A modal box would hang a headless run; fail loudly instead."""
    def _fail(*args, **_kwargs):
        raise AssertionError(f"unexpected dialog: {args[1:3]}")
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(_fail))
    monkeypatch.setattr(QMessageBox, "information", staticmethod(_fail))


def _entry(label, amps, center_shift=0.0, metadata=None):
    spec = FitModelSpec.empty()
    spec.nonresonant["amplitude"].value = 0.3
    for a, c, w in zip(amps, [2850.0, 2880.0], [10.0, 12.0]):
        spec.peaks.append(default_peak("lorentzian", c + center_shift, amplitude=a, width=w))
    intensity = np.abs(evaluate_chi(_OMEGA, spec)) ** 2
    df = pd.DataFrame({"Wavenumber": _OMEGA, "Intensity": intensity})
    spectrum = ProcessedSpectrum(df, metadata=dict(metadata or {}), history=[], provenance={})
    return _FileLoadedEntry(label=label, spectrum=spectrum, kind="conventional")


def _series(tab, n=3):
    """n spectra whose peaks drift a little (a 'temperature series')."""
    entries = [_entry(f"T{i}", [3.0, 5.0], center_shift=0.5 * i, metadata={"temperature": 20 + 5 * i})
               for i in range(n)]
    tab.add_entries_to_job(entries)
    for c in (2850.0, 2880.0):
        tab._add_peak_at(c)
    return entries


# ── chips bar ─────────────────────────────────────────────────────────────

def test_chips_guide_a_new_job(fitting_tab):
    bar = fitting_tab._job_bar
    assert bar.start_hint_target() is bar.chip(0)          # ① spectra first
    assert not bar.fit_button.isEnabled()
    fitting_tab.add_entries_to_job([_entry("a", [3.0, 5.0])])
    assert bar.start_hint_target() is bar.chip(1)          # then ② model
    fitting_tab._add_peak_at(2850.0)
    assert bar.start_hint_target() is None
    assert bar.fit_button.isEnabled()
    assert bar.fit_button.text() == "▶ Fit spectrum"
    assert "1 peak + NR" in bar.chip(1).text()


def test_job_list_is_opt_in(fitting_tab):
    class Provider:
        def entries(self, kind=None):
            return [_entry("lib-a", [1.0, 1.0]), _entry("lib-b", [1.0, 1.0])]

    fitting_tab.set_results_provider(Provider())
    assert fitting_tab._job.spectra == []   # nothing auto-added
    assert fitting_tab._job_list.count() == 0


def test_first_spectrum_becomes_the_reference_and_the_model_is_kept(fitting_tab):
    entries = _series(fitting_tab)
    assert fitting_tab._data.label == "T0"
    peaks_before = len(fitting_tab._model_spec.peaks)
    fitting_tab._set_reference(2)
    assert fitting_tab._data.label == "T2"
    assert len(fitting_tab._model_spec.peaks) == peaks_before   # the job's model, not reset
    assert fitting_tab._job.reference_entry() is entries[2]


# ── explicit mode ─────────────────────────────────────────────────────────

def test_shared_column_only_in_global_mode(fitting_tab):
    _series(fitting_tab)
    table = fitting_tab._param_table
    assert table.isColumnHidden(_COL_SHARED)            # Independent (default)
    fitting_tab._mode_radios["global"].setChecked(True)
    assert not table.isColumnHidden(_COL_SHARED)
    fitting_tab._mode_radios["sequential"].setChecked(True)
    assert table.isColumnHidden(_COL_SHARED)


def test_independent_mode_ignores_leftover_shared_flags(fitting_tab):
    _series(fitting_tab)
    fitting_tab._on_share_peak_shapes()                   # leftover from earlier work
    assert fitting_tab._job.mode == jobmod.INDEPENDENT
    fitting_tab._on_fit_clicked()
    assert fitting_tab._batch_run_mode == jobmod.INDEPENDENT
    assert fitting_tab._batch_global_result is None
    centers = [r.spec.peaks[0].params["center"].value for _e, _d, r in fitting_tab._batch_rows]
    assert np.ptp(centers) > 0.5                          # fit per spectrum, not shared
    assert fitting_tab.results_view.header_label.text().startswith("Independent fit of 3 spectra")


def test_global_with_nothing_shared_asks_instead_of_running(fitting_tab, monkeypatch):
    _series(fitting_tab)
    fitting_tab._job.mode = jobmod.GLOBAL                  # bypass the auto-share default
    shown = []
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: shown.append(a[1])))
    fitting_tab._on_fit_clicked()
    assert shown == ["Nothing is shared"]
    assert fitting_tab._batch_rows == []


# ── results: view, refit, use as start ────────────────────────────────────

def test_viewing_a_result_leaves_the_starting_model_alone(fitting_tab):
    _series(fitting_tab)
    fitting_tab._on_fit_clicked()
    start_spec = fitting_tab._model_spec
    start_values = [p.params["center"].value for p in start_spec.peaks]

    fitting_tab.results_view.select_row(2)
    assert fitting_tab._view is not None and fitting_tab._data.label == "T2"
    assert fitting_tab._model_spec is not start_spec
    # editing the viewed fit touches only its working copy, and isn't undoable
    count = fitting_tab.undo_stack.count()
    fitting_tab._on_param_edit(("peak", 0, "center"), "value", 2900.0)
    assert fitting_tab.undo_stack.count() == count
    assert "edited" in fitting_tab._pill_label.text()

    fitting_tab._on_back_to_start()
    assert fitting_tab._view is None
    assert fitting_tab._model_spec is start_spec
    assert [p.params["center"].value for p in start_spec.peaks] == start_values
    assert fitting_tab._data.label == "T0"


def test_refit_selected_only_touches_selected_rows(fitting_tab):
    _series(fitting_tab)
    fitting_tab._on_fit_clicked()
    before = [r for _e, _d, r in fitting_tab._batch_rows]
    count = fitting_tab.undo_stack.count()

    fitting_tab._refit_rows([1])
    after = [r for _e, _d, r in fitting_tab._batch_rows]
    assert after[0] is before[0] and after[2] is before[2]
    assert after[1] is not before[1]
    assert fitting_tab.undo_stack.count() == count + 1
    fitting_tab.undo_stack.undo()
    assert fitting_tab._batch_rows[1][2] is before[1]


def test_refit_this_spectrum_from_the_view_updates_only_its_row(fitting_tab):
    _series(fitting_tab)
    fitting_tab._on_fit_clicked()
    others = [fitting_tab._batch_rows[i][2] for i in (0, 2)]
    fitting_tab.results_view.select_row(1)
    fitting_tab._refit_viewed_row()
    assert fitting_tab._view is not None and fitting_tab._view["row"] == 1
    assert [fitting_tab._batch_rows[i][2] for i in (0, 2)] == others
    assert fitting_tab._last_result is fitting_tab._batch_rows[1][2]


def test_use_a_result_as_the_starting_model_is_undoable(fitting_tab):
    _series(fitting_tab)
    fitting_tab._on_fit_clicked()
    target = fitting_tab._batch_rows[2][2].spec.peaks[0].params["center"].value
    fitting_tab._use_row_as_start(2)
    assert fitting_tab._view is None
    assert fitting_tab._model_spec.peaks[0].params["center"].value == pytest.approx(target)
    fitting_tab.undo_stack.undo()
    assert fitting_tab._model_spec.peaks[0].params["center"].value != pytest.approx(target)


def test_results_table_has_parameter_columns_and_trend(fitting_tab):
    _series(fitting_tab)
    fitting_tab._on_fit_clicked()
    view = fitting_tab.results_view
    headers = [view.table.horizontalHeaderItem(c).text() for c in range(view.table.columnCount())]
    assert "P1 center" in headers and "P2 amplitude" in headers
    view.show_trend_for_column(headers.index("P1 center"))
    assert view.tabs.currentIndex() == 1
    assert view.trend_param_combo.currentText() == "P1 center"
    assert view.trend_x_combo.findData("temperature") >= 0


# ── sequential pauses ─────────────────────────────────────────────────────

def test_paused_sequence_seeds_from_the_paused_row_not_the_workspace(fitting_tab, qtbot):
    _series(fitting_tab)
    fitting_tab._mode_radios["sequential"].setChecked(True)
    fitting_tab._pause_combo.setCurrentIndex(fitting_tab._pause_combo.findData(jobmod.PAUSE_EACH))
    fitting_tab._on_fit_clicked()
    run = fitting_tab._sequential_run
    assert run["paused"] and len(fitting_tab._batch_rows) == 1
    assert fitting_tab._view["row"] == 0

    paused_result = fitting_tab._batch_rows[0][2]
    # Wander off to an unrelated view and edit it -- must not leak into the seed.
    fitting_tab._on_back_to_start()
    fitting_tab._on_param_edit(("peak", 0, "center"), "value", 2700.0)

    fitting_tab._on_sequential_continue()
    expected = paused_result.spec.peaks[0].params["center"].value
    assert run["current_spec"].peaks[0].params["center"].value == pytest.approx(expected)
    qtbot.waitUntil(lambda: fitting_tab._sequential_run is None or fitting_tab._sequential_run["paused"])


def test_stop_ends_a_paused_sequence_keeping_its_rows(fitting_tab):
    _series(fitting_tab)
    fitting_tab._mode_radios["sequential"].setChecked(True)
    fitting_tab._pause_combo.setCurrentIndex(fitting_tab._pause_combo.findData(jobmod.PAUSE_EACH))
    fitting_tab._on_fit_clicked()
    count = fitting_tab.undo_stack.count()
    fitting_tab._on_sequential_stop()
    assert fitting_tab._sequential_run is None
    assert len(fitting_tab._batch_rows) == 1
    assert fitting_tab.undo_stack.count() == count + 1
    assert fitting_tab._job_bar.fit_button.isEnabled()


def test_changing_spectra_while_paused_asks_first(fitting_tab, monkeypatch):
    _series(fitting_tab)
    fitting_tab._mode_radios["sequential"].setChecked(True)
    fitting_tab._pause_combo.setCurrentIndex(fitting_tab._pause_combo.findData(jobmod.PAUSE_EACH))
    fitting_tab._on_fit_clicked()
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.StandardButton.No))
    assert fitting_tab.add_entries_to_job([_entry("late", [1.0, 1.0])]) == 0
    assert fitting_tab._sequential_run is not None


# ── send to Spectra Library ───────────────────────────────────────────────

def test_send_to_library_adds_entries_carrying_the_fit(fitting_tab, results_tab):
    fitting_tab.set_results_provider(results_tab)
    _series(fitting_tab)
    fitting_tab._on_fit_clicked()
    fitting_tab._send_rows_to_library([0, 2])
    labels = [e.label for e in results_tab._entries]
    assert labels == ["T0", "T2"]
    entry = results_tab._entries[0]
    assert entry.fit_components   # fit curves are plottable components
    assert "Fit (total)" in entry.spectrum.data.columns
    assert "fit_json" in entry.spectrum.provenance

    fitting_tab._send_rows_to_library([0])   # same label again: kept apart
    assert results_tab._entries[-1].label == "T0 (fit)"


# ── plots and theme ───────────────────────────────────────────────────────

def test_overlay_keeps_a_user_set_x_range_across_redraws(fitting_tab):
    _series(fitting_tab)
    fitting_tab._on_fit_clicked()
    plot = fitting_tab.results_view.overlay_plot
    # what a user edit of the x min/max spinboxes does
    plot._x_min_spin.setValue(2860.0)
    plot._x_max_spin.setValue(2900.0)
    assert plot.ax.get_xlim() == pytest.approx((2860.0, 2900.0))

    fitting_tab._refit_rows([0])   # redraws the overlay from scratch
    assert plot.ax.get_xlim() == pytest.approx((2860.0, 2900.0))
    # and y follows the visible window, not the full spectrum
    lo, hi = plot.ax.get_ylim()
    assert hi < 30.0


def test_hint_text_and_view_pill_follow_the_theme(fitting_tab):
    from PySide6.QtGui import QPalette
    from sfg_app2.app.tabs.fitting_tab import _note
    assert _note("x").foregroundRole() == QPalette.ColorRole.PlaceholderText
    _series(fitting_tab)
    fitting_tab._on_fit_clicked()
    fitting_tab.results_view.select_row(0)
    style = fitting_tab._pill.styleSheet()
    assert "palette(" in style and "#e8f0fe" not in style
