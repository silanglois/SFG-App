from __future__ import annotations
import logging
import warnings

import matplotlib as mpl
import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QDialogButtonBox,
    QMessageBox,
)

from sfg_app2.app.utils.plotting_settings import (
    PlottingSettings, MATPLOTLIB_DEFAULT, available_styles, apply_rcparams,
)

logger = logging.getLogger(__name__)


def _display_name(style: str) -> str:
    if style == MATPLOTLIB_DEFAULT:
        return "Matplotlib default"
    return style.replace("_", " ").title()


class PlottingSettingsDialog(QDialog):
    """Lets the user preview and pick a matplotlib/aquarel plotting style."""

    def __init__(self, settings: PlottingSettings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Plotting Settings")
        self.resize(500, 400)
        self._settings = settings

        self._styles = available_styles()
        self._build_ui()
        self._connect_signals()

        self._style_combo.setCurrentText(_display_name(settings.style))
        self._update_preview()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        layout = QVBoxLayout(self)

        row = QHBoxLayout()
        row.addWidget(QLabel("Style:"))
        self._style_combo = QComboBox()
        self._style_combo.addItems([_display_name(s) for s in self._styles])
        row.addWidget(self._style_combo)
        row.addStretch()
        layout.addLayout(row)

        self._figure = Figure(figsize=(4, 3), tight_layout=True)
        self._canvas = FigureCanvasQTAgg(self._figure)
        layout.addWidget(self._canvas)

        self._button_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        layout.addWidget(self._button_box)

    def _connect_signals(self):
        self._style_combo.currentIndexChanged.connect(self._update_preview)
        self._button_box.accepted.connect(self._on_ok)
        self._button_box.rejected.connect(self.reject)

    # ── Preview ───────────────────────────────────────────────────────────────

    def _selected_style(self) -> str:
        return self._styles[self._style_combo.currentIndex()]

    def _update_preview(self):
        style = self._selected_style()
        rcparams_orig = dict(mpl.rcParams)
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", mpl.MatplotlibDeprecationWarning)
                apply_rcparams(style)
                self._draw_sample_plot()
        finally:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", mpl.MatplotlibDeprecationWarning)
                mpl.rcParams.update(rcparams_orig)

    def _draw_sample_plot(self):
        self._figure.clf()
        ax = self._figure.add_subplot(111)
        x = np.linspace(0, 10, 200)
        for i, phase in enumerate((0, 1, 2)):
            ax.plot(x, np.sin(x + phase), label=f"trace {i + 1}")
        ax.set_xlabel("X-axis")
        ax.set_ylabel("Y-axis")
        ax.set_title("Preview")
        ax.legend()
        self._canvas.draw_idle()

    # ── OK ────────────────────────────────────────────────────────────────────

    def _on_ok(self):
        if not self._settings.set_style(self._selected_style()):
            QMessageBox.warning(
                self, "Couldn't save settings",
                "The plotting style could not be saved to disk. "
                "It will apply for this session but won't persist.",
            )
        self.accept()
