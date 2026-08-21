from __future__ import annotations
import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QComboBox,
    QPushButton, QCheckBox, QDoubleSpinBox, QLineEdit, QTableWidget,
    QTableWidgetItem, QHeaderView, QSizePolicy, QFileDialog, QMessageBox,
    QInputDialog,
)

from sfg_app2.app.widgets.spectrum_plot_widget import SpectrumPlotWidget
from sfg_app2.app.widgets.dockable_panels import DockablePlotPanel
from sfg_app2.app.utils.loading_indicator import show_loading
from sfg_app2.app.utils.fit_template_manager import FitTemplateManager
from sfg_app2.processing import provenance
from sfg_app2.processing.processed_spectrum import ProcessedSpectrum
from sfg_app2.processing.fitting import (
    FitParam, PeakInstance, FitModelSpec, default_peak,
    evaluate_homodyne, evaluate_peak_component, fit_homodyne, compute_weights,
    available_lineshapes, get_lineshape, fit_model_spec_from_provenance_payload,
)

logger = logging.getLogger(__name__)

_COL_LABEL, _COL_PARAM, _COL_VALUE, _COL_ERROR, _COL_FIXED, _COL_MIN, _COL_MAX, _COL_EXPR = range(8)
_PEAK_COL_INDEX, _PEAK_COL_LINESHAPE, _PEAK_COL_VISIBLE, _PEAK_COL_REMOVE = range(4)


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
        self._peak_visible: list[bool] = []
        self._last_result = None
        self._param_row_keys: list[tuple] = []
        self._extra_lines: list = []
        self._placement_armed = False
        self._template_manager = FitTemplateManager()

        self._preview_timer = QTimer()
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(50)
        self._preview_timer.timeout.connect(self._update_preview)

        self.plot_widget = SpectrumPlotWidget()
        self.plot_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.plot_widget.canvas.mpl_connect("button_press_event", self._on_plot_click)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(4, 4, 4, 4)
        main_layout.setSpacing(4)

        self._init_dock_area(self.plot_widget)
        self._add_dock("data_source", "Data source", self._build_data_source_section())
        self._add_dock("model", "Model", self._build_model_section())
        self._add_dock("parameters", "Parameters", self._build_parameters_section())
        self._add_dock("fit", "Fit", self._build_fit_section())
        main_layout.addWidget(self._dock_main_window)

        self._plot_data()
        self._rebuild_peak_table()
        self._rebuild_parameter_table()
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
        self._peak_visible = [True] * len(self._model_spec.peaks)
        self._last_result = None
        self._data_label.setText(f"Loaded: {self._data.label} ({len(self._data.omega)} points)")
        self._plot_data()
        self._rebuild_peak_table()
        self._rebuild_parameter_table()
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

        self._peak_table = QTableWidget(0, 4)
        self._peak_table.setHorizontalHeaderLabels(["Peak", "Lineshape", "Visible", "Remove"])
        self._peak_table.verticalHeader().setVisible(False)
        self._peak_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self._peak_table)
        return widget

    def _on_add_peak_toggled(self, checked: bool):
        self._placement_armed = checked
        self._add_peak_btn.setText("Click on the plot..." if checked else "Add peak")

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
        self._peak_visible.append(True)
        self._rebuild_peak_table()
        self._rebuild_parameter_table()
        self._schedule_preview()

    def _on_nonresonant_toggled(self, checked: bool):
        nr = self._model_spec.nonresonant
        if checked:
            nr["amplitude"].vary = True
            if nr["amplitude"].value == 0.0:
                nr["amplitude"].value = 0.1
            nr["phase"].vary = True
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

            visible_check = QCheckBox()
            visible_check.setChecked(self._peak_visible[i] if i < len(self._peak_visible) else True)
            visible_check.toggled.connect(lambda checked, row=i: self._on_peak_visibility_toggled(row, checked))
            table.setCellWidget(i, _PEAK_COL_VISIBLE, _center_widget(visible_check))

            remove_btn = QPushButton("Remove")
            remove_btn.clicked.connect(lambda _checked=False, row=i: self._on_remove_peak(row))
            table.setCellWidget(i, _PEAK_COL_REMOVE, remove_btn)

    def _on_peak_visibility_toggled(self, row: int, checked: bool):
        if 0 <= row < len(self._peak_visible):
            self._peak_visible[row] = checked
        self._schedule_preview()

    def _on_remove_peak(self, row: int):
        if 0 <= row < len(self._model_spec.peaks):
            del self._model_spec.peaks[row]
            del self._peak_visible[row]
        self._rebuild_peak_table()
        self._rebuild_parameter_table()
        self._schedule_preview()

    # ── Parameters dock ──────────────────────────────────────────────────────

    def _build_parameters_section(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        self._param_table = QTableWidget(0, 8)
        self._param_table.setHorizontalHeaderLabels(
            ["Peak", "Parameter", "Value", "Error", "Fixed", "Min", "Max", "Expr"]
        )
        self._param_table.verticalHeader().setVisible(False)
        self._param_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
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

    # ── Fit dock ─────────────────────────────────────────────────────────────

    def _build_fit_section(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
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
        x_range = self.plot_widget.get_x_range()
        if x_range is None:
            return np.ones_like(self._data.omega, dtype=bool)
        lo, hi = x_range
        return (self._data.omega >= lo) & (self._data.omega <= hi)

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
        self._peak_visible = [True] * len(self._model_spec.peaks)
        self._last_result = None
        self._rebuild_peak_table()
        self._rebuild_parameter_table()
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
        self._extra_lines = []
        if self._data is None:
            self.plot_widget.canvas.draw_idle()
            return
        self.plot_widget.plot(
            self._data.omega, self._data.intensity, label="Data",
            color="black", marker=".", linestyle="none", markersize=3,
        )
        self.plot_widget.set_labels(
            xlabel="Wavenumber (cm$^{-1}$)", ylabel="Intensity (counts)", title=self._data.label,
        )

    def _schedule_preview(self):
        self._preview_timer.start()

    def _clear_extra_lines(self):
        for line in self._extra_lines:
            try:
                line.remove()
            except (ValueError, NotImplementedError):
                pass
        self._extra_lines = []

    def _update_preview(self):
        if self._data is None:
            return
        self._clear_extra_lines()
        omega = self._data.omega

        total = evaluate_homodyne(omega, self._model_spec)
        line, = self.plot_widget.ax.plot(omega, total, color="red", linewidth=1.5, label="Fit")
        self._extra_lines.append(line)

        for i, peak in enumerate(self._model_spec.peaks):
            if i < len(self._peak_visible) and not self._peak_visible[i]:
                continue
            comp = evaluate_peak_component(omega, peak)
            cline, = self.plot_widget.ax.plot(omega, comp, linestyle="--", linewidth=1.0, label=f"Peak {i + 1}")
            self._extra_lines.append(cline)

        residual = self._data.intensity - total
        ax2 = self.plot_widget.secondary_axis()
        rline, = ax2.plot(omega, residual, color="gray", linewidth=0.7, alpha=0.7, label="_nolegend_")
        ax2.set_ylabel("Residual")
        self._extra_lines.append(rline)

        self.plot_widget.ax.legend(fontsize=8)
        self.plot_widget.canvas.draw_idle()
