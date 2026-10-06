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
from PySide6.QtGui import QColor, QBrush, QPalette, QUndoStack, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QComboBox, QGroupBox,
    QPushButton, QCheckBox, QDoubleSpinBox, QLineEdit, QTableWidget, QRadioButton,
    QTableWidgetItem, QHeaderView, QSizePolicy, QFileDialog, QMessageBox, QButtonGroup,
    QInputDialog, QColorDialog, QListWidget, QListWidgetItem, QAbstractItemView,
    QProgressDialog, QApplication, QMenu, QSplitter, QFrame,
)

from sfg_app2.app.widgets.spectrum_plot_widget import SpectrumPlotWidget
from sfg_app2.app.widgets.dockable_panels import DockablePlotPanel
from sfg_app2.app.utils.fit_template_manager import FitTemplateManager
from sfg_app2.app.utils import color_coding, recent_paths_settings
from sfg_app2.app.tabs.fitting import job as jobmod
from sfg_app2.app.tabs.fitting.job import FitJob, JobSpectrum
from sfg_app2.app.tabs.fitting.job_bar import JobBar, Popover
from sfg_app2.app.tabs.fitting.results_view import ResultsView, ResultRow, ResultColumn, OK, WARN, FAIL
from sfg_app2.processing import provenance
from sfg_app2.processing.processed_spectrum import ProcessedSpectrum
from sfg_app2.processing.fitting import (
    FitParam, FitModelSpec, default_peak, estimate_peak_seed,
    evaluate_conventional, evaluate_chi, evaluate_peak_component,
    fit_conventional, fit_phase_resolved, compute_weights, compute_phase_resolved_weights,
    available_lineshapes, get_lineshape, fit_model_spec_from_provenance_payload,
    BatchDataset, fit_sequential_batch, fit_independent_batch, fit_one_dataset, advance_seed,
    fit_global_batch, fit_polarization_set, apply_sign_constraints, restore_amplitude_bounds,
)
from sfg_app2.app.tabs.fitting_tab_undo import (
    AddPeakCommand, ApplyTemplateCommand, EditParamCommand, RemovePeakCommand,
    ReplaceModelSpecCommand, RunBatchFitCommand, RunFitCommand,
)

logger = logging.getLogger(__name__)

(_COL_LABEL, _COL_PARAM, _COL_VALUE, _COL_ERROR, _COL_MIN, _COL_MAX,
 _COL_FIXED, _COL_SHARED, _COL_EXPR) = range(9)
_PEAK_COL_INDEX, _PEAK_COL_CENTER, _PEAK_COL_LINESHAPE, _PEAK_COL_REMOVE = range(4)
(_DISPLAY_COL_LABEL, _DISPLAY_COL_PLOT1, _DISPLAY_COL_PLOT2,
 _DISPLAY_COL_COLOR, _DISPLAY_COL_LINESTYLE) = range(5)

# Chip order in the job bar.
_CHIP_SPECTRA, _CHIP_MODEL, _CHIP_STRATEGY, _CHIP_FIT = range(4)

# Fixed series always available for plotting, in display order; peak_{i}
# series are appended dynamically, one per current peak. The set differs
# by mode (conventional fits a single intensity channel; phase-resolved fits
# Real/Imaginary simultaneously, so there's no single "total"/"residual"
# curve) -- _series_order()/_sync_series_assignment() pick the right one
# based on self._data.kind. "fit_real"/"fit_imag" keys (and their labels)
# are shared verbatim across both modes: in conventional mode they're a
# diagnostic overlay of the model's complex chi_eff; in phase-resolved mode
# they're the actual fitted curves against data_real/data_imag.
_FIXED_SERIES_CONVENTIONAL = [
    ("data", "Data"),
    ("fit_total", "Fit (total)"),
    ("fit_real", "Fit (real)"),
    ("fit_imag", "Fit (imaginary)"),
    ("residual", "Residual"),
]
_FIXED_SERIES_PHASE_RESOLVED = [
    ("data_real", "Data (real)"),
    ("data_imag", "Data (imaginary)"),
    ("fit_real", "Fit (real)"),
    ("fit_imag", "Fit (imaginary)"),
    ("residual_real", "Residual (real)"),
    ("residual_imag", "Residual (imaginary)"),
]
# Residuals start on Plot 2, so a fit's quality is visible without
# opening the curves settings; peaks start hidden.
_DEFAULT_PLOT1_SERIES_CONVENTIONAL = {"data", "fit_total"}
_DEFAULT_PLOT2_SERIES_CONVENTIONAL = {"residual"}
_DEFAULT_PLOT1_SERIES_PHASE_RESOLVED = {"data_real", "data_imag", "fit_real", "fit_imag"}
_DEFAULT_PLOT2_SERIES_PHASE_RESOLVED = {"residual_real", "residual_imag"}

# (display name, matplotlib linestyle code) -- "None" gives markers only,
# which is Data's own default look.
_LINESTYLE_OPTIONS = [
    ("Solid", "-"), ("Dashed", "--"), ("Dash-dot", "-."), ("Dotted", ":"), ("None (markers only)", "none"),
]
_LINESTYLE_CODE_TO_LABEL = {code: label for label, code in _LINESTYLE_OPTIONS}

_MODE_RUN_NAMES = {
    jobmod.INDEPENDENT: "Independent fit",
    jobmod.SEQUENTIAL: "Sequential fit",
    jobmod.GLOBAL: "Global fit",
}


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


