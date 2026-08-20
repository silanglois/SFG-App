from __future__ import annotations
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QComboBox,
    QSpinBox, QDoubleSpinBox, QCheckBox, QLineEdit, QDialogButtonBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QWidget, QLabel,
)


class SavePlotDialog(QDialog):
    """Collects export options for a SpectrumPlotWidget's plot, with a
    live preview: the widget's own canvas is temporarily borrowed and
    reparented into this (modal) dialog, and every option is applied
    directly to the live axes so the preview is exactly what export()
    will produce. Everything is restored when the dialog closes, however
    it closes (accept/reject/Esc/titlebar close) — see done().
    """

    _EXTS = ["png", "tiff", "svg"]

    def __init__(self, plot_widget, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Save plot")
        self.resize(760, 640)

        self._plot_widget = plot_widget
        self.figure = plot_widget.figure
        self.ax = plot_widget.ax
        self.ax2 = plot_widget.ax2
        self._canvas = plot_widget.canvas

        self._snapshot_original_state()
        self._reparent_canvas_in()

        layout = QVBoxLayout(self)
        layout.addWidget(self._canvas, stretch=1)

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
        layout.addWidget(button_box)

        self._apply_overrides()

    # ── Setup: snapshot / canvas borrowing ──────────────────────────────────

    def _snapshot_original_state(self):
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

    def _reparent_canvas_in(self):
        host_layout = self._plot_widget.layout()
        self._host_layout = host_layout
        self._canvas_index = host_layout.indexOf(self._canvas)
        host_layout.removeWidget(self._canvas)
        self._canvas.setParent(self)

    def _reparent_canvas_out(self):
        self._canvas.setParent(self._plot_widget)
        self._host_layout.insertWidget(self._canvas_index, self._canvas)

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
        self._apply_overrides()

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
            orig_w, orig_h = self.figure.get_size_inches()
            w = self._width_spin.value() if self._width_check.isChecked() else orig_w
            h = self._height_spin.value() if self._height_check.isChecked() else orig_h
            self.figure.set_size_inches(w, h)

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
        self._reparent_canvas_out()
        self._canvas.draw_idle()
        super().done(result)

    def selected_format(self) -> str:
        return self._EXTS[self._format_combo.currentIndex()]

    def export(self, path: str):
        """Re-applies the currently chosen overrides (including forced
        width/height, which the live preview intentionally skips — see
        _apply_overrides), saves to `path`, then restores the figure.
        Called by the caller after this dialog has already closed (and
        so already restored/reparented everything once); this briefly
        re-applies the same overrides purely for the export, and cleans
        up again immediately after.
        """
        fmt = self.selected_format()
        dpi = self._dpi_spin.value()
        orig_size = self.figure.get_size_inches()
        try:
            self._apply_overrides(include_size=True)
            self.figure.savefig(path, format=fmt, dpi=dpi)
        finally:
            self._restore_original_state()
            self.figure.set_size_inches(*orig_size)
            self._canvas.draw_idle()
