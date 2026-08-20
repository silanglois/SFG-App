from __future__ import annotations
import numpy as np
from matplotlib.backends.backend_qtagg import NavigationToolbar2QT
from matplotlib.figure import Figure
from matplotlib.gridspec import GridSpec
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QCheckBox,
    QDoubleSpinBox, QPushButton, QDialog, QFileDialog, QMessageBox,
)

from sfg_app2.app.widgets.spectrum_plot_widget import _ThemedFigureCanvas
from sfg_app2.app.dialogs.save_plot_dialog import SavePlotDialog
from sfg_app2.app.utils.loading_indicator import show_loading

_COLORMAPS = [
    "gray", "viridis", "plasma", "inferno", "magma", "cividis",
    "jet", "hot", "coolwarm", "seismic",
]


class ImagePlotWidget(QWidget):
    """Heatmap view of a CCDImage, with a single click-to-move marker
    whose row/column intensity profiles are plotted around the image
    (top = row profile, right = column profile)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.figure = Figure(constrained_layout=True)
        self.canvas = _ThemedFigureCanvas(self.figure)
        self.toolbar = NavigationToolbar2QT(self.canvas, self)

        gs = GridSpec(
            2, 2, figure=self.figure, width_ratios=[4, 1], height_ratios=[1, 4],
            hspace=0.05, wspace=0.05,
        )
        self.ax = self.figure.add_subplot(gs[1, 0])
        self.ax2 = None   # SavePlotDialog contract — no secondary/twin axis here
        self.ax_top = self.figure.add_subplot(gs[0, 0], sharex=self.ax)
        self.ax_right = self.figure.add_subplot(gs[1, 1], sharey=self.ax)
        self.ax_top.tick_params(labelbottom=False)
        self.ax_right.tick_params(labelleft=False)

        self._data: np.ndarray | None = None
        self._rows: np.ndarray | None = None
        self._cols: np.ndarray | None = None
        self._marker: tuple[int, int] | None = None   # (row_idx, col_idx)
        self._image = None
        self._colorbar = None

        self._build_controls()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addWidget(self.toolbar)
        layout.addWidget(self.canvas)
        layout.addWidget(self._controls_widget)

        self.canvas.mpl_connect("button_press_event", self._on_click)

    def _build_controls(self):
        widget = QWidget()
        row = QHBoxLayout(widget)
        row.setContentsMargins(4, 2, 4, 2)

        self._save_button = QPushButton("💾 Save plot")
        self._save_button.setToolTip("Save this plot to an image file")
        self._save_button.clicked.connect(self._on_save_plot)
        row.addWidget(self._save_button)

        row.addWidget(QLabel("Colormap:"))
        self._cmap_combo = QComboBox()
        self._cmap_combo.addItems(_COLORMAPS)
        self._cmap_combo.currentTextChanged.connect(self._on_cmap_changed)
        row.addWidget(self._cmap_combo)

        self._auto_contrast_check = QCheckBox("Auto contrast")
        self._auto_contrast_check.setChecked(True)
        row.addWidget(self._auto_contrast_check)

        row.addWidget(QLabel("min:"))
        self._vmin_spin = QDoubleSpinBox()
        self._vmin_spin.setRange(-1e9, 1e9)
        self._vmin_spin.setDecimals(2)
        self._vmin_spin.setEnabled(False)
        row.addWidget(self._vmin_spin)

        row.addWidget(QLabel("max:"))
        self._vmax_spin = QDoubleSpinBox()
        self._vmax_spin.setRange(-1e9, 1e9)
        self._vmax_spin.setDecimals(2)
        self._vmax_spin.setEnabled(False)
        row.addWidget(self._vmax_spin)

        self._auto_contrast_check.toggled.connect(lambda on: self._vmin_spin.setEnabled(not on))
        self._auto_contrast_check.toggled.connect(lambda on: self._vmax_spin.setEnabled(not on))
        self._auto_contrast_check.toggled.connect(self._on_contrast_changed)
        self._vmin_spin.valueChanged.connect(self._on_contrast_changed)
        self._vmax_spin.valueChanged.connect(self._on_contrast_changed)

        row.addStretch()

        self._marker_label = QLabel("Click the image to place a marker")
        row.addWidget(self._marker_label)

        self._controls_widget = widget

    # ── Public API ────────────────────────────────────────────────────────────

    def set_image(self, image):
        """`image` is a processing.image_file.CCDImage."""
        self._data = image.data
        self._rows = image.rows
        self._cols = image.cols
        self._marker = None
        self._draw_image()

    # ── Image / contrast / colormap ─────────────────────────────────────────

    def _auto_clim(self) -> tuple[float, float]:
        return float(np.percentile(self._data, 1)), float(np.percentile(self._data, 99))

    def _draw_image(self):
        data, rows, cols = self._data, self._rows, self._cols

        self.ax.clear()
        self.ax_top.clear()
        self.ax_right.clear()
        self.ax_top.tick_params(labelbottom=False)
        self.ax_right.tick_params(labelleft=False)

        vmin, vmax = self._auto_clim()
        self._vmin_spin.blockSignals(True)
        self._vmax_spin.blockSignals(True)
        self._vmin_spin.setValue(vmin)
        self._vmax_spin.setValue(vmax)
        self._vmin_spin.blockSignals(False)
        self._vmax_spin.blockSignals(False)

        extent = [cols.min(), cols.max(), rows.max(), rows.min()]
        self._image = self.ax.imshow(
            data, cmap=self._cmap_combo.currentText(), vmin=vmin, vmax=vmax,
            origin="upper", aspect="auto", extent=extent,
        )
        if self._colorbar is not None:
            try:
                self._colorbar.remove()
            except (ValueError, KeyError):
                pass
        self._colorbar = self.figure.colorbar(self._image, ax=self.ax, fraction=0.046, pad=0.04)
        self._colorbar.set_label("Intensity (counts)")

        self.ax.set_xlabel("Column pixel")
        self.ax.set_ylabel("Row pixel")

        self._redraw_marker_and_profiles()

    def _on_cmap_changed(self, name: str):
        if self._image is not None:
            self._image.set_cmap(name)
            self.canvas.draw_idle()

    def _on_contrast_changed(self, *_args):
        if self._image is None:
            return
        if self._auto_contrast_check.isChecked():
            vmin, vmax = self._auto_clim()
            self._vmin_spin.blockSignals(True)
            self._vmax_spin.blockSignals(True)
            self._vmin_spin.setValue(vmin)
            self._vmax_spin.setValue(vmax)
            self._vmin_spin.blockSignals(False)
            self._vmax_spin.blockSignals(False)
        else:
            vmin, vmax = self._vmin_spin.value(), self._vmax_spin.value()
        if vmin >= vmax:
            return
        self._image.set_clim(vmin, vmax)
        self.canvas.draw_idle()

    # ── Marker + profiles ────────────────────────────────────────────────────

    def _on_click(self, event):
        if event.inaxes != self.ax or event.xdata is None or event.ydata is None:
            return
        if self._data is None:
            return
        col_idx = int(np.argmin(np.abs(self._cols - event.xdata)))
        row_idx = int(np.argmin(np.abs(self._rows - event.ydata)))
        self._marker = (row_idx, col_idx)
        self._redraw_marker_and_profiles()

    def _redraw_marker_and_profiles(self):
        # marker crosshairs are the only Line2D artists on the image axes —
        # remove just those, the imshow AxesImage isn't in ax.lines
        for line in list(self.ax.lines):
            line.remove()
        self.ax_top.cla()
        self.ax_right.cla()
        self.ax_top.tick_params(labelbottom=False)
        self.ax_right.tick_params(labelleft=False)
        self.ax_top.set_ylabel("Intensity (counts)")
        self.ax_right.set_xlabel("Intensity (counts)")

        if self._marker is None:
            self.ax_top.text(
                0.5, 0.5, "Click the image to place a marker",
                ha="center", va="center", transform=self.ax_top.transAxes, fontsize=8,
            )
            self._marker_label.setText("Click the image to place a marker")
            self.canvas.draw_idle()
            return

        row_idx, col_idx = self._marker
        row_val, col_val = self._rows[row_idx], self._cols[col_idx]
        intensity = self._data[row_idx, col_idx]

        self.ax.axhline(row_val, color="red", linewidth=0.8)
        self.ax.axvline(col_val, color="red", linewidth=0.8)

        self.ax_top.plot(self._cols, self._data[row_idx, :], color="black", linewidth=0.8)
        self.ax_top.axvline(col_val, color="red", linewidth=0.8)

        # ax_right shares its y-axis with ax (set up via sharey= at
        # construction), so it already matches ax's row orientation —
        # no separate invert_yaxis() needed here.
        self.ax_right.plot(self._data[:, col_idx], self._rows, color="black", linewidth=0.8)
        self.ax_right.axhline(row_val, color="red", linewidth=0.8)

        self._marker_label.setText(
            f"row {row_val:.0f}, col {col_val:.0f} — intensity {intensity:.1f}"
        )
        self.canvas.draw_idle()

    # ── Save ─────────────────────────────────────────────────────────────────

    def _on_save_plot(self):
        dlg = SavePlotDialog(self, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        fmt = dlg.selected_format()
        filters = {
            "png": "PNG Image (*.png)",
            "tiff": "TIFF Image (*.tif *.tiff)",
            "svg": "SVG Image (*.svg)",
        }
        path, _ = QFileDialog.getSaveFileName(self, "Save plot", "", filters[fmt])
        if not path:
            return
        valid_exts = (".tif", ".tiff") if fmt == "tiff" else (f".{fmt}",)
        if not path.lower().endswith(valid_exts):
            path += f".{fmt}"

        loading = show_loading(self, "Saving plot...")
        try:
            dlg.export(path)
        except Exception as e:
            QMessageBox.warning(self, "Save failed", f"Could not save plot: {e}")
        finally:
            loading.close()
