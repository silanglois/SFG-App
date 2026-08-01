from __future__ import annotations
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QDoubleSpinBox, QSizePolicy, QPushButton,
    QDialog, QFileDialog, QMessageBox,
)
from PySide6.QtCore import Qt, Signal

from sfg_app2.app.utils.plotting_settings import style_figure
from sfg_app2.app.dialogs.save_plot_dialog import SavePlotDialog
from sfg_app2.app.utils.loading_indicator import show_loading


class _ThemedFigureCanvas(FigureCanvasQTAgg):
    """FigureCanvasQTAgg that re-asserts the active plotting style's
    background on every draw, so it can't drift out of sync no matter
    which code path (including ax.twinx() calls made directly by callers)
    triggered the redraw.
    """

    def draw(self):
        style_figure(self.figure)
        super().draw()


class SpectrumPlotWidget(QWidget):
    """Reusable matplotlib canvas with x-range spinboxes and auto y-scaling."""

    xRangeEdited = Signal()   # emitted when the user manually changes/resets the visible x-range

    def __init__(self, parent=None):
        super().__init__(parent)
        self.figure = Figure(tight_layout=True)
        self.canvas = _ThemedFigureCanvas(self.figure)
        self.toolbar = NavigationToolbar2QT(self.canvas, self)
        self.ax = self.figure.add_subplot(111)

        self._x_range_widget = self._build_x_range_controls()
        self._x_range_initialized = False
        self._x_full_range: tuple[float, float] | None = None
        self._x_range_locked = False   # True once the user manually edits x min/max
        self._zoom_memory: list[dict] = []   # remembered zoom per x-axis domain

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

        self._save_plot_button = QPushButton("💾 Save plot")
        self._save_plot_button.setToolTip("Save this plot to an image file")
        self._save_plot_button.clicked.connect(self._on_save_plot)
        layout.addWidget(self._save_plot_button)

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

    def _on_save_plot(self):
        dlg = SavePlotDialog(self.figure, self.ax, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        opts = dlg.result_options()

        filters = {
            "png": "PNG Image (*.png)",
            "tiff": "TIFF Image (*.tif *.tiff)",
            "svg": "SVG Image (*.svg)",
        }
        path, _ = QFileDialog.getSaveFileName(self, "Save plot", "", filters[opts["format"]])
        if not path:
            return
        valid_exts = (".tif", ".tiff") if opts["format"] == "tiff" else (f".{opts['format']}",)
        if not path.lower().endswith(valid_exts):
            path += f".{opts['format']}"

        orig_size = self.figure.get_size_inches()
        orig_title = self.ax.get_title()
        loading = show_loading(self, "Saving plot...")
        try:
            w = opts["width"] if opts["width"] is not None else orig_size[0]
            h = opts["height"] if opts["height"] is not None else orig_size[1]
            self.figure.set_size_inches(w, h)
            self.ax.set_title(opts["title"])
            self.figure.savefig(path, format=opts["format"], dpi=opts["dpi"])
        except Exception as e:
            QMessageBox.warning(self, "Save failed", f"Could not save plot: {e}")
        finally:
            loading.close()
            self.figure.set_size_inches(*orig_size)
            self.ax.set_title(orig_title)
            self.canvas.draw_idle()

    # ── Public API ────────────────────────────────────────────────────────────

    def clear(self):
        self.ax.clear()
        self._x_range_initialized = False
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
        """Re-sync the plot to the current axes data after a replot.

        If the user has manually zoomed (moved the x min/max spinboxes),
        that zoom stays locked in and is simply reapplied to the new data —
        it is never overwritten until the user clicks "↺ Reset". If the new
        data is on a completely different x-axis domain than before (e.g.
        wavenumber vs. time), the current zoom is replaced either by a zoom
        previously remembered for that domain, or — if none — a fresh fit
        to the new data's full range.
        """
        old_range = self._x_full_range
        new_range = self._compute_full_range()
        domain_changed = (
            old_range is not None and new_range is not None
            and (new_range[1] < old_range[0] or new_range[0] > old_range[1])
        )

        if domain_changed:
            remembered = self._recall_zoom(new_range) if new_range else None
            if remembered is not None:
                x_min, x_max = remembered
                self._x_min_spin.blockSignals(True)
                self._x_max_spin.blockSignals(True)
                self._x_min_spin.setValue(x_min)
                self._x_max_spin.setValue(x_max)
                self._x_min_spin.blockSignals(False)
                self._x_max_spin.blockSignals(False)
                self._x_range_locked = True
                self._apply_x_range()
                return
            self._x_range_locked = False   # no memory for this domain — fall through to full refit

        if self._x_range_locked:
            self._apply_x_range()
            return
        self._x_range_initialized = False   # force fresh sync
        self._sync_x_range_from_data()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _remember_current_zoom(self):
        """Record the active zoom against the currently-plotted x domain,
        so it can be restored next time this domain is revisited."""
        if self._x_full_range is None:
            return
        lo, hi = self._x_full_range
        x_min, x_max = self._x_min_spin.value(), self._x_max_spin.value()
        for entry in self._zoom_memory:
            e_lo, e_hi = entry["range"]
            if not (hi < e_lo or lo > e_hi):
                entry.update(range=(lo, hi), x_min=x_min, x_max=x_max)
                return
        self._zoom_memory.append({"range": (lo, hi), "x_min": x_min, "x_max": x_max})

    def _recall_zoom(self, new_range: tuple[float, float]) -> tuple[float, float] | None:
        lo, hi = new_range
        for entry in self._zoom_memory:
            e_lo, e_hi = entry["range"]
            if not (hi < e_lo or lo > e_hi):
                return entry["x_min"], entry["x_max"]
        return None

    def _forget_zoom(self, rng: tuple[float, float] | None):
        if rng is None:
            return
        lo, hi = rng
        self._zoom_memory = [
            e for e in self._zoom_memory
            if e["range"][1] < lo or e["range"][0] > hi
        ]

    def _compute_full_range(self) -> tuple[float, float] | None:
        """Compute and cache the full x-range of currently plotted data
        (used by the Reset button), without touching the spinboxes."""
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
            return None

        rng = (float(np.nanmin(all_x)), float(np.nanmax(all_x)))
        self._x_full_range = rng
        return rng

    def _sync_x_range_from_data(self):
        if self._x_range_initialized:
            return

        rng = self._compute_full_range()
        if rng is None:
            return
        x_min, x_max = rng

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
        self._x_range_locked = True
        self._remember_current_zoom()
        self._apply_x_range()
        self.xRangeEdited.emit()

    def _apply_x_range(self):
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
        self._x_range_locked = False
        self._forget_zoom(self._x_full_range)
        x_min, x_max = self._x_full_range
        self._x_min_spin.blockSignals(True)
        self._x_max_spin.blockSignals(True)
        self._x_min_spin.setValue(x_min)
        self._x_max_spin.setValue(x_max)
        self._x_min_spin.blockSignals(False)
        self._x_max_spin.blockSignals(False)
        self._apply_x_range()
        self.xRangeEdited.emit()

    def get_x_range(self) -> tuple[float, float] | None:
        """The currently visible x-range, or None if nothing's been plotted yet."""
        if not (self._x_range_initialized or self._x_range_locked):
            return None
        return self._x_min_spin.value(), self._x_max_spin.value()

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

    def soft_clear(self):
        """Clear plot artists but preserve primary axes structure.
        Removes twin axes (twinx) but keeps the primary axis object.
        Much faster than full_clear() for same-step redraws.
        """
        axes = self.figure.get_axes()
        # remove all secondary axes (twin axes created by twinx())
        for ax in axes[1:]:
            self.figure.delaxes(ax)

        # clear primary axis artists without destroying it
        if axes:
            ax = axes[0]
            while ax.lines:
                ax.lines[0].remove()
            while ax.collections:
                ax.collections[0].remove()
            legend = ax.get_legend()
            if legend:
                legend.remove()
            ax.set_prop_cycle(None)   # reset color cycle to start
            self.ax = ax

        self._x_range_initialized = False