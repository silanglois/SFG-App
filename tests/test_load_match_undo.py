"""Undo/redo for LoadMatchTab and its MatchTableModel."""
import types
from pathlib import Path

import pytest
from PySide6.QtWidgets import QMessageBox

from sfg_app2.app.tabs.load_match import LoadMatchTab
from sfg_app2.app.dialogs.metadata_edit_dialog import MetadataEditDialog


@pytest.fixture
def load_match_tab(qtbot):
    tab = LoadMatchTab()
    qtbot.addWidget(tab)
    return tab


def _fake_file(path_str: str):
    return types.SimpleNamespace(path=Path(path_str), metadata={})


def _put_files(tab, *files):
    tab._files = list(files)
    tab._file_registry = {str(f.path): f for f in files}
    tab._individual_file_paths = [f.path for f in files]


# ── Match table: clear / remove / drag-drop-equivalent ──────────────────────

def test_clear_cell_then_undo(load_match_tab):
    model = load_match_tab.match_table._table_model
    model.add_row()
    model.set_cell(0, 0, "C:/a.csv", "a.csv")

    before = model.snapshot()
    model.clear_cell(0, 0)
    load_match_tab.match_table._push_table_change(before, "Clear cell")
    assert model.data(model.createIndex(0, 0)) == "—"

    load_match_tab.undo_stack.undo()
    assert model.data(model.createIndex(0, 0)) == "a.csv"

    load_match_tab.undo_stack.redo()
    assert model.data(model.createIndex(0, 0)) == "—"


def test_remove_row_then_undo(load_match_tab):
    model = load_match_tab.match_table._table_model
    model.add_row()
    model.set_cell(0, 0, "C:/a.csv", "a.csv")
    model.add_row()
    model.set_cell(1, 0, "C:/b.csv", "b.csv")

    before = model.snapshot()
    model.remove_row(0)
    load_match_tab.match_table._push_table_change(before, "Remove row")
    assert model.rowCount() == 1
    assert model.data(model.createIndex(0, 0)) == "b.csv"

    load_match_tab.undo_stack.undo()
    assert model.rowCount() == 2
    assert model.data(model.createIndex(0, 0)) == "a.csv"
    assert model.data(model.createIndex(1, 0)) == "b.csv"


def test_no_op_table_change_pushes_nothing(load_match_tab):
    """clear_cell on an already-empty cell changes nothing -- shouldn't
    add a dead undo step."""
    model = load_match_tab.match_table._table_model
    model.add_row()
    before_count = load_match_tab.undo_stack.count()

    before = model.snapshot()
    model.clear_cell(0, 0)   # already empty
    load_match_tab.match_table._push_table_change(before, "Clear cell")

    assert load_match_tab.undo_stack.count() == before_count


# ── Auto-match rebuild ────────────────────────────────────────────────────

def test_auto_match_rebuild_then_undo_restores_hand_built_table(load_match_tab):
    model = load_match_tab.match_table._table_model
    model.add_row()
    model.set_cell(0, 0, "C:/hand_built.csv", "hand_built.csv")

    matched = [types.SimpleNamespace(
        signal=types.SimpleNamespace(path=Path("C:/auto.csv")),
        background=None, reference=None, reference_background=None,
        spectrum_type="homodyne",
    )]
    load_match_tab._populate_table_from_matched(matched)

    assert model.rowCount() == 1
    assert model.data(model.createIndex(0, 0)) == "auto.csv"

    load_match_tab.undo_stack.undo()
    assert model.rowCount() == 1
    assert model.data(model.createIndex(0, 0)) == "hand_built.csv"


# ── Remove files (file list + match-table cells, one undo step) ────────────

def test_remove_files_then_undo_restores_files_and_table_cell(load_match_tab, monkeypatch):
    file_a = _fake_file("C:/a.csv")
    file_b = _fake_file("C:/b.csv")
    _put_files(load_match_tab, file_a, file_b)

    model = load_match_tab.match_table._table_model
    model.add_row()
    model.set_cell(0, 0, str(file_a.path), "a.csv")

    monkeypatch.setattr(QMessageBox, "question",
                         staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))

    count_before = load_match_tab.undo_stack.count()
    load_match_tab._on_remove_files([str(file_a.path)])

    assert load_match_tab._files == [file_b]
    assert str(file_a.path) not in load_match_tab._file_registry
    assert model.data(model.createIndex(0, 0)) == "—"
    assert load_match_tab.undo_stack.count() == count_before + 1

    load_match_tab.undo_stack.undo()
    assert load_match_tab._files == [file_a, file_b]
    assert str(file_a.path) in load_match_tab._file_registry
    assert model.data(model.createIndex(0, 0)) == "a.csv"


def test_remove_ignored_files_then_undo(load_match_tab):
    file_a = _fake_file("C:/a.csv")
    file_b = _fake_file("C:/b.csv")
    _put_files(load_match_tab, file_a, file_b)

    removed = load_match_tab.remove_ignored_files({file_a.path.resolve()})
    assert removed == 1
    assert load_match_tab._files == [file_b]

    load_match_tab.undo_stack.undo()
    assert load_match_tab._files == [file_a, file_b]


# ── Metadata edits ────────────────────────────────────────────────────────

def test_review_metadata_then_undo(load_match_tab, monkeypatch):
    file_a = _fake_file("C:/a.csv")
    file_a.metadata["sample"] = "A"
    _put_files(load_match_tab, file_a)

    def _fake_exec(self):
        # Simulate the dialog's own synchronous mutation on Accept.
        file_a.metadata["sample"] = "B"
        return MetadataEditDialog.DialogCode.Accepted

    monkeypatch.setattr(MetadataEditDialog, "exec", _fake_exec)

    load_match_tab._on_review_metadata([str(file_a.path)])
    assert file_a.metadata["sample"] == "B"

    load_match_tab.undo_stack.undo()
    assert file_a.metadata["sample"] == "A"

    load_match_tab.undo_stack.redo()
    assert file_a.metadata["sample"] == "B"
