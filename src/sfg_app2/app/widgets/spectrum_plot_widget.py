from __future__ import annotations
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QDoubleSpinBox, QSizePolicy, QPushButton  
)
from PySide6.QtCore import Qt


class SpectrumPlotWidget(QWidget):
    """Reusable matplotlib canvas with x-range spinboxes and auto y-scaling."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.figure = Figure(tight_layout=True)
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.toolbar = NavigationToolbar2QT(self.canvas, self)
        self.ax = self.figure.add_subplot(111)

        self._x_range_widget = self._build_x_range_controls()
        self._x_range_initialized = False
        self._x_full_range: tuple[float, float] | None = None
        self._plotting: bool = False   # ← add this

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addWidget(self.toolbar)
        layout.addWidget(self.canvas)
        layout.addWidget(self._x_range_widget)

    def _build_x_range_controls(self) -> QWidget:
        widget = QWidget()
        widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(4, 2, 4, 2)

        layout.addStretch()

        layout.addWidget(QLabel("x min:"))
        self._x_min_spin = QDoubleSpinBox()
        self._x_min_spin.setRange(-1e6, 1e6)
        self._x_min_spin.setDecimals(1)
        self._x_min_spin.setSingleStep(10.0)
        self._x_min_spin.setFixedWidth(100)
        layout.addWidget(self._x_min_spin)

        layout.addWidget(QLabel("x max:"))
        self._x_max_spin = QDoubleSpinBox()
        self._x_max_spin.setRange(-1e6, 1e6)
        self._x_max_spin.setDecimals(1)
        self._x_max_spin.setSingleStep(10.0)
        self._x_max_spin.setFixedWidth(100)
        layout.addWidget(self._x_max_spin)

        self._reset_button = QPushButton("↺ Reset")
        self._reset_button.setFixedWidth(70)
        self._reset_button.setToolTip("Reset x-axis to full data range")
        self._reset_button.clicked.connect(self._on_reset_x_range)
        layout.addWidget(self._reset_button)

        self._x_min_spin.valueChanged.connect(self._on_x_range_changed)
        self._x_max_spin.valueChanged.connect(self._on_x_range_changed)

        return widget

    # ── Public API ────────────────────────────────────────────────────────────

    def clear(self):
        self.ax.clear()
        self._x_range_initialized = False
        self._x_full_range = None
        self.canvas.draw_idle()

    def plot(self, x, y, label: str = None, **kwargs):
        self.ax.plot(x, y, label=label, **kwargs)
        if label:
            self.ax.legend()
        self._sync_x_range_from_data()
        self.canvas.draw_idle()

    def set_labels(self, xlabel: str = "", ylabel: str = "", title: str = ""):
        self.ax.set_xlabel(xlabel)
        self.ax.set_ylabel(ylabel)
        self.ax.set_title(title)
        self.canvas.draw_idle()

    def set_x_range(self, x_min: float, x_max: float):
        """Programmatically set the x range (e.g. from calibration dialog)."""
        self._x_min_spin.blockSignals(True)
        self._x_max_spin.blockSignals(True)
        self._x_min_spin.setValue(x_min)
        self._x_max_spin.setValue(x_max)
        self._x_min_spin.blockSignals(False)
        self._x_max_spin.blockSignals(False)
        self._apply_x_range()

    def sync_x_range(self):
        """Sync x-range spinboxes to current axes data range.
        Call after using ax.plot() directly rather than self.plot().
        """
        self._x_range_initialized = False   # force fresh sync
        self._sync_x_range_from_data()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _sync_x_range_from_data(self):
        if self._x_range_initialized:
            return

        import numpy as np
        all_x = []

        for ax in self.figure.get_axes():
            for line in ax.get_lines():
                xd = np.asarray(line.get_xdata(), dtype=float)
                if not len(xd):
                    continue
                # skip axhline — its xdata is exactly [0, 1] in axes fraction space
                if len(xd) == 2 and np.allclose(xd, [0.0, 1.0]):
                    continue
                all_x.extend(xd)

        if not all_x:
            return

        x_min = float(np.nanmin(all_x))
        x_max = float(np.nanmax(all_x))
        self._x_full_range = (x_min, x_max)

        self._x_min_spin.blockSignals(True)
        self._x_max_spin.blockSignals(True)
        self._x_min_spin.setValue(x_min)
        self._x_max_spin.setValue(x_max)
        self._x_min_spin.blockSignals(False)
        self._x_max_spin.blockSignals(False)
        self._x_range_initialized = True
        self._apply_x_range()

    def _on_x_range_changed(self):
        if self._x_min_spin.value() >= self._x_max_spin.value():
            return  # ignore invalid range
        self._apply_x_range()

    def _apply_x_range(self):
        if self._plotting:
            return
        x_min = self._x_min_spin.value()
        x_max = self._x_max_spin.value()
        if x_min >= x_max:
            return
        for ax in self.figure.get_axes():
            ax.set_xlim(x_min, x_max)
        self._autoscale_y(x_min, x_max)
        self.canvas.draw_idle()

    def _on_reset_x_range(self):
        if self._x_full_range is None:
            return
        x_min, x_max = self._x_full_range
        self._x_min_spin.blockSignals(True)
        self._x_max_spin.blockSignals(True)
        self._x_min_spin.setValue(x_min)
        self._x_max_spin.setValue(x_max)
        self._x_min_spin.blockSignals(False)
        self._x_max_spin.blockSignals(False)
        self._apply_x_range()

    def _autoscale_y(self, x_min: float, x_max: float):
        import numpy as np
        y_vals_by_ax: dict = {}

        for ax in self.figure.get_axes():
            y_for_ax = []
            for line in ax.get_lines():
                xd = np.asarray(line.get_xdata(), dtype=float)
                yd = np.asarray(line.get_ydata(), dtype=float)
                if not len(xd):
                    continue
                # skip axhline/axvline
                if len(xd) == 2 and np.allclose(xd, [0.0, 1.0]):
                    continue
                mask = (xd >= x_min) & (xd <= x_max)
                if mask.any():
                    y_for_ax.extend(yd[mask])
            for coll in ax.collections:
                try:
                    offsets = coll.get_offsets()
                    if len(offsets):
                        mask = (offsets[:, 0] >= x_min) & (offsets[:, 0] <= x_max)
                        if mask.any():
                            y_for_ax.extend(offsets[mask, 1])
                except Exception:
                    pass
            if y_for_ax:
                y_vals_by_ax[ax] = y_for_ax

        for ax, y_vals in y_vals_by_ax.items():
            y_min = float(np.nanmin(y_vals))
            y_max = float(np.nanmax(y_vals))
            margin = (y_max - y_min) * 0.05 if y_max != y_min else 1.0
            ax.set_ylim(y_min - margin, y_max + margin)

    def full_clear(self):
        """Clear the entire figure including twin axes, then recreate main axes.
        Use this instead of clear() when twin axes have been created.
        """
        self.figure.clf()
        self.ax = self.figure.add_subplot(111)
        self._x_range_initialized = False
        self._x_full_range = None