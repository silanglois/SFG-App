# src/sfg_app2/app/tabs/fitting_tab_undo.py
"""QUndoCommand subclasses for FittingTab.

A fit run is fully synchronous (lmfit on the GUI thread, no QThread),
so these commands snapshot/restore plain attributes rather than
coordinate with any background worker. FitModelSpec snapshots are
deepcopy'd (cheap -- a handful of dataclasses) since _model_spec is
mutated in place elsewhere (param-field edits, add/remove peak) and a
live reference would go stale across undo/redo; FitResult objects are
kept as plain references since nothing mutates them after a fit
completes.

Every command that touches the starting model first returns the
workspace from a viewed result row to the starting model
(tab._leave_view()), so an undo can never land on a result's working
copy instead.
"""
from __future__ import annotations
from copy import deepcopy
from typing import TYPE_CHECKING

from PySide6.QtGui import QUndoCommand

if TYPE_CHECKING:
    from sfg_app2.app.tabs.fitting_tab import FittingTab
    from sfg_app2.processing.fitting import FitModelSpec, PeakInstance


class AddPeakCommand(QUndoCommand):
    def __init__(self, tab: "FittingTab", peak: "PeakInstance",
                 description: str = "Add peak"):
        super().__init__(description)
        self._tab = tab
        self._peak = peak

    def _refresh(self):
        self._tab._rebuild_peak_table()
        self._tab._rebuild_parameter_table()
        self._tab._rebuild_display_table()
        self._tab._schedule_preview()

    def redo(self):
        self._tab._leave_view()
        self._tab._model_spec.peaks.append(self._peak)
        self._refresh()

    def undo(self):
        self._tab._leave_view()
        self._tab._model_spec.peaks.remove(self._peak)
        self._refresh()


class RemovePeakCommand(QUndoCommand):
    def __init__(self, tab: "FittingTab", index: int, peak: "PeakInstance",
                 description: str = "Remove peak"):
        super().__init__(description)
        self._tab = tab
        self._index = index
        self._peak = peak

    def _refresh(self):
        self._tab._rebuild_peak_table()
        self._tab._rebuild_parameter_table()
        self._tab._rebuild_display_table()
        self._tab._schedule_preview()

    def redo(self):
        self._tab._leave_view()
        del self._tab._model_spec.peaks[self._index]
        self._refresh()

    def undo(self):
        self._tab._leave_view()
        self._tab._model_spec.peaks.insert(self._index, self._peak)
        self._refresh()


class ApplyTemplateCommand(QUndoCommand):
    """`state` dicts: {spec, result, fit_range, weighting}. Both before
    and after are captured as independent deepcopies of the spec at
    construction time -- decoupled from whatever `tab._model_spec`
    later gets mutated into by (non-undoable) param edits, so a later
    undo/redo can't pick up stale in-place edits."""

    def __init__(self, tab: "FittingTab", before: dict, after: dict,
                 description: str = "Apply fit template"):
        super().__init__(description)
        self._tab = tab
        self._before = before
        self._after = after

    def _apply(self, state: dict):
        tab = self._tab
        tab._leave_view()
        tab._model_spec = deepcopy(state["spec"])
        tab._last_result = state["result"]
        tab._rebuild_peak_table()
        tab._rebuild_parameter_table()
        tab._rebuild_display_table()
        tab._update_quality_readout()
        if state["fit_range"] is not None:
            tab._set_fit_range(*state["fit_range"])
        if state["weighting"] is not None:
            idx = tab._weighting_combo.findData(state["weighting"])
            if idx >= 0:
                tab._weighting_combo.setCurrentIndex(idx)
        tab._schedule_preview()

    def redo(self):
        self._apply(self._after)

    def undo(self):
        self._apply(self._before)


