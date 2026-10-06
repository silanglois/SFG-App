"""Load/Match preview windows: default view per file count, per-frame
colors for a single file, and the Full / Minimized / None legend."""
import matplotlib.colors as mcolors
import pytest

from sfg_app2.app.widgets.plot_window import PlotWindow
from sfg_app2.processing.data_file import DataFile


@pytest.fixture
def files(raw_matched_files):
    folder, roles = raw_matched_files()
    return [DataFile(folder / roles[r]) for r in ("signal", "background")]


def _window(qtbot, files):
    window = PlotWindow(files)
    qtbot.addWidget(window)
    return window


def _legend_texts(window):
    legend = window.plot_widget.ax.get_legend()
    return None if legend is None else [t.get_text() for t in legend.get_texts()]


def test_single_file_shows_every_frame_in_its_own_color(qtbot, files):
    window = _window(qtbot, files[:1])
    assert window._view_combo.currentData() == "all"
    lines = window.plot_widget.ax.get_lines()
    assert len(lines) == 2   # two frames in the fixture
    colors = {mcolors.to_hex(line.get_color()) for line in lines}
    assert len(colors) == 2


def test_several_files_default_to_averages_one_color_each(qtbot, files):
    window = _window(qtbot, files)
    assert window._view_combo.currentData() == "average"
    assert len(window.plot_widget.ax.get_lines()) == 2
    assert _legend_texts(window) == [f.path.name for f in files]

    # "All frames" with several files keeps one color per file.
    window._view_combo.setCurrentIndex(window._view_combo.findData("all"))
    lines = window.plot_widget.ax.get_lines()
    assert len(lines) == 4
    assert lines[0].get_color() == lines[1].get_color() != lines[2].get_color()


def test_minimized_and_no_legend(qtbot, files):
    window = _window(qtbot, files)
    window._view_combo.setCurrentIndex(window._view_combo.findData("all"))
    assert len(_legend_texts(window)) == 4

    window._legend_combo.setCurrentIndex(window._legend_combo.findData("minimized"))
    assert _legend_texts(window) == [f"{f.path.stem} (F1–F2)" for f in files]

    window._legend_combo.setCurrentIndex(window._legend_combo.findData("none"))
    assert _legend_texts(window) is None


def test_minimized_single_file_lists_frames(qtbot, files):
    window = _window(qtbot, files[:1])
    window._legend_combo.setCurrentIndex(window._legend_combo.findData("minimized"))
    assert _legend_texts(window) == ["F1", "F2"]
