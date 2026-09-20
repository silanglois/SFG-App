"""Qt-layer tests for the Fitting tab.

Run with:
    uv run pytest tests/test_fitting_tab.py -v
"""
import numpy as np
import pandas as pd
import pytest
from PySide6.QtWidgets import QMessageBox

from sfg_app2.app.tabs.fitting_tab import (
    FittingTab, _FileLoadedEntry, _make_list_item,
)
from sfg_app2.processing.processed_spectrum import ProcessedSpectrum

_OMEGA = np.linspace(3200.0, 3400.0, 64)


@pytest.fixture
def fitting_tab(qtbot):
    tab = FittingTab()
    qtbot.addWidget(tab)
    return tab


def _load_batch_entries(tab, count=2):
    """Put real, fittable entries in the Batch list so _on_run_batch_fit
    gets past its `len(entries) < 2` early return -- otherwise a guard
    test passes for the wrong reason."""
    for i in range(count):
        df = pd.DataFrame({
            "Wavenumber": _OMEGA,
            "Intensity": np.sin(_OMEGA / 40.0) + i,
        })
        spectrum = ProcessedSpectrum(df, metadata={}, history=[], provenance={})
        entry = _FileLoadedEntry(label=f"batch-{i}", spectrum=spectrum, kind="homodyne")
        tab._batch_file_entries.append(entry)
        tab._batch_list.addItem(_make_list_item(entry, checkable=False))


def _pause_a_sequential_run(tab):
    """Minimal stand-in for a run parked at a checkpoint. Only the
    'paused' flag is read by the guard under test."""
    tab._sequential_run = {"queue": [], "index": 0, "paused": True}
    tab._batch_rows = [("sentinel-entry", "sentinel-dataset", "sentinel-result")]
    return list(tab._batch_rows)


def test_batch_run_declined_leaves_paused_run_and_rows_intact(fitting_tab, monkeypatch):
    """Declining the prompt must abandon nothing.

    A paused sequential run still owns _batch_rows and keeps appending
    into it at each checkpoint, so letting a batch run overwrite them
    interleaves two runs' results in one table.
    """
    _load_batch_entries(fitting_tab)   # so the run would really proceed
    rows_before = _pause_a_sequential_run(fitting_tab)
    monkeypatch.setattr(
        QMessageBox, "question",
        staticmethod(lambda *a, **k: QMessageBox.StandardButton.No),
    )

    fitting_tab._on_run_batch_fit()

    assert fitting_tab._batch_rows == rows_before
    assert fitting_tab._sequential_run is not None
    assert fitting_tab._sequential_run["paused"] is True


def test_batch_run_accepted_clears_the_paused_run(fitting_tab, monkeypatch):
    """Accepting abandons the sequential run before the batch proceeds,
    so the two can never append into the same list."""
    _pause_a_sequential_run(fitting_tab)
    monkeypatch.setattr(
        QMessageBox, "question",
        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes),
    )

    # Bails out right after the guard (the batch list is empty), which is
    # all this test needs -- the guard has already run by then.
    fitting_tab._on_run_batch_fit()

    assert fitting_tab._sequential_run is None


def test_no_prompt_when_no_sequential_run_is_paused(fitting_tab, monkeypatch):
    def _fail(*_args, **_kwargs):
        raise AssertionError("should not prompt when nothing is paused")

    monkeypatch.setattr(QMessageBox, "question", staticmethod(_fail))
    fitting_tab._sequential_run = None

    fitting_tab._on_run_batch_fit()   # no entries loaded: returns harmlessly
