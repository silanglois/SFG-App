"""Undo/redo for ProcessedResultsTab (Spectra Library)."""
from PySide6.QtWidgets import QInputDialog, QMessageBox

from sfg_app2.app.tabs.processed_results import SpectrumEntry
from sfg_app2.app.tabs.processed_results_undo import (
    AddEntryCommand, OverwriteEntryCommand, RemoveEntriesCommand,
    ReplaceAnnotationsCommand, ResetTraceStylesCommand, SetTraceStylesCommand,
    SortEntriesCommand, UpdateMetadataCommand,
)
from sfg_app2.app.tabs.trace_style import TraceStyle


# ── Remove / add ─────────────────────────────────────────────────────────

def test_remove_then_undo_restores_exact_index(load_entries, make_homodyne_entry):
    e0, e1, e2 = (make_homodyne_entry(f"e{i}") for i in range(3))
    tab = load_entries(e0, e1, e2)

    tab.undo_stack.push(RemoveEntriesCommand(tab, [e1]))
    assert tab._entries == [e0, e2]

    tab.undo_stack.undo()
    assert tab._entries == [e0, e1, e2]

    tab.undo_stack.redo()
    assert tab._entries == [e0, e2]


def test_remove_multiple_then_undo_restores_original_order(load_entries, make_homodyne_entry):
    entries = [make_homodyne_entry(f"e{i}") for i in range(5)]
    tab = load_entries(*entries)

    tab.undo_stack.push(RemoveEntriesCommand(tab, [entries[1], entries[3]]))
    assert tab._entries == [entries[0], entries[2], entries[4]]

    tab.undo_stack.undo()
    assert tab._entries == entries


def test_add_entry_then_undo(load_entries, make_homodyne_entry):
    e0 = make_homodyne_entry("e0")
    tab = load_entries(e0)
    new_entry = make_homodyne_entry("new")

    tab.undo_stack.push(AddEntryCommand(tab, new_entry))
    assert tab._entries == [e0, new_entry]

    tab.undo_stack.undo()
    assert tab._entries == [e0]


def test_overwrite_entry_then_undo(load_entries, make_homodyne_entry):
    e0 = make_homodyne_entry("e0")
    tab = load_entries(e0)
    replacement = make_homodyne_entry("e0", amplitude=2.0)

    tab.undo_stack.push(OverwriteEntryCommand(tab, 0, e0, replacement))
    assert tab._entries == [replacement]

    tab.undo_stack.undo()
    assert tab._entries == [e0]


def test_batch_add_via_add_from_file_collapses_to_one_undo_step(results_tab, tmp_path, monkeypatch):
    csv1 = tmp_path / "a.csv"
    csv1.write_text("Wavenumber,Intensity\n2800.0,1.0\n2850.0,1.1\n")
    csv2 = tmp_path / "b.csv"
    csv2.write_text("Wavenumber,Intensity\n2800.0,2.0\n2850.0,2.1\n")

    from PySide6.QtWidgets import QFileDialog
    monkeypatch.setattr(
        QFileDialog, "getOpenFileNames",
        staticmethod(lambda *a, **k: ([str(csv1), str(csv2)], "")),
    )

    results_tab._on_add_from_file()

    assert len(results_tab._entries) == 2
    assert results_tab.undo_stack.count() == 1

    results_tab.undo_stack.undo()
    assert results_tab._entries == []


def test_add_from_file_all_skipped_leaves_no_dead_undo_step(results_tab, tmp_path, monkeypatch):
    # A directory, not a file -- guaranteed to raise inside the per-file
    # try/except (caught as "failed"), so nothing ever gets added.
    bad = tmp_path / "unreadable.csv"
    bad.mkdir()

    from PySide6.QtWidgets import QFileDialog
    monkeypatch.setattr(
        QFileDialog, "getOpenFileNames",
        staticmethod(lambda *a, **k: ([str(bad)], "")),
    )

    results_tab._on_add_from_file()

    assert results_tab._entries == []
    # The empty macro was discarded via undo() -- Undo shows nothing to
    # do (canUndo() is False). QUndoStack.undo() doesn't delete entries
    # outright, so the harmless no-op macro can still technically be
    # redone, but that's invisible in normal use (nobody hits Redo
    # before ever hitting Undo).
    assert not results_tab.undo_stack.canUndo()


# ── Trace style ──────────────────────────────────────────────────────────

