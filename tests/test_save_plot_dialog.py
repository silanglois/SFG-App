"""Tests for SavePlotDialog's per-row legend inclusion/exclusion.

An unchecked row is hidden in place (its handle + text set invisible)
rather than rebuilt without it -- see _apply_legend_overrides()'s
docstring-adjacent comment in save_plot_dialog.py. That keeps restore
exact without having to reconstruct a legend's original loc/ncol/
frameon, at the cost of a blank gap where a hidden entry sat.
"""
from PySide6.QtCore import Qt

from sfg_app2.app.dialogs.save_plot_dialog import SavePlotDialog
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


def test_unchecking_a_row_hides_it_during_render_then_restores(qtbot, monkeypatch):
    widget = _widget_with_legend(qtbot)
    dialog = SavePlotDialog(widget)
    qtbot.addWidget(dialog)

    dialog._legend_table.item(0, 0).setCheckState(Qt.CheckState.Unchecked)

    captured = {}
    orig_savefig = dialog.figure.savefig

    def spy_savefig(*args, **kwargs):
        legend = widget.ax.get_legend()
        captured["labels"] = [t.get_text() for t in legend.get_texts()]
        captured["visible"] = [t.get_visible() for t in legend.get_texts()]
        return orig_savefig(*args, **kwargs)

    monkeypatch.setattr(dialog.figure, "savefig", spy_savefig)

    dialog._render_bytes("png", 72)

    assert captured["labels"] == ["Alpha", "Beta"]
    assert captured["visible"] == [False, True], "Alpha was unchecked, Beta wasn't"

    # _render_bytes restores immediately after rendering -- the live
    # on-screen legend must never end up permanently altered.
    legend = widget.ax.get_legend()
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
