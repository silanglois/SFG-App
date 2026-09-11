from __future__ import annotations
import io
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication, QImage, QPixmap
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QComboBox,
    QSpinBox, QDoubleSpinBox, QCheckBox, QLineEdit, QDialogButtonBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QWidget, QLabel,
)

# Preview image is capped to this box (px) and scaled down preserving
# its true (possibly tight-cropped) aspect ratio -- see _refresh_preview().
_PREVIEW_MAX_W = 700
_PREVIEW_MAX_H = 380

# Fixed DPI the preview snapshot itself is rendered at, independent of the
# DPI spinbox -- DPI only changes pixel resolution, not the trim/crop
# shape being previewed, so re-rendering at the (possibly much higher)
# chosen export DPI on every settings tweak would just be slower for no
# visual benefit (the preview is always scaled to fit _PREVIEW_MAX_W/H
# anyway).
_PREVIEW_RENDER_DPI = 150

# Figure-width presets offered in _build_export_fields() -- (label, width
# in inches). 3.5in matches SciencePlots' own single-column figure.figsize
# convention; 7.0in is double that for a full-width/double-column figure.
_WIDTH_PRESETS = [
    ("Single column (3.5 in)", 3.5),
    ("Double column (7.0 in)", 7.0),
]


class SavePlotDialog(QDialog):
    """Collects export options for a SpectrumPlotWidget's plot, with a
    live preview: a real snapshot re-rendered through the exact same
    path export() uses (_render_bytes()), so the preview is guaranteed
    to match what gets exported -- including the tight-crop/padding and
    forced width/height, not just title/label/legend/range overrides.
    Rendering happens directly off the plot's own Figure/Axes objects
    (never a copy), restored to their original state whenever nothing
    is actively rendering and definitively when the dialog closes,
    however it closes (accept/reject/Esc/titlebar close) — see done().
    """

    _EXTS = ["png", "tiff", "svg"]

    def __init__(self, plot_widget, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Save plot")
        self.resize(760, 640)

        self.figure = plot_widget.figure
        self.ax = plot_widget.ax
        self.ax2 = plot_widget.ax2
        self._canvas = plot_widget.canvas

        self._snapshot_original_state()

        # Debounces rapid settings changes (typing in a text field, etc.)
        # into one re-render -- same coalescing-rapid-input pattern used
        # elsewhere in this app (HDSFGPanel._redraw_timer,
        # FittingTab._preview_timer, ...), since a full savefig() per
        # keystroke would otherwise feel laggy.
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(50)
        self._preview_timer.timeout.connect(self._refresh_preview)

        layout = QVBoxLayout(self)

        # Preview sits in a centered row -- _refresh_preview() sizes the
        # label to match the actual rendered (possibly tight-cropped)
        # image's aspect ratio, and without the stretches on either side
        # a narrower-than-wide preview would just hug the left edge
        # instead of centering.
        self._preview_label = QLabel()
        self._preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview_row = QHBoxLayout()
        preview_row.addStretch(1)
        preview_row.addWidget(self._preview_label)
        preview_row.addStretch(1)
        layout.addLayout(preview_row, stretch=1)

        columns = QHBoxLayout()
        layout.addLayout(columns)

        form_container = QWidget()
        form = QFormLayout(form_container)
        columns.addWidget(form_container, stretch=1)
        self._build_export_fields(form)
        self._build_axis_fields(form)

        legend_container = self._build_legend_section()
        if legend_container is not None:
            columns.addWidget(legend_container, stretch=1)

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        copy_btn = button_box.addButton(
            "📋 Copy to clipboard", QDialogButtonBox.ButtonRole.ActionRole
        )
        copy_btn.setToolTip("Copy the plot, as currently configured below, to the clipboard as an image.")
        copy_btn.clicked.connect(self._on_copy_to_clipboard)
        layout.addWidget(button_box)

        self._width_check.toggled.connect(self._on_setting_changed)
        self._width_spin.valueChanged.connect(self._on_setting_changed)
        self._height_check.toggled.connect(self._on_setting_changed)
        self._height_spin.valueChanged.connect(self._on_setting_changed)
        self._trim_check.toggled.connect(self._on_setting_changed)
        self._trim_pad_spin.valueChanged.connect(self._on_setting_changed)

        self._refresh_preview()   # immediate first render, no debounce wait

    # ── Setup: snapshot original state ──────────────────────────────────────

    def _snapshot_original_state(self):
        self._orig_fig_size = self.figure.get_size_inches()
        self._orig_title = self.ax.get_title()
        self._orig_xlabel = self.ax.get_xlabel()
        self._orig_ylabel = self.ax.get_ylabel()
        self._orig_xlim = self.ax.get_xlim()
        self._orig_ylim = self.ax.get_ylim()
        self._orig_ylabel2 = self.ax2.get_ylabel() if self.ax2 is not None else None

        # Prefer whatever legend already exists (its texts reflect however
        # the panel built it — combined axes, proxy handles, etc.) rather
        # than recomputing handles/labels ourselves, since that recompute
        # can't see proxy artists (e.g. homodyne_panel's mlines.Line2D
        # handles) that were never added to an axes as real children.
        self._legend_ax = None
        legend = None
        for candidate in (self.ax, self.ax2):
            if candidate is not None and candidate.get_legend() is not None:
                self._legend_ax = candidate
                legend = candidate.get_legend()
                break

        self._legend_created_by_dialog = False
        if legend is not None:
            self._orig_legend_visible = bool(legend.get_visible())
            self._legend_labels = [t.get_text() for t in legend.get_texts()]
        else:
            self._orig_legend_visible = False
            handles, labels = [], []
            for ax in (self.ax, self.ax2):
                if ax is None:
                    continue
                h, l = ax.get_legend_handles_labels()
                handles += h
                labels += l
            self._legend_handles = handles
            self._legend_labels = labels

        self._orig_legend_labels = list(self._legend_labels)

    # ── Setup: fields ────────────────────────────────────────────────────────

    def _build_export_fields(self, form: QFormLayout):
        self._format_combo = QComboBox()
        self._format_combo.addItems(["PNG", "TIFF", "SVG"])
        form.addRow("File format:", self._format_combo)

        self._dpi_spin = QSpinBox()
        self._dpi_spin.setRange(50, 2400)
        self._dpi_spin.setValue(300)
        form.addRow("DPI:", self._dpi_spin)

        orig_w, orig_h = self.figure.get_size_inches()

        self._width_preset_combo = QComboBox()
        self._width_preset_combo.addItem("Custom", None)
        for label, width_in in _WIDTH_PRESETS:
            self._width_preset_combo.addItem(label, width_in)
        self._width_preset_combo.currentIndexChanged.connect(self._on_width_preset_changed)
        form.addRow("Figure width preset:", self._width_preset_combo)

        self._trim_check = QCheckBox("Trim whitespace on export")
        self._trim_check.setChecked(True)
        self._trim_check.setToolTip(
            "Crops the exported image to the actual rendered content "
            "(axis/tick labels and title included, not just the bare "
            "axes box) via savefig(bbox_inches=\"tight\"). If a Force "
            "width/height below is also set, that's the pre-crop size -- "
            "tight cropping can only shrink the final image further."
        )
        self._trim_pad_spin = QDoubleSpinBox()
        self._trim_pad_spin.setRange(0.0, 2.0)
        self._trim_pad_spin.setSingleStep(0.05)
        self._trim_pad_spin.setDecimals(2)
        self._trim_pad_spin.setValue(0.0)
        self._trim_pad_spin.setToolTip(
            "Extra padding added back after the tight crop, in inches. "
            "0 puts labels/title flush against the border."
        )
        self._trim_check.toggled.connect(self._trim_pad_spin.setEnabled)
        trim_row = QHBoxLayout()
        trim_row.addWidget(self._trim_check)
        trim_row.addWidget(QLabel("Padding (in):"))
        trim_row.addWidget(self._trim_pad_spin)
        form.addRow(trim_row)

        self._width_check = QCheckBox("Force width (in)")
        self._width_spin = QDoubleSpinBox()
        self._width_spin.setRange(0.1, 100.0)
        self._width_spin.setValue(orig_w)
        self._width_spin.setEnabled(False)
        self._width_check.toggled.connect(self._width_spin.setEnabled)
        width_row = QHBoxLayout()
        width_row.addWidget(self._width_check)
        width_row.addWidget(self._width_spin)
        form.addRow(width_row)

        self._height_check = QCheckBox("Force height (in)")
        self._height_spin = QDoubleSpinBox()
        self._height_spin.setRange(0.1, 100.0)
        self._height_spin.setValue(orig_h)
        self._height_spin.setEnabled(False)
        self._height_check.toggled.connect(self._height_spin.setEnabled)
        height_row = QHBoxLayout()
        height_row.addWidget(self._height_check)
        height_row.addWidget(self._height_spin)
        form.addRow(height_row)

        self._title_check = QCheckBox("Include title:")
        self._title_check.setChecked(bool(self._orig_title))
        self._title_edit = QLineEdit(self._orig_title)
        self._title_edit.setEnabled(bool(self._orig_title))
        self._title_check.toggled.connect(self._title_edit.setEnabled)
        self._title_check.toggled.connect(self._on_setting_changed)
        self._title_edit.textChanged.connect(self._on_setting_changed)
        title_row = QHBoxLayout()
        title_row.addWidget(self._title_check)
        title_row.addWidget(self._title_edit)
        form.addRow(title_row)

    def _build_axis_fields(self, form: QFormLayout):
        self._xlabel_edit = QLineEdit()
        self._xlabel_edit.setPlaceholderText(self._orig_xlabel)
        self._xlabel_edit.textChanged.connect(self._on_setting_changed)
        form.addRow("X label:", self._xlabel_edit)

        self._ylabel_edit = QLineEdit()
        self._ylabel_edit.setPlaceholderText(self._orig_ylabel)
        self._ylabel_edit.textChanged.connect(self._on_setting_changed)
        form.addRow("Y label:", self._ylabel_edit)

        self._ylabel2_edit = None
        if self.ax2 is not None:
            self._ylabel2_edit = QLineEdit()
            self._ylabel2_edit.setPlaceholderText(self._orig_ylabel2 or "")
            self._ylabel2_edit.textChanged.connect(self._on_setting_changed)
            form.addRow("Y label (secondary axis):", self._ylabel2_edit)

        x0, x1 = self._orig_xlim
        self._xrange_check = QCheckBox("Force x-range")
        self._xmin_spin = QDoubleSpinBox()
        self._xmin_spin.setRange(-1e6, 1e6)
        self._xmin_spin.setDecimals(2)
        self._xmin_spin.setValue(x0)
        self._xmax_spin = QDoubleSpinBox()
        self._xmax_spin.setRange(-1e6, 1e6)
        self._xmax_spin.setDecimals(2)
        self._xmax_spin.setValue(x1)
        self._xmin_spin.setEnabled(False)
        self._xmax_spin.setEnabled(False)
        self._xrange_check.toggled.connect(self._xmin_spin.setEnabled)
        self._xrange_check.toggled.connect(self._xmax_spin.setEnabled)
        self._xrange_check.toggled.connect(self._on_setting_changed)
        self._xmin_spin.valueChanged.connect(self._on_setting_changed)
        self._xmax_spin.valueChanged.connect(self._on_setting_changed)
        xrange_row = QHBoxLayout()
        xrange_row.addWidget(self._xrange_check)
        xrange_row.addWidget(self._xmin_spin)
        xrange_row.addWidget(QLabel("to"))
        xrange_row.addWidget(self._xmax_spin)
        form.addRow(xrange_row)

        y0, y1 = self._orig_ylim
        self._yrange_check = QCheckBox("Force y-range")
        self._ymin_spin = QDoubleSpinBox()
        self._ymin_spin.setRange(-1e9, 1e9)
        self._ymin_spin.setDecimals(3)
        self._ymin_spin.setValue(y0)
        self._ymax_spin = QDoubleSpinBox()
        self._ymax_spin.setRange(-1e9, 1e9)
        self._ymax_spin.setDecimals(3)
        self._ymax_spin.setValue(y1)
        self._ymin_spin.setEnabled(False)
        self._ymax_spin.setEnabled(False)
        self._yrange_check.toggled.connect(self._ymin_spin.setEnabled)
        self._yrange_check.toggled.connect(self._ymax_spin.setEnabled)
        self._yrange_check.toggled.connect(self._on_setting_changed)
        self._ymin_spin.valueChanged.connect(self._on_setting_changed)
        self._ymax_spin.valueChanged.connect(self._on_setting_changed)
        yrange_row = QHBoxLayout()
        yrange_row.addWidget(self._yrange_check)
        yrange_row.addWidget(self._ymin_spin)
        yrange_row.addWidget(QLabel("to"))
        yrange_row.addWidget(self._ymax_spin)
        form.addRow(yrange_row)

    def _build_legend_section(self) -> QWidget | None:
        if not self._legend_labels:
            return None

        container = QWidget()
        vbox = QVBoxLayout(container)
        vbox.setContentsMargins(0, 0, 0, 0)

        self._legend_check = QCheckBox("Show legend")
        self._legend_check.setChecked(self._orig_legend_visible)
        self._legend_check.toggled.connect(self._on_setting_changed)
        vbox.addWidget(self._legend_check)

        self._legend_table = QTableWidget(len(self._legend_labels), 1)
        self._legend_table.setHorizontalHeaderLabels(["Legend label"])
        self._legend_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._legend_table.verticalHeader().setVisible(False)
        for row, text in enumerate(self._legend_labels):
            self._legend_table.setItem(row, 0, QTableWidgetItem(text))
        self._legend_table.itemChanged.connect(self._on_setting_changed)
        vbox.addWidget(self._legend_table)

        return container

    # ── Live preview ─────────────────────────────────────────────────────────

    def _on_setting_changed(self, *_args):
        self._preview_timer.start()

    def _on_width_preset_changed(self, _index: int):
        """A preset sets both Force width and Force height together,
        scaling height to preserve the figure's *current* aspect ratio
        (rather than forcing a fixed height) -- so a preset works
        sensibly whether the underlying plot is a line plot, a twin-axis
        plot, or an image heatmap. Reuses the existing Force width/height
        checkboxes/spinboxes and their already-wired _on_setting_changed
        signal chain instead of introducing any new plumbing. "Custom"
        (the default entry) does nothing --
        editing width/height by hand afterward just leaves the combo on
        its now-stale preset selection, harmlessly (same one-way
        relationship Force width/height already have with each other).
        """
        width_in = self._width_preset_combo.currentData()
        if width_in is None:
            return
        orig_w, orig_h = self._orig_fig_size
        height_in = width_in * (orig_h / orig_w) if orig_w > 0 else width_in
        self._width_check.setChecked(True)
        self._width_spin.setValue(width_in)
        self._height_check.setChecked(True)
        self._height_spin.setValue(height_in)

    def _target_size_inches(self) -> tuple[float, float]:
        """The (width, height) in inches export() will actually use --
        the forced value where checked, the original figure size
        otherwise. Shared by export()/the clipboard action/
        _refresh_preview() (all via _render_bytes())."""
        orig_w, orig_h = self._orig_fig_size
        w = self._width_spin.value() if self._width_check.isChecked() else orig_w
        h = self._height_spin.value() if self._height_check.isChecked() else orig_h
        return w, h

    def _refresh_preview(self):
        """Re-renders a real snapshot through the exact same path
        export()/_on_copy_to_clipboard() use (_render_bytes()) -- so the
        preview is guaranteed to reflect trim/padding/forced-size
        exactly like the real export will, not a second parallel
        approximation. Rendered at a fixed, fast DPI regardless of the
        chosen export DPI (only pixel resolution differs, not the
        crop/shape being previewed) and always as PNG regardless of the
        chosen export format (same simplifying convention
        _on_copy_to_clipboard() already uses)."""
        data = self._render_bytes("png", _PREVIEW_RENDER_DPI)
        pixmap = QPixmap()
        pixmap.loadFromData(data, "PNG")
        scaled = pixmap.scaled(
            _PREVIEW_MAX_W, _PREVIEW_MAX_H,
            Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation,
        )
        self._preview_label.setPixmap(scaled)
        self._preview_label.setFixedSize(scaled.size())

    def _apply_overrides(self, include_size: bool = False):
        self.ax.set_title(self._title_edit.text() if self._title_check.isChecked() else "")

        xlabel = self._xlabel_edit.text().strip() or self._orig_xlabel
        ylabel = self._ylabel_edit.text().strip() or self._orig_ylabel
        self.ax.set_xlabel(xlabel)
        self.ax.set_ylabel(ylabel)
        if self.ax2 is not None and self._ylabel2_edit is not None:
            ylabel2 = self._ylabel2_edit.text().strip() or (self._orig_ylabel2 or "")
            self.ax2.set_ylabel(ylabel2)

        if self._xrange_check.isChecked() and self._xmin_spin.value() < self._xmax_spin.value():
            self.ax.set_xlim(self._xmin_spin.value(), self._xmax_spin.value())
        else:
            self.ax.set_xlim(self._orig_xlim)

        if self._yrange_check.isChecked() and self._ymin_spin.value() < self._ymax_spin.value():
            self.ax.set_ylim(self._ymin_spin.value(), self._ymax_spin.value())
        else:
            self.ax.set_ylim(self._orig_ylim)

        self._apply_legend_overrides()

        if include_size:
            self.figure.set_size_inches(*self._target_size_inches())

        self._canvas.draw_idle()

    def _apply_legend_overrides(self):
        if not self._legend_labels:
            return

        show = self._legend_check.isChecked()

        if self._legend_ax is None:
            if not show:
                return
            self.ax.legend(self._legend_handles, self._legend_labels, fontsize=8)
            self._legend_ax = self.ax
            self._legend_created_by_dialog = True

        legend = self._legend_ax.get_legend()
        if legend is None:
            return
        legend.set_visible(show)

        texts = legend.get_texts()
        for row in range(min(self._legend_table.rowCount(), len(texts))):
            item = self._legend_table.item(row, 0)
            if item is not None:
                texts[row].set_text(item.text())

    # ── Teardown / export ────────────────────────────────────────────────────

    def _restore_original_state(self):
        self.ax.set_title(self._orig_title)
        self.ax.set_xlabel(self._orig_xlabel)
        self.ax.set_ylabel(self._orig_ylabel)
        self.ax.set_xlim(self._orig_xlim)
        self.ax.set_ylim(self._orig_ylim)
        if self.ax2 is not None and self._orig_ylabel2 is not None:
            self.ax2.set_ylabel(self._orig_ylabel2)

        if self._legend_ax is not None:
            legend = self._legend_ax.get_legend()
            if legend is not None:
                if self._legend_created_by_dialog:
                    legend.remove()
                else:
                    legend.set_visible(self._orig_legend_visible)
                    for text, original in zip(legend.get_texts(), self._orig_legend_labels):
                        text.set_text(original)

    def done(self, result):
        self._restore_original_state()
        self.figure.set_size_inches(*self._orig_fig_size, forward=False)
        self._canvas.draw_idle()
        super().done(result)

    def selected_format(self) -> str:
        return self._EXTS[self._format_combo.currentIndex()]

    def _render_bytes(self, fmt: str, dpi: int) -> bytes:
        """Applies the currently chosen overrides (including forced
        width/height), renders to an in-memory buffer, then restores the
        figure -- shared by export() (writes the bytes to disk),
        _on_copy_to_clipboard() (hands them to QImage instead), and
        _refresh_preview() (hands them to QPixmap instead), so all three
        produce byte-identical output for the same settings. `forward=False`
        on the restore avoids forcing a Qt resize event on the original,
        still-live widget behind this (modal) dialog -- only its
        figure's *inches* bookkeeping needs resetting, not its actual
        on-screen pixel size, which this dialog never touches.
        """
        buf = io.BytesIO()
        try:
            self._apply_overrides(include_size=True)
            savefig_kwargs = {}
            if self._trim_check.isChecked():
                savefig_kwargs["bbox_inches"] = "tight"
                savefig_kwargs["pad_inches"] = self._trim_pad_spin.value()
            self.figure.savefig(buf, format=fmt, dpi=dpi, **savefig_kwargs)
        finally:
            self._restore_original_state()
            self.figure.set_size_inches(*self._orig_fig_size, forward=False)
            self._canvas.draw_idle()
        return buf.getvalue()

    def export(self, path: str):
        """Renders with the currently chosen overrides and writes
        straight to `path`. Called by the caller after this dialog has
        already closed (and so already restored everything once); this
        briefly re-applies the same overrides purely for the export,
        and cleans up again immediately after.
        """
        fmt = self.selected_format()
        dpi = self._dpi_spin.value()
        with open(path, "wb") as f:
            f.write(self._render_bytes(fmt, dpi))

    def _on_copy_to_clipboard(self):
        """Same render path as export(), minus the file write -- always
        PNG (clipboard image formats don't include vector SVG/TIFF, and
        PNG is what every target application expects for a pasted
        image). The on-screen preview is an independent cached pixmap
        (see _refresh_preview()), not the live axes _render_bytes()
        transiently mutates, so nothing needs reapplying here afterward."""
        data = self._render_bytes("png", self._dpi_spin.value())
        image = QImage.fromData(data, "PNG")
        QGuiApplication.clipboard().setImage(image)
