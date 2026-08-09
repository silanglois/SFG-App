# src/sfg_app2/app/dialogs/plot_dialog.py
from __future__ import annotations
import logging
import matplotlib.pyplot as plt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QDialogButtonBox,
)

from sfg_app2.app.widgets.spectrum_plot_widget import SpectrumPlotWidget
from sfg_app2.app.utils.loading_indicator import show_loading

logger = logging.getLogger(__name__)


def _colors(n: int) -> list:
    prop_cycle = plt.rcParams["axes.prop_cycle"]
    colors = [p["color"] for p in prop_cycle]
    return [colors[i % len(colors)] for i in range(max(n, 1))]


class PlotDialog(QDialog):
    """Overlay plot of multiple DataFile spectra — average across all
    frames, all frames individually, or a single selected frame."""

    def __init__(self, files: list, parent=None):
        super().__init__(parent)
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
        self._view_combo.currentIndexChanged.connect(lambda: self._plot_files(self._files))
        view_row.addWidget(self._view_combo)
        view_row.addStretch()
        layout.addLayout(view_row)

        self.plot_widget = SpectrumPlotWidget()
        layout.addWidget(self.plot_widget)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        loading = show_loading(self, "Loading spectra...")
        try:
            self._plot_files(files)
        finally:
            loading.close()

    def _plot_files(self, files: list):
        self.plot_widget.clear()
        mode = self._view_combo.currentData()
        colors = _colors(len(files))

        for f, color in zip(files, colors):
            try:
                if mode == "average":
                    avg = f.average_spectrum().frame(1)
                    self.plot_widget.plot(
                        avg["Wavelength"].to_numpy(),
                        avg["Intensity"].to_numpy(),
                        label=f.path.name, color=color,
                    )
                elif mode == "all":
                    for fid in f.data["Frame"].unique():
                        fd = f.frame(fid)
                        self.plot_widget.plot(
                            fd["Wavelength"].to_numpy(),
                            fd["Intensity"].to_numpy(),
                            label=f"{f.path.name} F{fid}", color=color, alpha=0.85,
                        )
                else:
                    if mode not in f.data["Frame"].unique():
                        logger.warning(
                            "%s has no frame %s, skipping", f.path.name, mode
                        )
                        continue
                    fd = f.frame(mode)
                    self.plot_widget.plot(
                        fd["Wavelength"].to_numpy(),
                        fd["Intensity"].to_numpy(),
                        label=f.path.name, color=color,
                    )
            except Exception as e:
                logger.warning("Could not plot %s: %s", f.path.name, e)

        mode_label = {"average": "averaged", "all": "all frames"}.get(mode, f"frame {mode}")
        self.plot_widget.set_labels(
            xlabel="Wavelength",
            ylabel="Intensity",
            title=f"{len(files)} file(s) overlaid — {mode_label}",
        )
