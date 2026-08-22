from __future__ import annotations
import json
import logging
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QComboBox,
    QPushButton, QCheckBox, QDoubleSpinBox, QLineEdit, QTableWidget,
    QTableWidgetItem, QHeaderView, QSizePolicy, QFileDialog, QMessageBox,
    QInputDialog, QColorDialog, QListWidget, QListWidgetItem, QAbstractItemView,
    QProgressDialog, QApplication, QMenu,
)

from sfg_app2.app.widgets.spectrum_plot_widget import SpectrumPlotWidget
from sfg_app2.app.widgets.dockable_panels import DockablePlotPanel
from sfg_app2.app.utils.loading_indicator import show_loading
from sfg_app2.app.utils.fit_template_manager import FitTemplateManager
from sfg_app2.processing import provenance
from sfg_app2.processing.processed_spectrum import ProcessedSpectrum
from sfg_app2.processing.fitting import (
    FitParam, PeakInstance, FitModelSpec, default_peak,
    evaluate_homodyne, evaluate_chi, evaluate_peak_component,
    fit_homodyne, fit_heterodyne, compute_weights, compute_heterodyne_weights,
    available_lineshapes, get_lineshape, fit_model_spec_from_provenance_payload,
    BatchDataset, fit_sequential_batch, fit_independent_batch, fit_one_dataset, advance_seed,
)

logger = logging.getLogger(__name__)

_COL_LABEL, _COL_PARAM, _COL_FIXED, _COL_VALUE, _COL_ERROR, _COL_MIN, _COL_MAX, _COL_EXPR = range(8)
_PEAK_COL_INDEX, _PEAK_COL_LINESHAPE, _PEAK_COL_REMOVE = range(3)
(_DISPLAY_COL_LABEL, _DISPLAY_COL_PLOT1, _DISPLAY_COL_PLOT2,
 _DISPLAY_COL_COLOR, _DISPLAY_COL_LINESTYLE) = range(5)

# Fixed series always available for plotting, in display order; peak_{i}
# series are appended dynamically, one per current peak. The set differs
# by mode (homodyne fits a single intensity channel; heterodyne fits
# Real/Imaginary simultaneously, so there's no single "total"/"residual"
# curve) -- _series_order()/_sync_series_assignment() pick the right one
# based on self._data.kind. "fit_real"/"fit_imag" keys (and their labels)
# are shared verbatim across both modes: in homodyne mode they're a
# diagnostic overlay of the model's complex chi_eff; in heterodyne mode
# they're the actual fitted curves against data_real/data_imag.
_FIXED_SERIES_HOMODYNE = [
    ("data", "Data"),
    ("fit_total", "Fit (total)"),
    ("fit_real", "Fit (real)"),
    ("fit_imag", "Fit (imaginary)"),
    ("residual", "Residual"),
]
_FIXED_SERIES_HETERODYNE = [
    ("data_real", "Data (real)"),
    ("data_imag", "Data (imaginary)"),
    ("fit_real", "Fit (real)"),
    ("fit_imag", "Fit (imaginary)"),
    ("residual_real", "Residual (real)"),
    ("residual_imag", "Residual (imaginary)"),
]
_DEFAULT_PLOT1_SERIES_HOMODYNE = {"data", "fit_total"}
_DEFAULT_PLOT2_SERIES_HOMODYNE = {"fit_real", "fit_imag"}
_DEFAULT_PLOT1_SERIES_HETERODYNE = {"data_real", "data_imag"}
_DEFAULT_PLOT2_SERIES_HETERODYNE = {"fit_real", "fit_imag"}
# residual(s) and every peak_i default to hidden on both plots -- opt in
# via the Display dock.

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
    return "none" if key in ("data", "data_real", "data_imag") else "-"


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


def _extract_homodyne_channels(df) -> dict | None:
    if "Wavenumber" not in df.columns or "Intensity" not in df.columns:
        return None
    omega = df["Wavenumber"].to_numpy(dtype=float)
    intensity = df["Intensity"].to_numpy(dtype=float)
    intensity_std = df["Intensity_std"].to_numpy(dtype=float) if "Intensity_std" in df.columns else None
    count = df["count"].to_numpy(dtype=float) if "count" in df.columns else None
    order = np.argsort(omega)
    return dict(
        kind="homodyne", omega=omega[order], intensity=intensity[order],
        intensity_std=intensity_std[order] if intensity_std is not None else None,
        count=count[order] if count is not None else None,
    )


def _extract_heterodyne_channels(df) -> dict | None:
    if not {"Wavenumber", "Real", "Imaginary"}.issubset(df.columns):
        return None
    omega = df["Wavenumber"].to_numpy(dtype=float)
    real = df["Real"].to_numpy(dtype=float)
    imag = df["Imaginary"].to_numpy(dtype=float)
    real_err = df["Real_err"].to_numpy(dtype=float) if "Real_err" in df.columns else None
    imag_err = df["Imag_err"].to_numpy(dtype=float) if "Imag_err" in df.columns else None
    order = np.argsort(omega)
    return dict(
        kind="heterodyne", omega=omega[order], real=real[order], imag=imag[order],
        real_err=real_err[order] if real_err is not None else None,
        imag_err=imag_err[order] if imag_err is not None else None,
    )


def _extract_channels(df, preferred_kind: str | None = None) -> dict | None:
    """Try the preferred kind first (from a Results-tab entry's own kind,
    or a loaded file's provenance Type: header), then fall back to
    whichever column set actually matches -- mirrors
    processed_results.py's own kind-detection fallback chain."""
    extractors = {"homodyne": _extract_homodyne_channels, "heterodyne": _extract_heterodyne_channels}
    order = [preferred_kind] if preferred_kind in extractors else []
    order += [k for k in extractors if k != preferred_kind]
    for k in order:
        result = extractors[k](df)
        if result is not None:
            return result
    return None


@dataclass(eq=False)
class _FileLoadedEntry:
    """Duck-type compatible with processed_results.SpectrumEntry (same
    .label/.spectrum/.kind), so a spectrum loaded directly from a file
    can sit in the same Batch/Sequential selection list as a Results-tab
    entry and flow through _extract_channels()/drill-down unmodified.
    eq=False keeps default identity-based equality/hash (matching
    SpectrumEntry's own default semantics) -- two separate loads are
    always distinct entries, never coalesced by value."""
    label: str
    spectrum: object   # a ProcessedSpectrum
    kind: str


def _entry_display_text(entry) -> str:
    prefix = "[heterodyne] " if entry.kind == "heterodyne" else ""
    return f"{prefix}{entry.label}"


