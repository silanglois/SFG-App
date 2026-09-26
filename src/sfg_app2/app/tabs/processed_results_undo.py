# src/sfg_app2/app/tabs/processed_results_undo.py
"""QUndoCommand subclasses for ProcessedResultsTab (Spectra Library).

Each command captures only the small delta it needs -- never a deep
copy of a whole SpectrumEntry/its ProcessedSpectrum DataFrame -- and
ends with whatever refresh calls the original (now-removed) inline
code already made, so behavior outside of undo/redo is unchanged.
"""
from __future__ import annotations
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QUndoCommand

if TYPE_CHECKING:
    from sfg_app2.app.tabs.processed_results import ProcessedResultsTab, SpectrumEntry
    from sfg_app2.app.tabs.trace_style import PlotAnnotation, TraceStyle


class AddEntryCommand(QUndoCommand):
    """A brand-new entry, or a "Keep Both" duplicate -- both are a
    plain append, structurally identical."""

    def __init__(self, tab: "ProcessedResultsTab", entry: "SpectrumEntry",
                 description: str = "Add spectrum"):
        super().__init__(description)
        self._tab = tab
        self._entry = entry
        self._index: int | None = None

    def redo(self):
        self._tab._entries.append(self._entry)
        self._index = len(self._tab._entries) - 1
        self._tab._rebuild_list()
        self._tab._refresh_plot()

    def undo(self):
        del self._tab._entries[self._index]
        self._tab._rebuild_list()
        self._tab._refresh_plot()


class OverwriteEntryCommand(QUndoCommand):
    """The "Overwrite" conflict-resolution choice: replace one entry
    in place, keeping its list row (found by stored index, not widget
    row number, since drag-reordering can move it)."""

    def __init__(self, tab: "ProcessedResultsTab", index: int,
                 old_entry: "SpectrumEntry", new_entry: "SpectrumEntry",
                 description: str = "Overwrite spectrum"):
        super().__init__(description)
        self._tab = tab
        self._index = index
        self._old_entry = old_entry
        self._new_entry = new_entry

    def redo(self):
        self._tab._entries[self._index] = self._new_entry
        self._refresh_row_text(self._new_entry)
        self._tab._refresh_plot()

    def undo(self):
        self._tab._entries[self._index] = self._old_entry
        self._refresh_row_text(self._old_entry)
        self._tab._refresh_plot()

    def _refresh_row_text(self, entry: "SpectrumEntry"):
        from sfg_app2.app.tabs.processed_results import _entry_display_text
        list_widget = self._tab.ui.spectraList
        for row in range(list_widget.count()):
            item = list_widget.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == self._index:
                item.setText(_entry_display_text(entry))
                break


class RemoveEntriesCommand(QUndoCommand):
    """Restores exact original positions on undo, not just membership."""

    def __init__(self, tab: "ProcessedResultsTab", entries: list["SpectrumEntry"],
                 description: str | None = None):
        n = len(entries)
        label = f"Remove {n} spectra" if n > 1 else f'Remove "{entries[0].label}"'
        super().__init__(description or label)
        self._tab = tab
        self._labels_to_remove = {e.label for e in entries}
        self._removed: list[tuple[int, "SpectrumEntry"]] = []

    def redo(self):
        self._removed = [
            (i, e) for i, e in enumerate(self._tab._entries)
            if e.label in self._labels_to_remove
        ]
        self._tab._entries = [
            e for e in self._tab._entries if e.label not in self._labels_to_remove
        ]
        self._tab._rebuild_list()
        self._tab._refresh_plot()

    def undo(self):
        for index, entry in self._removed:
            self._tab._entries.insert(index, entry)
        self._tab._rebuild_list()
        self._tab._refresh_plot()