class ReplaceModelSpecCommand(QUndoCommand):
    """A one-shot rewrite of the model's settings that leaves the last fit
    result alone -- "Share peak shapes", per-polarization sign rules.
    Both specs are deepcopied for the same reason as ApplyTemplateCommand."""

    def __init__(self, tab: "FittingTab", old_spec: "FitModelSpec", new_spec: "FitModelSpec",
                 description: str):
        super().__init__(description)
        self._tab = tab
        self._old_spec = deepcopy(old_spec)
        self._new_spec = deepcopy(new_spec)

    def _apply(self, spec: "FitModelSpec"):
        tab = self._tab
        tab._leave_view()
        tab._model_spec = deepcopy(spec)
        tab._rebuild_peak_table()
        tab._rebuild_parameter_table()
        tab._rebuild_display_table()
        tab._apply_fit_result_to_table()
        tab._schedule_preview()

    def redo(self):
        self._apply(self._new_spec)

    def undo(self):
        self._apply(self._old_spec)


class RunFitCommand(QUndoCommand):
    """The "undo a fit" ask. redo() restores the already-computed
    result rather than re-running the (potentially slow) minimizer."""

    def __init__(self, tab: "FittingTab", old_spec: "FitModelSpec", old_result,
                 new_spec: "FitModelSpec", new_result,
                 description: str = "Run fit"):
        super().__init__(description)
        self._tab = tab
        self._old_spec = deepcopy(old_spec)
        self._old_result = old_result
        self._new_spec = deepcopy(new_spec)
        self._new_result = new_result

    def _apply(self, spec: "FitModelSpec", result):
        tab = self._tab
        tab._leave_view()
        tab._model_spec = deepcopy(spec)
        tab._last_result = result
        tab._apply_fit_result_to_table()
        tab._update_quality_readout()
        tab._update_preview()

    def redo(self):
        self._apply(self._new_spec, self._new_result)

    def undo(self):
        self._apply(self._old_spec, self._old_result)


class EditParamCommand(QUndoCommand):
    """One field of one starting-model parameter (value, vary, shared,
    min, max, expr). Consecutive edits of the same field merge into one
    step, so typing a number or spinning a value is a single undo."""

    _ID = 4711

    def __init__(self, tab: "FittingTab", key: tuple, field: str, old, new, label: str):
        super().__init__(f"Edit {label} {field}")
        self._tab = tab
        self._key = key
        self._field = field
        self._old = old
        self._new = new
        self._first = True

    def id(self) -> int:
        return self._ID

    def mergeWith(self, other) -> bool:
        if not isinstance(other, EditParamCommand) or (other._key, other._field) != (self._key, self._field):
            return False
        self._new = other._new
        return True

    def _apply(self, value, refresh_widget: bool):
        tab = self._tab
        tab._leave_view()
        setattr(tab._param_at(self._key), self._field, value)
        if refresh_widget:
            tab._set_param_widget(self._key, self._field, value)
        tab._schedule_preview()
        if self._field == "shared":
            tab._refresh_job_bar()

    def redo(self):
        # the first redo is the push itself: the widget already shows it
        self._apply(self._new, refresh_widget=not self._first)
        self._first = False

    def undo(self):
        self._apply(self._old, refresh_widget=True)


_RUN_NAMES = {"independent": "Independent fit", "sequential": "Sequential fit", "global": "Global fit"}


class RunBatchFitCommand(QUndoCommand):
    """Covers an entire multi-spectrum run (however many review pauses it
    took), or a refit of some of its rows, as one atomic undo step --
    only pushed once the run finishes (FittingTab._maybe_push_batch_undo),
    so a paused run never has a half-finished state pushed."""

    def __init__(self, tab: "FittingTab", old_state: tuple, new_state: tuple,
                 description: str | None = None):
        mode = new_state[5]
        super().__init__(description or _RUN_NAMES.get(mode, "Fit"))
        self._tab = tab
        self._old_state = old_state
        self._new_state = new_state

    def redo(self):
        self._tab._restore_batch_state(self._new_state)
        self._tab._finish_multifit_run()

    def undo(self):
        self._tab._restore_batch_state(self._old_state)
        self._tab._finish_multifit_run()
