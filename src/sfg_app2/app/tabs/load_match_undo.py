# src/sfg_app2/app/tabs/load_match_undo.py
"""QUndoCommand subclasses for LoadMatchTab and its MatchTableModel.

MatchTableModel._rows/_types are plain lists of (path, name) string
tuples -- cheap to snapshot wholesale, so one reusable command
(ReplaceMatchTableCommand) covers every table-shape mutation (clear
cell, remove row, drag-drop, auto-match rebuild) instead of bespoke
per-operation commands.
"""
from __future__ import annotations
from typing import TYPE_CHECKING

from PySide6.QtGui import QUndoCommand

if TYPE_CHECKING:
    from sfg_app2.app.tabs.load_match import LoadMatchTab
    from sfg_app2.app.widgets.match_table import MatchTableModel


class ReplaceMatchTableCommand(QUndoCommand):
    def __init__(self, model: "MatchTableModel", old: tuple, new: tuple,
                 description: str = "Edit match table"):
        super().__init__(description)
        self._model = model
        self._old = old
        self._new = new

    def redo(self):
        self._model.restore(self._new)

    def undo(self):
        self._model.restore(self._old)


class RemoveFilesCommand(QUndoCommand):
    """Mirrors Spectra Library's RemoveEntriesCommand: restores exact
    original positions in tab._files, not just membership. Only
    _files/_file_registry/_individual_file_paths are handled here --
    any match-table cells the removal also clears are covered by a
    separate ReplaceMatchTableCommand, macro'd together by the caller
    so removing files is one undo step that restores both."""

    def __init__(self, tab: "LoadMatchTab", paths_to_remove: set[str],
                 description: str | None = None):
        n = len(paths_to_remove)
        super().__init__(description or (f"Remove {n} files" if n > 1 else "Remove file"))
        self._tab = tab
        self._paths_to_remove = set(paths_to_remove)
        self._removed_files: list[tuple[int, object]] = []
        self._removed_registry: dict[str, object] = {}
        self._removed_individual: list[tuple[int, object]] = []

    def redo(self):
        tab = self._tab
        self._removed_files = [
            (i, f) for i, f in enumerate(tab._files) if str(f.path) in self._paths_to_remove
        ]
        tab._files = [f for f in tab._files if str(f.path) not in self._paths_to_remove]
        self._removed_registry = {
            p: tab._file_registry[p] for p in self._paths_to_remove if p in tab._file_registry
        }
        for p in self._paths_to_remove:
            tab._file_registry.pop(p, None)
        self._removed_individual = [
            (i, p) for i, p in enumerate(tab._individual_file_paths)
            if str(p) in self._paths_to_remove
        ]
        tab._individual_file_paths = [
            p for p in tab._individual_file_paths if str(p) not in self._paths_to_remove
        ]

    def undo(self):
        tab = self._tab
        for index, f in self._removed_files:
            tab._files.insert(index, f)
        tab._file_registry.update(self._removed_registry)
        for index, p in self._removed_individual:
            tab._individual_file_paths.insert(index, p)


class UpdateFileMetadataCommand(QUndoCommand):
    """Same shape as Spectra Library's UpdateMetadataCommand, scoped to
    LoadMatchTab's own DataFile objects. Snapshot the "old" metadata
    before MetadataEditDialog.exec() (it mutates synchronously inside
    exec()); construct and push this only after Accepted."""

    def __init__(self, files: list, old_metadata_list: list[dict],
                 description: str = "Edit metadata"):
        super().__init__(description)
        self._files = list(files)
        self._old = old_metadata_list
        self._new = [dict(f.metadata) for f in self._files]

    def redo(self):
        for f, new in zip(self._files, self._new):
            f.metadata.clear()
            f.metadata.update(new)

    def undo(self):
        for f, old in zip(self._files, self._old):
            f.metadata.clear()
            f.metadata.update(old)