def _make_list_item(entry, checkable: bool = False) -> QListWidgetItem:
    """checkable=True is Sequential's per-row "checkpoint" flag (an
    inline checkbox via Qt's own ItemIsUserCheckable, left of the
    label) -- Batch's list has no per-row state besides selection, so
    it never needs this."""
    item = QListWidgetItem(_entry_display_text(entry))
    item.setData(Qt.ItemDataRole.UserRole, entry)
    if checkable:
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(Qt.CheckState.Unchecked)
    return item


def _all_entries_in_order(list_widget: QListWidget) -> list:
    """Every entry currently in the list, in list order -- Batch/
    Sequential fit everything in the list, not just what's selected;
    selection is reserved for right-click removal and drag-reordering."""
    return [list_widget.item(i).data(Qt.ItemDataRole.UserRole) for i in range(list_widget.count())]


@dataclass
class _FittableSpectrum:
    label: str
    omega: np.ndarray
    kind: str                            # "homodyne" | "heterodyne"
    # homodyne channel:
    intensity: np.ndarray | None = None
    intensity_std: np.ndarray | None = None
    count: np.ndarray | None = None
    # heterodyne channels:
    real: np.ndarray | None = None
    imag: np.ndarray | None = None
    real_err: np.ndarray | None = None
    imag_err: np.ndarray | None = None
    source_spectrum: object | None = None   # the original ProcessedSpectrum, if loaded from Results tab
    fit_json_payload: dict | None = None    # a previous fit's payload, if the file carried one