class SetTraceStylesCommand(QUndoCommand):
    """changes: (entry, key, had_key_before, old_style_or_None, new_style)
    tuples. TraceStyleDialog writes every row unconditionally on OK, so
    the caller snapshots all rows before exec() and reads all rows
    after -- no diffing needed here."""

    def __init__(self, tab: "ProcessedResultsTab",
                 changes: list[tuple["SpectrumEntry", str, bool, "TraceStyle | None", "TraceStyle"]],
                 description: str = "Set trace properties"):
        super().__init__(description)
        self._tab = tab
        self._changes = changes

    def redo(self):
        for entry, key, _had, _old, new in self._changes:
            entry.styles[key] = new
        self._tab._refresh_plot()

    def undo(self):
        for entry, key, had, old, _new in self._changes:
            if had:
                entry.styles[key] = old
            else:
                entry.styles.pop(key, None)
        self._tab._refresh_plot()


class ResetTraceStylesCommand(QUndoCommand):
    def __init__(self, tab: "ProcessedResultsTab", entries: list["SpectrumEntry"],
                 description: str = "Reset trace overrides"):
        super().__init__(description)
        self._tab = tab
        self._entries = list(entries)
        # TraceStyle instances are only ever whole-object-replaced, never
        # mutated in place, so a shallow dict copy is a sufficient snapshot.
        self._old_styles = [dict(e.styles) for e in self._entries]

    def redo(self):
        for entry in self._entries:
            entry.styles.clear()
        self._tab._rebuild_list()
        self._tab._refresh_plot()

    def undo(self):
        for entry, old in zip(self._entries, self._old_styles):
            entry.styles.clear()
            entry.styles.update(old)
        self._tab._rebuild_list()
        self._tab._refresh_plot()


class SortEntriesCommand(QUndoCommand):
    def __init__(self, tab: "ProcessedResultsTab", key_field: str,
                 description: str | None = None):
        super().__init__(description or f"Sort by {key_field}")
        self._tab = tab
        self._key_field = key_field
        self._old_order: list["SpectrumEntry"] | None = None

    def redo(self):
        self._old_order = list(self._tab._entries)

        # Same sort_key as _on_sort_by_metadata(), copied verbatim
        # (including its existing float/str-mixing behavior -- not in
        # scope to fix here).
        def sort_key(entry):
            val = entry.spectrum.metadata.get(self._key_field)
            if val is None:
                return ""
            try:
                return float(val)
            except (ValueError, TypeError):
                return str(val)

        self._tab._entries.sort(key=sort_key)
        self._tab._rebuild_list()
        self._tab._refresh_plot()

    def undo(self):
        self._tab._entries = list(self._old_order)
        self._tab._rebuild_list()
        self._tab._refresh_plot()


class ReplaceAnnotationsCommand(QUndoCommand):
    def __init__(self, tab: "ProcessedResultsTab",
                 old: list["PlotAnnotation"], new: list["PlotAnnotation"],
                 description: str = "Edit annotations"):
        super().__init__(description)
        self._tab = tab
        self._old = old
        self._new = new

    def redo(self):
        self._tab._annotations = self._new
        self._tab._refresh_plot()

    def undo(self):
        self._tab._annotations = self._old
        self._tab._refresh_plot()


class UpdateMetadataCommand(QUndoCommand):
    """Snapshot the "old" metadata before MetadataEditDialog.exec() (it
    mutates synchronously inside exec()); construct and push this only
    after Accepted, reading "new" from the now-already-mutated entries.
    push()'s synchronous redo() just re-applies those same values --
    harmless. No refresh call, matching _on_review_metadata() today
    (metadata never feeds the list text or the plot)."""

    def __init__(self, entries: list["SpectrumEntry"], old_metadata_list: list[dict],
                 description: str = "Edit metadata"):
        super().__init__(description)
        self._entries = list(entries)
        self._old = old_metadata_list
        self._new = [dict(e.spectrum.metadata) for e in self._entries]

    def redo(self):
        for entry, new in zip(self._entries, self._new):
            entry.spectrum.metadata.clear()
            entry.spectrum.metadata.update(new)

    def undo(self):
        for entry, old in zip(self._entries, self._old):
            entry.spectrum.metadata.clear()
            entry.spectrum.metadata.update(old)