def test_set_trace_styles_then_undo_restores_sparse_absence(load_entries, make_homodyne_entry):
    # Unchecked -- _refresh_plot() never calls style_for() on it, so
    # (unlike a checked/plotted entry) its styles dict starts genuinely
    # empty, the same as an entry a user opens Trace Properties on
    # without ever having checked it.
    entry = make_homodyne_entry("e0", checked=False)
    tab = load_entries(entry)
    assert "__amplitude__" not in entry.styles

    changes = [(entry, "__amplitude__", False, None, TraceStyle(color="red"))]
    tab.undo_stack.push(SetTraceStylesCommand(tab, changes))
    assert entry.styles["__amplitude__"].color == "red"

    tab.undo_stack.undo()
    assert "__amplitude__" not in entry.styles


def test_set_trace_styles_then_undo_restores_prior_value(load_entries, make_homodyne_entry):
    entry = make_homodyne_entry("e0")
    tab = load_entries(entry)
    original = TraceStyle(color="blue")
    entry.styles["__amplitude__"] = original

    changes = [(entry, "__amplitude__", True, original, TraceStyle(color="green"))]
    tab.undo_stack.push(SetTraceStylesCommand(tab, changes))
    assert entry.styles["__amplitude__"].color == "green"

    tab.undo_stack.undo()
    assert entry.styles["__amplitude__"] is original


def test_reset_trace_styles_then_undo(load_entries, make_homodyne_entry):
    # Unchecked, so _refresh_plot() (called by both load_entries() and
    # the command itself) never re-populates a default style behind our
    # back via style_for()'s setdefault -- isolates the command's own
    # clear/restore logic from that unrelated auto-populate side effect.
    entry = make_homodyne_entry("e0", checked=False)
    entry.styles["__amplitude__"] = TraceStyle(color="red")
    tab = load_entries(entry)

    tab.undo_stack.push(ResetTraceStylesCommand(tab, [entry]))
    assert entry.styles == {}

    tab.undo_stack.undo()
    assert entry.styles["__amplitude__"].color == "red"


# ── Sort / annotations / metadata ────────────────────────────────────────

def test_sort_by_metadata_then_undo(load_entries, make_homodyne_entry):
    e0 = make_homodyne_entry("e0", metadata={"conc": "3"})
    e1 = make_homodyne_entry("e1", metadata={"conc": "1"})
    e2 = make_homodyne_entry("e2", metadata={"conc": "2"})
    tab = load_entries(e0, e1, e2)

    tab.undo_stack.push(SortEntriesCommand(tab, "conc"))
    assert [e.label for e in tab._entries] == ["e1", "e2", "e0"]

    tab.undo_stack.undo()
    assert tab._entries == [e0, e1, e2]


def test_sort_by_metadata_via_handler(load_entries, make_homodyne_entry, monkeypatch):
    e0 = make_homodyne_entry("e0", metadata={"conc": "3"})
    e1 = make_homodyne_entry("e1", metadata={"conc": "1"})
    tab = load_entries(e0, e1)

    monkeypatch.setattr(QInputDialog, "getItem", staticmethod(lambda *a, **k: ("conc", True)))
    tab._on_sort_by_metadata()

    assert [e.label for e in tab._entries] == ["e1", "e0"]
    tab.undo_stack.undo()
    assert [e.label for e in tab._entries] == ["e0", "e1"]


def test_replace_annotations_then_undo(load_entries, make_homodyne_entry):
    tab = load_entries(make_homodyne_entry("e0"))
    old = list(tab._annotations)

    tab.undo_stack.push(ReplaceAnnotationsCommand(tab, old, ["new-annotation"]))
    assert tab._annotations == ["new-annotation"]

    tab.undo_stack.undo()
    assert tab._annotations == old


def test_update_metadata_then_undo(load_entries, make_homodyne_entry):
    entry = make_homodyne_entry("e0", metadata={"sample": "A"})
    tab = load_entries(entry)
    old_metadata = [dict(entry.spectrum.metadata)]

    entry.spectrum.metadata["sample"] = "B"   # simulate the dialog's live mutation
    tab.undo_stack.push(UpdateMetadataCommand([entry], old_metadata))
    assert entry.spectrum.metadata["sample"] == "B"

    tab.undo_stack.undo()
    assert entry.spectrum.metadata == {"sample": "A"}

    tab.undo_stack.redo()
    assert entry.spectrum.metadata["sample"] == "B"


def test_on_remove_handler_pushes_undo(load_entries, make_homodyne_entry, monkeypatch):
    e0 = make_homodyne_entry("e0")
    e1 = make_homodyne_entry("e1")
    tab = load_entries(e0, e1)

    monkeypatch.setattr(QMessageBox, "question",
                         staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    tab._on_remove([e0])
    assert tab._entries == [e1]

    tab.undo_stack.undo()
    assert tab._entries == [e0, e1]
