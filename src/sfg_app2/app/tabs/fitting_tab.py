from __future__ import annotations
import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QComboBox,
    QPushButton, QCheckBox, QDoubleSpinBox, QLineEdit, QTableWidget,
    QTableWidgetItem, QHeaderView, QSizePolicy, QFileDialog, QMessageBox,
    QInputDialog, QColorDialog,
)

from sfg_app2.app.widgets.spectrum_plot_widget import SpectrumPlotWidget
from sfg_app2.app.widgets.dockable_panels import DockablePlotPanel
from sfg_app2.app.utils.loading_indicator import show_loading
from sfg_app2.app.utils.fit_template_manager import FitTemplateManager
from sfg_app2.processing import provenance
from sfg_app2.processing.processed_spectrum import ProcessedSpectrum
from sfg_app2.processing.fitting import (
    FitParam, PeakInstance, FitModelSpec, default_peak,
    evaluate_homodyne, evaluate_chi, evaluate_peak_component, fit_homodyne, compute_weights,
    available_lineshapes, get_lineshape, fit_model_spec_from_provenance_payload,
)

logger = logging.getLogger(__name__)

_COL_LABEL, _COL_PARAM, _COL_FIXED, _COL_VALUE, _COL_ERROR, _COL_MIN, _COL_MAX, _COL_EXPR = range(8)
_PEAK_COL_INDEX, _PEAK_COL_LINESHAPE, _PEAK_COL_REMOVE = range(3)
(_DISPLAY_COL_LABEL, _DISPLAY_COL_PLOT1, _DISPLAY_COL_PLOT2,
 _DISPLAY_COL_COLOR, _DISPLAY_COL_LINESTYLE) = range(5)

# Fixed series always available for plotting, in display order; peak_{i}
# series are appended dynamically, one per current peak.
_FIXED_SERIES = [
    ("data", "Data"),
    ("fit_total", "Fit (total)"),
    ("fit_real", "Fit (real)"),
    ("fit_imag", "Fit (imaginary)"),
    ("residual", "Residual"),
]
_DEFAULT_PLOT1_SERIES = {"data", "fit_total"}
_DEFAULT_PLOT2_SERIES = {"fit_real", "fit_imag"}
# residual and every peak_i default to hidden on both plots -- opt in via
# the Display dock.

# (display name, matplotlib linestyle code) -- "None" gives markers only,
# which is Data's own default look.
_LINESTYLE_OPTIONS = [
    ("Solid", "-"), ("Dashed", "--"), ("Dash-dot", "-."), ("Dotted", ":"), ("None (markers only)", "none"),
]
_LINESTYLE_CODE_TO_LABEL = {code: label for label, code in _LINESTYLE_OPTIONS}


@dataclass
class SeriesStyle:
    """color=None means "don't pass color= to ax.plot() at all" -- the
    active plotting style's own color cycle (see utils/plotting_settings.py)
    assigns it instead, same convention as processed_results.py's TraceStyle."""
    color: str | None = None
    linestyle: str = "-"


def _default_linestyle_for(key: str) -> str:
    return "none" if key == "data" else "-"


def _readonly_item(text: str) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
    return item


def _center_widget(widget: QWidget) -> QWidget:
    holder = QWidget()
    layout = QHBoxLayout(holder)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
    layout.addWidget(widget)
    return holder


def _fmt_bound(x: float) -> str:
    if x == float("-inf"):
        return "-inf"
    if x == float("inf"):
        return "inf"
    return f"{x:g}"


def _parse_bound(text: str, default: float) -> float:
    text = text.strip()
    if not text:
        return default
    try:
        return float(text)
    except ValueError:
        return default


def _lmfit_key(key: tuple) -> str:
    if key[0] == "nr":
        return f"nr_{key[1]}"
    _, i, name = key
    return f"p{i}_{name}"


@dataclass
class _FittableSpectrum:
    label: str
    omega: np.ndarray
    intensity: np.ndarray
    intensity_std: np.ndarray | None
    count: np.ndarray | None
    source_spectrum: object | None       # the original ProcessedSpectrum, if loaded from Results tab
    fit_json_payload: dict | None        # a previous fit's payload, if the file carried one


