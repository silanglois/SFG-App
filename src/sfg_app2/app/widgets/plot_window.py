# src/sfg_app2/app/widgets/plot_window.py
from __future__ import annotations
import logging
import math
import matplotlib.pyplot as plt
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QPushButton,
)

from sfg_app2.app.widgets.spectrum_plot_widget import SpectrumPlotWidget
from sfg_app2.app.utils.loading_indicator import show_loading
from sfg_app2.app.utils.legend_utils import build_legend

logger = logging.getLogger(__name__)


def _colors(n: int) -> list:
    prop_cycle = plt.rcParams["axes.prop_cycle"]
    colors = [p["color"] for p in prop_cycle]
    return [colors[i % len(colors)] for i in range(max(n, 1))]


def _frame_colors(n: int) -> list:
    """Distinct colors for n frames of one file: the style's own cycle
    while it lasts, a sequential colormap (frame order reads as a
    gradient) once there are more frames than cycle colors."""
    cycle = [p["color"] for p in plt.rcParams["axes.prop_cycle"]]
    if n <= len(cycle):
        return cycle[:max(n, 1)]
    cmap = plt.get_cmap("viridis")
    return [cmap(i / max(n - 1, 1)) for i in range(n)]


LEGEND_MODES = (("Full", "full"), ("Minimized", "minimized"), ("None", "none"))


class PlotWindow(QWidget):
    """Overlay plot of multiple DataFile spectra — average across all
    frames, all frames individually, or a single selected frame.

    A genuine independent top-level window (not a modal dialog) so several
    can stay open — and be minimized — at once; the caller is responsible
    for keeping a reference to it (e.g. LoadMatchTab.plot_windows) since
    nothing else does once it's shown.
    """

    def __init__(self, files: list, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Window)
        # a plain QWidget's close() only hides it by default — without
        # this, the window would never actually be destroyed, so the
        # caller's destroyed-signal-based cleanup (LoadMatchTab removing
        # it from plot_windows) would never fire
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle("Spectra Preview")
        self.resize(800, 500)

        self._files = files

        layout = QVBoxLayout(self)

        view_row = QHBoxLayout()
        view_row.addWidget(QLabel("View:"))
        self._view_combo = QComboBox()
        self._view_combo.addItem("Average (all frames)", userData="average")
        self._view_combo.addItem("All frames", userData="all")
        # cast to plain Python int — Frame columns are numpy.int64, and
        # storing those directly as combo userData causes Qt's QVariant
        # boxing to treat them as a different type than a plain python int,
        # breaking equality/lookup (e.g. findData()) against one
        frame_ids = sorted({int(fid) for f in files for fid in f.data["Frame"].unique()})
        for fid in frame_ids:
            self._view_combo.addItem(f"Frame {fid}", userData=fid)
        # One file: every frame, each in its own color (checking frame to
        # frame consistency is the usual reason to look at a single file).
        # Several files: one averaged curve per file, to compare files.
        if len(files) == 1:
            self._view_combo.setCurrentIndex(self._view_combo.findData("all"))
        self._view_combo.currentIndexChanged.connect(lambda: self._plot_files(self._files))
        view_row.addWidget(self._view_combo)

        view_row.addWidget(QLabel("Legend:"))
        self._legend_combo = QComboBox()
        for text, key in LEGEND_MODES:
            self._legend_combo.addItem(text, userData=key)
        self._legend_combo.setToolTip(
            "Full: every curve with its file name. Minimized: short names, "
            "one entry per file. None: no legend."
        )
        self._legend_combo.currentIndexChanged.connect(lambda: self._plot_files(self._files))
        view_row.addWidget(self._legend_combo)
        view_row.addStretch()
        layout.addLayout(view_row)

        self.plot_widget = SpectrumPlotWidget()
        layout.addWidget(self.plot_widget)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        close_row = QHBoxLayout()
        close_row.addStretch()
        close_row.addWidget(close_btn)
        layout.addLayout(close_row)

        loading = show_loading(self, "Loading spectra...")
        try:
            self._plot_files(files)
        finally:
            loading.close()

    def _plot_files(self, files: list):
        self.plot_widget.clear()
        mode = self._view_combo.currentData()
        legend_mode = self._legend_combo.currentData()
        minimized = legend_mode == "minimized"
        colors = _colors(len(files))
        single = len(files) == 1
        handles, labels = [], []

        def draw(fd, label, **kwargs):
            line, = self.plot_widget.ax.plot(
                fd["Wavelength"].to_numpy(), fd["Intensity"].to_numpy(), **kwargs)
            if label is not None:
                handles.append(line)
                labels.append(label)

        for f, color in zip(files, colors):
            name = f.path.stem if minimized else f.path.name
            try:
                if mode == "average":
                    draw(f.average_spectrum().frame(1), name, color=color)
                elif mode == "all":
                    frame_ids = list(f.data["Frame"].unique())
                    frame_colors = _frame_colors(len(frame_ids)) if single else None
                    for i, fid in enumerate(frame_ids):
                        if single:
                            label = f"F{fid}" if minimized else f"{name} F{fid}"
                        elif minimized:
                            # one entry per file, carried by its first frame
                            label = (f"{name} (F{frame_ids[0]}–F{frame_ids[-1]})"
                                     if len(frame_ids) > 1 else name) if i == 0 else None
                        else:
                            label = f"{name} F{fid}"
                        draw(f.frame(fid), label,
                             color=frame_colors[i] if single else color, alpha=0.85)
                else:
                    if mode not in f.data["Frame"].unique():
                        logger.warning(
                            "%s has no frame %s, skipping", f.path.name, mode
                        )
                        continue
                    draw(f.frame(mode), name, color=color)
            except Exception as e:
                logger.warning("Could not plot %s: %s", f.path.name, e)

        if handles and legend_mode != "none":
            kwargs = {"fontsize": 7} if minimized else {}
            if minimized and len(handles) > 12:
                kwargs["ncols"] = math.ceil(len(handles) / 12)
            build_legend(self.plot_widget.ax, handles, labels, **kwargs)

        # plot_widget.plot() auto-ranges against whatever's on the axes at
        # the moment of the *first* call in this loop -- i.e. just the
        # first file/frame, not the union of everything just plotted.
        # Force a fresh full-range computation now that every series is
        # actually on the axes.
        self.plot_widget.finalize_initial_range()

        mode_label = {"average": "averaged", "all": "all frames"}.get(mode, f"frame {mode}")
        self.plot_widget.set_labels(
            xlabel="Wavelength (nm)",
            ylabel="Intensity (counts)",
        )
        # descriptive window title instead of an on-plot title, so several
        # of these can be told apart while minimized/in the taskbar
        self.setWindowTitle(f"Spectra Preview — {len(files)} file(s), {mode_label}")