def _note(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet("color: palette(mid);")
    return label


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


def _format_sign_rules(signs: dict[str, str]) -> str:
    """"ppp −, ssp +" -- the Parameters table's inline summary."""
    return ", ".join(f"{pol} {'−' if rule == '-' else rule}" for pol, rule in sorted(signs.items()))


def _lmfit_key(key: tuple) -> str:
    if key[0] == "nr":
        return f"nr_{key[1]}"
    _, i, name = key
    return f"p{i}_{name}"


def _extract_conventional_channels(df) -> dict | None:
    if "Wavenumber" not in df.columns or "Intensity" not in df.columns:
        return None
    omega = df["Wavenumber"].to_numpy(dtype=float)
    intensity = df["Intensity"].to_numpy(dtype=float)
    intensity_std = df["Intensity_std"].to_numpy(dtype=float) if "Intensity_std" in df.columns else None
    count = df["count"].to_numpy(dtype=float) if "count" in df.columns else None
    order = np.argsort(omega)
    return dict(
        kind="conventional", omega=omega[order], intensity=intensity[order],
        intensity_std=intensity_std[order] if intensity_std is not None else None,
        count=count[order] if count is not None else None,
    )


def _extract_phase_resolved_channels(df) -> dict | None:
    if not {"Wavenumber", "Real", "Imaginary"}.issubset(df.columns):
        return None
    omega = df["Wavenumber"].to_numpy(dtype=float)
    real = df["Real"].to_numpy(dtype=float)
    imag = df["Imaginary"].to_numpy(dtype=float)
    real_err = df["Real_err"].to_numpy(dtype=float) if "Real_err" in df.columns else None
    imag_err = df["Imag_err"].to_numpy(dtype=float) if "Imag_err" in df.columns else None
    order = np.argsort(omega)
    return dict(
        kind="phase_resolved", omega=omega[order], real=real[order], imag=imag[order],
        real_err=real_err[order] if real_err is not None else None,
        imag_err=imag_err[order] if imag_err is not None else None,
    )


def _extract_channels(df, preferred_kind: str | None = None) -> dict | None:
    """Try the preferred kind first (from a Results-tab entry's own kind,
    or a loaded file's provenance Type: header), then fall back to
    whichever column set actually matches -- mirrors
    processed_results.py's own kind-detection fallback chain."""
    extractors = {"conventional": _extract_conventional_channels, "phase_resolved": _extract_phase_resolved_channels}
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
    sits in the fit job exactly like a Spectra Library entry.
    eq=False keeps identity-based equality: two separate loads are always
    distinct entries, never coalesced by value."""
    label: str
    spectrum: object   # a ProcessedSpectrum
    kind: str


def _entry_display_text(entry) -> str:
    prefix = "[phase-resolved] " if entry.kind == "phase_resolved" else ""
    return f"{prefix}{entry.label}"


@dataclass
class _FittableSpectrum:
    label: str
    omega: np.ndarray
    kind: str                            # "conventional" | "phase_resolved"
    # conventional channel:
    intensity: np.ndarray | None = None
    intensity_std: np.ndarray | None = None
    count: np.ndarray | None = None
    # phase-resolved channels:
    real: np.ndarray | None = None
    imag: np.ndarray | None = None
    real_err: np.ndarray | None = None
    imag_err: np.ndarray | None = None
    source_spectrum: object | None = None   # the ProcessedSpectrum it came from
    fit_json_payload: dict | None = None    # a previous fit's payload, if it carried one
    metadata: dict | None = None


# Keys parse_export_header() adds on its own, not the user's metadata
# fields -- never offered as a "Polarization field" choice.
_HEADER_ONLY_METADATA_KEYS = {"label", "exported", "source_filename"}


def _user_metadata(meta: dict) -> dict:
    return {k: v for k, v in meta.items() if k not in _HEADER_ONLY_METADATA_KEYS and v is not None}


def _load_entry_from_file(path: Path) -> _FileLoadedEntry:
    """Raises ValueError with a user-facing message when the file can't
    be fit."""
    df = provenance.load_csv_skip_comments(path)
    _, prov, meta = provenance.parse_export_header(path)
    channels = _extract_channels(df, preferred_kind=prov.get("kind"))
    if channels is None:
        raise ValueError("no Wavenumber/Intensity or Wavenumber/Real/Imaginary columns found.")
    spectrum = ProcessedSpectrum(df, metadata=_user_metadata(meta), history=["loaded_from_file"],
                                 provenance=prov)
    return _FileLoadedEntry(label=meta.get("label", path.stem), spectrum=spectrum, kind=channels["kind"])


class FittingTab(QWidget, DockablePlotPanel):
    """Peak fitting via processing.fitting (lmfit-based, Qt-free).

    The tab reads as one fit *job*, laid out as a row of numbered chips
    (see fitting/job_bar.py): ① which spectra, ② the model, ③ how to fit
    several spectra (independent / sequential / global), ④ fit range and
    weighting, then one Fit button that says exactly what it will do.
    Below it, the workspace shows the reference spectrum with the
    starting model (Plot + Parameters docks), and the Results dock
    tabulates a multi-spectrum run; selecting a result row *views* that
    fit in the workspace without touching the starting model.

    Two data kinds, auto-selected per spectrum: conventional
    (|chi_NR*e^{i.phi} + sum_j resonance_j(omega)|^2 fit against measured
    intensity) and phase-resolved (Re/Im of the same complex chi_eff fit
    simultaneously against measured Real/Imaginary data).
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        self._results_provider = None
        self._display_settings = None
        self._job = FitJob()
        self._data: _FittableSpectrum | None = None
        self._model_spec: FitModelSpec = FitModelSpec.empty()
        self._series_assignment: dict[str, set[str]] = {}
        self._series_styles: dict[str, SeriesStyle] = {}
        self._last_result = None
        self._param_row_keys: list[tuple] = []
        self._display_row_keys: list[str] = []
        self._placement_armed = False
        self._template_manager = FitTemplateManager()
        # Set while a result row is shown in the workspace: {"row": int,
        # "saved": the starting state to return to}. See _enter_view().
        self._view: dict | None = None

        # Multi-spectrum results. _batch_rows holds (entry, BatchDataset,
        # FitResult|None) triples in run order; _batch_row_overrides is a
        # parallel list of {"fit_range", "weighting"}|None for rows refit
        # with different settings than the run's. _batch_template/
        # _fit_range/_weighting/_run_mode are captured at run time so a
        # later edit to the live controls doesn't retroactively change
        # what the export/view reproduce.
        self._batch_rows: list[tuple] = []
        self._batch_row_overrides: list[dict | None] = []
        self._batch_template: FitModelSpec | None = None
        self._batch_fit_range: tuple[float, float] | None = None
        self._batch_weighting: str | None = None
        self._batch_run_mode: str | None = None   # jobmod.INDEPENDENT | SEQUENTIAL | GLOBAL
        self._batch_global_result = None
        self._batch_shared_keys: list[str] = []
        self._undo_stack = QUndoStack(self)
        self._pending_undo_snapshot: tuple | None = None

        # Sequential run state machine -- see _run_sequential(). None
        # outside of an active/paused run.
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

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(4, 4, 4, 4)
        main_layout.setSpacing(4)

        warning_banner = QLabel(
            "⚠ Fitting is experimental — results should be independently verified."
        )
        warning_banner.setStyleSheet(
            "background-color: #fff3cd; color: #664d03; border: 1px solid #ffeeba; padding: 2px 4px;"
        )
        main_layout.addWidget(warning_banner)

        self._job_bar = JobBar()
        self._job_bar.add_chip("Spectra", "① Spectra to fit", self._build_spectra_section())
        self._job_bar.add_chip("Model", "② Model", self._build_model_section())
        self._job_bar.add_chip("Strategy", "③ How to fit several spectra", self._build_strategy_section())
        self._job_bar.add_chip("Fit settings", "④ Fit range and weighting", self._build_fit_section())
        self._job_bar.fit_clicked.connect(self._on_fit_clicked)
        self._job_bar.continue_clicked.connect(self._on_sequential_continue)
        self._job_bar.stop_clicked.connect(self._on_sequential_stop)
        self._job_bar.popover_closed.connect(self._refresh_job_bar)
        self._job_bar.tour_finished.connect(self._on_tour_finished)
        main_layout.addWidget(self._job_bar)

        self._init_dock_area()
        self._add_dock("plot", "Plot", self._build_plot_section(), fill=True,
                       tabify=False, area=Qt.DockWidgetArea.LeftDockWidgetArea)
        self._add_dock("parameters", "Parameters", self._build_parameters_section(), fill=True,
                       tabify=False, area=Qt.DockWidgetArea.RightDockWidgetArea)
        self.results_view = ResultsView()
        self.results_view.row_selected.connect(self._on_result_row_selected)
        self.results_view.refit_requested.connect(self._refit_rows)
        self.results_view.use_as_start_requested.connect(self._use_row_as_start)
        self.results_view.remove_requested.connect(self._remove_result_rows_from_job)
        self.results_view.export_requested.connect(self._on_export_batch_summary)
        self.results_view.send_requested.connect(self._send_rows_to_library)
        self.results_view.overlay_requested.connect(self._draw_overlay)
        self._add_dock("results", "Results", self.results_view, fill=True,
                       tabify=False, area=Qt.DockWidgetArea.BottomDockWidgetArea)
        main_layout.addWidget(self._dock_main_window)
        # Workspace first: the plot gets most of the height, results a strip.
        self._dock_main_window.resizeDocks(
            [self._docks["plot"], self._docks["parameters"]], [650, 450], Qt.Orientation.Horizontal)
        self._dock_main_window.resizeDocks(
            [self._docks["plot"], self._docks["results"]], [700, 230], Qt.Orientation.Vertical)
        self._layout_applied = False

        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, activated=self._stop_placement)

        self._job_bar.set_tour_steps([
            (self._job_bar.chip(_CHIP_SPECTRA),
             "① Pick the spectra to fit — from the Spectra Library or from files. One of them, "
             "marked ★, is shown in the workspace and is the one you build the model on."),
            (self._job_bar.chip(_CHIP_MODEL),
             "② Build the model: turn on “Add peaks” and click the plot where peaks are. "
             "Templates and per-polarization sign rules live here too."),
            (self._job_bar.chip(_CHIP_STRATEGY),
             "③ With several spectra, choose how to fit them: independently, in sequence "
             "(each fit seeds the next), or globally with shared peak positions/widths."),
            (self._job_bar.chip(_CHIP_FIT),
             "④ Optional: restrict the fit range and choose the weighting."),
            (self._job_bar.fit_button,
             "Then press Fit — its label always says what will run. Results of a "
             "multi-spectrum fit appear in the Results table below: select a row to view "
             "that fit, right-click a column to plot its trend."),
        ])

        self._plot_data()
        self._rebuild_peak_table()
        self._rebuild_parameter_table()
        self._rebuild_display_table()
        self._update_quality_readout()
        self._refresh_job_bar()
        self._update_view_pill()

    # ── Public API — called by MainWindow ───────────────────────────────────

    @property
    def undo_stack(self) -> QUndoStack:
        return self._undo_stack

    def set_results_provider(self, provider):
        """`provider` is the ProcessedResultsTab instance (duck-typed:
        needs .entries(kind=...), and .add_fitted_spectrum() for "Send to
        Spectra Library") -- set once from MainWindow."""
        self._results_provider = provider

    def set_display_settings(self, settings):
        """`settings` is a FittingDisplaySettings instance, set once from
        MainWindow: peak-row coloring, and whether the first-use tour has
        been shown."""
        self._display_settings = settings
        self._apply_peak_row_colors()

    def refresh_peak_coloring(self):
        self._apply_peak_row_colors()

    def restore_dock_state(self, data: bytes | None):
        super().restore_dock_state(data)
        self._layout_applied = bool(data)

    def showEvent(self, event):
        super().showEvent(event)
        if not self._layout_applied:
            # resizeDocks() before the first show only sees nominal sizes;
            # re-apply the default proportions against the real window.
            self._layout_applied = True
            h = max(self._dock_main_window.height(), 400)
            w = max(self._dock_main_window.width(), 600)
            self._dock_main_window.resizeDocks(
                [self._docks["plot"], self._docks["results"]], [int(h * 0.72), int(h * 0.28)],
                Qt.Orientation.Vertical)
            self._dock_main_window.resizeDocks(
                [self._docks["plot"], self._docks["parameters"]], [int(w * 0.58), int(w * 0.42)],
                Qt.Orientation.Horizontal)
        if (self._display_settings is not None and not self._display_settings.tour_seen
                and not self._job_bar.tour_active()):
            QTimer.singleShot(300, self._job_bar.start_tour)

    def _on_tour_finished(self):
        if self._display_settings is not None and not self._display_settings.tour_seen:
            self._display_settings.tour_seen = True
            self._display_settings.save()

    def statusBar_message(self, msg: str):
        try:
            self.window().statusBar().showMessage(msg)
        except Exception:
            pass

    # ── Job bar ──────────────────────────────────────────────────────────────

    def _weighting_label(self) -> str:
        text = self._weighting_combo.currentText()
        return text.split(" (")[0] if text else "None"

    def _refresh_job_bar(self):
        bar = self._job_bar
        job = self._job
        bar.set_chip(_CHIP_SPECTRA, job.spectra_summary(), needs_attention=not job.spectra)
        if self._view is not None:
            model_text = "viewing a result"
        else:
            model_text = jobmod.model_summary(self._model_spec)
        bar.set_chip(_CHIP_MODEL, model_text,
                     needs_attention=bool(job.spectra) and not self._model_spec.peaks and self._view is None)
        bar.set_chip(_CHIP_STRATEGY, job.strategy_summary(self._model_spec),
                     needs_attention=(job.effective_mode() == jobmod.GLOBAL
                                      and not jobmod.any_shared(self._model_spec)))
        fit_range = None
        if self._data is not None:
            lo, hi = self._fit_min_spin.value(), self._fit_max_spin.value()
            full = (float(self._data.omega.min()), float(self._data.omega.max()))
            if not (np.isclose(lo, full[0]) and np.isclose(hi, full[1])):
                fit_range = (lo, hi)
        bar.set_chip(_CHIP_FIT, jobmod.fit_settings_summary(fit_range, self._weighting_label()))

        problems = job.problems()
        if not problems and not self._model_spec.peaks:
            problems = ["Add at least one peak in ② Model."]
        if self._sequential_run is not None:
            return   # the bar is showing the paused run's controls
        bar.set_fit_label(job.run_label(), enabled=not problems, why_disabled=" ".join(problems))
        self._refresh_strategy_section()
        self._refresh_spectra_list_decorations()
        self._update_shared_column_visibility()

    # ── ① Spectra ────────────────────────────────────────────────────────────

    def _build_spectra_section(self) -> QWidget:
        widget = QWidget()
        widget.setMinimumWidth(420)
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)

        buttons = QHBoxLayout()
        add_lib_btn = QPushButton("Add from library…")
        add_lib_btn.setToolTip("Choose spectra from the Spectra Library")
        add_lib_btn.clicked.connect(self._on_add_from_library)
        add_file_btn = QPushButton("Add file(s)…")
        add_file_btn.clicked.connect(self._on_add_files)
        buttons.addWidget(add_lib_btn)
        buttons.addWidget(add_file_btn)
        buttons.addStretch()
        layout.addLayout(buttons)

        self._job_list = QListWidget()
        self._job_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._job_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self._job_list.setMinimumHeight(180)
        self._job_list.model().rowsMoved.connect(lambda *_a: self._sync_job_order_from_list())
        self._job_list.itemDoubleClicked.connect(
            lambda item: self._set_reference(self._job_list.row(item)))
        self._job_list.itemChanged.connect(self._on_job_item_changed)
        self._job_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._job_list.customContextMenuRequested.connect(self._on_job_list_menu)
        layout.addWidget(self._job_list)

        row = QHBoxLayout()
        ref_btn = QPushButton("★ Show in workspace")
        ref_btn.setToolTip("Make the selected spectrum the reference: shown in the plot, used to build the model")
        ref_btn.clicked.connect(lambda: self._set_reference(self._job_list.currentRow()))
        remove_btn = QPushButton("Remove")
        remove_btn.clicked.connect(lambda: self._remove_from_job(
            [self._job_list.row(i) for i in self._job_list.selectedItems()]))
        row.addWidget(ref_btn)
        row.addWidget(remove_btn)
        row.addStretch()
        layout.addLayout(row)
        self._spectra_hint = _note(
            "★ marks the spectrum shown in the workspace — build the model on it. "
            "Double-click a spectrum to show it instead."
        )
        layout.addWidget(self._spectra_hint)
        return widget

    def _rebuild_job_list(self):
        lw = self._job_list
        lw.blockSignals(True)
        lw.clear()
        for s in self._job.spectra:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, s)
            lw.addItem(item)
        lw.blockSignals(False)
        self._refresh_spectra_list_decorations()

    def _refresh_spectra_list_decorations(self):
        """Text (★, sequence numbers) and pause checkboxes depend on the
        mode, so they are redrawn whenever the job changes."""
        lw = self._job_list
        mode = self._job.effective_mode()
        marked = mode == jobmod.SEQUENTIAL and self._job.pause == jobmod.PAUSE_MARKED
        lw.blockSignals(True)
        for i in range(lw.count()):
            item = lw.item(i)
            s = item.data(Qt.ItemDataRole.UserRole)
            star = "★ " if i == self._job.reference else "    "
            number = f"{i + 1}. " if mode == jobmod.SEQUENTIAL else ""
            item.setText(f"{star}{number}{_entry_display_text(s.entry)}")
            flags = item.flags()
            if marked:
                item.setFlags(flags | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked if s.pause else Qt.CheckState.Unchecked)
                item.setToolTip("Tick to pause for review after this spectrum is fit")
            else:
                item.setFlags(flags & ~Qt.ItemFlag.ItemIsUserCheckable)
                item.setData(Qt.ItemDataRole.CheckStateRole, None)
                item.setToolTip("")
        lw.blockSignals(False)
        if mode == jobmod.SEQUENTIAL:
            self._spectra_hint.setText("Spectra are fit in this order — drag to reorder. "
                                       "★ = shown in the workspace (double-click to change).")
        else:
            self._spectra_hint.setText("★ marks the spectrum shown in the workspace — build the model on it. "
                                       "Double-click a spectrum to show it instead.")

    def _on_job_item_changed(self, item: QListWidgetItem):
        s = item.data(Qt.ItemDataRole.UserRole)
        if s is not None and item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
            s.pause = item.checkState() == Qt.CheckState.Checked

    def _sync_job_order_from_list(self):
        ref = self._job.reference_entry()
        self._job.spectra = [self._job_list.item(i).data(Qt.ItemDataRole.UserRole)
                             for i in range(self._job_list.count())]
        self._job.reference = next((i for i, s in enumerate(self._job.spectra) if s.entry is ref), 0)
        self._refresh_job_bar()

    def _on_job_list_menu(self, pos):
        item = self._job_list.itemAt(pos)
        if item is None:
            return
        row = self._job_list.row(item)
        menu = QMenu(self)
        show = menu.addAction("★ Show in workspace")
        remove = menu.addAction("Remove from job")
        chosen = menu.exec(self._job_list.mapToGlobal(pos))
        if chosen is show:
            self._set_reference(row)
        elif chosen is remove:
            rows = [self._job_list.row(i) for i in self._job_list.selectedItems()] if item.isSelected() else [row]
            self._remove_from_job(rows)

    def add_entries_to_job(self, entries: list) -> int:
        """Adds entries (skipping ones already in the job); the first
        spectrum ever added becomes the reference. Returns how many were
        added."""
        if not self._confirm_abandon_paused_sequential_run("Changing the job's spectra"):
            return 0
        was_empty = not self._job.spectra
        added = sum(1 for e in entries if self._job.add(e))
        if added:
            self._rebuild_job_list()
            self._refresh_polarization_combo()
            if was_empty:
                self._set_reference(0)
            self._refresh_job_bar()
        return added

    def _on_add_from_library(self):
        from sfg_app2.app.tabs.fitting.library_picker import LibraryPickerDialog
        entries = self._results_provider.entries(kind=None) if self._results_provider is not None else []
        if not entries:
            QMessageBox.information(
                self, "Spectra Library is empty",
                "Nothing in the Spectra Library yet — process a spectrum or load one there first, "
                "or use “Add file(s)…”.",
            )
            return
        self._job_bar.close_popovers()
        dialog = LibraryPickerDialog(entries, self._job.entries(), self)
        if dialog.exec() == LibraryPickerDialog.DialogCode.Accepted:
            self.add_entries_to_job(dialog.selected_entries())
        if self.isVisible():
            self._job_bar.open_popover(_CHIP_SPECTRA)

    def _on_add_files(self):
        self._job_bar.close_popovers()
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Add spectra", recent_paths_settings.get_last_dir("fitting"),
            "CSV files (*.csv);;All files (*.*)",
        )
        if paths:
            recent_paths_settings.remember_dir("fitting", paths[0])
            entries = []
            for path_str in paths:
                path = Path(path_str)
                try:
                    entries.append(_load_entry_from_file(path))
                except Exception as e:
                    QMessageBox.warning(self, "Could not load file", f"{path.name}: {e}")
            self.add_entries_to_job(entries)
        if self.isVisible():
            self._job_bar.open_popover(_CHIP_SPECTRA)

    def _remove_from_job(self, rows: list[int]):
        rows = [r for r in rows if r >= 0]
        if not rows or not self._confirm_abandon_paused_sequential_run("Changing the job's spectra"):
            return
        old_ref = self._job.reference_entry()
        self._job.remove(rows)
        self._rebuild_job_list()
        self._refresh_polarization_combo()
        new_ref = self._job.reference_entry()
        if new_ref is not old_ref:
            if new_ref is None:
                self._leave_view()
                self._data = None
                self._last_result = None
                self._plot_data()
                self._update_quality_readout()
            else:
                self._set_reference(self._job.reference)
        self._refresh_job_bar()

    def _set_reference(self, row: int):
        if not (0 <= row < len(self._job.spectra)):
            return
        if not self._confirm_abandon_paused_sequential_run():
            return
        self._leave_view()
        self._job.reference = row
        entry = self._job.spectra[row].entry
        self._load_entry_into_workspace(entry)
        self._refresh_spectra_list_decorations()
        self._refresh_job_bar()

    def _load_entry_into_workspace(self, entry) -> bool:
        """Show `entry` as the workspace spectrum. The starting model is
        kept -- it's the job's model, meant for every spectrum -- except
        that an empty model is prefilled from a fit the spectrum already
        carries (a reloaded fit export)."""
        channels = _extract_channels(entry.spectrum.data, preferred_kind=entry.kind)
        if channels is None:
            QMessageBox.warning(
                self, "Cannot fit this spectrum",
                f"{entry.label}: no Wavenumber/Intensity or Wavenumber/Real/Imaginary columns found — "
                "has it been averaged and upconverted?",
            )
            return False
        prov = getattr(entry.spectrum, "provenance", None) or {}
        previous_kind = self._data.kind if self._data is not None else None
        previous_range = (self._fit_min_spin.value(), self._fit_max_spin.value()) if self._data else None
        self._data = _FittableSpectrum(
            label=entry.label, source_spectrum=entry.spectrum,
            fit_json_payload=provenance.parse_fit_json(prov),
            metadata=_user_metadata(entry.spectrum.metadata or {}), **channels,
        )
        if not self._model_spec.peaks:
            prefill = None
            if self._data.fit_json_payload:
                prefill = fit_model_spec_from_provenance_payload(self._data.fit_json_payload)
            if prefill is not None:
                self._model_spec = prefill
                self.statusBar_message(f"Restored a previous fit from {entry.label}'s provenance.")
            else:
                self._model_spec = FitModelSpec.empty()
                if self._data.kind == "phase_resolved":
                    # phase is degenerate with the peaks' own phase/amplitude
                    # in conventional mode (only |chi|^2 is measured), so it's
                    # fixed there by default -- but fitting Re/Im directly
                    # constrains it well, so let it vary here.
                    self._model_spec.nonresonant["phase"].vary = True
            self._last_result = None
        elif previous_kind is not None and previous_kind != self._data.kind:
            self._last_result = None
        self._rebuild_weighting_combo()
        if previous_kind != self._data.kind:
            self._series_assignment = {}

        lo, hi = float(self._data.omega.min()), float(self._data.omega.max())
        if previous_range is not None and previous_range[1] > previous_range[0]:
            # keep the user's fit range if it still overlaps this spectrum
            p_lo, p_hi = previous_range
            if p_hi > lo and p_lo < hi:
                lo, hi = max(lo, p_lo), min(hi, p_hi)
        self._set_fit_range(lo, hi)

        self._plot_data()
        self._rebuild_peak_table()
        self._rebuild_parameter_table()
        self._rebuild_display_table()
        self._apply_fit_result_to_table()
        self._update_quality_readout()
        self._schedule_preview()
        return True

    def _load_from_processed_spectrum(self, spectrum, label: str, kind: str = "conventional"):
        """Make `spectrum` the job's reference (adding it if needed) --
        the programmatic equivalent of picking one spectrum."""
        for i, s in enumerate(self._job.spectra):
            if s.entry.spectrum is spectrum:
                self._set_reference(i)
                return
        self.add_entries_to_job([_FileLoadedEntry(label=label, spectrum=spectrum, kind=kind)])
        self._set_reference(len(self._job.spectra) - 1)

    def _confirm_abandon_paused_sequential_run(self, action: str = "Loading a different spectrum") -> bool:
        """True if it's OK to proceed with something that abandons a
        paused sequential run (asks the user)."""
        if self._sequential_run is not None and self._sequential_run.get("paused"):
            reply = QMessageBox.question(
                self, "Sequential run paused",
                f"A sequential fit is paused for review — {action.lower()} "
                "ends it; the spectra fitted so far are kept. Continue anyway?",
            )
            if reply != QMessageBox.StandardButton.Yes:
                return False
            self._finish_sequential_run()
        return True

    # ── ② Model ──────────────────────────────────────────────────────────────

    def _build_model_section(self) -> QWidget:
        widget = QWidget()
        widget.setMinimumWidth(460)
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)

        self._model_view_note = _note("You are viewing a fit result — go “Back to starting model” "
                                      "(Parameters panel) to change the model.")
        self._model_view_note.setVisible(False)
        layout.addWidget(self._model_view_note)

        self._model_controls = QWidget()
        mc = QVBoxLayout(self._model_controls)
        mc.setContentsMargins(0, 0, 0, 0)

        row = QHBoxLayout()
        row.addWidget(QLabel("New peaks:"))
        self._lineshape_combo = QComboBox()
        for ls in available_lineshapes():
            self._lineshape_combo.addItem(ls.display_name, userData=ls.key)
        row.addWidget(self._lineshape_combo)
        self._add_peak_btn = QPushButton("Add peaks")
        self._add_peak_btn.setCheckable(True)
        self._add_peak_btn.setToolTip(
            "Turn on, then click the plot at each peak. Ctrl+click seeds a negative "
            "amplitude. Right-click, Esc or this button again to stop."
        )
        self._add_peak_btn.toggled.connect(self._on_add_peak_toggled)
        row.addWidget(self._add_peak_btn)
        row.addStretch()
        mc.addLayout(row)

        self._nonresonant_check = QCheckBox("Non-resonant background")
        self._nonresonant_check.setChecked(True)
        self._nonresonant_check.toggled.connect(self._on_nonresonant_toggled)
        mc.addWidget(self._nonresonant_check)

        self._peak_table = QTableWidget(0, 4)
        self._peak_table.setHorizontalHeaderLabels(["Peak", "Center", "Lineshape", ""])
        self._peak_table.verticalHeader().setVisible(False)
        self._peak_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._peak_table.setMinimumHeight(140)
        mc.addWidget(self._peak_table)

        sign_box = QGroupBox("Amplitude sign rules (optional)")
        sign_layout = QHBoxLayout(sign_box)
        sign_layout.addWidget(QLabel("Polarization field:"))
        self._polarization_combo = QComboBox()
        self._polarization_combo.addItem("(none)", userData=None)
        self._polarization_combo.setToolTip(
            "The metadata field that tells spectra of different polarization combinations "
            "apart. It selects each spectrum's amplitude sign rules, in every kind of fit."
        )
        self._polarization_combo.currentIndexChanged.connect(lambda _i: self._refresh_sign_rules_button())
        sign_layout.addWidget(self._polarization_combo)
        self._sign_rules_btn = QPushButton("Sign rules…")
        self._sign_rules_btn.setToolTip("Force a peak's amplitude to be positive, negative or free, per polarization.")
        self._sign_rules_btn.clicked.connect(self._on_sign_constraints)
        sign_layout.addWidget(self._sign_rules_btn)
        sign_layout.addStretch()
        mc.addWidget(sign_box)

        template_box = QGroupBox("Templates")
        tl = QHBoxLayout(template_box)
        self._template_combo = QComboBox()
        self._refresh_template_combo()
        tl.addWidget(self._template_combo, stretch=1)
        apply_btn = QPushButton("Apply")
        apply_btn.setToolTip("Replace the model (and fit range/weighting) with this template")
        apply_btn.clicked.connect(self._on_apply_template)
        tl.addWidget(apply_btn)
        save_template_btn = QPushButton("Save as…")
        save_template_btn.setToolTip("Save the current model, fit range and weighting as a template")
        save_template_btn.clicked.connect(self._on_save_template)
        tl.addWidget(save_template_btn)
        manage_templates_btn = QPushButton("Manage…")
        manage_templates_btn.clicked.connect(self._on_manage_templates)
        tl.addWidget(manage_templates_btn)
        mc.addWidget(template_box)

        layout.addWidget(self._model_controls)
        return widget

    def _on_add_peak_toggled(self, checked: bool):
        self._placement_armed = checked
        if checked:
            self._job_bar.close_popovers()
            self._add_peak_btn.setText("Adding peaks… (click to stop)")
            self.plot_widget.canvas.setCursor(Qt.CursorShape.CrossCursor)
            self.statusBar_message("Click the plot at each peak (Ctrl+click: negative amplitude). "
                                   "Right-click or Esc to stop.")
        else:
            self._add_peak_btn.setText("Add peaks")
            self.plot_widget.canvas.setCursor(Qt.CursorShape.ArrowCursor)
            self.statusBar_message("")
        self._update_placement_banner()

    def _stop_placement(self):
        if self._placement_armed:
            self._add_peak_btn.setChecked(False)

    def _on_plot_click(self, event):
        if not self._placement_armed:
            return
        if event.inaxes != self.plot_widget.ax:
            return
        if event.button == 3:   # right-click stops placement
            self._add_peak_btn.setChecked(False)
            return
        if event.button != 1 or event.xdata is None:
            return
        negative = bool(QApplication.keyboardModifiers() & Qt.KeyboardModifier.ControlModifier)
        self._add_peak_at(event.xdata, negative_amplitude=negative)

    def _add_peak_at(self, center: float, negative_amplitude: bool = False):
        if self._data is None or self._view is not None:
            return
        lineshape_key = self._lineshape_combo.currentData()
        omega = self._data.omega
        idx = int(np.argmin(np.abs(omega - center)))

        # Estimate against the residual (data minus what's already
        # modeled), not the raw data -- otherwise an existing peak's/the
        # background's contribution gets counted as if it belonged to
        # the new peak (see estimate_peak_seed's docstring).
        if self._data.kind == "phase_resolved":
            chi_existing = evaluate_chi(omega, self._model_spec)
            residual = np.hypot(self._data.real - chi_existing.real,
                                 self._data.imag - chi_existing.imag)
            amplitude, width = estimate_peak_seed(omega, residual, idx, squared=False)
        else:
            model_existing = evaluate_conventional(omega, self._model_spec)
            residual = self._data.intensity - model_existing
            amplitude, width = estimate_peak_seed(omega, residual, idx, squared=True)

        if negative_amplitude:
            amplitude = -amplitude

        peak = default_peak(lineshape_key, center=float(center), amplitude=amplitude, width=width)
        # A new peak joins the model with the same sharing as its
        # siblings, so a global job keeps sharing peak shapes.
        if self._job.effective_mode() == jobmod.GLOBAL:
            for group in ("center", "width"):
                if jobmod.share_state(self._model_spec, group) is True:
                    for name, fp in peak.params.items():
                        if (group == "center") == (name == "center") and name != "amplitude":
                            fp.shared = True
        self._undo_stack.push(AddPeakCommand(self, peak))

    def _on_nonresonant_toggled(self, checked: bool):
        nr = self._model_spec.nonresonant
        if checked:
            nr["amplitude"].vary = True
            if nr["amplitude"].value == 0.0:
                nr["amplitude"].value = 0.1
        else:
            nr["amplitude"].vary = False
            nr["amplitude"].value = 0.0
            nr["phase"].vary = False
        self._rebuild_parameter_table()
        self._schedule_preview()
        self._refresh_job_bar()

    def _rebuild_peak_table(self):
        table = self._peak_table
        table.setRowCount(len(self._model_spec.peaks))
        keys = [ls.key for ls in available_lineshapes()]
        for i, peak in enumerate(self._model_spec.peaks):
            table.setItem(i, _PEAK_COL_INDEX, _readonly_item(f"Peak {i + 1}"))
            center = peak.params.get("center")
            table.setItem(i, _PEAK_COL_CENTER, _readonly_item("" if center is None else f"{center.value:.1f}"))

            combo = QComboBox()
            for ls in available_lineshapes():
                combo.addItem(ls.display_name, userData=ls.key)
            combo.setCurrentIndex(max(keys.index(peak.lineshape_key) if peak.lineshape_key in keys else 0, 0))
            combo.currentIndexChanged.connect(
                lambda _idx, row=i, c=combo: self._on_change_peak_lineshape(row, c.currentData()))
            table.setCellWidget(i, _PEAK_COL_LINESHAPE, combo)

            remove_btn = QPushButton("Remove")
            remove_btn.clicked.connect(lambda _checked=False, row=i: self._on_remove_peak(row))
            table.setCellWidget(i, _PEAK_COL_REMOVE, remove_btn)
        self._apply_peak_row_colors()
        self._refresh_job_bar()

    def _on_change_peak_lineshape(self, row: int, lineshape_key: str):
        if not (0 <= row < len(self._model_spec.peaks)):
            return
        old = self._model_spec.peaks[row]
        if old.lineshape_key == lineshape_key:
            return
        values = {name: fp.value for name, fp in old.params.items()}
        new_peak = default_peak(lineshape_key, center=values.get("center", 0.0),
                                amplitude=values.get("amplitude", 1.0), width=values.get("width", 10.0))
        new_peak.amplitude_signs = dict(old.amplitude_signs)
        for name, fp in new_peak.params.items():
            if name in old.params:
                fp.shared = old.params[name].shared
        new = deepcopy(self._model_spec)
        new.peaks[row] = new_peak
        self._undo_stack.push(ReplaceModelSpecCommand(self, self._model_spec, new, "Change lineshape"))
        self._rebuild_peak_table()
        self._rebuild_display_table()

    def _on_remove_peak(self, row: int):
        if 0 <= row < len(self._model_spec.peaks):
            self._undo_stack.push(RemovePeakCommand(self, row, self._model_spec.peaks[row]))

    # sign rules (part of the model: saved in templates and exports)

    def _refresh_polarization_combo(self):
        """Offers the metadata fields present on the job's spectra. Keeps
        the current choice; a field whose name starts with "pol" is picked
        automatically the first time it appears, unless the user already
        chose one."""
        combo = self._polarization_combo
        current = combo.currentData()
        previous_keys = {combo.itemData(i) for i in range(combo.count())}
        keys = set()
        for entry in self._job.entries():
            keys.update(_user_metadata(entry.spectrum.metadata or {}))
        keys = sorted(keys, key=str.lower)

        selected = current
        if current is None:
            selected = next((k for k in keys if k.lower().startswith("pol") and k not in previous_keys), None)
        if current is not None and current not in keys:
            keys.append(current)   # keep a choice whose spectra were removed

        combo.blockSignals(True)
        combo.clear()
        combo.addItem("(none)", userData=None)
        for k in keys:
            combo.addItem(k, userData=k)
        combo.setCurrentIndex(max(combo.findData(selected), 0) if selected is not None else 0)
        combo.blockSignals(False)
        self._refresh_sign_rules_button()

    def _refresh_sign_rules_button(self):
        self._sign_rules_btn.setEnabled(self._polarization_combo.currentData() is not None)

    def _batch_polarization_values(self) -> list[str]:
        """Distinct polarization values over the job's spectra, in
        first-seen order."""
        values = []
        for entry in self._job.entries():
            pol = self._polarization_of(entry.spectrum.metadata or {})
            if pol is not None and pol not in values:
                values.append(pol)
        return values

    def _on_sign_constraints(self):
        from sfg_app2.app.dialogs.sign_constraints_dialog import SignConstraintsDialog

        key = self._polarization_combo.currentData()
        if key is None:
            return
        if not self._model_spec.peaks:
            QMessageBox.information(self, "No peaks", "Add peaks to the model first.")
            return
        values = self._batch_polarization_values()
        for peak in self._model_spec.peaks:
            values += [pol for pol in peak.amplitude_signs if pol not in values]
        if not values:
            QMessageBox.information(
                self, "No polarizations found",
                f"No spectrum in the job has a \"{key}\" value.",
            )
            return
        self._job_bar.close_popovers()
        dialog = SignConstraintsDialog(self._model_spec, values, key, self)
        if dialog.exec() == SignConstraintsDialog.DialogCode.Accepted:
            self._apply_sign_rules(dialog.rules())

    def _apply_sign_rules(self, rules: list[dict[str, str]]):
        new = deepcopy(self._model_spec)
        for peak, signs in zip(new.peaks, rules):
            peak.amplitude_signs = dict(signs)
        if new != self._model_spec:
            self._undo_stack.push(ReplaceModelSpecCommand(self, self._model_spec, new, "Set amplitude sign rules"))

    def _data_polarization(self) -> str | None:
        if self._data is None:
            return None
        if self._data.metadata is not None:
            metadata = self._data.metadata
        elif self._data.source_spectrum is not None:
            metadata = self._data.source_spectrum.metadata
        else:
            metadata = {}
        return self._polarization_of(metadata)

    def _polarization_of(self, metadata: dict) -> str | None:
        key = self._polarization_combo.currentData()
        if not key or metadata.get(key) in (None, ""):
            return None
        return str(metadata[key])

    # templates

    def _refresh_template_combo(self):
        self._template_combo.clear()
        self._template_combo.addItems(self._template_manager.names())

    def _on_save_template(self):
        self._job_bar.close_popovers()
        name, ok = QInputDialog.getText(self, "Save fit template", "Template name:")
        if not ok or not name.strip():
            return
        fit_range = (self._fit_min_spin.value(), self._fit_max_spin.value())
        weighting = self._weighting_combo.currentData()
        if not self._template_manager.set(name.strip(), self._model_spec, fit_range, weighting):
            QMessageBox.warning(
                self, "Couldn't save template",
                "The fit template could not be saved to disk. "
                "It will be available for this session but won't persist.",
            )
        self._refresh_template_combo()

    def _on_apply_template(self):
        name = self._template_combo.currentText()
        if not name:
            return
        full = self._template_manager.get_full(name)
        if full is None:
            return
        unknown = [p.lineshape_key for p in full["spec"].peaks
                   if p.lineshape_key not in {ls.key for ls in available_lineshapes()}]
        if unknown:
            QMessageBox.warning(
                self, "Can't apply this template",
                f"It uses a lineshape this version doesn't have: "
                f"{', '.join(sorted(set(unknown)))}.",
            )
            return
        before = {
            "spec": self._model_spec, "result": self._last_result,
            "fit_range": (self._fit_min_spin.value(), self._fit_max_spin.value()),
            "weighting": self._weighting_combo.currentData(),
        }
        after = {
            "spec": full["spec"], "result": None,
            "fit_range": full["fit_range"], "weighting": full["weighting"],
        }
        self._undo_stack.push(ApplyTemplateCommand(self, before, after))

    def _on_manage_templates(self):
        from sfg_app2.app.dialogs.template_manager_dialog import TemplateManagerDialog
        self._job_bar.close_popovers()
        dlg = TemplateManagerDialog(self._template_manager, self)
        dlg.exec()
        self._refresh_template_combo()

    # ── ③ Strategy ───────────────────────────────────────────────────────────

    def _build_strategy_section(self) -> QWidget:
        widget = QWidget()
        widget.setMinimumWidth(460)
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)

        self._strategy_single_note = _note(
            "Fitting one spectrum. Add more spectra in ① to fit several at once — "
            "the choices below then apply."
        )
        layout.addWidget(self._strategy_single_note)

        self._mode_group = QButtonGroup(self)
        self._mode_radios: dict[str, QRadioButton] = {}
        for mode in jobmod.MULTI_MODES:
            radio = QRadioButton(jobmod.MODE_LABELS[mode])
            radio.setStyleSheet("font-weight: bold;")
            self._mode_group.addButton(radio)
            self._mode_radios[mode] = radio
            layout.addWidget(radio)
            layout.addWidget(_note(jobmod.MODE_DESCRIPTIONS[mode]))
            radio.toggled.connect(lambda checked, m=mode: checked and self._on_mode_chosen(m))

            if mode == jobmod.SEQUENTIAL:
                self._sequential_options = QWidget()
                so = QFormLayout(self._sequential_options)
                so.setContentsMargins(24, 0, 0, 6)
                self._pause_combo = QComboBox()
                for key, label in jobmod.PAUSE_LABELS.items():
                    self._pause_combo.addItem(label, userData=key)
                self._pause_combo.setToolTip(
                    "Pause after a spectrum is fit so you can check it (and refit it) before the "
                    "sequence continues from it. “At marked spectra”: tick them in ①."
                )
                self._pause_combo.currentIndexChanged.connect(self._on_pause_changed)
                so.addRow("Pause for review:", self._pause_combo)
                layout.addWidget(self._sequential_options)
            elif mode == jobmod.GLOBAL:
                self._global_options = QWidget()
                go = QVBoxLayout(self._global_options)
                go.setContentsMargins(24, 0, 0, 6)
                go.addWidget(QLabel("Share across all spectra:"))
                share_row = QHBoxLayout()
                self._share_checks: dict[str, QCheckBox] = {}
                for group, label in jobmod.SHARE_GROUPS:
                    check = QCheckBox(label)
                    check.setTristate(False)
                    check.clicked.connect(lambda checked, g=group: self._on_share_group_toggled(g, checked))
                    self._share_checks[group] = check
                    share_row.addWidget(check)
                share_row.addStretch()
                go.addLayout(share_row)
                go.addWidget(_note("Fine-tune per parameter with the Shared ⇄ column in the Parameters panel."))
                self._seed_amplitudes_check = QCheckBox("Seed amplitudes per spectrum")
                self._seed_amplitudes_check.setChecked(True)
                self._seed_amplitudes_check.setToolTip(
                    "Before the joint fit, solve each spectrum's own amplitudes with the shared peak "
                    "shapes held fixed, then start the joint fit from those -- for spectra whose "
                    "amplitudes differ a lot (e.g. polarizations of one sample). The joint fit also "
                    "runs from the plain starting model, and the better of the two is kept."
                )
                self._seed_amplitudes_check.toggled.connect(self._on_seed_amplitudes_toggled)
                go.addWidget(self._seed_amplitudes_check)
                layout.addWidget(self._global_options)

        self._mode_radios[self._job.mode].setChecked(True)
        return widget

    def _on_mode_chosen(self, mode: str):
        if self._job.mode == mode:
            return
        self._job.mode = mode
        if (mode == jobmod.GLOBAL and self._model_spec.peaks
                and not jobmod.any_shared(self._model_spec) and self._view is None):
            # the common case, as a starting point: shared peak shapes
            self._on_share_peak_shapes()
        self._refresh_job_bar()

    def _on_pause_changed(self, _index: int):
        self._job.pause = self._pause_combo.currentData()
        self._refresh_job_bar()

    def _on_seed_amplitudes_toggled(self, checked: bool):
        self._job.seed_amplitudes = checked

    def _on_share_group_toggled(self, group: str, checked: bool):
        if self._view is not None:
            return
        new = deepcopy(self._model_spec)
        jobmod.set_share(new, group, checked)
        if new != self._model_spec:
            label = dict(jobmod.SHARE_GROUPS)[group].lower()
            self._undo_stack.push(ReplaceModelSpecCommand(
                self, self._model_spec, new, f"{'Share' if checked else 'Unshare'} {label}"))

    def _refresh_strategy_section(self):
        single = len(self._job.spectra) < 2
        self._strategy_single_note.setVisible(single)
        for radio in self._mode_radios.values():
            radio.setEnabled(not single)
        self._sequential_options.setEnabled(not single and self._job.mode == jobmod.SEQUENTIAL)
        self._global_options.setEnabled(not single and self._job.mode == jobmod.GLOBAL)
        for group, check in self._share_checks.items():
            state = jobmod.share_state(self._model_spec, group)
            check.blockSignals(True)
            check.setTristate(state is None)
            check.setCheckState(Qt.CheckState.PartiallyChecked if state is None
                                else Qt.CheckState.Checked if state else Qt.CheckState.Unchecked)
            check.blockSignals(False)

    def _on_share_peak_shapes(self):
        """Every peak's non-amplitude parameters (center, width,
        gauss_width, ...) Shared; amplitudes and the non-resonant terms per
        spectrum -- the usual global setup for spectra of one sample."""
        new = deepcopy(self._model_spec)
        for fp in new.nonresonant.values():
            fp.shared = False
        for peak in new.peaks:
            for name, fp in peak.params.items():
                fp.shared = name != "amplitude"
        if new != self._model_spec:
            self._undo_stack.push(ReplaceModelSpecCommand(self, self._model_spec, new, "Share peak shapes"))

    def _shared_param_keys(self, spec: FitModelSpec) -> list[str]:
        """Local lmfit-style keys ("nr_amplitude", "p0_width", ...) of
        every parameter marked Shared -- only used by a Global job."""
        keys = [f"nr_{name}" for name, fp in spec.nonresonant.items() if fp.shared]
        for i, peak in enumerate(spec.peaks):
            keys += [f"p{i}_{name}" for name, fp in peak.params.items() if fp.shared]
        return keys

    # ── ④ Fit settings ───────────────────────────────────────────────────────

    def _build_fit_section(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)

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
        range_row.addWidget(QLabel("cm⁻¹"))
        layout.addLayout(range_row)

        btn_row = QHBoxLayout()
        self._set_fit_range_to_view_btn = QPushButton("Use current plot view")
        self._set_fit_range_to_view_btn.setToolTip("Set the fit range to Plot 1's current zoomed x-axis view.")
        self._set_fit_range_to_view_btn.clicked.connect(self._on_set_fit_range_to_view)
        full_btn = QPushButton("Full range")
        full_btn.clicked.connect(self._on_full_fit_range)
        btn_row.addWidget(self._set_fit_range_to_view_btn)
        btn_row.addWidget(full_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)
        layout.addWidget(_note("Shown as a shaded band on Plot 1. Applies to every spectrum in the job."))

        form = QFormLayout()
        self._weighting_combo = QComboBox()
        self._rebuild_weighting_combo()
        self._weighting_combo.currentIndexChanged.connect(lambda _i: self._refresh_job_bar())
        form.addRow("Weighting:", self._weighting_combo)
        layout.addLayout(form)
        return widget

    def _rebuild_weighting_combo(self):
        """Phase-resolved mode has no "statistical" option -- conventional
        fitting's 1/sqrt(intensity) shot-noise justification doesn't apply
        to signed Real/Imaginary values."""
        combo = self._weighting_combo
        previous = combo.currentData()
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("None", userData="none")
        if self._data is not None and self._data.kind == "phase_resolved":
            combo.addItem("Measurement error (95% CI, per channel)", userData="measurement_error")
        else:
            combo.addItem("Statistical (1/√intensity)", userData="statistical")
            combo.addItem("Measurement error (SEM)", userData="measurement_error")
        idx = combo.findData(previous)
        combo.setCurrentIndex(idx if idx >= 0 else 0)
        combo.blockSignals(False)

    def _set_fit_range(self, lo: float, hi: float):
        for spin in (self._fit_min_spin, self._fit_max_spin):
            spin.blockSignals(True)
        self._fit_min_spin.setValue(lo)
        self._fit_max_spin.setValue(hi)
        for spin in (self._fit_min_spin, self._fit_max_spin):
            spin.blockSignals(False)
        self._on_fit_range_changed()

    def _fit_mask(self) -> np.ndarray:
        lo, hi = self._fit_min_spin.value(), self._fit_max_spin.value()
        return (self._data.omega >= lo) & (self._data.omega <= hi)

    def _on_fit_range_changed(self, *_args):
        self._schedule_preview()
        self._refresh_job_bar()

    def _on_set_fit_range_to_view(self):
        x_range = self.plot_widget.get_x_range()
        if x_range is not None:
            self._set_fit_range(*x_range)

    def _on_full_fit_range(self):
        if self._data is not None:
            self._set_fit_range(float(self._data.omega.min()), float(self._data.omega.max()))

    # ── Plot dock ────────────────────────────────────────────────────────────

    def _build_plot_section(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        self._placement_banner = QLabel("")
        self._placement_banner.setStyleSheet("color: palette(highlight); font-weight: bold;")
        bar.addWidget(self._placement_banner)
        bar.addStretch()
        self._plot2_check = QCheckBox("Show Plot 2")
        self._plot2_check.setChecked(True)
        self._plot2_check.setToolTip("A second plot below (residuals by default)")
        self._plot2_check.toggled.connect(self.plot_widget2.setVisible)
        bar.addWidget(self._plot2_check)
        self._curves_btn = QPushButton("Curves…")
        self._curves_btn.setToolTip("Choose which curves show on Plot 1 and Plot 2, and their style")
        bar.addWidget(self._curves_btn)
        layout.addLayout(bar)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self.plot_widget)
        splitter.addWidget(self.plot_widget2)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter)

        self._curves_popover = Popover("Curves on Plot 1 / Plot 2", self._build_display_section(), self)
        self._curves_btn.clicked.connect(
            lambda: self._curves_popover.hide() if self._curves_popover.isVisible()
            else self._curves_popover.show_below(self._curves_btn))
        return widget

    def _update_placement_banner(self):
        self._placement_banner.setText(
            "Click the plot to add peaks · Ctrl+click: negative · Esc/right-click: stop"
            if self._placement_armed else "")

    # ── Parameters dock ──────────────────────────────────────────────────────

    def _build_parameters_section(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)

        self._pill = QFrame()
        self._pill.setFrameShape(QFrame.Shape.StyledPanel)
        pill = QHBoxLayout(self._pill)
        pill.setContentsMargins(6, 3, 6, 3)
        self._pill_label = QLabel()
        self._pill_label.setWordWrap(True)
        pill.addWidget(self._pill_label, stretch=1)
        self._refit_view_btn = QPushButton("Refit this spectrum")
        self._refit_view_btn.setToolTip("Fit this spectrum again from the values shown, and update its row")
        self._refit_view_btn.clicked.connect(self._refit_viewed_row)
        self._use_view_btn = QPushButton("Use as starting model")
        self._use_view_btn.setToolTip("Copy these values into the starting model (undoable)")
        self._use_view_btn.clicked.connect(lambda: self._view and self._use_row_as_start(self._view["row"]))
        self._back_btn = QPushButton("Back to starting model")
        self._back_btn.clicked.connect(self._on_back_to_start)
        for b in (self._refit_view_btn, self._use_view_btn, self._back_btn):
            pill.addWidget(b)
        layout.addWidget(self._pill)

        self._param_table = QTableWidget(0, 9)
        self._param_table.setHorizontalHeaderLabels(
            ["Peak", "Parameter", "Value", "±", "Min", "Max", "Fixed", "Shared ⇄", "Expr"]
        )
        self._param_table.horizontalHeaderItem(_COL_ERROR).setToolTip("Standard error after a fit")
        self._param_table.horizontalHeaderItem(_COL_FIXED).setToolTip("Hold this value fixed during the fit")
        self._param_table.horizontalHeaderItem(_COL_SHARED).setToolTip(
            "Global fits only: one common value for every spectrum in the job, fit jointly. "
            "Shown when ③ is set to Global."
        )
        self._param_table.horizontalHeaderItem(_COL_EXPR).setToolTip(
            "Optional lmfit expression tying this parameter to others, e.g. p0_width")
        self._param_table.verticalHeader().setVisible(False)
        header = self._param_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.resizeSection(_COL_FIXED, 50)
        header.resizeSection(_COL_SHARED, 70)
        header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        header.customContextMenuRequested.connect(self._on_param_header_menu)
        self._param_table.setColumnHidden(_COL_EXPR, True)
        layout.addWidget(self._param_table)

        footer = QHBoxLayout()
        self._quality_label = QLabel("No fit yet.")
        self._quality_label.setWordWrap(True)
        footer.addWidget(self._quality_label, stretch=1)
        self._export_fit_btn = QPushButton("Export fit…")
        self._export_fit_btn.setToolTip("Save this fit as a CSV with provenance")
        self._export_fit_btn.clicked.connect(self._on_export_fit)
        self._send_fit_btn = QPushButton("Send to Spectra Library")
        self._send_fit_btn.clicked.connect(self._send_workspace_fit_to_library)
        footer.addWidget(self._export_fit_btn)
        footer.addWidget(self._send_fit_btn)
        layout.addLayout(footer)
        return widget

    def _on_param_header_menu(self, pos):
        menu = QMenu(self)
        expr = menu.addAction("Show Expr column")
        expr.setCheckable(True)
        expr.setChecked(not self._param_table.isColumnHidden(_COL_EXPR))
        chosen = menu.exec(self._param_table.horizontalHeader().mapToGlobal(pos))
        if chosen is expr:
            self._param_table.setColumnHidden(_COL_EXPR, not expr.isChecked())

    def _update_shared_column_visibility(self):
        self._param_table.setColumnHidden(_COL_SHARED, self._job.effective_mode() != jobmod.GLOBAL)

    def _param_at(self, key: tuple) -> FitParam:
        if key[0] == "nr":
            return self._model_spec.nonresonant[key[1]]
        _, i, name = key
        return self._model_spec.peaks[i].params[name]

    def _param_label(self, key: tuple) -> str:
        if key[0] == "nr":
            return f"non-resonant {key[1]}"
        return f"peak {key[1] + 1} {key[2]}"

    def _rebuild_parameter_table(self):
        rows = []
        for name, fp in self._model_spec.nonresonant.items():
            rows.append((("nr", name), "Non-resonant", name.capitalize(), fp))
        for i, peak in enumerate(self._model_spec.peaks):
            ls = get_lineshape(peak.lineshape_key)
            for p in ls.params:
                pname = p.display_name
                if p.name == "amplitude" and peak.amplitude_signs:
                    pname += f" ({_format_sign_rules(peak.amplitude_signs)})"
                rows.append((("peak", i, p.name), f"Peak {i + 1} ({ls.display_name})",
                             pname, peak.params[p.name]))

        table = self._param_table
        table.setRowCount(len(rows))
        self._param_row_keys = [r[0] for r in rows]

        for row, (key, label, pname, fp) in enumerate(rows):
            table.setItem(row, _COL_LABEL, _readonly_item(label))
            param_item = _readonly_item(pname)
            if key[0] == "peak" and key[2] == "amplitude" and self._model_spec.peaks[key[1]].amplitude_signs:
                param_item.setToolTip(
                    "Sign rules per polarization (② Model → Sign rules…). "
                    "They apply to any fit of a spectrum whose polarization has a rule."
                )
            table.setItem(row, _COL_PARAM, param_item)

            value_spin = QDoubleSpinBox()
            value_spin.setRange(-1e9, 1e9)
            value_spin.setDecimals(4)
            value_spin.setValue(fp.value)
            value_spin.valueChanged.connect(lambda v, k=key: self._on_param_edit(k, "value", v))
            table.setCellWidget(row, _COL_VALUE, value_spin)

            table.setItem(row, _COL_ERROR, _readonly_item(""))

            fixed_check = QCheckBox()
            fixed_check.setChecked(not fp.vary)
            fixed_check.toggled.connect(lambda checked, k=key: self._on_param_edit(k, "vary", not checked))
            table.setCellWidget(row, _COL_FIXED, _center_widget(fixed_check))

            shared_check = QCheckBox()
            shared_check.setChecked(fp.shared)
            shared_check.setToolTip("One common value for every spectrum in a global fit")
            shared_check.toggled.connect(lambda checked, k=key: self._on_param_edit(k, "shared", checked))
            table.setCellWidget(row, _COL_SHARED, _center_widget(shared_check))

            min_edit = QLineEdit(_fmt_bound(fp.min))
            min_edit.editingFinished.connect(lambda k=key, r=row: self._on_bound_edited(k, "min", r))
            table.setCellWidget(row, _COL_MIN, min_edit)

            max_edit = QLineEdit(_fmt_bound(fp.max))
            max_edit.editingFinished.connect(lambda k=key, r=row: self._on_bound_edited(k, "max", r))
            table.setCellWidget(row, _COL_MAX, max_edit)

            expr_edit = QLineEdit(fp.expr or "")
            expr_edit.editingFinished.connect(lambda k=key, r=row: self._on_expr_edited(k, r))
            table.setCellWidget(row, _COL_EXPR, expr_edit)

        self._apply_peak_row_colors()
        self._update_shared_column_visibility()
        self._refresh_job_bar()

    def _on_param_edit(self, key: tuple, field: str, value):
        """A parameter-table edit. On the starting model it's undoable
        (consecutive edits of one cell merge into one step); while viewing
        a result it only changes that view's working copy."""
        fp = self._param_at(key)
        old = getattr(fp, field)
        if old == value:
            return
        if self._view is not None:
            setattr(fp, field, value)
            self._view["dirty"] = True
            self._update_view_pill()
        else:
            self._undo_stack.push(EditParamCommand(self, key, field, old, value, self._param_label(key)))
        if field == "value":
            self._schedule_preview()
        if field == "shared":
            self._refresh_job_bar()

    def _on_bound_edited(self, key: tuple, field: str, row: int):
        widget = self._param_table.cellWidget(row, _COL_MIN if field == "min" else _COL_MAX)
        fp = self._param_at(key)
        value = _parse_bound(widget.text(), getattr(fp, field))
        widget.setText(_fmt_bound(value))
        self._on_param_edit(key, field, value)

    def _on_expr_edited(self, key: tuple, row: int):
        widget = self._param_table.cellWidget(row, _COL_EXPR)
        self._on_param_edit(key, "expr", widget.text().strip() or None)

    def _set_param_widget(self, key: tuple, field: str, value):
        """Reflect an undo/redo of one field in its table cell."""
        if key not in self._param_row_keys:
            return
        row = self._param_row_keys.index(key)
        table = self._param_table
        if field == "value":
            w = table.cellWidget(row, _COL_VALUE)
            w.blockSignals(True)
            w.setValue(value)
            w.blockSignals(False)
        elif field in ("vary", "shared"):
            holder = table.cellWidget(row, _COL_FIXED if field == "vary" else _COL_SHARED)
            check = holder.findChild(QCheckBox)
            check.blockSignals(True)
            check.setChecked(not value if field == "vary" else value)
            check.blockSignals(False)
        elif field in ("min", "max"):
            table.cellWidget(row, _COL_MIN if field == "min" else _COL_MAX).setText(_fmt_bound(value))
        elif field == "expr":
            table.cellWidget(row, _COL_EXPR).setText(value or "")

    # ── Peak-row coloring (Preferences > Fitting > Color parameter table
    # by peak) ───────────────────────────────────────────────────────────────

    def _peak_row_color(self, peak_index: int) -> QColor | None:
        style = self._series_styles.get(f"peak_{peak_index}")
        if style is not None and style.color:
            return QColor(style.color)
        return QColor(color_coding.color_for_key(f"peak_{peak_index}"))

    @staticmethod
    def _tint_widget(widget: QWidget, color: QColor | None):
        if color is None:
            widget.setAutoFillBackground(False)
            widget.setPalette(QPalette())
            return
        text = color_coding.contrasting_text_color(color)
        pal = widget.palette()
        for role in (QPalette.ColorRole.Base, QPalette.ColorRole.Window,
                     QPalette.ColorRole.Button):
            pal.setColor(role, color)
        for role in (QPalette.ColorRole.Text, QPalette.ColorRole.WindowText,
                     QPalette.ColorRole.ButtonText):
            pal.setColor(role, text)
        widget.setAutoFillBackground(True)
        widget.setPalette(pal)

    def _tint_table_row(self, table: QTableWidget, row: int,
                         item_cols: list[int], widget_cols: list[int], color: QColor | None):
        fg = color_coding.contrasting_text_color(color) if color is not None else QBrush()
        bg = QBrush(color) if color is not None else QBrush()
        for col in item_cols:
            item = table.item(row, col)
            if item is not None:
                item.setBackground(bg)
                item.setForeground(fg)
        for col in widget_cols:
            widget = table.cellWidget(row, col)
            if widget is not None:
                self._tint_widget(widget, color)

    def _apply_peak_row_colors(self):
        enabled = (self._display_settings is not None
                   and self._display_settings.color_parameter_table_by_peak)

        for row, key in enumerate(self._param_row_keys):
            color = self._peak_row_color(key[1]) if (enabled and key[0] == "peak") else None
            self._tint_table_row(
                self._param_table, row,
                item_cols=[_COL_LABEL, _COL_PARAM, _COL_ERROR],
                widget_cols=[_COL_VALUE, _COL_FIXED, _COL_SHARED, _COL_MIN, _COL_MAX, _COL_EXPR],
                color=color,
            )

        for row in range(self._peak_table.rowCount()):
            color = self._peak_row_color(row) if enabled else None
            self._tint_table_row(
                self._peak_table, row,
                item_cols=[_PEAK_COL_INDEX, _PEAK_COL_CENTER],
                widget_cols=[_PEAK_COL_LINESHAPE, _PEAK_COL_REMOVE],
                color=color,
            )

    def _apply_fit_result_to_table(self):
        table = self._param_table
        for row, key in enumerate(self._param_row_keys):
            value_widget = table.cellWidget(row, _COL_VALUE)
            err_item = table.item(row, _COL_ERROR)
            if value_widget is None:
                continue
            value_widget.blockSignals(True)
            value_widget.setValue(self._param_at(key).value)
            value_widget.blockSignals(False)
            pr = None if self._last_result is None else self._last_result.param_results.get(_lmfit_key(key))
            value_widget.setStyleSheet("background-color: #fff3cd;" if (pr is not None and pr.at_bound) else "")
            value_widget.setToolTip("At a bound after the fit" if (pr is not None and pr.at_bound) else "")
            if err_item is not None:
                err_item.setText("" if pr is None or pr.stderr is None else f"{pr.stderr:.3g}")
        self._refresh_peak_centers()

    def _refresh_peak_centers(self):
        for i, peak in enumerate(self._model_spec.peaks):
            center = peak.params.get("center")
            item = self._peak_table.item(i, _PEAK_COL_CENTER)
            if item is not None and center is not None:
                item.setText(f"{center.value:.1f}")

    def _update_quality_readout(self):
        r = self._last_result
        if r is None:
            self._quality_label.setText("No fit yet." if self._view is None else "")
        else:
            self._quality_label.setText(
                f"χ²ᵣ = {r.redchi:.4g}   R² = {r.r_squared:.4f}   "
                f"AIC = {r.aic:.4g}   BIC = {r.bic:.4g}   "
                f"({'converged' if r.success else 'did not converge'})"
            )
        has_fit = r is not None and self._data is not None
        self._export_fit_btn.setEnabled(has_fit)
        self._send_fit_btn.setEnabled(has_fit and self._results_provider is not None)

    # ── Display (Curves… popover) ────────────────────────────────────────────

    def _fixed_series(self) -> list[tuple[str, str]]:
        if self._data is not None and self._data.kind == "phase_resolved":
            return _FIXED_SERIES_PHASE_RESOLVED
        return _FIXED_SERIES_CONVENTIONAL

    def _default_plot1_series(self) -> set[str]:
        if self._data is not None and self._data.kind == "phase_resolved":
            return _DEFAULT_PLOT1_SERIES_PHASE_RESOLVED
        return _DEFAULT_PLOT1_SERIES_CONVENTIONAL

    def _default_plot2_series(self) -> set[str]:
        if self._data is not None and self._data.kind == "phase_resolved":
            return _DEFAULT_PLOT2_SERIES_PHASE_RESOLVED
        return _DEFAULT_PLOT2_SERIES_CONVENTIONAL

    def _series_order(self) -> list[str]:
        order = [key for key, _ in self._fixed_series()]
        order += [f"peak_{i}" for i in range(len(self._model_spec.peaks))]
        return order

    def _series_label(self, key: str) -> str:
        fixed = dict(_FIXED_SERIES_CONVENTIONAL + _FIXED_SERIES_PHASE_RESOLVED)
        if key in fixed:
            return fixed[key]
        if key.startswith("peak_"):
            return f"Peak {int(key.split('_')[1]) + 1}"
        return key

    def _sync_series_assignment(self):
        """Rebuild self._series_assignment/_series_styles for the current
        series set, keeping existing choices for series that still exist
        and defaulting newly-appeared ones. Peaks are identified by their
        current index, so removing an earlier peak reindexes later ones."""
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
        widget.setMinimumWidth(460)
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        self._display_table = QTableWidget(0, 5)
        self._display_table.setHorizontalHeaderLabels(
            ["Curve", "Plot 1", "Plot 2", "Color", "Line style"]
        )
        self._display_table.verticalHeader().setVisible(False)
        self._display_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._display_table.setMinimumHeight(220)
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
        chosen = QColorDialog.getColor(QColor(current), self, "Curve color")
        if chosen.isValid():
            self._series_styles[key].color = chosen.name()
            self._style_color_button(button, chosen.name())
            self._apply_peak_row_colors()
            self._schedule_preview()

    def _on_reset_series_color(self, key: str, button: QPushButton):
        self._series_styles[key].color = None
        self._style_color_button(button, None)
        self._apply_peak_row_colors()
        self._schedule_preview()

    def _on_series_linestyle_changed(self, key: str, combo_index: int):
        self._series_styles[key].linestyle = _LINESTYLE_OPTIONS[combo_index][1]
        self._schedule_preview()

    def _on_reset_all_styles(self):
        for key in self._series_styles:
            self._series_styles[key] = SeriesStyle(linestyle=_default_linestyle_for(key))
        self._rebuild_display_table()
        self._apply_peak_row_colors()
        self._schedule_preview()

    # ── Running ──────────────────────────────────────────────────────────────

    def _on_fit_clicked(self):
        self._job_bar.close_popovers()
        self._stop_placement()
        problems = self._job.problems()
        if problems:
            QMessageBox.information(self, "Can't fit yet", "\n".join(problems))
            return
        if not self._model_spec.peaks:
            QMessageBox.information(self, "Can't fit yet", "Add at least one peak in ② Model.")
            self._job_bar.open_popover(_CHIP_MODEL)
            return
        self._leave_view()
        mode = self._job.effective_mode()
        if mode == jobmod.SINGLE:
            self._on_run_fit()
        elif mode == jobmod.SEQUENTIAL:
            self._run_sequential()
        else:
            self._run_batch(mode)

    def _cancelable_busy_dialog(self, title: str, label: str) -> tuple[QProgressDialog, object]:
        """A busy dialog with Cancel, driven by lmfit's per-iteration
        iter_cb (returning True aborts the minimizer cleanly)."""
        dialog = QProgressDialog(label, "Cancel", 0, 0, self)
        dialog.setWindowTitle(title)
        dialog.setWindowModality(Qt.WindowModality.WindowModal)
        dialog.setMinimumDuration(400)

        def iter_cb(_params, iteration: int, _resid, *_args, **_kwargs) -> bool:
            # (lmfit also passes the residual function's own fcn_args)
            if iteration % 10 == 0:
                dialog.setLabelText(f"{label} (evaluation {iteration})")
                QApplication.processEvents()
            return dialog.wasCanceled()

        return dialog, iter_cb

    def _on_run_fit(self):
        """Fit the workspace spectrum (single-spectrum job, or a view's
        Refit) from the current model."""
        if self._data is None:
            QMessageBox.information(self, "No data", "Add a spectrum in ① first.")
            return
        mask = self._fit_mask()
        if not mask.any():
            QMessageBox.warning(self, "Empty fit window", "No data points fall inside the fit range.")
            return
        result = self._fit_workspace(mask)
        if result is None:
            return
        old_spec, old_result = self._model_spec, self._last_result
        self._undo_stack.push(RunFitCommand(self, old_spec, old_result, result.spec, result))

    def _fit_workspace(self, mask):
        omega = self._data.omega[mask]
        weighting = self._weighting_combo.currentData()
        constrained = apply_sign_constraints(self._model_spec, self._data_polarization(),
                                             mirror_ok=self._data.kind == "conventional")
        dialog, iter_cb = self._cancelable_busy_dialog("Fitting", f"Fitting {self._data.label}…")
        try:
            if self._data.kind == "phase_resolved":
                real = self._data.real[mask]
                imag = self._data.imag[mask]
                real_err = self._data.real_err[mask] if self._data.real_err is not None else None
                imag_err = self._data.imag_err[mask] if self._data.imag_err is not None else None
                weights_real, weights_imag = compute_phase_resolved_weights(weighting, real, imag, real_err, imag_err)
                result = fit_phase_resolved(omega, real, imag, constrained,
                                            weights_real=weights_real, weights_imag=weights_imag,
                                            iter_cb=iter_cb)
            else:
                intensity = self._data.intensity[mask]
                intensity_std = self._data.intensity_std[mask] if self._data.intensity_std is not None else None
                count = self._data.count[mask] if self._data.count is not None else None
                weights = compute_weights(weighting, intensity, intensity_std, count)
                result = fit_conventional(omega, intensity, constrained, weights=weights, iter_cb=iter_cb)
        except Exception as e:
            logger.warning("Fit failed: %s", e)
            QMessageBox.warning(self, "Fit failed", str(e))
            return None
        finally:
            dialog.close()
        if getattr(result.lmfit_result, "aborted", False):
            self.statusBar_message("Fit canceled.")
            return None
        restore_amplitude_bounds(result.spec, self._model_spec)
        return result

    def _build_batch_datasets(self, entries: list) -> list[BatchDataset] | None:
        """Returns None (after warning the user) if any entry's columns
        can't be extracted."""
        datasets = []
        for e in entries:
            channels = _extract_channels(e.spectrum.data, preferred_kind=e.kind)
            if channels is None:
                QMessageBox.warning(
                    self, "Cannot fit this spectrum",
                    f"{e.label}: no Wavenumber/Intensity or Wavenumber/Real/Imaginary columns found.",
                )
                return None
            datasets.append(BatchDataset(label=e.label, polarization=self._polarization_of(e.spectrum.metadata or {}),
                                         **channels))
        return datasets

    def _run_progress_dialog(self, n: int, title: str) -> tuple[QProgressDialog, object]:
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

    def _start_run(self, mode: str):
        self._pending_undo_snapshot = self._capture_batch_state()
        self._batch_template = deepcopy(self._model_spec)
        self._batch_fit_range = (self._fit_min_spin.value(), self._fit_max_spin.value())
        self._batch_weighting = self._weighting_combo.currentData()
        self._batch_run_mode = mode
        self._batch_global_result = None
        self._batch_shared_keys = []

    def _run_batch(self, mode: str):
        entries = self._job.entries()
        datasets = self._build_batch_datasets(entries)
        if datasets is None:
            return
        shared_keys = self._shared_param_keys(self._model_spec) if mode == jobmod.GLOBAL else []
        if mode == jobmod.GLOBAL and not shared_keys:
            QMessageBox.information(
                self, "Nothing is shared",
                "A global fit needs at least one shared parameter. Choose what to share in "
                "③ (or tick Shared ⇄ in the Parameters panel), or pick Independent.",
            )
            self._job_bar.open_popover(_CHIP_STRATEGY)
            return
        self._start_run(mode)
        fit_range, weighting = self._batch_fit_range, self._batch_weighting

        if mode == jobmod.GLOBAL:
            self._batch_shared_keys = shared_keys
            dialog, iter_cb = self._cancelable_busy_dialog(
                "Global fit", f"Fitting {len(datasets)} spectra together")
            dialog.setMinimumDuration(0)
            dialog.show()

            def seed_progress(i: int, total: int, label: str) -> bool:
                dialog.setLabelText(f"Seeding amplitudes {i + 1} of {total}: {label}")
                QApplication.processEvents()
                return not dialog.wasCanceled()

            try:
                if self._job.seed_amplitudes:
                    global_result = fit_polarization_set(
                        datasets, self._model_spec, weighting=weighting, fit_range=fit_range,
                        progress_cb=seed_progress, iter_cb=iter_cb,
                    )
                else:
                    global_result = fit_global_batch(
                        datasets, self._model_spec, weighting=weighting, fit_range=fit_range,
                        iter_cb=iter_cb,
                    )
            except Exception as e:
                dialog.close()
                QMessageBox.warning(self, "Global fit failed", str(e))
                return
            # (closing a QProgressDialog marks it canceled -- ask first)
            canceled = dialog.wasCanceled()
            dialog.close()
            if global_result is None or canceled:
                return
            self._batch_global_result = global_result
            results = global_result.per_dataset
        else:
            # Independent fits ignore Shared flags: each spectrum gets its own values.
            template = deepcopy(self._model_spec)
            for fp in list(template.nonresonant.values()) + [fp for p in template.peaks for fp in p.params.values()]:
                fp.shared = False
            dialog, progress_cb = self._run_progress_dialog(len(datasets), "Independent fit")
            try:
                results = fit_independent_batch(
                    datasets, template, weighting=weighting, fit_range=fit_range,
                    progress_cb=progress_cb,
                )
            except Exception as e:
                dialog.close()
                QMessageBox.warning(self, "Fit failed", str(e))
                return
            dialog.close()

        n = len(results)
        self._batch_rows = list(zip(entries[:n], datasets[:n], results))
        self._batch_row_overrides = [None] * len(self._batch_rows)
        self._finish_multifit_run()
        self._maybe_push_batch_undo()

    def _run_sequential(self):
        entries = self._job.entries()
        datasets = self._build_batch_datasets(entries)
        if datasets is None:
            return
        pauses = self._job.pause_flags()
        self._start_run(jobmod.SEQUENTIAL)
        self._batch_rows = []
        self._batch_row_overrides = []
        template = deepcopy(self._model_spec)
        for fp in list(template.nonresonant.values()) + [fp for p in template.peaks for fp in p.params.values()]:
            fp.shared = False

        if not any(pauses[:-1]):
            dialog, progress_cb = self._run_progress_dialog(len(datasets), "Sequential fit")
            try:
                results = fit_sequential_batch(
                    datasets, template, weighting=self._batch_weighting, fit_range=self._batch_fit_range,
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
            self._maybe_push_batch_undo()
            return

        self._job_bar.set_running("Running sequence…")
        self._sequential_run = {
            "queue": list(zip(entries, datasets, pauses)), "index": 0,
            "current_spec": template,
            "fit_range": self._batch_fit_range, "weighting": self._batch_weighting,
            "paused": False, "stop_requested": False,
        }
        self._finish_multifit_run()
        self._advance_sequential_run()

    def _advance_sequential_run(self):
        """Fits exactly one queued spectrum, then either pauses (a review
        point) or schedules the next step via QTimer.singleShot(0, ...),
        so Stop takes effect between spectra."""
        run = self._sequential_run
        if run is None:
            return
        if run["stop_requested"] or run["index"] >= len(run["queue"]):
            self._finish_sequential_run()
            return

        entry, dataset, pause = run["queue"][run["index"]]
        self._job_bar.set_running(f"Fitting {run['index'] + 1}/{len(run['queue'])}: {entry.label}…")
        QApplication.processEvents()
        result = fit_one_dataset(dataset, run["current_spec"], run["weighting"], run["fit_range"])
        self._batch_rows.append((entry, dataset, result))
        self._batch_row_overrides.append(None)
        run["current_spec"] = advance_seed(run["current_spec"], result)
        run["index"] += 1
        at_end = run["index"] >= len(run["queue"])
        self._finish_multifit_run()

        if pause and not at_end:
            run["paused"] = True
            row = len(self._batch_rows) - 1
            self._job_bar.set_paused(
                f"Paused after {entry.label} ({run['index']}/{len(run['queue'])}) — check it, "
                "refit if needed, then")
            self.results_view.select_row(row)
            self._enter_view(row)
            return
        if at_end:
            self._finish_sequential_run()
            return
        QTimer.singleShot(0, self._advance_sequential_run)

    def _on_sequential_continue(self):
        run = self._sequential_run
        if run is None or not run.get("paused"):
            return
        # Seed from the paused spectrum's row -- which a "Refit this
        # spectrum" at the review point may have replaced -- never from
        # whatever happens to be in the workspace.
        _entry, _dataset, result = self._batch_rows[-1]
        if result is not None:
            seed = deepcopy(result.spec)
            for fp in list(seed.nonresonant.values()) + [fp for p in seed.peaks for fp in p.params.values()]:
                fp.shared = False
            run["current_spec"] = seed
        override = self._batch_row_overrides[-1]
        if override is not None:
            run["fit_range"], run["weighting"] = override["fit_range"], override["weighting"]
        run["paused"] = False
        self._leave_view()
        self._job_bar.set_running("Running sequence…")
        QTimer.singleShot(0, self._advance_sequential_run)

    def _on_sequential_stop(self):
        run = self._sequential_run
        if run is None:
            return
        run["stop_requested"] = True
        if run["paused"]:
            self._finish_sequential_run()

    def _finish_sequential_run(self):
        self._sequential_run = None
        self._leave_view()
        self._job_bar.set_idle()
        self._finish_multifit_run()
        self._maybe_push_batch_undo()
        self._refresh_job_bar()

    # ── Results ──────────────────────────────────────────────────────────────

    def _capture_batch_state(self) -> tuple:
        return (
            list(self._batch_rows), list(self._batch_row_overrides),
            deepcopy(self._batch_template) if self._batch_template is not None else None,
            self._batch_fit_range, self._batch_weighting, self._batch_run_mode,
            self._batch_global_result, list(self._batch_shared_keys),
        )

    def _restore_batch_state(self, state: tuple):
        (self._batch_rows, self._batch_row_overrides, self._batch_template,
         self._batch_fit_range, self._batch_weighting, self._batch_run_mode,
         self._batch_global_result, self._batch_shared_keys) = state

    def _maybe_push_batch_undo(self, description: str | None = None):
        if self._pending_undo_snapshot is None:
            return
        old_state = self._pending_undo_snapshot
        self._pending_undo_snapshot = None
        self._undo_stack.push(RunBatchFitCommand(self, old_state, self._capture_batch_state(), description))

    def _batch_param_columns(self, template: FitModelSpec) -> list[tuple[tuple, str]]:
        columns = []
        for name in template.nonresonant:
            columns.append((("nr", name), f"NR {name}"))
        for i, peak in enumerate(template.peaks):
            ls = get_lineshape(peak.lineshape_key)
            for p in ls.params:
                columns.append((("peak", i, p.name), f"P{i + 1} {p.display_name.lower()}"))
        return columns

    def _finish_multifit_run(self):
        """Push the current _batch_rows into the results spreadsheet."""
        template = self._batch_template
        columns, rows = [], []
        if template is not None:
            shared = set(self._batch_shared_keys) if self._batch_run_mode == jobmod.GLOBAL else set()
            for key, label in self._batch_param_columns(template):
                param = (template.nonresonant[key[1]] if key[0] == "nr"
                         else template.peaks[key[1]].params[key[2]])
                if not param.vary and not param.expr:
                    continue   # fixed parameters are the same everywhere
                columns.append(ResultColumn(_lmfit_key(key), label, _lmfit_key(key) in shared))
        for entry, _dataset, result in self._batch_rows:
            meta = _user_metadata(entry.spectrum.metadata or {})
            if result is None:
                rows.append(ResultRow(entry.label, FAIL, "The fit raised an error for this spectrum.",
                                      metadata=meta))
                continue
            values = {c.key: (result.param_results[c.key].value, result.param_results[c.key].stderr)
                      for c in columns if c.key in result.param_results}
            rows.append(ResultRow(entry.label, OK if result.success else WARN,
                                  result.message or "", result.redchi, result.r_squared, values, meta))

        header, tip = self._results_header()
        self.results_view.refit_allowed = self._batch_run_mode != jobmod.GLOBAL
        self.results_view.set_results(rows, columns, header, tip)
        if self._view is not None:
            row = self._view["row"]
            if row < len(self._batch_rows):
                self._enter_view(row, refresh=True)
            else:
                self._leave_view()
        if self._batch_rows and not self._docks["results"].isVisible():
            self._docks["results"].show()

    def _results_header(self) -> tuple[str, str]:
        n = len(self._batch_rows)
        if not n or self._batch_run_mode is None:
            return ("No multi-spectrum fit yet — add 2 or more spectra in ①, choose how to fit "
                    "them in ③, and press Fit.", "")
        name = _MODE_RUN_NAMES.get(self._batch_run_mode, "Fit")
        text = f"{name} of {n} spectra"
        failed = sum(1 for _e, _d, r in self._batch_rows if r is None)
        warned = sum(1 for _e, _d, r in self._batch_rows if r is not None and not r.success)
        if self._sequential_run is not None:
            text += f" (in progress, {self._sequential_run['index']}/{len(self._sequential_run['queue'])})"
        tip = ""
        gr = self._batch_global_result
        if gr is not None:
            label_by_key = {_lmfit_key(k): label for k, label in self._batch_param_columns(self._batch_template)}
            shared = ", ".join(label_by_key.get(k, k) for k in gr.shared_keys)
            text += (f" · shared: {shared} · combined χ²ᵣ = {gr.redchi:.4g} "
                     f"({'converged' if gr.success else 'did not converge'})")
            if gr.seeded:
                text += " · amplitudes seeded per spectrum"
            tip = ("Each row's χ²ᵣ is that spectrum's own diagnostic, not the combined value.")
        if failed or warned:
            text += f" · {warned} not converged, {failed} failed" if failed else f" · {warned} not converged"
        return text, tip

    def _draw_overlay(self):
        plot = self.results_view.overlay_plot
        plot.full_clear()
        ax = plot.ax
        max_legend = 8
        for i, (entry, dataset, result) in enumerate(self._batch_rows):
            if result is None:
                continue
            omega = dataset.omega
            label = entry.label if i < max_legend else None
            # |chi_eff|^2 for both kinds: one consistent view
            data_y = dataset.real ** 2 + dataset.imag ** 2 if dataset.kind == "phase_resolved" else dataset.intensity
            fit_y = evaluate_conventional(omega, result.spec)
            data_line, = ax.plot(omega, data_y, marker=".", markersize=2, linestyle="none", alpha=0.5)
            fit_line, = ax.plot(omega, fit_y, label=label)
            data_line.set_color(fit_line.get_color())
        ax.set_xlabel("Wavenumber (cm$^{-1}$)")
        ax.set_ylabel("Intensity (a.u.)")
        if ax.get_legend_handles_labels()[0]:
            ax.legend(fontsize=7)
        plot.canvas.draw_idle()

    def _row_settings(self, row: int) -> tuple[tuple[float, float], str]:
        override = self._batch_row_overrides[row] if row < len(self._batch_row_overrides) else None
        if override:
            return override["fit_range"], override["weighting"]
        return self._batch_fit_range, self._batch_weighting

    # viewing a result row in the workspace

    def _on_result_row_selected(self, row: int):
        if row < 0:
            return
        self._enter_view(row)

    def _enter_view(self, row: int, refresh: bool = False):
        """Show result row `row` in the workspace. The starting state is
        saved and comes back with _leave_view(); nothing about the
        starting model changes."""
        if not (0 <= row < len(self._batch_rows)):
            return
        entry, _dataset, result = self._batch_rows[row]
        if self._view is None:
            self._stop_placement()
            self._view = {"saved": {
                "data": self._data, "spec": self._model_spec, "result": self._last_result,
                "fit_range": (self._fit_min_spin.value(), self._fit_max_spin.value()),
                "weighting": self._weighting_combo.currentData(),
            }}
        elif not refresh and self._view.get("row") == row:
            return
        self._view.update(row=row, dirty=False)
        channels = _extract_channels(entry.spectrum.data, preferred_kind=entry.kind)
        self._data = _FittableSpectrum(label=entry.label, source_spectrum=entry.spectrum,
                                       metadata=_user_metadata(entry.spectrum.metadata or {}), **channels)
        saved = self._view["saved"]
        self._model_spec = deepcopy(result.spec if result is not None else saved["spec"])
        self._last_result = result
        fit_range, weighting = self._row_settings(row)
        self._rebuild_weighting_combo()
        if weighting is not None:
            idx = self._weighting_combo.findData(weighting)
            if idx >= 0:
                self._weighting_combo.setCurrentIndex(idx)
        if fit_range is not None:
            self._set_fit_range(*fit_range)
        self._after_workspace_swap()

    def _leave_view(self):
        if self._view is None:
            return
        saved = self._view["saved"]
        self._view = None
        self._data = saved["data"]
        self._model_spec = saved["spec"]
        self._last_result = saved["result"]
        self._rebuild_weighting_combo()
        idx = self._weighting_combo.findData(saved["weighting"])
        if idx >= 0:
            self._weighting_combo.setCurrentIndex(idx)
        self._set_fit_range(*saved["fit_range"])
        self.results_view.clear_selection()
        self._after_workspace_swap()

    def _after_workspace_swap(self):
        self._plot_data()
        self._rebuild_peak_table()
        self._rebuild_parameter_table()
        self._rebuild_display_table()
        self._apply_fit_result_to_table()
        self._update_quality_readout()
        self._update_view_pill()
        self._refresh_job_bar()
        self._schedule_preview()

    def _on_back_to_start(self):
        if self._sequential_run is not None and self._sequential_run.get("paused"):
            # the review point stays open; only the workspace goes back
            pass
        self._leave_view()

    def _update_view_pill(self):
        viewing = self._view is not None
        paused = self._sequential_run is not None and self._sequential_run.get("paused")
        if viewing:
            row = self._view["row"]
            entry, _d, result = self._batch_rows[row]
            status = "fit failed" if result is None else "fit result"
            edited = " — edited, not refit yet" if self._view.get("dirty") else ""
            self._pill_label.setText(f"<b>Viewing:</b> {entry.label} ({status}){edited}")
            self._pill.setStyleSheet("QFrame { background: #e8f0fe; }")
        else:
            label = self._data.label if self._data is not None else "no spectrum yet"
            self._pill_label.setText(f"<b>Editing the starting model</b> — on {label}")
            self._pill.setStyleSheet("")
        global_run = self._batch_run_mode == jobmod.GLOBAL
        self._refit_view_btn.setVisible(viewing)
        self._refit_view_btn.setEnabled(viewing and not global_run)
        self._refit_view_btn.setToolTip(
            "Rows of a global fit can't be refit on their own — run the global fit again."
            if global_run else "Fit this spectrum again from the values shown, and update its row")
        self._use_view_btn.setVisible(viewing and not paused)
        self._back_btn.setVisible(viewing)
        self._model_controls.setEnabled(not viewing)
        self._model_view_note.setVisible(viewing)

    def _refit_viewed_row(self):
        if self._view is None:
            return
        row = self._view["row"]
        mask = self._fit_mask()
        if not mask.any():
            QMessageBox.warning(self, "Empty fit window", "No data points fall inside the fit range.")
            return
        result = self._fit_workspace(mask)
        if result is None:
            return
        self._replace_rows({row: result}, "Refit spectrum")

    def _replace_rows(self, results: dict, description: str):
        """Swap in new results for some rows, as one undo step; rows fit
        with other settings than the run's get an override."""
        self._pending_undo_snapshot = self._capture_batch_state()
        fit_range = (self._fit_min_spin.value(), self._fit_max_spin.value())
        weighting = self._weighting_combo.currentData()
        rows = list(self._batch_rows)
        overrides = list(self._batch_row_overrides)
        for row, result in results.items():
            entry, dataset, _old = rows[row]
            rows[row] = (entry, dataset, result)
            if (fit_range, weighting) != (self._batch_fit_range, self._batch_weighting):
                overrides[row] = {"fit_range": fit_range, "weighting": weighting}
        self._batch_rows, self._batch_row_overrides = rows, overrides
        self._finish_multifit_run()
        self._maybe_push_batch_undo(description)

    def _refit_rows(self, rows: list[int]):
        """Refit selected rows independently from the starting model, with
        the current fit range and weighting."""
        rows = [r for r in rows if 0 <= r < len(self._batch_rows)]
        if not rows or self._batch_run_mode == jobmod.GLOBAL:
            return
        start_spec = self._view["saved"]["spec"] if self._view is not None else self._model_spec
        settings = (self._view["saved"]["fit_range"], self._view["saved"]["weighting"]) if self._view else (
            (self._fit_min_spin.value(), self._fit_max_spin.value()), self._weighting_combo.currentData())
        template = deepcopy(start_spec)
        for fp in list(template.nonresonant.values()) + [fp for p in template.peaks for fp in p.params.values()]:
            fp.shared = False
        datasets = [self._batch_rows[r][1] for r in rows]
        dialog, progress_cb = self._run_progress_dialog(len(datasets), "Refit")
        try:
            results = fit_independent_batch(datasets, template, weighting=settings[1], fit_range=settings[0],
                                            progress_cb=progress_cb)
        except Exception as e:
            dialog.close()
            QMessageBox.warning(self, "Refit failed", str(e))
            return
        dialog.close()
        was_viewing = self._view["row"] if self._view is not None else None
        self._leave_view()
        self._set_fit_range(*settings[0])
        self._replace_rows(dict(zip(rows, results)), "Refit selected" if len(rows) > 1 else "Refit spectrum")
        if was_viewing is not None:
            self.results_view.select_row(was_viewing)

    def _use_row_as_start(self, row: int):
        if not (0 <= row < len(self._batch_rows)):
            return
        result = self._batch_rows[row][2]
        if result is None:
            return
        start = self._view["saved"]["spec"] if self._view is not None else self._model_spec
        new = deepcopy(result.spec)
        # keep the starting model's own settings (sharing, sign rules)
        for (fp_new, fp_old) in zip(
                list(new.nonresonant.values()) + [fp for p in new.peaks for fp in p.params.values()],
                list(start.nonresonant.values()) + [fp for p in start.peaks for fp in p.params.values()]):
            fp_new.shared = fp_old.shared
        self._leave_view()
        self._undo_stack.push(ReplaceModelSpecCommand(self, self._model_spec, new,
                                                      f"Use {self._batch_rows[row][0].label} as starting model"))

    def _remove_result_rows_from_job(self, rows: list[int]):
        entries = {id(self._batch_rows[r][0]) for r in rows if 0 <= r < len(self._batch_rows)}
        indices = [i for i, s in enumerate(self._job.spectra) if id(s.entry) in entries]
        self._remove_from_job(indices)

    # ── Export / send to library ─────────────────────────────────────────────

    def _fit_json(self, result, weighting: str, kind: str) -> str:
        lines = provenance.format_fit_section(
            result.spec.to_dict(), weighting, result.redchi, result.r_squared, result.aic, result.bic,
            kind=kind, param_errors={k: pr.stderr for k, pr in result.param_results.items()},
        )
        return lines[-1].split("Fit json:", 1)[1].strip()

    def _send_to_library(self, items: list[tuple]) -> list[str]:
        """`items`: (spectrum, label, kind, result, weighting). Returns the
        labels the Spectra Library gave the new entries."""
        provider = self._results_provider
        if provider is None or not hasattr(provider, "add_fitted_spectrum"):
            QMessageBox.information(self, "No Spectra Library", "The Spectra Library isn't available.")
            return []
        names = []
        for spectrum, label, kind, result, weighting in items:
            names.append(provider.add_fitted_spectrum(spectrum, label, kind, self._fit_json(result, weighting, kind)))
        return names

    def _workspace_spectrum(self) -> ProcessedSpectrum:
        spectrum = self._data.source_spectrum
        if spectrum is not None:
            return spectrum
        if self._data.kind == "phase_resolved":
            real, imag = self._data.real, self._data.imag
            data = {"Wavenumber": self._data.omega, "Real": real, "Imaginary": imag,
                    "Phase": np.degrees(np.arctan2(imag, real)), "Chi2_abs2": real ** 2 + imag ** 2}
            if self._data.real_err is not None:
                data["Real_err"] = self._data.real_err
            if self._data.imag_err is not None:
                data["Imag_err"] = self._data.imag_err
        else:
            data = {"Wavenumber": self._data.omega, "Intensity": self._data.intensity}
        return ProcessedSpectrum(pd.DataFrame(data), metadata={}, history=["loaded_from_file"], provenance={})

    def _send_workspace_fit_to_library(self):
        if self._data is None or self._last_result is None:
            return
        names = self._send_to_library([(self._workspace_spectrum(), self._data.label, self._data.kind,
                                        self._last_result, self._weighting_combo.currentData())])
        if names:
            self.statusBar_message(f"Added “{names[0]}” to the Spectra Library.")

    def _send_rows_to_library(self, rows: list[int]):
        rows = rows or list(range(len(self._batch_rows)))
        items = []
        for r in rows:
            entry, _d, result = self._batch_rows[r]
            if result is None:
                continue
            _range, weighting = self._row_settings(r)
            items.append((entry.spectrum, entry.label, entry.kind, result, weighting))
        names = self._send_to_library(items)
        if names:
            self.statusBar_message(f"Added {len(names)} fit(s) to the Spectra Library.")

    def _on_export_fit(self):
        if self._data is None or self._last_result is None:
            QMessageBox.information(self, "Nothing to export", "Run a fit first.")
            return
        last_dir = recent_paths_settings.get_last_dir("fitting")
        default_name = f"{self._data.label}_fit.csv"
        default_path = str(Path(last_dir) / default_name) if last_dir else default_name
        path_str, _ = QFileDialog.getSaveFileName(self, "Export fit", default_path, "CSV files (*.csv)")
        if not path_str:
            return
        recent_paths_settings.remember_dir("fitting", path_str)
        weighting = self._weighting_combo.currentData()
        r = self._last_result
        fit_section = provenance.format_fit_section(
            self._model_spec.to_dict(), weighting, r.redchi, r.r_squared, r.aic, r.bic,
            kind=self._data.kind,
            param_errors={k: pr.stderr for k, pr in r.param_results.items()},
        )
        try:
            provenance.write_csv_with_provenance(
                self._workspace_spectrum(), self._data.kind, self._data.label, Path(path_str),
                fit_section=fit_section,
            )
        except Exception as e:
            QMessageBox.warning(self, "Export failed", str(e))
            return
        self.statusBar_message(f"Fit exported to {path_str}")

    def _on_export_batch_summary(self):
        """Writes <mode>_fit_summary.csv (one row per spectrum, every
        parameter's value/stderr as columns) plus one provenance CSV per
        row into a chosen folder."""
        if not self._batch_rows:
            QMessageBox.information(self, "Nothing to export", "Run a multi-spectrum fit first.")
            return
        folder = QFileDialog.getExistingDirectory(
            self, "Select export folder", recent_paths_settings.get_last_dir("fitting"),
        )
        if not folder:
            return
        recent_paths_settings.remember_dir("fitting", folder)
        summary_name = f"{self._batch_run_mode or 'batch'}_fit_summary.csv"
        path = Path(folder) / summary_name
        if path.exists():
            reply = QMessageBox.question(self, "Overwrite?", f"{summary_name} already exists there. Overwrite it?")
            if reply != QMessageBox.StandardButton.Yes:
                return

        param_columns = self._batch_param_columns(self._batch_template)
        rows = []
        for i, (entry, _dataset, result) in enumerate(self._batch_rows):
            override = self._batch_row_overrides[i] if i < len(self._batch_row_overrides) else None
            status = "failed" if result is None else ("converged" if result.success else "did not converge")
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
            f"# SFG-App {_MODE_RUN_NAMES.get(self._batch_run_mode, 'batch fit').lower()} summary",
            f"# Exported:    {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "#",
            f"# Batch json: {json.dumps(batch_payload)}",
        ]
        if self._batch_global_result is not None:
            gr = self._batch_global_result
            header_lines.append(f"# Shared parameters (fit jointly across every row): {', '.join(gr.shared_keys)}")
            header_lines.append(
                f"# Combined fit: redchi={gr.redchi:.6g}, aic={gr.aic:.6g}, bic={gr.bic:.6g}, "
                f"success={gr.success} -- per-row redchi/aic/bic below are per-row diagnostics, "
                f"not this combined value."
            )
        header_lines.append("#")
        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                for line in header_lines:
                    f.write(line + "\n")
                df.to_csv(f, index=False)
        except Exception as e:
            QMessageBox.warning(self, "Export failed", str(e))
            return

        exported, failed = 0, 0
        for i, (entry, _dataset, result) in enumerate(self._batch_rows):
            if result is None:
                continue
            _range, weighting = self._row_settings(i)
            try:
                fit_section = provenance.format_fit_section(
                    result.spec.to_dict(), weighting, result.redchi, result.r_squared,
                    result.aic, result.bic, kind=entry.kind,
                    param_errors={k: pr.stderr for k, pr in result.param_results.items()},
                )
                provenance.write_csv_with_provenance(
                    entry.spectrum, entry.kind, entry.label, Path(folder) / f"{entry.label}_fit.csv",
                    fit_section=fit_section,
                )
                exported += 1
            except Exception as e:
                logger.warning("Could not export per-spectrum fit CSV for %s: %s", entry.label, e)
                failed += 1

        msg = f"Exported {summary_name} + {exported} per-spectrum fit CSV(s) to {folder}."
        if failed:
            msg += f" {failed} failed — see the log."
        self.statusBar_message(msg)

    # ── Plot ─────────────────────────────────────────────────────────────────

    def _plot_data(self):
        self.plot_widget.full_clear()
        self.plot_widget2.full_clear()
        if self._data is None:
            self.plot_widget.ax.text(
                0.5, 0.5, "Start with ① — choose the spectra to fit.",
                ha="center", va="center", transform=self.plot_widget.ax.transAxes, color="gray",
            )
            self.plot_widget.canvas.draw_idle()
            self.plot_widget2.canvas.draw_idle()
            return
        title = self._data.label + ("  (fit result)" if self._view is not None else "")
        self.plot_widget.set_labels(xlabel="Wavenumber (cm$^{-1}$)", title=title)
        self.plot_widget2.set_labels(xlabel="Wavenumber (cm$^{-1}$)")

    def redraw_for_style_change(self):
        self._plot_data()
        self._update_preview()
        self.results_view.draw_trend()
        self._draw_overlay()

    def _schedule_preview(self):
        self._preview_timer.start()

    def _compute_series_values(self) -> dict[str, np.ndarray]:
        omega = self._data.omega
        chi = evaluate_chi(omega, self._model_spec)
        if self._data.kind == "phase_resolved":
            values = {
                "data_real": self._data.real,
                "data_imag": self._data.imag,
                "fit_real": chi.real,
                "fit_imag": chi.imag,
                "residual_real": self._data.real - chi.real,
                "residual_imag": self._data.imag - chi.imag,
            }
        else:
            total = evaluate_conventional(omega, self._model_spec)
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
        return "Intensity (a.u.)"

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
        else:
            ax.axhline(0.0, color="gray", linewidth=0.6, zorder=0)

        if any_line:
            ax.legend(fontsize=8)
        ax.set_ylabel(self._ylabel_for(plot_id))
        plot_widget.sync_x_range()
        plot_widget.canvas.draw_idle()
