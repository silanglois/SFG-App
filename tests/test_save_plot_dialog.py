"""Tests for SavePlotDialog's per-row legend inclusion/exclusion.

An unchecked row is dropped by rebuilding the legend from the kept rows
only (so the rest close up, with no blank gap), using the original
legend's loc/ncol/frame settings; on restore the panel's own Legend
object is re-attached unchanged.
"""
import numpy as np
import pytest
from matplotlib.legend_handler import HandlerTuple
from PySide6.QtCore import Qt

from sfg_app2.app.dialogs.save_plot_dialog import SavePlotDialog
from sfg_app2.app.utils.legend_utils import build_legend
from sfg_app2.app.widgets.spectrum_plot_widget import SpectrumPlotWidget


def _widget_with_legend(qtbot):
    widget = SpectrumPlotWidget()
    qtbot.addWidget(widget)
    widget.plot([0, 1, 2], [0, 1, 2], label="Alpha")
    widget.plot([0, 1, 2], [2, 1, 0], label="Beta")
    widget.ax.legend(fontsize=8)
    widget.canvas.draw()
    return widget


def test_legend_table_lists_one_row_per_entry_checked_by_default(qtbot):
    widget = _widget_with_legend(qtbot)
    dialog = SavePlotDialog(widget)
    qtbot.addWidget(dialog)

    assert dialog._legend_table.rowCount() == 2
    assert [dialog._legend_table.item(r, 1).text() for r in range(2)] == ["Alpha", "Beta"]
    assert all(
        dialog._legend_table.item(r, 0).checkState() == Qt.CheckState.Checked
        for r in range(2)
    )
    dialog.done(0)


def test_unchecking_a_row_drops_it_during_render_then_restores(qtbot, monkeypatch):
    widget = _widget_with_legend(qtbot)
    dialog = SavePlotDialog(widget)
    qtbot.addWidget(dialog)

    dialog._legend_table.item(0, 0).setCheckState(Qt.CheckState.Unchecked)

    captured = {}
    orig_savefig = dialog.figure.savefig

    def spy_savefig(*args, **kwargs):
        legend = widget.ax.get_legend()
        captured["labels"] = [t.get_text() for t in legend.get_texts()]
        return orig_savefig(*args, **kwargs)

    monkeypatch.setattr(dialog.figure, "savefig", spy_savefig)
    original = widget.ax.get_legend()

    dialog._render_bytes("png", 72)

    assert captured["labels"] == ["Beta"], "Alpha was unchecked -- gone, not a blank row"

    # _render_bytes restores immediately after rendering -- the live
    # on-screen legend must never end up permanently altered.
    legend = widget.ax.get_legend()
    assert legend is original
    assert all(t.get_visible() for t in legend.get_texts())
    assert [t.get_text() for t in legend.get_texts()] == ["Alpha", "Beta"]

    dialog.done(0)


def test_editing_a_label_travels_into_the_render_and_then_restores(qtbot, monkeypatch):
    widget = _widget_with_legend(qtbot)
    dialog = SavePlotDialog(widget)
    qtbot.addWidget(dialog)

    dialog._legend_table.item(1, 1).setText("Beta (renamed)")

    captured = {}
    orig_savefig = dialog.figure.savefig

    def spy_savefig(*args, **kwargs):
        legend = widget.ax.get_legend()
        captured["labels"] = [t.get_text() for t in legend.get_texts()]
        return orig_savefig(*args, **kwargs)

    monkeypatch.setattr(dialog.figure, "savefig", spy_savefig)
    dialog._render_bytes("png", 72)

    assert captured["labels"] == ["Alpha", "Beta (renamed)"]

    legend = widget.ax.get_legend()
    assert [t.get_text() for t in legend.get_texts()] == ["Alpha", "Beta"], (
        "closing/re-rendering must not leave the live legend's own text edited"
    )

    dialog.done(0)


# ── Rebuild keeps the original legend's settings ──────────────────────────
@pytest.fixture
def plot(qtbot):
    widget = SpectrumPlotWidget()
    qtbot.addWidget(widget)
    x = np.linspace(0, 1, 20)
    for i, name in enumerate("abc"):
        widget.ax.plot(x, x + i, label=name)
    return widget


def _untick(dialog, row):
    dialog._legend_table.item(row, 0).setCheckState(Qt.CheckState.Unchecked)


def _visible_texts(ax):
    legend = ax.get_legend()
    return [t.get_text() for t in legend.get_texts() if t.get_visible()]


def test_dropped_entry_leaves_no_gap_and_restores(plot, qtbot):
    original = plot.ax.legend(loc="lower right", ncols=2, frameon=False)
    dialog = SavePlotDialog(plot)
    qtbot.addWidget(dialog)

    _untick(dialog, 1)
    dialog._apply_legend_overrides()
    rebuilt = plot.ax.get_legend()
    assert rebuilt is not original
    assert [t.get_text() for t in rebuilt.get_texts()] == ["a", "c"]   # no hidden row
    assert rebuilt._loc == original._loc and rebuilt._ncols == 2
    assert not rebuilt.get_frame_on()

    dialog._restore_original_state()
    assert plot.ax.get_legend() is original
    assert _visible_texts(plot.ax) == ["a", "b", "c"]


def test_relabel_and_hide_all(plot, qtbot):
    original = plot.ax.legend()
    dialog = SavePlotDialog(plot)
    qtbot.addWidget(dialog)

    dialog._legend_table.item(0, 1).setText("renamed")
    dialog._apply_legend_overrides()
    assert [t.get_text() for t in plot.ax.get_legend().get_texts()] == ["renamed", "b", "c"]
    dialog._restore_original_state()

    for row in range(3):
        _untick(dialog, row)
    dialog._apply_legend_overrides()
    assert plot.ax.get_legend() is original and not original.get_visible()
    dialog._restore_original_state()
    assert original.get_visible()


def test_tuple_handles_survive_a_rebuild(plot, qtbot):
    a, b, c = plot.ax.get_lines()
    build_legend(plot.ax, [(a, b), c], ["a+b", "c"],
                 handler_map={tuple: HandlerTuple(ndivide=1)})
    dialog = SavePlotDialog(plot)
    qtbot.addWidget(dialog)
    assert dialog._legend_handles[0] == (a, b)

    _untick(dialog, 1)
    dialog._apply_legend_overrides()
    assert [t.get_text() for t in plot.ax.get_legend().get_texts()] == ["a+b"]
    dialog._restore_original_state()


def test_dialog_created_legend_is_removed_again(plot, qtbot):
    dialog = SavePlotDialog(plot)
    qtbot.addWidget(dialog)
    dialog._legend_check.setChecked(True)
    _untick(dialog, 0)
    dialog._apply_legend_overrides()
    assert [t.get_text() for t in plot.ax.get_legend().get_texts()] == ["b", "c"]
    dialog._restore_original_state()
    assert plot.ax.get_legend() is None