class FittingTab(QWidget, DockablePlotPanel):
    """Single-spectrum homodyne peak fitting: |chi_NR*e^{i.phi} +
    sum_j resonance_j(omega)|^2 fit against measured intensity, via
    processing.fitting (lmfit-based, Qt-free).
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        self._results_provider = None
        self._results_entries: list = []
        self._data: _FittableSpectrum | None = None
        self._model_spec: FitModelSpec = FitModelSpec.empty()
        self._series_assignment: dict[str, set[str]] = {}
        self._series_styles: dict[str, SeriesStyle] = {}
        self._last_result = None
        self._param_row_keys: list[tuple] = []
        self._display_row_keys: list[str] = []
        self._placement_armed = False
        self._template_manager = FitTemplateManager()

        self._preview_timer = QTimer()
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(50)
        self._preview_timer.timeout.connect(self._update_preview)

        self.plot_widget = SpectrumPlotWidget()
        self.plot_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.plot_widget.canvas.mpl_connect("button_press_event", self._on_plot_click)

        self.plot_widget2 = SpectrumPlotWidget()
        self.plot_widget2.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(4, 4, 4, 4)
        main_layout.setSpacing(4)

        self._init_dock_area(self.plot_widget)
        self._add_dock("data_source", "Data source", self._build_data_source_section())
        self._add_dock("model", "Model", self._build_model_section())
        self._add_dock("parameters", "Parameters", self._build_parameters_section(), fill=True)
        self._add_dock("display", "Display", self._build_display_section(), fill=True)
        self._add_dock("fit", "Fit", self._build_fit_section())
        self._add_dock("plot2", "Secondary plot", self.plot_widget2, fill=True)
        main_layout.addWidget(self._dock_main_window)

        self._plot_data()
        self._rebuild_peak_table()
        self._rebuild_parameter_table()
        self._rebuild_display_table()
        self._update_quality_readout()

    # ── Data source dock ─────────────────────────────────────────────────────

    def set_results_provider(self, provider):
        """`provider` is the ProcessedResultsTab instance (duck-typed:
        needs .entries(kind=...)) -- set once from MainWindow after both
        tabs exist."""
        self._results_provider = provider
        self._on_refresh_results()

    def _build_data_source_section(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("From Results tab:"))
        self._results_combo = QComboBox()
        self._results_combo.setMinimumWidth(160)
        row1.addWidget(self._results_combo, stretch=1)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self._on_refresh_results)
        row1.addWidget(refresh_btn)
        layout.addLayout(row1)

        load_selected_btn = QPushButton("Load selected")
        load_selected_btn.clicked.connect(self._on_load_selected_result)
        layout.addWidget(load_selected_btn)

        layout.addWidget(QLabel("— or —"))

        load_file_btn = QPushButton("Load from file...")
        load_file_btn.clicked.connect(self._on_load_from_file)
        layout.addWidget(load_file_btn)

        self._data_label = QLabel("No spectrum loaded.")
        layout.addWidget(self._data_label)
        layout.addStretch()
        return widget

    def _on_refresh_results(self):
        self._results_combo.clear()
        self._results_entries = []
        if self._results_provider is None:
            return
        entries = self._results_provider.entries(kind="homodyne")
        self._results_entries = entries
        for e in entries:
            self._results_combo.addItem(e.label)

    def _on_load_selected_result(self):
        idx = self._results_combo.currentIndex()
        if idx < 0 or idx >= len(self._results_entries):
            QMessageBox.information(self, "No spectrum selected", "Pick a spectrum from the list first.")
            return
        entry = self._results_entries[idx]
        self._load_from_processed_spectrum(entry.spectrum, entry.label)

    def _load_from_processed_spectrum(self, spectrum, label: str):
        df = spectrum.data
        if "Wavenumber" not in df.columns or "Intensity" not in df.columns:
            QMessageBox.warning(
                self, "Cannot fit this spectrum",
                "No Wavenumber/Intensity columns found — has it been averaged and upconverted?",
            )
            return
        omega = df["Wavenumber"].to_numpy(dtype=float)
        intensity = df["Intensity"].to_numpy(dtype=float)
        intensity_std = df["Intensity_std"].to_numpy(dtype=float) if "Intensity_std" in df.columns else None
        count = df["count"].to_numpy(dtype=float) if "count" in df.columns else None
        order = np.argsort(omega)
        self._data = _FittableSpectrum(
            label=label, omega=omega[order], intensity=intensity[order],
            intensity_std=intensity_std[order] if intensity_std is not None else None,
            count=count[order] if count is not None else None,
            source_spectrum=spectrum, fit_json_payload=None,
        )
        self._on_data_loaded()

    def _on_load_from_file(self):
        path_str, _ = QFileDialog.getOpenFileName(
            self, "Load spectrum", "", "CSV files (*.csv);;All files (*.*)",
        )
        if not path_str:
            return
        path = Path(path_str)
        try:
            df = provenance.load_csv_skip_comments(path)
            _, prov, meta = provenance.parse_export_header(path)
        except Exception as e:
            QMessageBox.warning(self, "Could not load file", str(e))
            return
        if "Wavenumber" not in df.columns or "Intensity" not in df.columns:
            QMessageBox.warning(self, "Cannot fit this file", "No Wavenumber/Intensity columns found.")
            return
        omega = df["Wavenumber"].to_numpy(dtype=float)
        intensity = df["Intensity"].to_numpy(dtype=float)
        intensity_std = df["Intensity_std"].to_numpy(dtype=float) if "Intensity_std" in df.columns else None
        count = df["count"].to_numpy(dtype=float) if "count" in df.columns else None
        order = np.argsort(omega)
        self._data = _FittableSpectrum(
            label=meta.get("label", path.stem), omega=omega[order], intensity=intensity[order],
            intensity_std=intensity_std[order] if intensity_std is not None else None,
            count=count[order] if count is not None else None,
            source_spectrum=None, fit_json_payload=provenance.parse_fit_json(prov),
        )
        self._on_data_loaded()

    def _on_data_loaded(self):
        prefill = None
        if self._data.fit_json_payload:
            prefill = fit_model_spec_from_provenance_payload(self._data.fit_json_payload)
            if prefill is not None:
                self.statusBar_message(f"Restored a previous fit from {self._data.label}'s provenance.")
        self._model_spec = prefill or FitModelSpec.empty()
        self._series_assignment = {}
        self._last_result = None
        self._data_label.setText(f"Loaded: {self._data.label} ({len(self._data.omega)} points)")

        self._plot_data()
        lo, hi = float(self._data.omega.min()), float(self._data.omega.max())
        self.plot_widget.set_x_range(lo, hi)
        self.plot_widget2.set_x_range(lo, hi)
        for spin in (self._fit_min_spin, self._fit_max_spin):
            spin.blockSignals(True)
        self._fit_min_spin.setValue(lo)
        self._fit_max_spin.setValue(hi)
        for spin in (self._fit_min_spin, self._fit_max_spin):
            spin.blockSignals(False)

        self._rebuild_peak_table()
        self._rebuild_parameter_table()
        self._rebuild_display_table()
        self._update_quality_readout()
        self._schedule_preview()

    def statusBar_message(self, msg: str):
        try:
            self.window().statusBar().showMessage(msg)
        except Exception:
            pass

    # ── Model dock ───────────────────────────────────────────────────────────

    def _build_model_section(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        row = QHBoxLayout()
        row.addWidget(QLabel("Lineshape:"))
        self._lineshape_combo = QComboBox()
        for ls in available_lineshapes():
            self._lineshape_combo.addItem(ls.display_name, userData=ls.key)
        row.addWidget(self._lineshape_combo)
        self._add_peak_btn = QPushButton("Add peak")
        self._add_peak_btn.setCheckable(True)
        self._add_peak_btn.setToolTip(
            "Click, then click on the plot to place a peak there "
            "(right-click to cancel)"
        )
        self._add_peak_btn.toggled.connect(self._on_add_peak_toggled)
        row.addWidget(self._add_peak_btn)
        layout.addLayout(row)

        self._nonresonant_check = QCheckBox("Include non-resonant background")
        self._nonresonant_check.setChecked(True)
        self._nonresonant_check.toggled.connect(self._on_nonresonant_toggled)
        layout.addWidget(self._nonresonant_check)

        self._peak_table = QTableWidget(0, 3)
        self._peak_table.setHorizontalHeaderLabels(["Peak", "Lineshape", "Remove"])
        self._peak_table.verticalHeader().setVisible(False)
        self._peak_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self._peak_table)
        layout.addWidget(QLabel(
            "Which curves show is controlled by the Display dock, not this table."
        ))
        return widget

    def _on_add_peak_toggled(self, checked: bool):
        self._placement_armed = checked
        if checked:
            self._add_peak_btn.setText("Click on the plot...")
            self.plot_widget.canvas.setCursor(Qt.CursorShape.CrossCursor)
            self.statusBar_message("Armed: click the plot to place a peak (right-click to cancel).")
        else:
            self._add_peak_btn.setText("Add peak")
            self.plot_widget.canvas.setCursor(Qt.CursorShape.ArrowCursor)
            self.statusBar_message("")

    def _on_plot_click(self, event):
        if not self._placement_armed:
            return
        if event.inaxes != self.plot_widget.ax:
            return
        if event.button == 3:   # right-click cancels placement
            self._add_peak_btn.setChecked(False)
            return
        if event.button != 1 or event.xdata is None:
            return
        self._add_peak_at(event.xdata)
        self._add_peak_btn.setChecked(False)

    def _add_peak_at(self, center: float):
        if self._data is None:
            return
        lineshape_key = self._lineshape_combo.currentData()
        idx = int(np.argmin(np.abs(self._data.omega - center)))
        baseline = float(np.min(self._data.intensity))
        x_range = self.plot_widget.get_x_range()
        span = (x_range[1] - x_range[0]) if x_range else float(self._data.omega.max() - self._data.omega.min())
        width = max(span * 0.02, 1.0)
        amplitude = max(float(np.sqrt(max(self._data.intensity[idx] - baseline, 0.0))) * (width / 2.0), 0.5)

        peak = default_peak(lineshape_key, center=float(center), amplitude=amplitude, width=width)
        self._model_spec.peaks.append(peak)
        self._rebuild_peak_table()
        self._rebuild_parameter_table()
        self._rebuild_display_table()
        self._schedule_preview()

    def _on_nonresonant_toggled(self, checked: bool):
        nr = self._model_spec.nonresonant
        if checked:
            nr["amplitude"].vary = True
            if nr["amplitude"].value == 0.0:
                nr["amplitude"].value = 0.1
            # phase's fixed/varying state is left as-is (it's fixed by
            # default -- see FitModelSpec.empty() -- and otherwise
            # reflects whatever the user set via the parameter table's
            # own Fixed checkbox, not this one)
        else:
            nr["amplitude"].vary = False
            nr["amplitude"].value = 0.0
            nr["phase"].vary = False
        self._rebuild_parameter_table()
        self._schedule_preview()

    def _rebuild_peak_table(self):
        table = self._peak_table
        table.setRowCount(len(self._model_spec.peaks))
        for i, peak in enumerate(self._model_spec.peaks):
            ls = get_lineshape(peak.lineshape_key)
            table.setItem(i, _PEAK_COL_INDEX, _readonly_item(f"Peak {i + 1}"))
            table.setItem(i, _PEAK_COL_LINESHAPE, _readonly_item(ls.display_name))

            remove_btn = QPushButton("Remove")
            remove_btn.clicked.connect(lambda _checked=False, row=i: self._on_remove_peak(row))
            table.setCellWidget(i, _PEAK_COL_REMOVE, remove_btn)

    def _on_remove_peak(self, row: int):
        if 0 <= row < len(self._model_spec.peaks):
            del self._model_spec.peaks[row]
        self._rebuild_peak_table()
        self._rebuild_parameter_table()
        self._rebuild_display_table()
        self._schedule_preview()

    # ── Parameters dock ──────────────────────────────────────────────────────

    def _build_parameters_section(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        self._param_table = QTableWidget(0, 8)
        self._param_table.setHorizontalHeaderLabels(
            ["Peak", "Parameter", "Fixed", "Value", "Error", "Min", "Max", "Expr"]
        )
        self._param_table.verticalHeader().setVisible(False)
        # Interactive (not Stretch) so the user can drag-resize columns --
        # Stretch locks every column's width to fill the viewport.
        self._param_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        # Error/Expr are rarely needed day-to-day; hidden (not removed) so
        # a future "show hidden columns" toggle stays cheap to add.
        self._param_table.setColumnHidden(_COL_ERROR, True)
        self._param_table.setColumnHidden(_COL_EXPR, True)
        layout.addWidget(self._param_table)
        return widget

    def _param_at(self, key: tuple) -> FitParam:
        if key[0] == "nr":
            return self._model_spec.nonresonant[key[1]]
        _, i, name = key
        return self._model_spec.peaks[i].params[name]

    def _rebuild_parameter_table(self):
        rows = []
        for name, fp in self._model_spec.nonresonant.items():
            rows.append((("nr", name), "Non-resonant", name.capitalize(), fp))
        for i, peak in enumerate(self._model_spec.peaks):
            ls = get_lineshape(peak.lineshape_key)
            for p in ls.params:
                rows.append((("peak", i, p.name), f"Peak {i + 1} ({ls.display_name})",
                             p.display_name, peak.params[p.name]))

        table = self._param_table
        table.setRowCount(len(rows))
        self._param_row_keys = [r[0] for r in rows]

        for row, (key, label, pname, fp) in enumerate(rows):
            table.setItem(row, _COL_LABEL, _readonly_item(label))
            table.setItem(row, _COL_PARAM, _readonly_item(pname))

            value_spin = QDoubleSpinBox()
            value_spin.setRange(-1e9, 1e9)
            value_spin.setDecimals(4)
            value_spin.setValue(fp.value)
            value_spin.valueChanged.connect(lambda v, r=row: self._on_param_value_changed(r, v))
            table.setCellWidget(row, _COL_VALUE, value_spin)

            table.setItem(row, _COL_ERROR, _readonly_item(""))

            fixed_check = QCheckBox()
            fixed_check.setChecked(not fp.vary)
            fixed_check.toggled.connect(lambda checked, r=row: self._on_param_fixed_changed(r, checked))
            table.setCellWidget(row, _COL_FIXED, _center_widget(fixed_check))

            min_edit = QLineEdit(_fmt_bound(fp.min))
            min_edit.editingFinished.connect(lambda r=row: self._on_param_min_changed(r))
            table.setCellWidget(row, _COL_MIN, min_edit)

            max_edit = QLineEdit(_fmt_bound(fp.max))
            max_edit.editingFinished.connect(lambda r=row: self._on_param_max_changed(r))
            table.setCellWidget(row, _COL_MAX, max_edit)

            expr_edit = QLineEdit(fp.expr or "")
            expr_edit.editingFinished.connect(lambda r=row: self._on_param_expr_changed(r))
            table.setCellWidget(row, _COL_EXPR, expr_edit)

    def _on_param_value_changed(self, row: int, value: float):
        key = self._param_row_keys[row]
        self._param_at(key).value = value
        self._schedule_preview()

    def _on_param_fixed_changed(self, row: int, checked: bool):
        key = self._param_row_keys[row]
        self._param_at(key).vary = not checked

    def _on_param_min_changed(self, row: int):
        key = self._param_row_keys[row]
        fp = self._param_at(key)
        widget = self._param_table.cellWidget(row, _COL_MIN)
        fp.min = _parse_bound(widget.text(), fp.min)
        widget.setText(_fmt_bound(fp.min))

    def _on_param_max_changed(self, row: int):
        key = self._param_row_keys[row]
        fp = self._param_at(key)
        widget = self._param_table.cellWidget(row, _COL_MAX)
        fp.max = _parse_bound(widget.text(), fp.max)
        widget.setText(_fmt_bound(fp.max))

    def _on_param_expr_changed(self, row: int):
        key = self._param_row_keys[row]
        fp = self._param_at(key)
        widget = self._param_table.cellWidget(row, _COL_EXPR)
        text = widget.text().strip()
        fp.expr = text or None

    def _apply_fit_result_to_table(self):
        if self._last_result is None:
            return
        table = self._param_table
        for row, key in enumerate(self._param_row_keys):
            lmfit_key = _lmfit_key(key)
            pr = self._last_result.param_results.get(lmfit_key)
            value_widget = table.cellWidget(row, _COL_VALUE)
            if value_widget is None:
                continue
            value_widget.blockSignals(True)
            value_widget.setValue(self._param_at(key).value)
            value_widget.blockSignals(False)
            if pr is not None:
                value_widget.setStyleSheet("background-color: #fff3cd;" if pr.at_bound else "")
                err_item = table.item(row, _COL_ERROR)
                if err_item is not None:
                    err_item.setText("" if pr.stderr is None else f"{pr.stderr:.4g}")

    # ── Display dock ─────────────────────────────────────────────────────────
    # Which of the available curves (data/fit/fit-real/fit-imag/residual/
    # each peak) show on which plot area -- decoupled from the peak table
    # (which only manages peak identity/lineshape/removal).

    def _series_order(self) -> list[str]:
        order = [key for key, _ in _FIXED_SERIES]
        order += [f"peak_{i}" for i in range(len(self._model_spec.peaks))]
        return order

    def _series_label(self, key: str) -> str:
        fixed = dict(_FIXED_SERIES)
        if key in fixed:
            return fixed[key]
        if key.startswith("peak_"):
            return f"Peak {int(key.split('_')[1]) + 1}"
        return key

    def _sync_series_assignment(self):
        """Rebuild self._series_assignment/_series_styles for the current
        series set, keeping existing choices for series that still exist
        and defaulting newly-appeared ones (dropping stale ones for
        removed peaks). Note: since peaks are identified by their current
        index, removing an earlier peak reindexes later ones -- a later
        peak can inherit an earlier one's display assignment/style across
        such a removal (same known limitation as expr constraints
        referencing peaks by index)."""
        order = self._series_order()
        new_assignment = {}
        new_styles = {}
        for key in order:
            if key in self._series_assignment:
                new_assignment[key] = self._series_assignment[key]
            elif key in _DEFAULT_PLOT2_SERIES:
                new_assignment[key] = {"plot2"}
            elif key in _DEFAULT_PLOT1_SERIES:
                new_assignment[key] = {"plot1"}
            else:
                new_assignment[key] = set()

            new_styles[key] = self._series_styles.get(key) or SeriesStyle(linestyle=_default_linestyle_for(key))
        self._series_assignment = new_assignment
        self._series_styles = new_styles

    def _build_display_section(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.addWidget(QLabel("Pick which curves show on which plot area, and how they look:"))
        self._display_table = QTableWidget(0, 5)
        self._display_table.setHorizontalHeaderLabels(
            ["Series", "Plot 1", "Plot 2", "Color", "Line style"]
        )
        self._display_table.verticalHeader().setVisible(False)
        self._display_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self._display_table)

        reset_btn = QPushButton("Reset all styles to auto")
        reset_btn.clicked.connect(self._on_reset_all_styles)
        layout.addWidget(reset_btn)
        return widget

    def _rebuild_display_table(self):
        self._sync_series_assignment()
        order = self._series_order()
        self._display_row_keys = order

        table = self._display_table
        table.setRowCount(len(order))
        for row, key in enumerate(order):
            table.setItem(row, _DISPLAY_COL_LABEL, _readonly_item(self._series_label(key)))

            plot1_check = QCheckBox()
            plot1_check.setChecked("plot1" in self._series_assignment[key])
            plot1_check.toggled.connect(lambda checked, k=key: self._on_series_toggle(k, "plot1", checked))
            table.setCellWidget(row, _DISPLAY_COL_PLOT1, _center_widget(plot1_check))

            plot2_check = QCheckBox()
            plot2_check.setChecked("plot2" in self._series_assignment[key])
            plot2_check.toggled.connect(lambda checked, k=key: self._on_series_toggle(k, "plot2", checked))
            table.setCellWidget(row, _DISPLAY_COL_PLOT2, _center_widget(plot2_check))

            style = self._series_styles[key]

            color_row = QHBoxLayout()
            color_row.setContentsMargins(0, 0, 0, 0)
            color_holder = QWidget()
            color_btn = QPushButton()
            color_btn.setFixedWidth(50)
            self._style_color_button(color_btn, style.color)
            color_btn.clicked.connect(lambda _checked=False, k=key, b=color_btn: self._on_pick_series_color(k, b))
            reset_btn = QPushButton("×")
            reset_btn.setFixedWidth(20)
            reset_btn.setToolTip("Reset to auto color")
            reset_btn.clicked.connect(lambda _checked=False, k=key, b=color_btn: self._on_reset_series_color(k, b))
            color_row.addWidget(color_btn)
            color_row.addWidget(reset_btn)
            color_holder.setLayout(color_row)
            table.setCellWidget(row, _DISPLAY_COL_COLOR, color_holder)

            linestyle_combo = QComboBox()
            for label, _code in _LINESTYLE_OPTIONS:
                linestyle_combo.addItem(label)
            linestyle_combo.setCurrentText(_LINESTYLE_CODE_TO_LABEL.get(style.linestyle, "Solid"))
            linestyle_combo.currentIndexChanged.connect(
                lambda idx, k=key: self._on_series_linestyle_changed(k, idx)
            )
            table.setCellWidget(row, _DISPLAY_COL_LINESTYLE, linestyle_combo)

    def _on_series_toggle(self, key: str, plot_id: str, checked: bool):
        assignment = self._series_assignment.setdefault(key, set())
        if checked:
            assignment.add(plot_id)
        else:
            assignment.discard(plot_id)
        self._schedule_preview()

    @staticmethod
    def _style_color_button(button: QPushButton, color: str | None):
        if color:
            button.setStyleSheet(f"background-color: {color};")
            button.setText("")
        else:
            button.setStyleSheet("")
            button.setText("Auto")

    def _on_pick_series_color(self, key: str, button: QPushButton):
        current = self._series_styles[key].color or "#ffffff"
        chosen = QColorDialog.getColor(QColor(current), self, "Series color")
        if chosen.isValid():
            self._series_styles[key].color = chosen.name()
            self._style_color_button(button, chosen.name())
            self._schedule_preview()

    def _on_reset_series_color(self, key: str, button: QPushButton):
        self._series_styles[key].color = None
        self._style_color_button(button, None)
        self._schedule_preview()

    def _on_series_linestyle_changed(self, key: str, combo_index: int):
        self._series_styles[key].linestyle = _LINESTYLE_OPTIONS[combo_index][1]
        self._schedule_preview()

    def _on_reset_all_styles(self):
        for key in self._series_styles:
            self._series_styles[key] = SeriesStyle(linestyle=_default_linestyle_for(key))
        self._rebuild_display_table()
        self._schedule_preview()

    # ── Fit dock ─────────────────────────────────────────────────────────────

    def _build_fit_section(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        range_row = QHBoxLayout()
        range_row.addWidget(QLabel("Fit range:"))
        self._fit_min_spin = QDoubleSpinBox()
        self._fit_min_spin.setRange(-1e6, 1e6)
        self._fit_min_spin.setDecimals(2)
        self._fit_min_spin.valueChanged.connect(self._on_fit_range_changed)
        range_row.addWidget(self._fit_min_spin)
        range_row.addWidget(QLabel("to"))
        self._fit_max_spin = QDoubleSpinBox()
        self._fit_max_spin.setRange(-1e6, 1e6)
        self._fit_max_spin.setDecimals(2)
        self._fit_max_spin.valueChanged.connect(self._on_fit_range_changed)
        range_row.addWidget(self._fit_max_spin)
        layout.addLayout(range_row)
        layout.addWidget(QLabel(
            "Independent of the plots' own view zoom — shown as a shaded region on Plot 1."
        ))

        form = QFormLayout()
        layout.addLayout(form)

        self._weighting_combo = QComboBox()
        self._weighting_combo.addItem("None", userData="none")
        self._weighting_combo.addItem("Statistical (1/√intensity)", userData="statistical")
        self._weighting_combo.addItem("Measurement error (SEM)", userData="measurement_error")
        form.addRow("Weighting:", self._weighting_combo)

        run_btn = QPushButton("Run fit")
        run_btn.clicked.connect(self._on_run_fit)
        layout.addWidget(run_btn)

        self._quality_label = QLabel("No fit yet.")
        self._quality_label.setWordWrap(True)
        layout.addWidget(self._quality_label)

        ci_btn = QPushButton("Compute confidence intervals")
        ci_btn.clicked.connect(self._on_compute_ci)
        layout.addWidget(ci_btn)

        layout.addWidget(QLabel("Fit templates:"))
        template_row = QHBoxLayout()
        self._template_combo = QComboBox()
        self._refresh_template_combo()
        template_row.addWidget(self._template_combo, stretch=1)
        apply_btn = QPushButton("Apply")
        apply_btn.clicked.connect(self._on_apply_template)
        template_row.addWidget(apply_btn)
        layout.addLayout(template_row)
        save_template_btn = QPushButton("Save current model as template")
        save_template_btn.clicked.connect(self._on_save_template)
        layout.addWidget(save_template_btn)

        export_btn = QPushButton("Export fit (CSV with provenance)")
        export_btn.clicked.connect(self._on_export_fit)
        layout.addWidget(export_btn)

        layout.addStretch()
        return widget

    def _fit_mask(self) -> np.ndarray:
        lo, hi = self._fit_min_spin.value(), self._fit_max_spin.value()
        return (self._data.omega >= lo) & (self._data.omega <= hi)

    def _on_fit_range_changed(self, *_args):
        self._schedule_preview()

    def _on_run_fit(self):
        if self._data is None:
            QMessageBox.information(self, "No data", "Load a spectrum first.")
            return
        mask = self._fit_mask()
        if not mask.any():
            QMessageBox.warning(self, "Empty fit window", "No data points fall inside the current x-range.")
            return
        omega = self._data.omega[mask]
        intensity = self._data.intensity[mask]
        intensity_std = self._data.intensity_std[mask] if self._data.intensity_std is not None else None
        count = self._data.count[mask] if self._data.count is not None else None
        weighting = self._weighting_combo.currentData()
        weights = compute_weights(weighting, intensity, intensity_std, count)

        loading = show_loading(self, "Fitting...")
        try:
            self._last_result = fit_homodyne(omega, intensity, self._model_spec, weights=weights)
        except Exception as e:
            logger.warning("Fit failed: %s", e)
            QMessageBox.warning(self, "Fit failed", str(e))
            return
        finally:
            loading.close()

        self._model_spec = self._last_result.spec
        self._apply_fit_result_to_table()
        self._update_quality_readout()
        self._update_preview()

    def _update_quality_readout(self):
        if self._last_result is None:
            self._quality_label.setText("No fit yet.")
            return
        r = self._last_result
        self._quality_label.setText(
            f"redchi = {r.redchi:.4g}   R² = {r.r_squared:.4f}   "
            f"AIC = {r.aic:.4g}   BIC = {r.bic:.4g}   "
            f"({'converged' if r.success else 'did not converge'})"
        )

    def _on_compute_ci(self):
        if self._last_result is None or self._last_result.lmfit_minimizer is None:
            QMessageBox.information(self, "No fit yet", "Run a fit first.")
            return
        import lmfit
        loading = show_loading(self, "Computing confidence intervals...")
        try:
            ci = lmfit.conf_interval(self._last_result.lmfit_minimizer, self._last_result.lmfit_result)
            text = lmfit.ci_report(ci)
        except Exception as e:
            logger.warning("Could not compute confidence intervals: %s", e)
            QMessageBox.warning(self, "Could not compute confidence intervals", str(e))
            return
        finally:
            loading.close()
        QMessageBox.information(self, "Confidence intervals", text)

    def _refresh_template_combo(self):
        self._template_combo.clear()
        self._template_combo.addItems(self._template_manager.names())

    def _on_save_template(self):
        name, ok = QInputDialog.getText(self, "Save fit template", "Template name:")
        if not ok or not name.strip():
            return
        self._template_manager.set(name.strip(), self._model_spec)
        self._refresh_template_combo()

    def _on_apply_template(self):
        name = self._template_combo.currentText()
        if not name:
            return
        spec = self._template_manager.get(name)
        if spec is None:
            return
        self._model_spec = spec
        self._last_result = None
        self._rebuild_peak_table()
        self._rebuild_parameter_table()
        self._rebuild_display_table()
        self._update_quality_readout()
        self._schedule_preview()

    def _on_export_fit(self):
        if self._data is None or self._last_result is None:
            QMessageBox.information(self, "Nothing to export", "Load data and run a fit first.")
            return
        path_str, _ = QFileDialog.getSaveFileName(
            self, "Export fit", f"{self._data.label}_fit.csv", "CSV files (*.csv)",
        )
        if not path_str:
            return

        spectrum = self._data.source_spectrum
        if spectrum is None:
            df = pd.DataFrame({"Wavenumber": self._data.omega, "Intensity": self._data.intensity})
            spectrum = ProcessedSpectrum(df, metadata={}, history=["loaded_from_file"], provenance={})

        weighting = self._weighting_combo.currentData()
        r = self._last_result
        fit_section = provenance.format_fit_section(
            self._model_spec.to_dict(), weighting, r.redchi, r.r_squared, r.aic, r.bic,
        )
        try:
            provenance.write_csv_with_provenance(
                spectrum, "homodyne", self._data.label, Path(path_str), fit_section=fit_section,
            )
        except Exception as e:
            QMessageBox.warning(self, "Export failed", str(e))
            return
        QMessageBox.information(self, "Export complete", f"Fit exported to {path_str}")

    # ── Plot ─────────────────────────────────────────────────────────────────

    def _plot_data(self):
        self.plot_widget.full_clear()
        self.plot_widget2.full_clear()
        if self._data is None:
            self.plot_widget.canvas.draw_idle()
            self.plot_widget2.canvas.draw_idle()
            return
        self.plot_widget.set_labels(xlabel="Wavenumber (cm$^{-1}$)", title=self._data.label)
        self.plot_widget2.set_labels(xlabel="Wavenumber (cm$^{-1}$)")

    def redraw_for_style_change(self):
        """Called after the global plotting style changes. full_clear()
        recreates each Axes fresh under the new rcParams (a style change
        alters the Axes' own background/grid/spine chrome, which is
        baked in at Axes-creation time -- just re-plotting lines on the
        existing Axes would leave that pre-restyle chrome behind, same
        reasoning as ProcessedResultsTab/HDSFGPanel's own
        redraw_for_style_change()). Every visible series' auto-cycled
        color is also baked into its Line2D at plot time, so a normal
        preview redraw after the clear is what actually picks up the new
        style's color cycle, not just the background.
        """
        self._plot_data()
        self._update_preview()

    def _schedule_preview(self):
        self._preview_timer.start()

    def _compute_series_values(self) -> dict[str, np.ndarray]:
        omega = self._data.omega
        total = evaluate_homodyne(omega, self._model_spec)
        chi = evaluate_chi(omega, self._model_spec)
        values = {
            "data": self._data.intensity,
            "fit_total": total,
            "fit_real": chi.real,
            "fit_imag": chi.imag,
            "residual": self._data.intensity - total,
        }
        for i, peak in enumerate(self._model_spec.peaks):
            values[f"peak_{i}"] = evaluate_peak_component(omega, peak)
        return values

    def _style_for(self, key: str) -> dict:
        # Data keeps its fixed marker identity; every series' color/linestyle
        # comes from self._series_styles (None color = let the active
        # plotting style's own cycle assign it -- see SeriesStyle).
        kwargs = {"marker": ".", "markersize": 3} if key == "data" else {}
        style = self._series_styles.get(key) or SeriesStyle(linestyle=_default_linestyle_for(key))
        kwargs["linestyle"] = style.linestyle
        if style.color is not None:
            kwargs["color"] = style.color
        return kwargs

    def _ylabel_for(self, plot_id: str) -> str:
        keys = {k for k, plots in self._series_assignment.items() if plot_id in plots}
        if keys == {"residual"}:
            return "Residual (counts)"
        if keys and keys <= {"fit_real", "fit_imag"}:
            return "χ_eff (a.u.)"
        return "Intensity (counts)"

    def _update_preview(self):
        if self._data is None:
            return
        values = self._compute_series_values()
        self._redraw_plot(self.plot_widget, "plot1", values)
        self._redraw_plot(self.plot_widget2, "plot2", values)

    def _redraw_plot(self, plot_widget: SpectrumPlotWidget, plot_id: str, values: dict):
        ax = plot_widget.ax
        for line in list(ax.lines):
            line.remove()
        for patch in list(ax.patches):
            patch.remove()
        ax.set_prop_cycle(None)

        omega = self._data.omega
        any_line = False
        for key in self._series_order():
            if plot_id not in self._series_assignment.get(key, set()):
                continue
            y = values.get(key)
            if y is None:
                continue
            ax.plot(omega, y, label=self._series_label(key), **self._style_for(key))
            any_line = True

        if plot_id == "plot1":
            lo, hi = self._fit_min_spin.value(), self._fit_max_spin.value()
            if hi > lo:
                ax.axvspan(lo, hi, color="tab:blue", alpha=0.08, zorder=0)

        if any_line:
            ax.legend(fontsize=8)
        ax.set_ylabel(self._ylabel_for(plot_id))
        plot_widget.canvas.draw_idle()
