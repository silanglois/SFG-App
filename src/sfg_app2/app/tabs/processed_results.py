from __future__ import annotations
import logging
import csv
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt
import matplotlib as mpl

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidgetItem, QFileDialog,
    QMessageBox, QAbstractItemView, QInputDialog, QMenu, QCheckBox,
    QMainWindow, QDockWidget, QComboBox, QLabel,
)

from sfg_app2.app.ui.ui_processed_results_tab import Ui_Form
from sfg_app2.app.widgets.spectrum_plot_widget import SpectrumPlotWidget
from sfg_app2.processing.processed_spectrum import ProcessedSpectrum
from sfg_app2.app.utils.loading_indicator import show_loading
from sfg_app2.app.utils.phase_wrap import wrap_phase_for_plot

logger = logging.getLogger(__name__)

# curated colormaps shown first, then all matplotlib ones
CURATED_COLORMAPS = [
    "viridis", "plasma", "inferno", "magma",
    "coolwarm", "RdYlBu", "Spectral",
    "Blues", "Reds", "Greens",
    "turbo", "rainbow",
]

def _build_provenance_from_history(spectrum: ProcessedSpectrum) -> dict:
    """Fallback provenance for spectra not processed via pipeline."""
    return {
        "source": spectrum.metadata.get("source_filename", "unknown"),
        "history": spectrum.history,
        "note": "Loaded directly from file — full provenance unavailable.",
    }

def _all_colormaps() -> list[str]:
    all_mpl = sorted(
        c for c in mpl.colormaps
        if not c.endswith("_r")
    )
    extras = [c for c in all_mpl if c not in CURATED_COLORMAPS]
    return CURATED_COLORMAPS + extras


# HD-SFG component checkboxes — display name -> to_dataframe() column name
_HD_COMPONENT_COLUMN = {
    "Imaginary": "Imaginary",
    "Real": "Real",
    "Phase": "Phase",
    "|χ⁽²⁾|² (Homodyne)": "Homodyne",
}

# display name -> to_dataframe() 95%-CI error column name
_HD_ERROR_COLUMN = {
    "Imaginary": "Imag_err",
    "Real": "Real_err",
    "Phase": "Phase_err",
    "|χ⁽²⁾|² (Homodyne)": "Homodyne_err",
}

# display name -> matplotlib mathtext y-axis label (plain Unicode
# superscript/subscript glyphs render as missing-glyph boxes in most fonts,
# so plotted labels use mathtext while the checkbox text itself stays plain
# Unicode — Qt widgets don't interpret mathtext syntax)
_HD_YLABEL = {
    "Imaginary": r"Im($\chi^{(2)}$)",
    "Real": r"Re($\chi^{(2)}$)",
    "Phase": "Phase (°)",
    "|χ⁽²⁾|² (Homodyne)": r"$|\chi^{(2)}|^2$",
}

# display name -> mathtext-safe legend label suffix (same reasoning as
# _HD_YLABEL — the checkbox display name itself contains raw Unicode
# superscript parentheses that most fonts lack a glyph for)
_HD_LEGEND_LABEL = {
    "Imaginary": "Im($\\chi^{(2)}$)",
    "Real": "Re($\\chi^{(2)}$)",
    "Phase": "Phase",
    "|χ⁽²⁾|² (Homodyne)": r"$|\chi^{(2)}|^2$",
}


# key used for the (sole) plotted line of a homodyne entry in
# SpectrumEntry.styles — heterodyne entries use the _HD_COMPONENT_COLUMN
# display names ("Imaginary"/"Real"/"Phase"/"|χ⁽²⁾|² (Homodyne)") instead
AMPLITUDE_COMPONENT = "__amplitude__"

_LINESTYLE_CHOICES = [("Solid", "-"), ("Dashed", "--"), ("Dotted", ":"), ("Dash-dot", "-.")]


@dataclass
class TraceStyle:
    """User-configurable overrides for a single plotted line. `None`/default
    values mean "use the automatic behavior _refresh_plot already has"."""
    color: str | None = None       # None = auto-assigned positional color
    linestyle: str = "-"
    axis: str = "primary"          # "primary" | "secondary"
    label: str | None = None       # None = use the computed legend label
    visible: bool = True

    def is_default(self) -> bool:
        return self == TraceStyle()


# components whose auto (un-overridden) axis isn't "primary" — Phase is in
# degrees, a very different scale from the other chi(2) components, so it
# defaults to the secondary axis rather than sharing the primary one
_DEFAULT_AXIS_BY_COMPONENT = {"Phase": "secondary"}


def _default_trace_style(component: str) -> TraceStyle:
    return TraceStyle(axis=_DEFAULT_AXIS_BY_COMPONENT.get(component, "primary"))


@dataclass
class PlotAnnotation:
    """A free-form element drawn on top of the plotted traces."""
    kind: str               # "vline" | "hline" | "region" | "text"
    x: float | None = None        # vline, text
    y: float | None = None        # hline, text
    x0: float | None = None       # region
    x1: float | None = None       # region
    text: str = ""
    color: str = "#000000"
    linestyle: str = "--"


class SpectrumEntry:
    """Lightweight container binding a ProcessedSpectrum to a display label."""
    def __init__(self, spectrum: ProcessedSpectrum, label: str, kind: str = "homodyne"):
        self.spectrum = spectrum
        self.label = label
        self.kind = kind   # "homodyne" | "heterodyne"
        self.styles: dict[str, TraceStyle] = {}

    def style_for(self, component: str) -> TraceStyle:
        return self.styles.setdefault(component, _default_trace_style(component))

    def __repr__(self):
        return f"SpectrumEntry({self.label})"


class ProcessedResultsTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.ui = Ui_Form()
        self.ui.setupUi(self)

        self._entries: list[SpectrumEntry] = []
        self._annotations: list[PlotAnnotation] = []

        self._setup_plot()
        self._setup_list()
        self._setup_colormap_combo()
        self._setup_normalization()
        self._setup_hd_component_checkboxes()
        self._refresh_legend_field_options()
        self._connect_signals()

    # ── Setup ─────────────────────────────────────────────────────────────────

    def _setup_plot(self):
        layout = QVBoxLayout(self.ui.plotWidget)
        layout.setContentsMargins(0, 0, 0, 0)
        self.plot_widget = SpectrumPlotWidget()
        layout.addWidget(self.plot_widget)

        # Host the plot + visualization-params tabs inside a nested QMainWindow
        # purely as a local dock area — QDockWidget requires a QMainWindow to
        # dock into, and docking against the app's single real MainWindow
        # would snap the panel to the whole app window's edges instead of
        # staying scoped to this tab's plot.
        outer_layout = self.ui.verticalLayout_4
        outer_layout.removeWidget(self.ui.visualizationParamsTabWidget)
        outer_layout.removeWidget(self.ui.plotWidget)

        self._plot_main_window = QMainWindow()
        self._plot_main_window.setCentralWidget(self.ui.plotWidget)

        self._vis_params_dock = QDockWidget("Visualization parameters", self._plot_main_window)
        self._vis_params_dock.setWidget(self.ui.visualizationParamsTabWidget)
        self._vis_params_dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )
        self._vis_params_dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self._plot_main_window.addDockWidget(Qt.DockWidgetArea.TopDockWidgetArea, self._vis_params_dock)

        outer_layout.addWidget(self._plot_main_window)

    def _setup_list(self):
        lw = self.ui.spectraList
        lw.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        lw.setDefaultDropAction(Qt.DropAction.MoveAction)
        lw.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        lw.model().rowsMoved.connect(self._refresh_plot)

    def _setup_colormap_combo(self):
        self.ui.colorMapComboBox.addItem("Default")
        for name in _all_colormaps():
            self.ui.colorMapComboBox.addItem(name)
        self.ui.colormapStartSpinner.setEnabled(False)
        self.ui.colormapStopSpinner.setEnabled(False)

    def _setup_normalization(self):
        self.ui.doubleSpinBox.setEnabled(False)
        self.ui.doubleSpinBox.setRange(500.0, 4000.0)
        self.ui.doubleSpinBox.setDecimals(1)
        self.ui.doubleSpinBox.setSingleStep(10.0)
        self.ui.doubleSpinBox.setValue(2900.0)
        self.ui.doubleSpinBox.setSuffix(" cm⁻¹")

    def _setup_hd_component_checkboxes(self):
        self._hd_checkboxes = {
            "Imaginary": self.ui.hdCheckImaginary,
            "Real": self.ui.hdCheckReal,
            "Phase": self.ui.hdCheckPhase,
            "|χ⁽²⁾|² (Homodyne)": self.ui.hdCheckHomodyne,
        }
        for cb in self._hd_checkboxes.values():
            cb.setToolTip(
                "Plot this component for heterodyne (HD-SFG) entries — "
                "has no effect on homodyne entries. Check multiple to overlay them."
            )
        self.ui.hdCheckShowError.setToolTip(
            "Shade the 95% CI error band around each heterodyne (HD-SFG) "
            "line — has no effect on homodyne entries."
        )

        phase_row = QHBoxLayout()
        phase_row.addWidget(QLabel("Phase range:"))
        self._phase_range_combo = QComboBox()
        self._phase_range_combo.addItem("[-180°, 180°]", userData="pm180")
        self._phase_range_combo.addItem("[0°, 360°)", userData="0to360")
        phase_row.addWidget(self._phase_range_combo)
        phase_row.addStretch()
        self.ui.verticalLayout_6.addLayout(phase_row)

    def _checked_hd_components(self) -> list[str]:
        return [name for name, cb in self._hd_checkboxes.items() if cb.isChecked()]

    def _connect_signals(self):
        self.ui.addSpectraButton.clicked.connect(self._on_add_from_file)
        self.ui.pushButton.clicked.connect(self._on_sort_by_metadata)
        self.ui.annotationsButton.clicked.connect(self._on_edit_annotations)
        self.ui.exportSelectedButton.clicked.connect(self._on_export_selected)
        self.ui.exportAllButton.clicked.connect(self._on_export_all)

        self.ui.spectraList.itemSelectionChanged.connect(self._refresh_plot)
        self.ui.spectraList.model().rowsMoved.connect(self._refresh_plot)

        self.ui.normalizationComboBox.currentIndexChanged.connect(
            self._on_normalization_changed
        )
        self.ui.doubleSpinBox.valueChanged.connect(self._refresh_plot)
        self.ui.colorMapComboBox.currentTextChanged.connect(
            self._on_colormap_changed
        )
        self.ui.colormapStartSpinner.valueChanged.connect(self._refresh_plot)
        self.ui.colormapStopSpinner.valueChanged.connect(self._refresh_plot)
        self.ui.offsetSpectraSpinner.valueChanged.connect(self._refresh_plot)
        for cb in self._hd_checkboxes.values():
            cb.toggled.connect(self._refresh_plot)
        self.ui.hdCheckShowError.toggled.connect(self._refresh_plot)
        self._phase_range_combo.currentIndexChanged.connect(self._refresh_plot)
        self.ui.legendFieldComboBox.currentIndexChanged.connect(self._refresh_plot)
        self.ui.xAxisLabelEdit.editingFinished.connect(self._refresh_plot)
        self.ui.yAxisLabelEdit.editingFinished.connect(self._refresh_plot)
        self.plot_widget.xRangeEdited.connect(self._refresh_plot)
        self.ui.spectraList.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.ui.spectraList.customContextMenuRequested.connect(self._on_context_menu)
        self.ui.spectraList.itemDoubleClicked.connect(self._on_item_double_clicked)

    # ── Public API — called by MainWindow ─────────────────────────────────────

    def add_results(self, results: dict):
        from sfg_app2.processing.hd_sfg import HDSFGResult
        from sfg_app2.processing.processed_spectrum import ProcessedSpectrum

        remembered: dict = {}
        loading = show_loading(self, "Adding results...")
        try:
            for filename, spectrum in results.items():
                kind = "homodyne"
                # convert HDSFGResult to ProcessedSpectrum for display, keeping
                # every component (Real/Imaginary/Phase/Homodyne + per-frame-avg
                # and error-bar variants) intact — no lossy column renaming
                if isinstance(spectrum, HDSFGResult):
                    df = spectrum.to_dataframe()
                    df.insert(0, "Frame", 1)
                    ps = ProcessedSpectrum(
                        df,
                        metadata  = spectrum.metadata,
                        history   = spectrum.history,
                    )
                    ps.provenance = spectrum.provenance
                    spectrum = ps
                    kind = "heterodyne"

                label = Path(filename).stem
                existing_idx = next(
                    (i for i, e in enumerate(self._entries) if e.label == label), None
                )
                if existing_idx is not None:
                    if self._same_content(self._entries[existing_idx].spectrum, spectrum):
                        continue   # byte-identical — nothing to resolve, skip silently
                    choice = self._prompt_conflict(
                        "Result already exists",
                        f'A result named "{label}" already exists in Results with '
                        f'different data. Overwrite it?',
                        ["Overwrite", "Keep Both", "Skip"], remembered,
                    )
                    if choice == "Skip":
                        continue
                    if choice == "Keep Both":
                        new_label = self._unique_label(label)
                        self._entries.append(SpectrumEntry(spectrum, new_label, kind=kind))
                        self.ui.spectraList.addItem(
                            self._make_list_item(len(self._entries) - 1)
                        )
                        continue
                    self._entries[existing_idx] = SpectrumEntry(spectrum, label, kind=kind)
                    continue

                self._entries.append(SpectrumEntry(spectrum, label, kind=kind))
                self.ui.spectraList.addItem(
                    self._make_list_item(len(self._entries) - 1)
                )
        finally:
            loading.close()

        self._refresh_legend_field_options()
        self._refresh_plot()

    def _prompt_conflict(self, title: str, message: str, options: list[str], remembered: dict) -> str:
        """Show a conflict dialog with the given button options (last option
        is the "do nothing" fallback, e.g. "Skip"). `remembered` is owned by
        the caller for one batch operation — once the user checks "apply to
        all", it holds their choice and every subsequent call returns it
        without prompting again."""
        if remembered.get("apply_to_all"):
            return remembered["choice"]

        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setText(message)
        buttons = {opt: box.addButton(opt, QMessageBox.ButtonRole.ActionRole) for opt in options}
        checkbox = QCheckBox("Apply this choice to all remaining conflicts")
        box.setCheckBox(checkbox)
        box.exec()
        clicked = box.clickedButton()
        choice = next((k for k, b in buttons.items() if b is clicked), options[-1])
        if checkbox.isChecked():
            remembered["choice"] = choice
            remembered["apply_to_all"] = True
        return choice

    # ── List management ───────────────────────────────────────────────────────

    def _entry_exists(self, label: str) -> bool:
        return any(e.label == label for e in self._entries)

    def _same_content(self, a: ProcessedSpectrum, b: ProcessedSpectrum) -> bool:
        """Exact comparison of the underlying spectral data only — ignores
        metadata (sample name, exposure, load timestamp), which doesn't
        reflect the actual measurement."""
        return a.data.reset_index(drop=True).equals(b.data.reset_index(drop=True))

    def _unique_label(self, label: str) -> str:
        """Mirrors _unique_path()'s ' (2)', ' (3)', ... convention, but
        against in-memory entry labels instead of filesystem paths."""
        n = 2
        candidate = f"{label} ({n})"
        while self._entry_exists(candidate):
            n += 1
            candidate = f"{label} ({n})"
        return candidate

    def _make_list_item(self, index: int) -> QListWidgetItem:
        entry = self._entries[index]
        item = QListWidgetItem(entry.label)
        item.setData(Qt.ItemDataRole.UserRole, index)
        return item

    def _ordered_entries(self) -> list[SpectrumEntry]:
        """Return entries in current list widget order (may differ from
        self._entries after drag-reorder)."""
        result = []
        for i in range(self.ui.spectraList.count()):
            item = self.ui.spectraList.item(i)
            idx = item.data(Qt.ItemDataRole.UserRole)
            if idx is not None and 0 <= idx < len(self._entries):
                result.append(self._entries[idx])
        return result

    def _selected_entries(self) -> list[SpectrumEntry]:
        ordered = self._ordered_entries()
        selected_rows = {
            self.ui.spectraList.row(item)
            for item in self.ui.spectraList.selectedItems()
        }
        return [e for i, e in enumerate(ordered) if i in selected_rows]

    # ── Normalization ─────────────────────────────────────────────────────────

    def _on_normalization_changed(self, index: int):
        self.ui.doubleSpinBox.setEnabled(index == 1)  # "Normalize to given wavenumber"
        self._refresh_plot()

    def _normalize_factor(self, x: np.ndarray, y: np.ndarray) -> float:
        """The scalar _normalize() multiplies y by — exposed separately so
        error bands can be scaled consistently with the plotted line."""
        mode = self.ui.normalizationComboBox.currentIndex()
        if mode == 0:
            return 1.0
        if mode == 1:
            target_wn = self.ui.doubleSpinBox.value()
            idx = np.argmin(np.abs(x - target_wn))
            ref = y[idx]
            # divide by the magnitude, not the signed value, so a negative
            # reference point doesn't invert the sign of the whole trace
            return 1.0 / abs(ref) if ref != 0 else 1.0
        if mode == 2:
            x_range = self.plot_widget.get_x_range()
            if x_range is not None:
                lo, hi = x_range
                mask = (x >= lo) & (x <= hi)
                y_visible = y[mask] if mask.any() else y
            else:
                y_visible = y
            peak = np.nanmax(np.abs(y_visible))
            return 1.0 / peak if peak != 0 else 1.0
        return 1.0

    def _normalize(self, x: np.ndarray, y: np.ndarray) -> np.ndarray:
        return y * self._normalize_factor(x, y)

    # ── Colormap ──────────────────────────────────────────────────────────────

    def _on_colormap_changed(self, name: str):
        is_default = name == "Default"
        self.ui.colormapStartSpinner.setEnabled(not is_default)
        self.ui.colormapStopSpinner.setEnabled(not is_default)
        self._refresh_plot()

    def _get_colors(self, n: int) -> list:
        if n == 0:
            return []
        cmap_name = self.ui.colorMapComboBox.currentText()
        if cmap_name == "Default" or n == 1:
            prop_cycle = plt.rcParams["axes.prop_cycle"]
            colors = [p["color"] for p in prop_cycle]
            return [colors[i % len(colors)] for i in range(n)]

        cmap = mpl.colormaps[cmap_name]   # was: mpl_cm.get_cmap(cmap_name)
        start = self.ui.colormapStartSpinner.value()
        stop = self.ui.colormapStopSpinner.value()
        if start >= stop:
            stop = min(start + 0.05, 1.0)
        positions = np.linspace(start, stop, n)
        return [cmap(p) for p in positions]

    # ── Plot ──────────────────────────────────────────────────────────────────

    def _legend_base(self, entry: SpectrumEntry, legend_field: str) -> str:
        if legend_field in ("Filename", "None"):
            return entry.label
        value = entry.spectrum.metadata.get(legend_field)
        return str(value) if value not in (None, "") else entry.label

    def _ylabel_for(self, hd_components: list[str], has_amplitude_line: bool) -> str:
        if hd_components:
            return (_HD_YLABEL.get(hd_components[0], "Amplitude")
                    if len(set(hd_components)) == 1 else "Amplitude")
        if has_amplitude_line:
            return ("Intensity" if self.ui.normalizationComboBox.currentIndex() == 0
                     else "Normalized Intensity")
        return ""

    def _draw_annotations(self):
        ax = self.plot_widget.ax
        for ann in self._annotations:
            try:
                if ann.kind == "region" and ann.x0 is not None and ann.x1 is not None:
                    ax.axvspan(ann.x0, ann.x1, color=ann.color, alpha=0.15, zorder=0.5, linewidth=0)
                elif ann.kind == "vline" and ann.x is not None:
                    ax.axvline(ann.x, color=ann.color, linestyle=ann.linestyle, zorder=3)
                elif ann.kind == "hline" and ann.y is not None:
                    ax.axhline(ann.y, color=ann.color, linestyle=ann.linestyle, zorder=3)
                elif ann.kind == "text" and ann.x is not None and ann.y is not None:
                    ax.text(ann.x, ann.y, ann.text, color=ann.color, zorder=4)
            except Exception as e:
                logger.warning("Could not draw annotation %r: %s", ann, e)

    def _refresh_plot(self):
        self.plot_widget.soft_clear()
        entries = self._selected_entries()
        if not entries:
            self.plot_widget.canvas.draw_idle()
            return

        offset_step = self.ui.offsetSpectraSpinner.value()
        checked_components = self._checked_hd_components()
        legend_field = self.ui.legendFieldComboBox.currentText()

        # determine x column — use Wavenumber if available, else Wavelength
        first_data = entries[0].spectrum.data
        first_x_col = "Wavenumber" if "Wavenumber" in first_data.columns else "Wavelength"
        x_label = "Wavenumber (cm$^{-1}$)" if first_x_col == "Wavenumber" else "Wavelength (nm)"

        # flatten to one spec per plotted line — a heterodyne entry produces
        # one line per checked component, a homodyne entry always one line —
        # so colors/offset are assigned per line, not per entry
        multi_line = len(entries) > 1 or len(checked_components) > 1
        # with only one spectrum selected, the filename is redundant (it's
        # already obvious from the selection/plot title) — show just the
        # component name instead
        single_entry = len(entries) == 1
        # the y-axis already names the sole component when it's Im/Re/Phase,
        # so repeating it on every line's legend would be redundant
        suppress_suffix = (
            len(checked_components) == 1
            and checked_components[0] in ("Imaginary", "Real", "Phase")
        )
        show_error = self.ui.hdCheckShowError.isChecked()

        specs = []   # (entry, component, y_col, err_col, label, style)
        for entry in entries:
            base_label = self._legend_base(entry, legend_field)
            if entry.kind == "heterodyne":
                for component in checked_components:
                    style = entry.style_for(component)
                    if not style.visible:
                        continue
                    y_col = _HD_COMPONENT_COLUMN[component]
                    err_col = _HD_ERROR_COLUMN[component]
                    if single_entry:
                        label = _HD_LEGEND_LABEL[component]
                    elif suppress_suffix:
                        label = base_label
                    elif multi_line:
                        label = f"{base_label} ({_HD_LEGEND_LABEL[component]})"
                    else:
                        label = base_label
                    specs.append((entry, component, y_col, err_col, style.label or label, style))
            else:
                style = entry.style_for(AMPLITUDE_COMPONENT)
                if style.visible:
                    specs.append((entry, None, "Intensity", None, style.label or base_label, style))

        colors = self._get_colors(len(specs))
        primary_hd, secondary_hd = [], []
        primary_amp, secondary_amp = False, False

        for i, (entry, component, y_col, err_col, label, style) in enumerate(specs):
            try:
                if entry.kind == "heterodyne":
                    # already one row per wavenumber point — bypass .frame(),
                    # which sorts by a "Wavelength" column heterodyne data
                    # doesn't have
                    data = entry.spectrum.data
                    x_col = "Wavenumber"
                else:
                    data = entry.spectrum.frame(1)
                    x_col = "Wavenumber" if "Wavenumber" in data.columns else "Wavelength"

                x = data[x_col].to_numpy()
                raw_y = data[y_col].to_numpy()
                if component == "Phase":
                    raw_y = wrap_phase_for_plot(
                        raw_y, self._phase_range_combo.currentData() == "0to360"
                    )
                is_secondary = style.axis == "secondary"
                # normalization is scoped to the primary axis — a secondary
                # axis is meant to show a trace in its own native units
                factor = 1.0 if is_secondary else self._normalize_factor(x, raw_y)
                y_offset = raw_y * factor + i * offset_step

                color = style.color or colors[i]
                target_ax = self.plot_widget.secondary_axis() if is_secondary else self.plot_widget.ax

                target_ax.plot(
                    x, y_offset,
                    color=color,
                    linestyle=style.linestyle,
                    label=label,
                )

                if show_error and entry.kind == "heterodyne" and err_col in data.columns:
                    y_err = data[err_col].to_numpy() * factor
                    target_ax.fill_between(
                        x, y_offset - y_err, y_offset + y_err,
                        color=color, alpha=0.25, linewidth=0,
                    )

                if entry.kind == "heterodyne":
                    (secondary_hd if is_secondary else primary_hd).append(component)
                elif is_secondary:
                    secondary_amp = True
                else:
                    primary_amp = True
            except Exception as e:
                logger.warning("Could not plot %s: %s", label, e)

        self._draw_annotations()

        handles, labels = self.plot_widget.ax.get_legend_handles_labels()
        if self.plot_widget.ax2 is not None:
            h2, l2 = self.plot_widget.ax2.get_legend_handles_labels()
            handles, labels = handles + h2, labels + l2
        if len(handles) > 1 and legend_field != "None":
            self.plot_widget.ax.legend(handles, labels, fontsize=8)

        primary_ylabel = self._ylabel_for(primary_hd, primary_amp)
        secondary_ylabel = (self._ylabel_for(secondary_hd, secondary_amp)
                             if self.plot_widget.ax2 is not None else None)

        self.ui.xAxisLabelEdit.setPlaceholderText(x_label)
        self.ui.yAxisLabelEdit.setPlaceholderText(primary_ylabel)
        custom_x = self.ui.xAxisLabelEdit.text().strip()
        custom_y = self.ui.yAxisLabelEdit.text().strip()

        self.plot_widget.set_labels(
            xlabel=custom_x or x_label,
            ylabel=custom_y or primary_ylabel,
            title=f"{len(entries)} spectrum/spectra",
            ylabel2=secondary_ylabel,
        )
        self.plot_widget.sync_x_range()

    # ── Metadata helpers ──────────────────────────────────────────────────────

    def _all_metadata_keys(self) -> list[str]:
        all_keys = set()
        for e in self._entries:
            all_keys.update(e.spectrum.metadata.keys())
        return sorted(all_keys)

    def _refresh_legend_field_options(self):
        combo = self.ui.legendFieldComboBox
        current = combo.currentText()
        combo.blockSignals(True)
        combo.clear()
        combo.addItems(["Filename", "None"] + self._all_metadata_keys())
        idx = combo.findText(current)
        combo.setCurrentIndex(idx if idx >= 0 else 0)
        combo.blockSignals(False)

    # ── Sort by metadata ──────────────────────────────────────────────────────

    def _on_sort_by_metadata(self):
        if not self._entries:
            return

        all_keys = self._all_metadata_keys()

        if not all_keys:
            QMessageBox.information(self, "No metadata", "No metadata found.")
            return

        key, ok = QInputDialog.getItem(
            self, "Sort by metadata", "Select metadata field:", all_keys, 0, False
        )
        if not ok:
            return

        def sort_key(entry: SpectrumEntry):
            val = entry.spectrum.metadata.get(key)
            if val is None:
                return ""
            try:
                return float(val)
            except (ValueError, TypeError):
                return str(val)

        self._entries.sort(key=sort_key)
        self._rebuild_list()
        self._refresh_plot()
        logger.info("Sorted spectra by metadata field '%s'.", key)

    def _rebuild_list(self):
        """Repopulate list widget from current self._entries order."""
        self.ui.spectraList.blockSignals(True)
        self.ui.spectraList.clear()
        for i, entry in enumerate(self._entries):
            item = QListWidgetItem(entry.label)
            item.setData(Qt.ItemDataRole.UserRole, i)
            self.ui.spectraList.addItem(item)
        self.ui.spectraList.blockSignals(False)

    # ── Add from file ─────────────────────────────────────────────────────────

    def _get_active_patterns(self) -> list[list[str]] | None:
        """Pull active patterns from MainWindow if available and toggle is on."""
        try:
            main = self.window()
            if hasattr(main, "use_metadata_patterns") and not main.use_metadata_patterns:
                return None
            if hasattr(main, "pattern_manager"):
                return main.pattern_manager.active_patterns
        except Exception:
            pass
        return None

    def _get_role_kwargs(self) -> dict:
        try:
            main = self.window()
            if hasattr(main, "matching_settings"):
                return main.matching_settings.role_kwargs()
        except Exception:
            pass
        from sfg_app2.processing.utils import DEFAULT_ROLE_SUFFIXES
        return {"role_mode": "suffix", "role_values": DEFAULT_ROLE_SUFFIXES, "role_field": ""}

    def _on_add_from_file(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Load processed spectra", "",
            "CSV files (*.csv);;All files (*.*)"
        )
        if not paths:
            return

        from sfg_app2.processing.utils import resolve_role
        import pandas as pd

        patterns = self._get_active_patterns()
        pattern_map = {len(p): p for p in patterns} if patterns else {}
        role_kwargs = self._get_role_kwargs()

        added, skipped, failed, renamed = 0, 0, 0, 0
        remembered: dict = {}
        loading = show_loading(self, "Loading files...")
        for path_str in paths:
            path = Path(path_str)
            try:
                header_lines, provenance, metadata = self._parse_export_header(path)
                df = self._load_csv_skip_comments(path)

                # parse filename metadata if patterns are active
                # manual metadata from header always wins (update order matters)
                if pattern_map:
                    from sfg_app2.processing.data_file import DataFile
                    # strip a "Keep Both" duplicate suffix (e.g. "sample1 (2)")
                    # before parsing filename fields, so it doesn't get
                    # absorbed into the last underscore-separated field
                    metadata_stem = re.sub(r"\s\(\d+\)$", "", path.stem)
                    clean_stem, _, _ = resolve_role(
                        metadata_stem, role_kwargs["role_mode"], role_kwargs["role_values"]
                    )
                    n_parts = len(clean_stem.split("_"))
                    fields = pattern_map.get(n_parts)
                    if fields:
                        metadata_path = (
                            path.with_stem(metadata_stem)
                            if metadata_stem != path.stem else path
                        )
                        parsed = DataFile._parse_filename_metadata(metadata_path, fields)
                        # merge: parsed first, then header metadata overwrites
                        merged_metadata = {**parsed, **metadata}
                    else:
                        merged_metadata = metadata
                else:
                    merged_metadata = metadata

                # ensure Frame column exists
                if "Frame" not in df.columns:
                    df.insert(0, "Frame", 1)

                spectrum = ProcessedSpectrum(
                    df,
                    metadata=merged_metadata,
                    history=provenance.get("history_list", ["loaded_from_file"]),
                )
                spectrum.provenance = provenance

                kind = provenance.get("kind")
                if kind is None:
                    # no/old-style header — fall back to sniffing columns
                    kind = ("heterodyne"
                            if {"Real", "Imaginary", "Phase", "Homodyne"}.issubset(df.columns)
                            else "homodyne")

                label = path.stem
                existing_idx = next(
                    (i for i, e in enumerate(self._entries) if e.label == label), None
                )
                if existing_idx is None:
                    self._entries.append(SpectrumEntry(spectrum, label, kind=kind))
                    self.ui.spectraList.addItem(
                        self._make_list_item(len(self._entries) - 1)
                    )
                    added += 1
                elif self._same_content(self._entries[existing_idx].spectrum, spectrum):
                    skipped += 1
                    logger.info("Skipping identical duplicate: %s", label)
                else:
                    choice = self._prompt_conflict(
                        "Name collision, different content",
                        f'"{label}" already exists in Results with different '
                        f'data. Overwrite it?',
                        ["Overwrite", "Keep Both", "Skip"], remembered,
                    )
                    if choice == "Skip":
                        skipped += 1
                    elif choice == "Keep Both":
                        new_label = self._unique_label(label)
                        self._entries.append(SpectrumEntry(spectrum, new_label, kind=kind))
                        self.ui.spectraList.addItem(
                            self._make_list_item(len(self._entries) - 1)
                        )
                        added += 1
                        renamed += 1
                    else:  # Overwrite
                        self._entries[existing_idx] = SpectrumEntry(spectrum, label, kind=kind)
                        added += 1

            except Exception as e:
                logger.warning("Could not load %s: %s", path.name, e)
                failed += 1
        loading.close()

        if added:
            self._refresh_legend_field_options()
            self._refresh_plot()

        msg_parts = []
        if added:
            msg_parts.append(f"{added} added")
        if renamed:
            msg_parts.append(f"{renamed} kept as a new copy (renamed)")
        if skipped:
            msg_parts.append(f"{skipped} duplicate(s) skipped")
        if failed:
            msg_parts.append(f"{failed} failed (check terminal)")
        if msg_parts:
            self.statusBar_message(", ".join(msg_parts) + ".")


    def statusBar_message(self, msg: str):
        """Post a message to MainWindow status bar if accessible."""
        try:
            self.window().statusBar().showMessage(msg)
        except Exception:
            pass


    @staticmethod
    def _load_csv_skip_comments(path: Path) -> "pd.DataFrame":
        """Load CSV, skipping # comment lines in the header."""
        import pandas as pd
        return pd.read_csv(path, comment="#")


    @staticmethod
    def _parse_export_header(path: Path) -> tuple[list[str], dict, dict]:
        """Parse the # comment header written by _write_csv_with_provenance.
        Returns (raw_header_lines, provenance_dict, metadata_dict).
        Gracefully returns empty dicts if the file has no such header.
        """
        header_lines = []
        provenance: dict = {}
        metadata: dict = {}

        with open(path, encoding="utf-8") as f:
            for line in f:
                if not line.startswith("#"):
                    break
                header_lines.append(line.rstrip())

        if not header_lines:
            metadata["source_filename"] = path.name
            return header_lines, provenance, metadata

        # parse key: value pairs from comment lines
        raw: dict[str, str] = {}
        current_section = None
        for line in header_lines:
            content = line.lstrip("# ").strip()
            if not content or content.startswith("---"):
                current_section = content.strip("- ").lower() if "---" in content else None
                continue
            if ":" in content:
                k, _, v = content.partition(":")
                raw[k.strip().lower()] = v.strip()

        # source files → provenance
        provenance["signal"]               = raw.get("signal", "N/A")
        provenance["background"]           = raw.get("background", "N/A")
        provenance["reference"]            = raw.get("reference", "N/A")
        provenance["reference_background"] = raw.get("reference background", "N/A")

        # history string → list
        history_str = raw.get("history", "")
        provenance["history_list"] = (
            [s.strip() for s in history_str.split("→")]
            if history_str else ["loaded_from_file"]
        )

        # processing params → nested provenance
        is_heterodyne = raw.get("type", "").strip().lower() == "heterodyne"
        provenance["kind"] = "heterodyne" if is_heterodyne else "homodyne"

        def parse_excluded(key: str) -> list[int]:
            v = raw.get(key, "").strip().lower()
            if not v or v == "none":
                return []
            return [int(x) for x in v.split(",") if x.strip()]

        provenance["excluded_frames"] = {
            "signal":               parse_excluded("excluded frames signal"),
            "background":           parse_excluded("excluded frames background"),
            "reference":            parse_excluded("excluded frames reference"),
            "reference_background": parse_excluded("excluded frames reference_background"),
        }

        if is_heterodyne:
            provenance["despike"] = {
                "signal":               {"window": raw.get("despike signal window"),
                                          "threshold": raw.get("despike signal threshold")},
                "background":           {"window": raw.get("despike background window"),
                                          "threshold": raw.get("despike background threshold")},
                "reference":            {"window": raw.get("despike reference window"),
                                          "threshold": raw.get("despike reference threshold")},
                "reference_background": {"window": raw.get("despike reference_background window"),
                                          "threshold": raw.get("despike reference_background threshold")},
            }
            provenance["background_subtraction"] = {
                "bg_offset":            raw.get("bg subtraction offset"),
                "edge_left":            raw.get("bg subtraction edge_left_pts"),
                "edge_right":           raw.get("bg subtraction edge_right_pts"),
                "bg_smoothing_window":  raw.get("bg smoothing window"),
                "bg_smoothing_order":   raw.get("bg smoothing order"),
                "sig_smoothing_window": raw.get("signal smoothing window"),
                "sig_smoothing_order":  raw.get("signal smoothing order"),
            }
            provenance["fft_filter"] = {
                "window_type":     raw.get("fft window_type"),
                "fft_start":       raw.get("fft start_pts"),
                "fft_end":         raw.get("fft end_pts"),
                "hg_left":         raw.get("fft hg_left_pts"),
                "hg_right":        raw.get("fft hg_right_pts"),
                "mask_start":      raw.get("fft mask_start_pts"),
                "mask_end":        raw.get("fft mask_end_pts"),
                "mask_transition": raw.get("fft mask_transition_pts"),
                "mask_factor":     raw.get("fft mask_factor"),
            }
            provenance["normalization"] = {
                "sample_exposure_s":    raw.get("normalization sample_exposure_s"),
                "reference_exposure_s": raw.get("normalization reference_exposure_s"),
                "phase_correction_deg": raw.get("normalization phase_correction_deg"),
            }
            provenance["upconversion"] = {"wavelength_nm": raw.get("upconversion wavelength_nm")}
            provenance["n_frames"] = raw.get("frames processed")
        else:
            provenance["despike"] = {
                "signal":               {"window": raw.get("despike signal window"),
                                          "threshold": raw.get("despike signal threshold")},
                "background":           {"window": raw.get("despike background window"),
                                          "threshold": raw.get("despike background threshold")},
                "reference":            {"window": raw.get("despike reference window"),
                                          "threshold": raw.get("despike reference threshold")},
                "reference_background": {"window": raw.get("despike reference_background window"),
                                          "threshold": raw.get("despike reference_background threshold")},
            }
            provenance["background_subtraction"] = {
                "applied":       raw.get("background subtraction", "").lower() == "applied",
                "signal_offset": raw.get("signal offset"),
                "ref_offset":    raw.get("ref offset"),
            }
            provenance["normalization"] = {
                "applied": raw.get("normalization", "").lower() == "applied",
            }
            provenance["upconversion"] = {
                "applied":        raw.get("upconversion", "").lower() == "applied",
                "wavelength_nm":  raw.get("wavelength"),
            }

        # sample metadata
        metadata["source_filename"] = path.name
        metadata["label"]           = raw.get("label", path.stem)
        metadata["exported"]        = raw.get("exported")

        # any remaining keys under "sample metadata" section go into metadata
        in_meta = False
        for line in header_lines:
            content = line.lstrip("#").strip()
            if "sample metadata" in content.lower():
                in_meta = True
                continue
            if in_meta and content.startswith("---"):
                in_meta = False
            if in_meta and ":" in content:
                k, _, v = content.partition(":")
                k = k.strip().lstrip("#").strip()
                if k and not k.startswith("---"):
                    metadata[k] = v.strip()

        return header_lines, provenance, metadata

    # ── Export ────────────────────────────────────────────────────────────────

    def _export_entries(self, entries: list[SpectrumEntry]):
        if not entries:
            QMessageBox.information(self, "Nothing to export", "No spectra to export.")
            return

        folder = QFileDialog.getExistingDirectory(self, "Select export folder")
        if not folder:
            return

        remembered: dict = {}
        exported, skipped, failed = 0, 0, 0
        loading = show_loading(self, "Exporting...")
        for entry in entries:
            try:
                out_path = Path(folder) / f"{entry.label}.csv"
                if out_path.exists():
                    choice = self._prompt_conflict(
                        "File already exists",
                        f'"{out_path.name}" already exists in {folder}.',
                        ["Overwrite", "Keep Both", "Skip"], remembered,
                    )
                    if choice == "Skip":
                        skipped += 1
                        continue
                    if choice == "Keep Both":
                        out_path = self._unique_path(out_path)
                self._write_csv_with_provenance(entry, out_path)
                exported += 1
                logger.info("Exported %s → %s", entry.label, out_path)
            except Exception as e:
                logger.warning("Could not export %s: %s", entry.label, e)
                failed += 1
        loading.close()

        msg = f"{exported} file(s) exported to {folder}."
        if skipped:
            msg += f"\n{skipped} file(s) skipped."
        if failed:
            msg += f"\n{failed} file(s) failed — check terminal for details."
        QMessageBox.information(self, "Export complete", msg)

    def _unique_path(self, path: Path) -> Path:
        n = 2
        candidate = path.parent / f"{path.stem} ({n}){path.suffix}"
        while candidate.exists():
            n += 1
            candidate = path.parent / f"{path.stem} ({n}){path.suffix}"
        return candidate

    def _write_csv_with_provenance(self, entry: SpectrumEntry, out_path: Path):
        """Write a CSV with a commented provenance header, readable by pandas
        via pd.read_csv(path, comment='#').
        """
        from datetime import datetime

        spectrum = entry.spectrum
        provenance = getattr(spectrum, "provenance", None) or \
                    _build_provenance_from_history(spectrum)

        header_lines = ["# SFG-App export"]
        if entry.kind == "heterodyne":
            header_lines.append("# Type:        heterodyne")
        header_lines += [
            f"# Label:       {entry.label}",
            f"# Exported:    {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"# History:     {' → '.join(spectrum.history)}",
            "#",
            "# --- Source files ---",
            f"# Signal:               {provenance.get('signal', 'N/A')}",
            f"# Background:           {provenance.get('background', 'N/A')}",
            f"# Reference:            {provenance.get('reference', 'N/A')}",
            f"# Reference background: {provenance.get('reference_background', 'N/A')}",
            "#",
            "# --- Processing parameters ---",
        ]

        if entry.kind == "heterodyne":
            header_lines += self._format_heterodyne_provenance(provenance)
        else:
            header_lines += self._format_homodyne_provenance(provenance)

        # sample metadata
        if spectrum.metadata:
            header_lines += [
                "#",
                "# --- Sample metadata ---",
            ]
            for k, v in spectrum.metadata.items():
                if v is not None:
                    header_lines.append(f"#   {k:<25} {v}")

        header_lines.append("#")

        # write header + data
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            for line in header_lines:
                f.write(line + "\n")
            spectrum.data.to_csv(f, index=False)

    @staticmethod
    def _format_homodyne_provenance(provenance: dict) -> list[str]:
        lines = []

        # despike — per component, same shape/format as heterodyne
        d = provenance.get("despike", {})

        def comp(key, label):
            c = d.get(key) or {}
            return [
                f"# Despike {label} window:      {c.get('window', 'N/A')}",
                f"# Despike {label} threshold:   {c.get('threshold', 'N/A')}",
            ]

        lines += comp("signal", "signal")
        lines += comp("background", "background")
        lines += comp("reference", "reference")
        lines += comp("reference_background", "reference_background")

        # excluded frames — per component
        excl = provenance.get("excluded_frames", {})

        def excl_line(key, label):
            ids = excl.get(key) or []
            return f"# Excluded frames {label}:      {','.join(map(str, ids)) if ids else 'none'}"

        lines.append(excl_line("signal", "signal"))
        lines.append(excl_line("background", "background"))
        lines.append(excl_line("reference", "reference"))
        lines.append(excl_line("reference_background", "reference_background"))

        # background subtraction
        bg = provenance.get("background_subtraction", {})
        if bg.get("applied"):
            lines += [
                f"# Background subtraction: applied",
                f"#   signal offset:      {bg.get('signal_offset', 'None')}",
                f"#   ref offset:         {bg.get('ref_offset', 'None')}",
            ]
        else:
            lines.append("# Background subtraction: not applied")

        # normalization
        norm = provenance.get("normalization", {})
        lines.append(
            f"# Normalization:        {'applied' if norm.get('applied') else 'not applied'}"
        )

        # upconversion
        upconv = provenance.get("upconversion", {})
        if upconv.get("applied"):
            lines += [
                f"# Upconversion:         applied",
                f"#   wavelength:         {upconv.get('wavelength_nm', 'N/A')} nm",
            ]
        else:
            lines.append("# Upconversion:         not applied")

        return lines

    @staticmethod
    def _format_heterodyne_provenance(provenance: dict) -> list[str]:
        d    = provenance.get("despike", {})
        bg   = provenance.get("background_subtraction", {})
        fft  = provenance.get("fft_filter", {})
        norm = provenance.get("normalization", {})
        up   = provenance.get("upconversion", {})

        def comp(key, label):
            c = d.get(key, {})
            return [
                f"# Despike {label} window:      {c.get('window', 'N/A')}",
                f"# Despike {label} threshold:   {c.get('threshold', 'N/A')}",
            ]

        excl = provenance.get("excluded_frames", {})

        def excl_line(key, label):
            ids = excl.get(key) or []
            return f"# Excluded frames {label}:      {','.join(map(str, ids)) if ids else 'none'}"

        lines = []
        lines += comp("signal", "signal")
        lines += comp("background", "background")
        lines += comp("reference", "reference")
        lines += comp("reference_background", "reference_background")
        lines.append(excl_line("signal", "signal"))
        lines.append(excl_line("background", "background"))
        lines.append(excl_line("reference", "reference"))
        lines.append(excl_line("reference_background", "reference_background"))
        lines += [
            f"# BG subtraction offset:              {bg.get('bg_offset', 'N/A')}",
            f"# BG subtraction edge_left_pts:       {bg.get('edge_left', 'N/A')}",
            f"# BG subtraction edge_right_pts:      {bg.get('edge_right', 'N/A')}",
            f"# BG smoothing window:                {bg.get('bg_smoothing_window', 'N/A')}",
            f"# BG smoothing order:                 {bg.get('bg_smoothing_order', 'N/A')}",
            f"# Signal smoothing window:            {bg.get('sig_smoothing_window', 'N/A')}",
            f"# Signal smoothing order:             {bg.get('sig_smoothing_order', 'N/A')}",
            f"# FFT window_type:                    {fft.get('window_type', 'N/A')}",
            f"# FFT start_pts:                      {fft.get('fft_start', 'N/A')}",
            f"# FFT end_pts:                        {fft.get('fft_end', 'N/A')}",
            f"# FFT hg_left_pts:                    {fft.get('hg_left', 'N/A')}",
            f"# FFT hg_right_pts:                   {fft.get('hg_right', 'N/A')}",
            f"# FFT mask_start_pts:                 {fft.get('mask_start', 'N/A')}",
            f"# FFT mask_end_pts:                   {fft.get('mask_end', 'N/A')}",
            f"# FFT mask_transition_pts:             {fft.get('mask_transition', 'N/A')}",
            f"# FFT mask_factor:                    {fft.get('mask_factor', 'N/A')}",
            f"# Normalization sample_exposure_s:     {norm.get('sample_exposure_s', 'N/A')}",
            f"# Normalization reference_exposure_s:  {norm.get('reference_exposure_s', 'N/A')}",
            f"# Normalization phase_correction_deg:  {norm.get('phase_correction_deg', 'N/A')}",
            f"# Upconversion wavelength_nm:          {up.get('wavelength_nm', 'N/A')}",
            f"# Frames processed:                    {provenance.get('n_frames', 'N/A')}",
        ]
        return lines

    def _on_export_selected(self):
        self._export_entries(self._selected_entries())

    def _on_export_all(self):
        self._export_entries(self._ordered_entries())

    # ── Context menu ─────────────────────────────────

    def _on_context_menu(self, pos):
        item = self.ui.spectraList.itemAt(pos)
        if item is None:
            return

        selected = self._selected_entries()
        if not selected:
            return

        n = len(selected)
        label = f"{n} spectrum/spectra" if n > 1 else f"\"{selected[0].label}\""

        menu = QMenu(self)
        metadata_action = menu.addAction(f"Review / Edit metadata — {label}")
        params_action = menu.addAction(f"View processing parameters — {label}")
        menu.addSeparator()
        trace_props_action = menu.addAction("Trace properties...")
        menu.addSeparator()
        remove_action = menu.addAction(f"Remove {label}")

        action = menu.exec(self.ui.spectraList.viewport().mapToGlobal(pos))

        if action == metadata_action:
            self._on_review_metadata(selected)
        elif action == params_action:
            self._on_view_processing_params(selected)
        elif action == trace_props_action:
            self._on_trace_properties(selected)
        elif action == remove_action:
            self._on_remove(selected)

    def _on_edit_annotations(self):
        from sfg_app2.app.dialogs.plot_annotations_dialog import PlotAnnotationsDialog
        dialog = PlotAnnotationsDialog(self._annotations, self)
        if dialog.exec() == dialog.DialogCode.Accepted:
            self._annotations = dialog.result_annotations()
            self._refresh_plot()

    def _entry_component_rows(self, entry: SpectrumEntry) -> list[tuple[str, str]]:
        """(style_key, display_name) rows to show in the trace properties
        dialog for this entry — all HD components for heterodyne entries
        (not just the currently-checked ones), or a single amplitude row
        for homodyne entries."""
        if entry.kind == "heterodyne":
            return [(component, component) for component in _HD_COMPONENT_COLUMN]
        return [(AMPLITUDE_COMPONENT, "Amplitude")]

    def _on_trace_properties(self, entries: list[SpectrumEntry]):
        from sfg_app2.app.dialogs.trace_style_dialog import TraceStyleDialog
        rows = [
            (entry, key, display_name)
            for entry in entries
            for key, display_name in self._entry_component_rows(entry)
        ]
        dialog = TraceStyleDialog(rows, self)
        if dialog.exec() == dialog.DialogCode.Accepted:
            self._refresh_plot()

    def _on_item_double_clicked(self, item: QListWidgetItem):
        idx = item.data(Qt.ItemDataRole.UserRole)
        if idx is None or not (0 <= idx < len(self._entries)):
            return
        self.ui.spectraList.clearSelection()
        item.setSelected(True)
        self._on_trace_properties([self._entries[idx]])


    def _on_review_metadata(self, entries: list[SpectrumEntry]):
        from sfg_app2.app.dialogs.metadata_edit_dialog import MetadataEditDialog
        # MetadataEditDialog expects objects with a .metadata dict and optional .path
        # wrap each entry's spectrum, which has .metadata already
        spectra = [e.spectrum for e in entries]
        # attach label as a stand-in for path.name so the dialog header is readable
        for e, s in zip(entries, spectra):
            if not hasattr(s, "path"):
                s._display_name = e.label   # temporary attr for dialog display
        dialog = MetadataEditDialog(spectra, parent=self)
        dialog.exec()

    def _on_view_processing_params(self, entries: list[SpectrumEntry]):
        from sfg_app2.app.dialogs.processing_params_dialog import ProcessingParamsDialog
        dialog = ProcessingParamsDialog(entries, parent=self)
        dialog.exec()


    def _on_remove(self, entries: list[SpectrumEntry]):
        n = len(entries)
        label = f"{n} spectrum/spectra" if n > 1 else f"\"{entries[0].label}\""
        reply = QMessageBox.question(
            self, "Remove",
            f"Remove {label} from the results list?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.No:
            return

        labels_to_remove = {e.label for e in entries}
        self._entries = [e for e in self._entries if e.label not in labels_to_remove]
        self._rebuild_list()
        self._refresh_legend_field_options()
        self._refresh_plot()
        logger.info("Removed %d spectrum/spectra from results.", n)