class FittingTab(QWidget, DockablePlotPanel):
    """Single-spectrum peak fitting via processing.fitting (lmfit-based,
    Qt-free), in two modes auto-selected by the loaded spectrum's kind:
    homodyne (|chi_NR*e^{i.phi} + sum_j resonance_j(omega)|^2 fit against
    measured intensity) and heterodyne (Re/Im of the same complex
    chi_eff fit simultaneously against measured Real/Imaginary data).
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

        # Multi-fit (Batch/Sequential) shared results state -- see
        # _build_batch_section()/_build_sequential_section()/
        # _build_multifit_results_section(). _batch_rows holds
        # (entry, BatchDataset, FitResult|None) triples in the order the
        # run actually processed them; _batch_row_overrides is a
        # parallel list of {"fit_range":..., "weighting":...}|None for
        # rows whose actual fit conditions diverged from the run-wide
        # ones (a Sequential checkpoint retry using a different range/
        # weighting than the rest of the run). _batch_template/
        # _fit_range/_weighting/_run_mode are captured at run time so a
        # later edit to the live model/fit controls doesn't
        # retroactively change what "Export batch summary"/drill-down
        # reproduce.
        self._batch_rows: list[tuple] = []
        self._batch_row_overrides: list[dict | None] = []
        self._batch_template: FitModelSpec | None = None
        self._batch_fit_range: tuple[float, float] | None = None
        self._batch_weighting: str | None = None
        self._batch_run_mode: str | None = None   # "batch" | "sequential"

        # File-loaded spectra merged into each mode's own selection list
        # alongside Results-tab entries (see _load_files_into()).
        self._batch_file_entries: list[_FileLoadedEntry] = []
        self._sequential_file_entries: list[_FileLoadedEntry] = []

        # Sequential run state machine -- see _on_run_sequential_fit()/
        # _advance_sequential_run(). None outside of an active/paused run.
        self._sequential_run: dict | None = None

        self._preview_timer = QTimer()
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(50)
        self._preview_timer.timeout.connect(self._update_preview)

        self.plot_widget = SpectrumPlotWidget()
        self.plot_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.plot_widget.canvas.mpl_connect("button_press_event", self._on_plot_click)

        self.plot_widget2 = SpectrumPlotWidget()
        self.plot_widget2.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.plot_widget3 = SpectrumPlotWidget()
        self.plot_widget3.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(4, 4, 4, 4)
        main_layout.setSpacing(4)

        self._init_dock_area(self.plot_widget)
        self._add_dock("data_source", "Data source", self._build_data_source_section())
        self._add_dock("model", "Model", self._build_model_section())
        self._add_dock("parameters", "Parameters", self._build_parameters_section(), fill=True)
        self._add_dock("display", "Display", self._build_display_section(), fill=True)
        self._add_dock("fit", "Fit", self._build_fit_section())
        self._add_dock("batch", "Batch fit", self._build_batch_section(), fill=True)
        self._add_dock("sequential", "Sequential fit", self._build_sequential_section(), fill=True)
        self._add_dock("multifit_results", "Multi-fit results", self._build_multifit_results_section(), fill=True)
        self._add_dock("multifit_plot", "Multi-fit plot", self.plot_widget3, fill=True)
        self._add_dock("plot2", "Secondary plot", self.plot_widget2, fill=True)
        main_layout.addWidget(self._dock_main_window)

        self._plot_data()
        self._rebuild_peak_table()
        self._rebuild_parameter_table()
        self._rebuild_display_table()
        self._update_quality_readout()
        self._update_multifit_plot()

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
        self._data_label.setWordWrap(True)
        layout.addWidget(self._data_label)
        layout.addStretch()
        return widget

    def _on_refresh_results(self):
        self._results_combo.clear()
        self._results_entries = []
        if self._results_provider is not None:
            entries = self._results_provider.entries(kind=None)
            self._results_entries = entries
            for e in entries:
                self._results_combo.addItem(_entry_display_text(e))
        self._sync_list_with_results(self._batch_list, self._batch_file_entries, checkable=False)
        self._sync_list_with_results(self._sequential_list, self._sequential_file_entries, checkable=True)
        self._refresh_batch_controls()
        self._refresh_sequential_controls()

    def _sync_list_with_results(self, list_widget: QListWidget, file_entries: list, checkable: bool):
        """Merge self._results_entries into `list_widget` in place --
        remove rows whose Results-tab entry no longer exists, append
        newly-appeared ones at the end -- WITHOUT disturbing any
        surviving row's position, selection, or (for Sequential)
        checkbox state, and without ever touching `file_entries`' own
        rows (they aren't sourced from the Results tab, so a refresh
        never removes them)."""
        valid = set(self._results_entries) | set(file_entries)
        for i in reversed(range(list_widget.count())):
            if list_widget.item(i).data(Qt.ItemDataRole.UserRole) not in valid:
                list_widget.takeItem(i)
        present = {list_widget.item(i).data(Qt.ItemDataRole.UserRole) for i in range(list_widget.count())}
        for e in self._results_entries:
            if e not in present:
                list_widget.addItem(_make_list_item(e, checkable=checkable))

    def _load_files_into(self, list_widget: QListWidget, file_entries: list, checkable: bool):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Load spectra", "", "CSV files (*.csv);;All files (*.*)",
        )
        if not paths:
            return
        for path_str in paths:
            path = Path(path_str)
            try:
                df = provenance.load_csv_skip_comments(path)
                _, prov, meta = provenance.parse_export_header(path)
            except Exception as e:
                QMessageBox.warning(self, "Could not load file", f"{path.name}: {e}")
                continue
            channels = _extract_channels(df, preferred_kind=prov.get("kind"))
            if channels is None:
                QMessageBox.warning(
                    self, "Cannot fit this file",
                    f"{path.name}: no Wavenumber/Intensity or Wavenumber/Real/Imaginary columns found.",
                )
                continue
            spectrum = ProcessedSpectrum(df, metadata={}, history=["loaded_from_file"], provenance={})
            entry = _FileLoadedEntry(label=meta.get("label", path.stem), spectrum=spectrum, kind=channels["kind"])
            file_entries.append(entry)
            list_widget.addItem(_make_list_item(entry, checkable=checkable))
        self._refresh_batch_controls()
        self._refresh_sequential_controls()

    def _on_list_context_menu(self, list_widget: QListWidget, file_entries: list, pos):
        """Right-click -> Remove, since selection no longer gates which
        spectra get fit (Batch/Sequential now fit everything in the
        list) -- this is how a specific spectrum gets excluded. Acts on
        the whole current selection if the right-clicked row is part of
        it, otherwise just that one row."""
        item = list_widget.itemAt(pos)
        if item is None:
            return
        targets = list_widget.selectedItems() if item.isSelected() else [item]
        menu = QMenu(self)
        label = f"Remove {len(targets)} selected" if len(targets) > 1 else "Remove"
        action = menu.addAction(label)
        chosen = menu.exec(list_widget.mapToGlobal(pos))
        if chosen == action:
            self._remove_list_items(list_widget, file_entries, targets)

    def _remove_list_items(self, list_widget: QListWidget, file_entries: list, targets: list):
        """Removing a Results-tab-derived row is temporary (a Refresh
        brings it back); removing a file-loaded one also drops it from
        `file_entries` so it's gone for good. Split out from
        _on_list_context_menu() so the removal logic itself is testable
        without driving a real (blocking) QMenu.exec()."""
        for target in targets:
            entry = target.data(Qt.ItemDataRole.UserRole)
            if isinstance(entry, _FileLoadedEntry) and entry in file_entries:
                file_entries.remove(entry)
            list_widget.takeItem(list_widget.row(target))
        self._refresh_batch_controls()
        self._refresh_sequential_controls()

    def _on_load_selected_result(self):
        idx = self._results_combo.currentIndex()
        if idx < 0 or idx >= len(self._results_entries):
            QMessageBox.information(self, "No spectrum selected", "Pick a spectrum from the list first.")
            return
        entry = self._results_entries[idx]
        self._load_from_processed_spectrum(entry.spectrum, entry.label, kind=entry.kind)

    def _confirm_abandon_paused_sequential_run(self) -> bool:
        """True if it's OK to proceed loading a different spectrum. Checked
        BEFORE self._data is reassigned (in each load entry point, not
        inside _on_data_loaded()) -- by the time _on_data_loaded() runs,
        self._data already points at the new spectrum, too late to
        cleanly decline. If a Sequential run is currently paused at a
        checkpoint, loading something else abandons it -- silent
        abandonment is the wrong default since the failure mode (losing
        an in-progress retry) is exactly the kind of thing that goes
        unnoticed until export time."""
        if self._sequential_run is not None and self._sequential_run.get("paused"):
            reply = QMessageBox.question(
                self, "Sequential run paused",
                "A sequential run is paused for review — loading a different "
                "spectrum abandons it; any in-progress retry is lost and the "
                "run cannot resume. Continue anyway?",
            )
            if reply != QMessageBox.StandardButton.Yes:
                return False
            self._sequential_run = None
        return True

    def _load_from_processed_spectrum(self, spectrum, label: str, kind: str = "homodyne",
                                       preset: dict | None = None):
        if preset is None and not self._confirm_abandon_paused_sequential_run():
            return
        channels = _extract_channels(spectrum.data, preferred_kind=kind)
        if channels is None:
            QMessageBox.warning(
                self, "Cannot fit this spectrum",
                "No Wavenumber/Intensity or Wavenumber/Real/Imaginary columns found — "
                "has it been averaged and upconverted?",
            )
            return
        self._data = _FittableSpectrum(
            label=label, source_spectrum=spectrum, fit_json_payload=None, **channels,
        )
        self._on_data_loaded(preset=preset)

    def _on_load_from_file(self):
        if not self._confirm_abandon_paused_sequential_run():
            return
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
        channels = _extract_channels(df, preferred_kind=prov.get("kind"))
        if channels is None:
            QMessageBox.warning(
                self, "Cannot fit this file",
                "No Wavenumber/Intensity or Wavenumber/Real/Imaginary columns found.",
            )
            return
        self._data = _FittableSpectrum(
            label=meta.get("label", path.stem), source_spectrum=None,
            fit_json_payload=provenance.parse_fit_json(prov), **channels,
        )
        self._on_data_loaded()

    def _on_data_loaded(self, preset: dict | None = None):
        """`preset` (model_spec, last_result, fit_range, weighting) is
        given when drilling into a batch-fit result row -- it bypasses
        the normal empty/provenance-restored model and instead
        faithfully rehydrates the exact fit that produced that row
        (including the fit range/weighting the batch used), rather than
        resetting to the spectrum's full range like a fresh load does."""
        if preset is not None:
            self._model_spec = deepcopy(preset["model_spec"])
        else:
            prefill = None
            if self._data.fit_json_payload:
                prefill = fit_model_spec_from_provenance_payload(self._data.fit_json_payload)
                if prefill is not None:
                    self.statusBar_message(f"Restored a previous fit from {self._data.label}'s provenance.")
            if prefill is not None:
                self._model_spec = prefill
            else:
                self._model_spec = FitModelSpec.empty()
                if self._data.kind == "heterodyne":
                    # phase is degenerate with the peaks' own phase/amplitude
                    # in homodyne mode (only |chi|^2 is measured), so it's
                    # fixed there by default -- but fitting Re/Im directly
                    # constrains it well, so let it vary here.
                    self._model_spec.nonresonant["phase"].vary = True
        self._rebuild_weighting_combo()
        self._series_assignment = {}
        self._last_result = preset["last_result"] if preset is not None else None
        self._data_label.setText(f"Loaded: {self._data.label} ({len(self._data.omega)} points)")

        self._plot_data()
        if preset is not None and preset.get("fit_range") is not None:
            lo, hi = preset["fit_range"]
        else:
            lo, hi = float(self._data.omega.min()), float(self._data.omega.max())
        self.plot_widget.set_x_range(lo, hi)
        self.plot_widget2.set_x_range(lo, hi)
        for spin in (self._fit_min_spin, self._fit_max_spin):
            spin.blockSignals(True)
        self._fit_min_spin.setValue(lo)
        self._fit_max_spin.setValue(hi)
        for spin in (self._fit_min_spin, self._fit_max_spin):
            spin.blockSignals(False)

        if preset is not None and preset.get("weighting") is not None:
            idx = self._weighting_combo.findData(preset["weighting"])
            if idx >= 0:
                self._weighting_combo.setCurrentIndex(idx)

        self._rebuild_peak_table()
        self._rebuild_parameter_table()
        self._rebuild_display_table()
        self._apply_fit_result_to_table()
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
        peak_table_note = QLabel("Which curves show is controlled by the Display dock, not this table.")
        peak_table_note.setWordWrap(True)
        layout.addWidget(peak_table_note)
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
        x_range = self.plot_widget.get_x_range()
        span = (x_range[1] - x_range[0]) if x_range else float(self._data.omega.max() - self._data.omega.min())
        width = max(span * 0.02, 1.0)
        if self._data.kind == "heterodyne":
            magnitude = float(np.hypot(self._data.real[idx], self._data.imag[idx]))
            amplitude = max(magnitude * (width / 2.0), 0.5)
        else:
            baseline = float(np.min(self._data.intensity))
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

    def _fixed_series(self) -> list[tuple[str, str]]:
        if self._data is not None and self._data.kind == "heterodyne":
            return _FIXED_SERIES_HETERODYNE
        return _FIXED_SERIES_HOMODYNE

    def _default_plot1_series(self) -> set[str]:
        if self._data is not None and self._data.kind == "heterodyne":
            return _DEFAULT_PLOT1_SERIES_HETERODYNE
        return _DEFAULT_PLOT1_SERIES_HOMODYNE

    def _default_plot2_series(self) -> set[str]:
        if self._data is not None and self._data.kind == "heterodyne":
            return _DEFAULT_PLOT2_SERIES_HETERODYNE
        return _DEFAULT_PLOT2_SERIES_HOMODYNE

    def _series_order(self) -> list[str]:
        order = [key for key, _ in self._fixed_series()]
        order += [f"peak_{i}" for i in range(len(self._model_spec.peaks))]
        return order

    def _series_label(self, key: str) -> str:
        fixed = dict(_FIXED_SERIES_HOMODYNE + _FIXED_SERIES_HETERODYNE)
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
        default_plot1 = self._default_plot1_series()
        default_plot2 = self._default_plot2_series()
        new_assignment = {}
        new_styles = {}
        for key in order:
            if key in self._series_assignment:
                new_assignment[key] = self._series_assignment[key]
            elif key in default_plot2:
                new_assignment[key] = {"plot2"}
            elif key in default_plot1:
                new_assignment[key] = {"plot1"}
            else:
                new_assignment[key] = set()

            new_styles[key] = self._series_styles.get(key) or SeriesStyle(linestyle=_default_linestyle_for(key))
        self._series_assignment = new_assignment
        self._series_styles = new_styles

    def _build_display_section(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        display_note = QLabel("Pick which curves show on which plot area, and how they look:")
        display_note.setWordWrap(True)
        layout.addWidget(display_note)
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
        range_note = QLabel("Independent of the plots' own view zoom — shown as a shaded region on Plot 1.")
        range_note.setWordWrap(True)
        layout.addWidget(range_note)

        form = QFormLayout()
        layout.addLayout(form)

        self._weighting_combo = QComboBox()
        self._rebuild_weighting_combo()
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

    def _rebuild_weighting_combo(self):
        """Heterodyne mode has no "statistical" option -- homodyne's
        1/sqrt(intensity) shot-noise justification doesn't apply to
        signed Real/Imaginary values, so only "None" and the per-channel
        measurement-error mode are offered there."""
        combo = self._weighting_combo
        previous = combo.currentData()
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("None", userData="none")
        if self._data is not None and self._data.kind == "heterodyne":
            combo.addItem("Measurement error (95% CI, per channel)", userData="measurement_error")
        else:
            combo.addItem("Statistical (1/√intensity)", userData="statistical")
            combo.addItem("Measurement error (SEM)", userData="measurement_error")
        idx = combo.findData(previous)
        combo.setCurrentIndex(idx if idx >= 0 else 0)
        combo.blockSignals(False)

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
        weighting = self._weighting_combo.currentData()

        loading = show_loading(self, "Fitting...")
        try:
            if self._data.kind == "heterodyne":
                real = self._data.real[mask]
                imag = self._data.imag[mask]
                real_err = self._data.real_err[mask] if self._data.real_err is not None else None
                imag_err = self._data.imag_err[mask] if self._data.imag_err is not None else None
                weights_real, weights_imag = compute_heterodyne_weights(weighting, real, imag, real_err, imag_err)
                self._last_result = fit_heterodyne(
                    omega, real, imag, self._model_spec,
                    weights_real=weights_real, weights_imag=weights_imag,
                )
            else:
                intensity = self._data.intensity[mask]
                intensity_std = self._data.intensity_std[mask] if self._data.intensity_std is not None else None
                count = self._data.count[mask] if self._data.count is not None else None
                weights = compute_weights(weighting, intensity, intensity_std, count)
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
            if self._data.kind == "heterodyne":
                data = {"Wavenumber": self._data.omega, "Real": self._data.real, "Imaginary": self._data.imag}
                if self._data.real_err is not None:
                    data["Real_err"] = self._data.real_err
                if self._data.imag_err is not None:
                    data["Imag_err"] = self._data.imag_err
            else:
                data = {"Wavenumber": self._data.omega, "Intensity": self._data.intensity}
            df = pd.DataFrame(data)
            spectrum = ProcessedSpectrum(df, metadata={}, history=["loaded_from_file"], provenance={})

        weighting = self._weighting_combo.currentData()
        r = self._last_result
        fit_section = provenance.format_fit_section(
            self._model_spec.to_dict(), weighting, r.redchi, r.r_squared, r.aic, r.bic,
            kind=self._data.kind,
        )
        try:
            provenance.write_csv_with_provenance(
                spectrum, self._data.kind, self._data.label, Path(path_str), fit_section=fit_section,
            )
        except Exception as e:
            QMessageBox.warning(self, "Export failed", str(e))
            return
        QMessageBox.information(self, "Export complete", f"Fit exported to {path_str}")

    # ── Batch fit dock (independent mode) ───────────────────────────────────
    # Every selected spectrum is fit independently from the model
    # currently configured in the Model/Parameters docks -- no seeding,
    # order doesn't matter. See the Sequential fit dock below for the
    # seeded-chain mode.

    def _build_batch_section(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        label = QLabel(
            "Every spectrum in the list below is fit independently from "
            "the model currently configured in the Model/Parameters "
            "docks — order doesn't matter. Uses the Fit dock's current "
            "fit range and weighting. Right-click a row to remove it."
        )
        label.setWordWrap(True)
        layout.addWidget(label)

        self._batch_list = QListWidget()
        self._batch_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._batch_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._batch_list.customContextMenuRequested.connect(
            lambda pos: self._on_list_context_menu(self._batch_list, self._batch_file_entries, pos)
        )
        layout.addWidget(self._batch_list)

        load_files_btn = QPushButton("Load file(s)...")
        load_files_btn.clicked.connect(
            lambda: self._load_files_into(self._batch_list, self._batch_file_entries, checkable=False)
        )
        layout.addWidget(load_files_btn)

        self._run_batch_btn = QPushButton("Run batch fit")
        self._run_batch_btn.setEnabled(False)
        self._run_batch_btn.clicked.connect(self._on_run_batch_fit)
        layout.addWidget(self._run_batch_btn)
        return widget

    def _all_batch_entries(self) -> list:
        return _all_entries_in_order(self._batch_list)

    def _refresh_batch_controls(self):
        self._run_batch_btn.setEnabled(self._batch_list.count() >= 2)

    def _build_batch_datasets(self, entries: list) -> list[BatchDataset] | None:
        """Returns None (after warning the user) if any entry's columns
        can't be extracted -- shared by both Batch's and Sequential's
        run handlers."""
        datasets = []
        for e in entries:
            channels = _extract_channels(e.spectrum.data, preferred_kind=e.kind)
            if channels is None:
                QMessageBox.warning(
                    self, "Cannot fit this spectrum",
                    f"{e.label}: no Wavenumber/Intensity or Wavenumber/Real/Imaginary columns found.",
                )
                return None
            datasets.append(BatchDataset(label=e.label, **channels))
        return datasets

    def _run_progress_dialog(self, n: int, title: str) -> tuple[QProgressDialog, object]:
        """A determinate, cancelable progress dialog + its progress_cb,
        for a run that has no pause requirement (Batch, and Sequential
        when it has zero checkpoints) and so can be driven as one
        blocking call. A synchronous for-loop blocks the Qt event loop,
        so the Cancel button click is only ever queued, never
        processed, without the processEvents() call here."""
        dialog = QProgressDialog("Preparing...", "Cancel", 0, n, self)
        dialog.setWindowTitle(title)
        dialog.setWindowModality(Qt.WindowModality.WindowModal)
        dialog.setMinimumDuration(0)

        def progress_cb(i: int, total: int, label: str) -> bool:
            dialog.setLabelText(f"Fitting {i + 1} of {total}: {label}")
            dialog.setValue(i)
            QApplication.processEvents()
            return not dialog.wasCanceled()

        return dialog, progress_cb

    def _on_run_batch_fit(self):
        entries = self._all_batch_entries()
        if len(entries) < 2:
            return
        kinds = {e.kind for e in entries}
        if len(kinds) > 1:
            QMessageBox.warning(
                self, "Mixed spectrum kinds",
                "Batch fitting requires every spectrum in the list to be "
                f"the same kind (homodyne or heterodyne) -- got: {sorted(kinds)}.",
            )
            return
        datasets = self._build_batch_datasets(entries)
        if datasets is None:
            return

        fit_range = (self._fit_min_spin.value(), self._fit_max_spin.value())
        weighting = self._weighting_combo.currentData()
        self._batch_template = deepcopy(self._model_spec)
        self._batch_fit_range = fit_range
        self._batch_weighting = weighting
        self._batch_run_mode = "batch"

        dialog, progress_cb = self._run_progress_dialog(len(datasets), "Batch fit")
        try:
            results = fit_independent_batch(
                datasets, self._model_spec, weighting=weighting, fit_range=fit_range,
                progress_cb=progress_cb,
            )
        except Exception as e:
            dialog.close()
            QMessageBox.warning(self, "Batch fit failed", str(e))
            return
        dialog.close()

        n = len(results)
        self._batch_rows = list(zip(entries[:n], datasets[:n], results))
        self._batch_row_overrides = [None] * len(self._batch_rows)
        self._finish_multifit_run()

    # ── Sequential fit dock (seeded-chain mode) ─────────────────────────────
    # Each spectrum seeds from the previous one's converged result, in
    # list order -- drag to reorder. A per-row checkbox marks a
    # "checkpoint": the run pauses right after that spectrum fits,
    # loading it into the normal single-spectrum workspace so the user
    # can inspect it (and even retry via the existing "Run fit" button)
    # before continuing. Driven as an event-driven state machine
    # (self._sequential_run), not one blocking call, specifically so it
    # can pause -- see _advance_sequential_run().

    def _build_sequential_section(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        label = QLabel(
            "Every spectrum in the list below is fit, each one seeded "
            "from the previous one's converged fit, in list order — "
            "drag to reorder. Check a row to pause for review after "
            "that spectrum fits (a \"checkpoint\"). Uses the Fit dock's "
            "current fit range and weighting as the starting point. "
            "Right-click a row to remove it."
        )
        label.setWordWrap(True)
        layout.addWidget(label)

        self._sequential_list = QListWidget()
        self._sequential_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._sequential_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self._sequential_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._sequential_list.customContextMenuRequested.connect(
            lambda pos: self._on_list_context_menu(self._sequential_list, self._sequential_file_entries, pos)
        )
        layout.addWidget(self._sequential_list)

        load_files_btn = QPushButton("Load file(s)...")
        load_files_btn.clicked.connect(
            lambda: self._load_files_into(self._sequential_list, self._sequential_file_entries, checkable=True)
        )
        layout.addWidget(load_files_btn)

        checkpoint_row = QHBoxLayout()
        mark_all_btn = QPushButton("Mark all as checkpoints")
        mark_all_btn.clicked.connect(self._on_mark_all_checkpoints)
        checkpoint_row.addWidget(mark_all_btn, stretch=1)
        clear_all_btn = QPushButton("Clear all checkpoints")
        clear_all_btn.clicked.connect(self._on_clear_all_checkpoints)
        checkpoint_row.addWidget(clear_all_btn, stretch=1)
        layout.addLayout(checkpoint_row)

        self._run_sequential_btn = QPushButton("Run sequential fit")
        self._run_sequential_btn.setEnabled(False)
        self._run_sequential_btn.clicked.connect(self._on_run_sequential_fit)
        layout.addWidget(self._run_sequential_btn)

        run_control_row = QHBoxLayout()
        self._sequential_continue_btn = QPushButton("Continue to next spectrum")
        self._sequential_continue_btn.setEnabled(False)
        self._sequential_continue_btn.clicked.connect(self._on_sequential_continue)
        run_control_row.addWidget(self._sequential_continue_btn, stretch=1)
        self._sequential_stop_btn = QPushButton("Stop")
        self._sequential_stop_btn.setEnabled(False)
        self._sequential_stop_btn.clicked.connect(self._on_sequential_stop)
        run_control_row.addWidget(self._sequential_stop_btn, stretch=1)
        layout.addLayout(run_control_row)

        self._sequential_status_label = QLabel("")
        self._sequential_status_label.setWordWrap(True)
        layout.addWidget(self._sequential_status_label)
        return widget

    def _all_sequential_rows(self) -> list[tuple]:
        lw = self._sequential_list
        return [(lw.item(i).data(Qt.ItemDataRole.UserRole), lw.item(i).checkState() == Qt.CheckState.Checked)
                for i in range(lw.count())]

    def _on_mark_all_checkpoints(self):
        lw = self._sequential_list
        for i in range(lw.count()):
            lw.item(i).setCheckState(Qt.CheckState.Checked)

    def _on_clear_all_checkpoints(self):
        lw = self._sequential_list
        for i in range(lw.count()):
            lw.item(i).setCheckState(Qt.CheckState.Unchecked)

    def _refresh_sequential_controls(self):
        active = self._sequential_run is not None
        paused = active and self._sequential_run.get("paused", False)
        self._run_sequential_btn.setEnabled(not active and self._sequential_list.count() >= 2)
        self._sequential_continue_btn.setEnabled(paused)
        self._sequential_stop_btn.setEnabled(active)
        if paused:
            self._sequential_status_label.setText(
                "Paused at a checkpoint — inspect/retry above, then Continue or Stop."
            )
        elif active:
            self._sequential_status_label.setText("Running…")
        else:
            self._sequential_status_label.setText("")

    def _on_run_sequential_fit(self):
        rows = self._all_sequential_rows()
        if len(rows) < 2:
            return
        entries = [e for e, _ in rows]
        kinds = {e.kind for e in entries}
        if len(kinds) > 1:
            QMessageBox.warning(
                self, "Mixed spectrum kinds",
                "Sequential fitting requires every spectrum in the list to "
                f"be the same kind (homodyne or heterodyne) -- got: {sorted(kinds)}.",
            )
            return
        datasets = self._build_batch_datasets(entries)
        if datasets is None:
            return
        queue = [(e, ds, is_cp) for (e, is_cp), ds in zip(rows, datasets)]

        fit_range = (self._fit_min_spin.value(), self._fit_max_spin.value())
        weighting = self._weighting_combo.currentData()
        self._batch_template = deepcopy(self._model_spec)
        self._batch_fit_range = fit_range
        self._batch_weighting = weighting
        self._batch_run_mode = "sequential"
        self._batch_rows = []
        self._batch_row_overrides = []

        if not any(is_cp for _e, _ds, is_cp in queue):
            # nothing to pause for -- run straight through with the same
            # blocking-progress-dialog pattern Batch uses.
            dialog, progress_cb = self._run_progress_dialog(len(datasets), "Sequential fit")
            try:
                results = fit_sequential_batch(
                    datasets, self._model_spec, weighting=weighting, fit_range=fit_range,
                    progress_cb=progress_cb,
                )
            except Exception as e:
                dialog.close()
                QMessageBox.warning(self, "Sequential fit failed", str(e))
                return
            dialog.close()
            n = len(results)
            self._batch_rows = list(zip(entries[:n], datasets[:n], results))
            self._batch_row_overrides = [None] * len(self._batch_rows)
            self._finish_multifit_run()
            return

        self._sequential_run = {
            "queue": queue, "index": 0,
            "current_spec": deepcopy(self._model_spec),
            "fit_range": fit_range, "weighting": weighting,
            "paused": False, "stop_requested": False,
        }
        self._refresh_sequential_controls()
        self._advance_sequential_run()

    def _advance_sequential_run(self):
        """Fits exactly one queued dataset, then either pauses (a
        checkpoint, or the queue is now empty) or schedules the next
        step via QTimer.singleShot(0, ...) -- NOT a tight loop with
        processEvents(). This event-driven chaining makes Stop take
        effect between every dataset (checked once at the top here),
        not just at checkpoints, and avoids the reentrancy risk of
        calling processEvents() from inside a long-running call."""
        run = self._sequential_run
        if run is None:
            return
        if run["stop_requested"] or run["index"] >= len(run["queue"]):
            self._finish_sequential_run()
            return

        entry, dataset, is_checkpoint = run["queue"][run["index"]]
        result = fit_one_dataset(dataset, run["current_spec"], run["weighting"], run["fit_range"])
        self._batch_rows.append((entry, dataset, result))
        self._batch_row_overrides.append(None)
        self._append_multifit_row(len(self._batch_rows) - 1)
        run["current_spec"] = advance_seed(run["current_spec"], result)
        run["index"] += 1
        at_end = run["index"] >= len(run["queue"])

        if is_checkpoint and not at_end:
            run["paused"] = True
            if result is not None:
                preset = {
                    "model_spec": result.spec, "last_result": result,
                    "fit_range": run["fit_range"], "weighting": run["weighting"],
                }
                self._load_from_processed_spectrum(entry.spectrum, entry.label, kind=entry.kind, preset=preset)
            self._refresh_sequential_controls()
            return

        if at_end:
            if result is not None:
                preset = {
                    "model_spec": result.spec, "last_result": result,
                    "fit_range": run["fit_range"], "weighting": run["weighting"],
                }
                self._load_from_processed_spectrum(entry.spectrum, entry.label, kind=entry.kind, preset=preset)
            self._finish_sequential_run()
            return

        QTimer.singleShot(0, self._advance_sequential_run)

    def _on_sequential_continue(self):
        run = self._sequential_run
        if run is None or not run.get("paused"):
            return
        entry, dataset, original_result = self._batch_rows[-1]
        if original_result is not None:
            # pick up any live edit/retry the user made at the checkpoint
            # (e.g. via the existing "Run fit" button) as the seed/
            # recorded result for what's about to continue --
            # self._model_spec/_last_result reflect whatever's currently
            # in the workspace, which is exactly the point.
            self._batch_rows[-1] = (entry, dataset, self._last_result)
            self._update_multifit_row(len(self._batch_rows) - 1)
            retried_range = (self._fit_min_spin.value(), self._fit_max_spin.value())
            retried_weighting = self._weighting_combo.currentData()
            if retried_range != run["fit_range"] or retried_weighting != run["weighting"]:
                self._batch_row_overrides[-1] = {"fit_range": retried_range, "weighting": retried_weighting}
            run["current_spec"] = deepcopy(self._model_spec)
        run["paused"] = False
        self._refresh_sequential_controls()
        QTimer.singleShot(0, self._advance_sequential_run)

    def _on_sequential_stop(self):
        run = self._sequential_run
        if run is None:
            return
        run["stop_requested"] = True
        if run["paused"]:
            self._finish_sequential_run()
        # else: a non-checkpoint stretch is mid-chain via QTimer.singleShot;
        # the next _advance_sequential_run() call will see stop_requested
        # and finish there.

    def _finish_sequential_run(self):
        self._sequential_run = None
        self._refresh_sequential_controls()
        self._finish_multifit_run()

    # ── Multi-fit results dock (shared by Batch and Sequential) ────────────

    def _build_multifit_results_section(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        self._multifit_status_label = QLabel("No batch or sequential run yet.")
        layout.addWidget(self._multifit_status_label)

        self._multifit_table = QTableWidget(0, 4)
        self._multifit_table.setHorizontalHeaderLabels(["Label", "Status", "redchi", "R²"])
        self._multifit_table.verticalHeader().setVisible(False)
        self._multifit_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._multifit_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._multifit_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._multifit_table.cellDoubleClicked.connect(lambda row, _col: self._on_multifit_row_activated(row))
        layout.addWidget(self._multifit_table)
        multifit_note = QLabel("Double-click a row to inspect that spectrum's fit in the workspace above.")
        multifit_note.setWordWrap(True)
        layout.addWidget(multifit_note)

        view_row = QHBoxLayout()
        view_row.addWidget(QLabel("View:"))
        self._multifit_view_combo = QComboBox()
        self._multifit_view_combo.addItem("Trend", userData="trend")
        self._multifit_view_combo.addItem("Overlay", userData="overlay")
        self._multifit_view_combo.currentIndexChanged.connect(self._on_multifit_view_changed)
        view_row.addWidget(self._multifit_view_combo)
        view_row.addWidget(QLabel("Parameter:"))
        self._multifit_param_combo = QComboBox()
        self._multifit_param_combo.currentIndexChanged.connect(lambda _i: self._update_multifit_plot())
        view_row.addWidget(self._multifit_param_combo, stretch=1)
        layout.addLayout(view_row)

        export_btn = QPushButton("Export batch summary (CSV)")
        export_btn.clicked.connect(self._on_export_batch_summary)
        layout.addWidget(export_btn)
        return widget

    def _on_multifit_view_changed(self, _index: int):
        self._multifit_param_combo.setEnabled(self._multifit_view_combo.currentData() == "trend")
        self._update_multifit_plot()

    def _update_multifit_row(self, row: int):
        entry, _dataset, result = self._batch_rows[row]
        table = self._multifit_table
        table.setItem(row, 0, _readonly_item(entry.label))
        if result is None:
            status_item = _readonly_item("✗ failed")
            status_item.setToolTip("An exception was raised while fitting this spectrum.")
            table.setItem(row, 1, status_item)
            table.setItem(row, 2, _readonly_item(""))
            table.setItem(row, 3, _readonly_item(""))
            return
        status_text = "✓ converged" if result.success else "⚠ did not converge"
        status_item = _readonly_item(status_text)
        status_item.setToolTip(result.message or "")
        table.setItem(row, 1, status_item)
        table.setItem(row, 2, _readonly_item(f"{result.redchi:.4g}"))
        table.setItem(row, 3, _readonly_item(f"{result.r_squared:.4f}"))

    def _append_multifit_row(self, row: int):
        if self._multifit_table.rowCount() <= row:
            self._multifit_table.setRowCount(row + 1)
        self._update_multifit_row(row)

    def _populate_multifit_table(self):
        self._multifit_table.setRowCount(len(self._batch_rows))
        for row in range(len(self._batch_rows)):
            self._update_multifit_row(row)

    def _finish_multifit_run(self):
        self._populate_multifit_table()
        mode_label = "Batch fit" if self._batch_run_mode == "batch" else "Sequential fit"
        self._multifit_status_label.setText(f"Showing: {mode_label} of {len(self._batch_rows)} spectra")
        self._rebuild_multifit_param_combo()
        self._update_multifit_plot()

    def _rebuild_multifit_param_combo(self):
        combo = self._multifit_param_combo
        previous = combo.currentData()
        combo.blockSignals(True)
        combo.clear()
        if self._batch_template is not None:
            for key, label in self._batch_param_columns(self._batch_template):
                combo.addItem(label, userData=key)
        idx = combo.findData(previous)
        combo.setCurrentIndex(idx if idx >= 0 else 0)
        combo.blockSignals(False)

    def _on_multifit_row_activated(self, row: int):
        if row < 0 or row >= len(self._batch_rows):
            return
        entry, _dataset, result = self._batch_rows[row]
        if result is None:
            QMessageBox.information(
                self, "No result", "This spectrum's fit did not complete — nothing to inspect.",
            )
            return
        override = self._batch_row_overrides[row] if row < len(self._batch_row_overrides) else None
        fit_range = override["fit_range"] if override else self._batch_fit_range
        weighting = override["weighting"] if override else self._batch_weighting
        preset = {"model_spec": result.spec, "last_result": result, "fit_range": fit_range, "weighting": weighting}
        self._load_from_processed_spectrum(entry.spectrum, entry.label, kind=entry.kind, preset=preset)

    def _batch_param_columns(self, template: FitModelSpec) -> list[tuple[tuple, str]]:
        columns = []
        for name in template.nonresonant:
            columns.append((("nr", name), f"Non-resonant {name.capitalize()}"))
        for i, peak in enumerate(template.peaks):
            ls = get_lineshape(peak.lineshape_key)
            for p in ls.params:
                columns.append((("peak", i, p.name), f"Peak {i + 1} {p.display_name}"))
        return columns

    def _update_multifit_plot(self):
        self.plot_widget3.full_clear()
        ax = self.plot_widget3.ax   # full_clear() recreates the Axes -- fetch it fresh
        if self._batch_rows:
            if self._multifit_view_combo.currentData() == "overlay":
                self._draw_multifit_overlay(ax)
            else:
                self._draw_multifit_trend(ax)
        self.plot_widget3.canvas.draw_idle()

    def _draw_multifit_trend(self, ax):
        key = self._multifit_param_combo.currentData()
        if key is None:
            return
        labels, values, errors = [], [], []
        for _entry, _dataset, result in self._batch_rows:
            labels.append(_entry.label)
            pr = None if result is None else result.param_results.get(_lmfit_key(key))
            values.append(pr.value if pr is not None else np.nan)
            errors.append(pr.stderr if (pr is not None and pr.stderr is not None) else 0.0)
        x = np.arange(len(labels))
        ax.errorbar(x, values, yerr=errors, fmt="o-", capsize=3)
        ax.set_xticks(x)
        ax.set_xticklabels(labels, rotation=45, ha="right")
        ax.set_ylabel(self._multifit_param_combo.currentText())
        ax.set_xlabel("Spectrum")

    def _draw_multifit_overlay(self, ax):
        # Heterodyne rows show the real-part comparison only, as a
        # simplification -- enough to eyeball fit quality across a
        # series without doubling the number of curves drawn here.
        max_legend = 8
        for i, (entry, dataset, result) in enumerate(self._batch_rows):
            if result is None:
                continue
            omega = dataset.omega
            label = entry.label if i < max_legend else None
            if dataset.kind == "heterodyne":
                data_y = dataset.real
                fit_y = evaluate_chi(omega, result.spec).real
            else:
                data_y = dataset.intensity
                fit_y = evaluate_homodyne(omega, result.spec)
            data_line, = ax.plot(omega, data_y, marker=".", markersize=2, linestyle="none", alpha=0.5)
            fit_line, = ax.plot(omega, fit_y, label=label)
            data_line.set_color(fit_line.get_color())
        ax.set_xlabel("Wavenumber (cm$^{-1}$)")
        ax.set_ylabel("Intensity / χ_eff (real part, a.u.)")
        if ax.get_legend_handles_labels()[0]:
            ax.legend(fontsize=7)

    def _on_export_batch_summary(self):
        if not self._batch_rows:
            QMessageBox.information(self, "Nothing to export", "Run a batch or sequential fit first.")
            return
        path_str, _ = QFileDialog.getSaveFileName(
            self, "Export batch summary", "batch_fit_summary.csv", "CSV files (*.csv)",
        )
        if not path_str:
            return

        param_columns = self._batch_param_columns(self._batch_template)
        rows = []
        for i, (entry, _dataset, result) in enumerate(self._batch_rows):
            override = self._batch_row_overrides[i] if i < len(self._batch_row_overrides) else None
            if result is None:
                status = "failed"
            elif result.success:
                status = "converged"
            else:
                status = "did not converge"
            row = {
                "Label": entry.label, "Kind": entry.kind, "Status": status,
                "redchi": None if result is None else result.redchi,
                "r_squared": None if result is None else result.r_squared,
                "aic": None if result is None else result.aic,
                "bic": None if result is None else result.bic,
            }
            if override is not None:
                row["Fit range override"] = f"{override['fit_range'][0]:g}-{override['fit_range'][1]:g}"
                row["Weighting override"] = override["weighting"]
            for key, label in param_columns:
                pr = None if result is None else result.param_results.get(_lmfit_key(key))
                row[label] = None if pr is None else pr.value
                row[f"{label} stderr"] = None if pr is None else pr.stderr
            rows.append(row)
        df = pd.DataFrame(rows)

        batch_payload = {
            "mode": self._batch_run_mode,
            "template": self._batch_template.to_dict(),
            "fit_range": self._batch_fit_range,
            "weighting": self._batch_weighting,
            "kind": self._batch_rows[0][0].kind,
            "labels": [entry.label for entry, _dataset, _result in self._batch_rows],
        }
        header_lines = [
            "# SFG-App batch fit summary",
            f"# Exported:    {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "#",
            f"# Batch json: {json.dumps(batch_payload)}",
            "#",
        ]
        try:
            with open(path_str, "w", newline="", encoding="utf-8") as f:
                for line in header_lines:
                    f.write(line + "\n")
                df.to_csv(f, index=False)
        except Exception as e:
            QMessageBox.warning(self, "Export failed", str(e))
            return
        QMessageBox.information(self, "Export complete", f"Batch summary exported to {path_str}")

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
        self._update_multifit_plot()   # also recreates plot_widget3's Axes fresh

    def _schedule_preview(self):
        self._preview_timer.start()

    def _compute_series_values(self) -> dict[str, np.ndarray]:
        omega = self._data.omega
        chi = evaluate_chi(omega, self._model_spec)   # reused unmodified in both modes
        if self._data.kind == "heterodyne":
            values = {
                "data_real": self._data.real,
                "data_imag": self._data.imag,
                "fit_real": chi.real,
                "fit_imag": chi.imag,
                "residual_real": self._data.real - chi.real,
                "residual_imag": self._data.imag - chi.imag,
            }
        else:
            total = evaluate_homodyne(omega, self._model_spec)
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
        kwargs = {"marker": ".", "markersize": 3} if key in ("data", "data_real", "data_imag") else {}
        style = self._series_styles.get(key) or SeriesStyle(linestyle=_default_linestyle_for(key))
        kwargs["linestyle"] = style.linestyle
        if style.color is not None:
            kwargs["color"] = style.color
        return kwargs

    def _ylabel_for(self, plot_id: str) -> str:
        keys = {k for k, plots in self._series_assignment.items() if plot_id in plots}
        if keys and keys <= {"residual", "residual_real", "residual_imag"}:
            return "Residual (a.u.)"
        if keys and keys <= {"fit_real", "fit_imag", "data_real", "data_imag"}:
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
