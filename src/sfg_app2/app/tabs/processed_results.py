from __future__ import annotations
import logging
import csv
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt
import matplotlib as mpl

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QListWidgetItem, QFileDialog,
    QMessageBox, QAbstractItemView, QInputDialog, QMenu, QCheckBox,
    QComboBox, QLabel, QSizePolicy, QFrame, QPushButton,
)

from sfg_app2.app.ui.ui_processed_results_tab import Ui_Form
from sfg_app2.app.widgets.spectrum_plot_widget import SpectrumPlotWidget
from sfg_app2.app.widgets.dockable_panels import DockablePlotPanel
from sfg_app2.processing.processed_spectrum import ProcessedSpectrum
from sfg_app2.app.utils.loading_indicator import show_loading
from sfg_app2.app.utils.phase_wrap import wrap_phase_for_plot
from sfg_app2.app.utils.plotting_settings import PlottingSettings
# Re-exported for the dialogs and for callers that still import these
# from here; they live in trace_style.py so those dialogs don't have to
# import this tab module back.
from sfg_app2.app.tabs.trace_style import (   # noqa: F401
    AMPLITUDE_COMPONENT, HiddenReason, PlotAnnotation, TraceStyle,
    _DEFAULT_AXIS_BY_COMPONENT, _LINESTYLE_CHOICES, _MARKER_CHOICES,
    _default_trace_style, is_customized, resolve_visibility,
)
from sfg_app2.app.utils.app_logging import LOG_FILE
from sfg_app2.processing import provenance as provenance_mod
from sfg_app2.processing import fitting as fitting_mod
from sfg_app2.app.utils import notebook_export, notebook_plotting

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
    return provenance_mod.build_provenance_from_history(spectrum)

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
    "Imaginary": r"Im($\chi^{(2)}$) (a.u.)",
    "Real": r"Re($\chi^{(2)}$) (a.u.)",
    "Phase": "Phase (°)",
    "|χ⁽²⁾|² (Homodyne)": r"$|\chi^{(2)}|^2$ (a.u.)",
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


# fit-derived column name -> the HD component display name (matching
# _HD_COMPONENT_COLUMN's keys) it's derived from -- heterodyne only, used
# to match a fit curve's color to its corresponding data component's
# color when that component is currently checked (see _assign_spec_colors)
_FIT_TO_HD_COMPONENT = {
    "Fit (real)": "Real",
    "Fit (imaginary)": "Imaginary",
    "Fit (homodyne)": "|χ⁽²⁾|² (Homodyne)",
}


class SpectrumEntry:
    """Lightweight container binding a ProcessedSpectrum to a display label."""
    def __init__(self, spectrum: ProcessedSpectrum, label: str, kind: str = "homodyne"):
        self.spectrum = spectrum
        self.label = label
        self.kind = kind   # "homodyne" | "heterodyne"
        self.styles: dict[str, TraceStyle] = {}
        # (column_name, display_label) pairs for a reloaded fit's derived
        # curves (fit total/real/imaginary, each peak) -- column_name
        # doubles as the style_for() key. Empty unless the loaded file
        # carried a "Fit json:" provenance line -- see _on_add_from_file().
        self.fit_components: list[tuple[str, str]] = []
        # Whether this entry's checkbox is ticked in the spectra list --
        # this, not list *selection*, is what _refresh_plot() draws.
        # Selection is still used for context-menu/metadata/trace-property
        # actions, which are independent of what's currently plotted.
        self.checked: bool = False

    def style_for(self, component: str) -> TraceStyle:
        return self.styles.setdefault(component, _default_trace_style(component))

    def __repr__(self):
        return f"SpectrumEntry({self.label})"


def _customized_components(entry: SpectrumEntry) -> list[str]:
    """Components this entry carries a real style override for."""
    return [
        component for component, style in entry.styles.items()
        if is_customized(style, component)
    ]


def _entry_display_text(entry: SpectrumEntry) -> str:
    """List-item text for an entry -- appends "(fitted)" when it carries
    a loaded fit's derived curves, mirroring fitting_tab.py's own
    _entry_display_text()'s "[heterodyne] " prefix convention for the
    same kind of "extra fact about this entry" labeling. A "◆" marks
    per-trace style overrides, which are otherwise invisible until you
    open the trace properties dialog -- and which can hide a line on
    their own."""
    text = f"{entry.label} (fitted)" if entry.fit_components else entry.label
    return f"{text} ◆" if _customized_components(entry) else text


@dataclass
class PlotSpec:
    """One plotted line, flattened out of an entry.

    A heterodyne entry yields one spec per checked HD component, a
    homodyne entry one for its amplitude, and either kind adds one per
    fit-derived curve -- so colors and styling are resolved per line
    while the offset stays keyed to the owning entry.
    """
    entry: SpectrumEntry
    component: str | None   # HD component display name; None for amplitude/fit rows
    y_col: str
    err_col: str | None
    label: str
    style: TraceStyle
    is_fit: bool


@dataclass
class _AxisUsage:
    """Which quantities ended up on each axis, for labeling them after
    the traces are drawn."""
    primary_hd: list[str] = field(default_factory=list)
    secondary_hd: list[str] = field(default_factory=list)
    primary_amp: bool = False
    secondary_amp: bool = False


class ProcessedResultsTab(QWidget, DockablePlotPanel):
    def __init__(self, parent=None, plotting_settings: PlottingSettings | None = None):
        super().__init__(parent)
        self.ui = Ui_Form()
        self.ui.setupUi(self)

        # Shared with MainWindow when available, so a marker-size change in
        # Plotting Settings takes effect on the next replot -- falls back to
        # a standalone instance (its own on-disk load) for tests/ad-hoc use.
        self._plotting_settings = plotting_settings or PlottingSettings()

        self._entries: list[SpectrumEntry] = []
        self._annotations: list[PlotAnnotation] = []

        # before _setup_plot(), which reparents the Data display tab into
        # its dock -- the checkbox rides along with it
        self._setup_data_display_controls()
        self._setup_plot()
        self._setup_list()
        self._setup_colormap_combo()
        self._setup_normalization()
        self._setup_hd_component_checkboxes()
        self._setup_legend_fields()
        self._connect_signals()

    # ── Setup ─────────────────────────────────────────────────────────────────

    def _setup_plot(self):
        layout = QVBoxLayout(self.ui.plotWidget)
        layout.setContentsMargins(0, 0, 0, 0)
        self.plot_widget = SpectrumPlotWidget()
        layout.addWidget(self.plot_widget)

        # Everything below becomes its own dock (DockablePlotPanel — same
        # nested-QMainWindow mechanism used by the Process/Review panels,
        # since QDockWidget needs a QMainWindow to dock into and docking
        # against the app's single real MainWindow would snap panels to
        # the whole app window instead of staying scoped to this tab) --
        # including the plot itself and the spectra list, so the whole
        # tab is user-customizable the same way FittingTab's docks are.
        outer_layout = self.ui.verticalLayout_4
        outer_layout.removeWidget(self.ui.visualizationParamsTabWidget)
        outer_layout.removeWidget(self.ui.plotWidget)

        # Controls in these three tabs are stretched to fill the dock's
        # width (expand_horizontally=True below) -- lift each widget's
        # own maximumSize cap and Expanding-ify it too, otherwise the
        # dock-level flag alone has nothing to hand the extra width to.
        self._stretch_panel_controls()
        self._insert_panel_separators()

        fit_components_widget = self._setup_fit_component_checkboxes()
        sections = [
            ("data_display", "Data display", self.ui.dataDisplayTab, True),
            ("hd_components", "HD-SFG components", self.ui.hdComponentsTab, False),
            ("fit_components", "Fit components", fit_components_widget, False),
            ("colors", "Colors", self.ui.colorsTab, True),
            ("labels", "Labels, legend & annotations", self.ui.labelsTab, True),
        ]
        for _, _, widget, _expand in sections:
            widget.setParent(None)
        self.ui.visualizationParamsTabWidget.deleteLater()

        # verticalLayoutWidget is the Designer-built list pane (its own
        # self-contained layout: add/sort buttons, spectraList, export
        # buttons) -- detach it from the splitter so it can become a dock
        # too, same as the plot widget above.
        list_container = self.ui.verticalLayoutWidget

        self._init_dock_area()
        self._add_dock("spectra_list", "Spectra", list_container, fill=True,
                        tabify=False, area=Qt.DockWidgetArea.LeftDockWidgetArea)
        self._add_dock("plot", "Plot", self.ui.plotWidget, fill=True,
                        tabify=False, area=Qt.DockWidgetArea.RightDockWidgetArea)
        for key, title, widget, expand in sections:
            self._add_dock(key, title, widget, area=Qt.DockWidgetArea.TopDockWidgetArea,
                            expand_horizontally=expand)

        # Both list_container and plotWidget were just reparented into
        # dock wrappers above, so the splitter (and its now-empty
        # verticalLayoutWidget_2 shell) holds nothing worth keeping.
        self.ui.horizontalLayout_4.removeWidget(self.ui.splitter)
        self.ui.splitter.deleteLater()
        self.ui.horizontalLayout_4.addWidget(self._dock_main_window)

    def _stretch_panel_controls(self):
        """Lift the .ui-defined maximumSize cap and make each control
        Expanding-horizontal, so "Data display"/"Colors"/"Labels, legend
        & annotations" fill their dock's width instead of staying
        pinned small at the top-left. Each row's trailing Designer
        spacer (itself Expanding by default) is removed so it stops
        splitting the leftover space with the control instead of the
        control claiming all of it; each row's own QLabel is left
        untouched so labels stay compact while their control stretches.
        """
        def expand(widget):
            widget.setMaximumWidth(16777215)   # QWIDGETSIZE_MAX
            policy = widget.sizePolicy()
            policy.setHorizontalPolicy(QSizePolicy.Policy.Expanding)
            widget.setSizePolicy(policy)

        for widget in (self.ui.normalizationComboBox, self.ui.doubleSpinBox,
                       self.ui.offsetSpectraSpinner):
            expand(widget)
        self.ui.horizontalLayout_7.removeItem(self.ui.horizontalSpacer_2)

        for widget in (self.ui.colorMapComboBox, self.ui.colormapStartSpinner,
                       self.ui.colormapStopSpinner):
            expand(widget)
        self.ui.horizontalLayout_8.removeItem(self.ui.horizontalSpacer_3)

        for widget in (self.ui.xAxisLabelEdit, self.ui.yAxisLabelEdit,
                       self.ui.legendFieldButton, self.ui.annotationsButton):
            expand(widget)
        self.ui.horizontalLayout_2.removeItem(self.ui.horizontalSpacer_4)
        self.ui.horizontalLayout_5.removeItem(self.ui.horizontalSpacer_5)
        self.ui.horizontalLayout_6.removeItem(self.ui.horizontalSpacer_6)
        self.ui.horizontalLayout_9.removeItem(self.ui.horizontalSpacer_7)

    def _insert_separator(self, layout, index: int):
        frame = QFrame()
        frame.setFrameShape(QFrame.Shape.HLine)
        frame.setFrameShadow(QFrame.Shadow.Sunken)
        layout.insertWidget(index, frame)

    def _insert_panel_separators(self):
        """Divider lines between groups of unrelated controls within a
        panel -- confirmed groupings: Data display splits normalization
        (mode + value) from the spectrum offset; Colors splits the
        colormap choice from its start/stop range; Labels splits the
        axis-label overrides, the legend field, and the annotations
        button into three groups."""
        self._insert_separator(self.ui.verticalLayout_2, 2)   # data display
        self._insert_separator(self.ui.verticalLayout_5, 1)   # colors
        self._insert_separator(self.ui.verticalLayout_3, 2)   # labels: before legend field
        self._insert_separator(self.ui.verticalLayout_3, 4)   # labels: before annotations button

    def _setup_list(self):
        lw = self.ui.spectraList
        lw.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        lw.setDefaultDropAction(Qt.DropAction.MoveAction)
        lw.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        lw.model().rowsMoved.connect(self._refresh_plot)

        # "Check All"/"Check None" toggle the item checkboxes that drive
        # _checked_entries() (plot visibility) -- inserted between the
        # existing Add/Sort button row and the list itself.
        check_row = QHBoxLayout()
        self._check_all_button = QPushButton("Check All")
        self._check_none_button = QPushButton("Check None")
        self._check_all_button.clicked.connect(lambda: self._set_all_checked(True))
        self._check_none_button.clicked.connect(lambda: self._set_all_checked(False))
        check_row.addWidget(self._check_all_button)
        check_row.addWidget(self._check_none_button)
        self.ui.verticalLayout.insertLayout(1, check_row)

        # _refresh_plot keeps this current; set it now so the button never
        # shows the stale Designer text before the first draw.
        self._update_export_button_text(0)

        # Sits with the CSV exports: same inputs (the checked spectra),
        # different artifact.
        self._export_notebook_button = QPushButton("Export notebook...")
        self._export_notebook_button.setToolTip(
            "Write a self-contained Colab notebook that reproduces this "
            "figure, with the plotted spectra embedded — for full control "
            "over the figure outside the app."
        )
        self._export_notebook_button.clicked.connect(self._on_export_notebook)
        self.ui.horizontalLayout.addWidget(self._export_notebook_button)

    def _set_all_checked(self, checked: bool):
        """Sets every spectrum's checkbox (and backing SpectrumEntry.checked)
        at once, then redraws a single time -- _on_item_check_changed()
        (which fires per-row and redraws each time) is blocked for the
        duration so toggling a long list doesn't re-plot N times."""
        lw = self.ui.spectraList
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        lw.blockSignals(True)
        for i in range(lw.count()):
            item = lw.item(i)
            idx = item.data(Qt.ItemDataRole.UserRole)
            if idx is not None and 0 <= idx < len(self._entries):
                self._entries[idx].checked = checked
            item.setCheckState(state)
        lw.blockSignals(False)
        self._refresh_plot()

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

    def _setup_data_display_controls(self):
        """"Hide data" belongs with the other data-display options.

        It used to live in the Fit components panel, which
        _update_conditional_dock_state greys out when no checked spectrum
        carries a fit -- so ticking it and then unchecking that spectrum
        left an empty plot whose cause was disabled and unreachable.
        """
        self._hide_data_checkbox = QCheckBox("Hide data")
        self._hide_data_checkbox.setToolTip(
            "Hide the raw/measured data series, showing only the "
            "fit-derived curves selected in the Fit components panel."
        )
        self._hide_data_checkbox.toggled.connect(self._refresh_plot)
        self.ui.verticalLayout_2.addWidget(self._hide_data_checkbox)

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

    def _setup_fit_component_checkboxes(self) -> QWidget:
        """Global toggle panel for a reloaded fit's derived curves,
        mirroring the HD-SFG component checkboxes above. Peaks are
        collapsed into a single "Individual features" checkbox rather
        than one per peak index (peak count varies per entry, and
        Trace Properties already lists them individually for anyone
        who wants just one)."""
        widget = QWidget()
        outer = QVBoxLayout(widget)
        grid = QGridLayout()
        self._fit_checkboxes: dict[str, QCheckBox] = {
            "Fit total": QCheckBox("Fit total"),
            "Fit real": QCheckBox("Fit real"),
            "Fit imaginary": QCheckBox("Fit imaginary"),
            "Individual features": QCheckBox("Individual features"),
        }
        for i, cb in enumerate(self._fit_checkboxes.values()):
            cb.setToolTip(
                "Plot this fit-derived component for entries loaded from "
                "an exported fit — has no effect on entries without one."
            )
            grid.addWidget(cb, i // 2, i % 2)
            cb.toggled.connect(self._refresh_plot)
        outer.addLayout(grid)

        outer.addSpacing(6)
        # Only meaningful when there's a fit to distinguish the measured
        # data from -- lives in this panel (not Labels/legend) so it's
        # only available while this panel itself is enabled (see
        # _update_conditional_dock_state()'s fit_dock.setEnabled(has_fit)).
        self._markers_checkbox = QCheckBox("Show data as markers")
        self._markers_checkbox.setToolTip(
            "Render the raw/measured data series as markers instead of a "
            "line, so it's visually distinguishable from a fit curve drawn "
            "over it. Only affects the measured data — fit-derived curves "
            "always stay lines."
        )
        self._markers_checkbox.toggled.connect(self._refresh_plot)
        outer.addWidget(self._markers_checkbox)

        outer.addStretch()
        return widget

    def _fit_component_concept(self, column_name: str) -> str:
        """Maps a fit-derived column name to one of the four global
        panel keys above."""
        if column_name in ("Fit (total)", "Fit (homodyne)"):
            return "Fit total"
        if column_name == "Fit (real)":
            return "Fit real"
        if column_name == "Fit (imaginary)":
            return "Fit imaginary"
        return "Individual features"   # "Peak 1", "Peak 2", ...

    def _checked_fit_concepts(self) -> set[str]:
        return {name for name, cb in self._fit_checkboxes.items() if cb.isChecked()}

    def _connect_signals(self):
        self.ui.addSpectraButton.clicked.connect(self._on_add_from_file)
        self.ui.pushButton.clicked.connect(self._on_sort_by_metadata)
        self.ui.annotationsButton.clicked.connect(self._on_edit_annotations)
        self.ui.exportSelectedButton.clicked.connect(self._on_export_checked)
        self.ui.exportAllButton.clicked.connect(self._on_export_all)

        self.ui.spectraList.itemChanged.connect(self._on_item_check_changed)
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
        self.ui.legendFieldButton.clicked.connect(self._on_edit_legend_fields)
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
        failed: list[str] = []
        loading = show_loading(self, "Adding results...")
        try:
            for filename, spectrum in results.items():
                try:
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
                            f'A result named "{label}" already exists in the Spectra '
                            f'Library with different data. Overwrite it?',
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
                        new_entry = SpectrumEntry(spectrum, label, kind=kind)
                        self._entries[existing_idx] = new_entry
                        # same as _on_add_from_file()'s Overwrite branch --
                        # refresh this row's own text in place (e.g. a
                        # stale "(fitted)" suffix if the entry being
                        # replaced no longer carries fit_components),
                        # found by stored index since widget row order
                        # can differ from self._entries order after
                        # drag-reordering.
                        for row in range(self.ui.spectraList.count()):
                            item = self.ui.spectraList.item(row)
                            if item.data(Qt.ItemDataRole.UserRole) == existing_idx:
                                item.setText(_entry_display_text(new_entry))
                                break
                        continue

                    self._entries.append(SpectrumEntry(spectrum, label, kind=kind))
                    self.ui.spectraList.addItem(
                        self._make_list_item(len(self._entries) - 1)
                    )
                except Exception as e:
                    logger.error(
                        "Failed to add result %r to the Spectra Library: %s",
                        filename, e, exc_info=True,
                    )
                    failed.append(str(filename))
        finally:
            loading.close()

        self._refresh_plot()

        if failed:
            QMessageBox.warning(
                self, "Some results couldn't be added",
                "The following processed spectra could not be added to the "
                f"Spectra Library due to an unexpected error (see log for "
                f"details:\n{LOG_FILE}):\n\n" + "\n".join(failed),
            )

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
        item = QListWidgetItem(_entry_display_text(entry))
        item.setData(Qt.ItemDataRole.UserRole, index)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(Qt.CheckState.Checked if entry.checked else Qt.CheckState.Unchecked)
        overridden = _customized_components(entry)
        if overridden:
            item.setToolTip(
                "Trace properties overridden for: "
                + ", ".join(sorted(overridden))
                + "\nRight-click to reset them."
            )
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

    def entries(self, kind: str | None = None) -> list[SpectrumEntry]:
        """Public accessor for other tabs (e.g. Fitting) to read the
        currently-held, already-processed spectra without reaching into
        private state. `kind` filters to "homodyne"/"heterodyne" if given."""
        ordered = self._ordered_entries()
        if kind is None:
            return ordered
        return [e for e in ordered if e.kind == kind]

    def _selected_entries(self) -> list[SpectrumEntry]:
        ordered = self._ordered_entries()
        selected_rows = {
            self.ui.spectraList.row(item)
            for item in self.ui.spectraList.selectedItems()
        }
        return [e for i, e in enumerate(ordered) if i in selected_rows]

    def _checked_entries(self) -> list[SpectrumEntry]:
        """Entries whose list-item checkbox is ticked -- this is what
        _refresh_plot() draws, independent of selection."""
        return [e for e in self._ordered_entries() if e.checked]

    def _on_item_check_changed(self, item: QListWidgetItem):
        idx = item.data(Qt.ItemDataRole.UserRole)
        if idx is None or not (0 <= idx < len(self._entries)):
            return
        self._entries[idx].checked = item.checkState() == Qt.CheckState.Checked
        self._refresh_plot()

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

    def _assign_spec_colors(self, specs: list[PlotSpec]) -> list:
        """One color per spec (`specs`' own order/length) -- data traces
        keep today's positional color-cycling (now scoped to just data
        specs, so a fit's peak count no longer perturbs other entries'
        data colors as a side effect), while a fit-derived curve (Fit
        total/real/imaginary, peaks) reuses its own entry's matching
        data-trace color, so a fit visually matches the data it was fit
        against. Falls back to that entry's first data color (peaks, or
        a heterodyne component that isn't currently checked), then --
        only if the entry has no visible data at all (e.g. "Hide data")
        -- a fresh positional color, same as today's fit-only behavior.
        """
        data_indices = [i for i, spec in enumerate(specs) if not spec.is_fit]
        data_colors = self._get_colors(len(data_indices))
        result = [None] * len(specs)
        data_color_by_key = {}
        entry_fallback_color = {}
        for idx, color in zip(data_indices, data_colors):
            spec = specs[idx]
            key = spec.component if spec.component is not None else AMPLITUDE_COMPONENT
            data_color_by_key[(spec.entry, key)] = color
            entry_fallback_color.setdefault(spec.entry, color)
            result[idx] = color

        orphans = []
        for i, spec in enumerate(specs):
            if not spec.is_fit:
                continue   # already colored above
            entry = spec.entry
            matched_key = (_FIT_TO_HD_COMPONENT.get(spec.y_col)
                           if entry.kind == "heterodyne" else AMPLITUDE_COMPONENT)
            color = data_color_by_key.get((entry, matched_key)) if matched_key else None
            if color is None:
                color = entry_fallback_color.get(entry)
            if color is None:
                orphans.append(i)
            else:
                result[i] = color
        if orphans:
            for i, color in zip(orphans, self._get_colors(len(orphans))):
                result[i] = color
        return result

    # ── Plot ──────────────────────────────────────────────────────────────────

    def _legend_base(self, entry: SpectrumEntry, legend_fields: list[str]) -> str:
        if legend_fields == ["None"]:
            return entry.label
        parts = []
        for field in legend_fields:
            if field == "Filename":
                parts.append(entry.label)
            else:
                value = entry.spectrum.metadata.get(field)
                parts.append(str(value) if value not in (None, "") else entry.label)
        return " - ".join(parts)

    def _ylabel_for(self, hd_components: list[str], has_amplitude_line: bool) -> str:
        if hd_components:
            return (_HD_YLABEL.get(hd_components[0], "Amplitude (a.u.)")
                    if len(set(hd_components)) == 1 else "Amplitude (a.u.)")
        if has_amplitude_line:
            # Every entry reaching the Spectra Library has already been
            # through the full pipeline (despike -> background subtract ->
            # normalize -> upconvert) -- it's reference-normalized,
            # dimensionless, never raw camera counts. normalizationComboBox
            # is a separate in-tab *display* rescaling knob (_normalize_
            # factor()) and has no bearing on this.
            return "Normalized Intensity (a.u.)"
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

    def redraw_for_style_change(self):
        """Called after the global plotting style changes. _refresh_plot()
        only calls plot_widget.soft_clear(), which keeps the existing Axes
        (and its pre-restyle spine/grid/tick chrome) — full_clear() first
        recreates a fresh Axes under the new rcParams; the soft_clear()
        _refresh_plot() then does on it is a no-op since it's already empty.
        """
        self.plot_widget.full_clear()
        self._refresh_plot()

    def _update_conditional_dock_state(self, entries: list[SpectrumEntry]):
        """Grey out (not hide -- keeps the dock layout stable and the
        panel discoverable) the HD-SFG components / Fit components
        docks when nothing currently checked would respond to them --
        their checkboxes are otherwise silently inert for a homodyne-
        only or fit-free selection. Called from _refresh_plot(), which
        already runs on every state change that can affect this (check/
        uncheck, Check All/None, add, remove, sort/reorder)."""
        has_heterodyne = any(e.kind == "heterodyne" for e in entries)
        has_fit = any(e.fit_components for e in entries)
        hd_dock = self._docks.get("hd_components")
        if hd_dock is not None:
            hd_dock.setEnabled(has_heterodyne)
            hd_dock.setToolTip(
                "" if has_heterodyne else
                "Enabled when at least one checked spectrum is heterodyne (HD-SFG)."
            )
        fit_dock = self._docks.get("fit_components")
        if fit_dock is not None:
            fit_dock.setEnabled(has_fit)
            fit_dock.setToolTip(
                "" if has_fit else
                "Enabled when at least one checked spectrum has a loaded fit."
            )

    def _refresh_plot(self):
        self.plot_widget.soft_clear()
        entries = self._checked_entries()
        self._update_conditional_dock_state(entries)
        self._update_export_button_text(len(entries))
        if not entries:
            self.plot_widget.canvas.draw_idle()
            return

        specs = self._build_plot_specs(entries)
        if not specs:
            self._explain_empty_plot(entries)
            self.plot_widget.canvas.draw_idle()
            return
        axis_usage = self._draw_specs(specs)
        self._draw_annotations()
        self._decorate_axes(entries, axis_usage)
        self.plot_widget.sync_x_range()

    def _update_export_button_text(self, checked_count: int):
        """Name what the export actually covers.

        The button said "Export checked" against an objectName of
        exportSelectedButton, in a list where checked and selected are
        different things -- the live count makes which one it means
        unambiguous.
        """
        self.ui.exportSelectedButton.setText(f"Export plotted ({checked_count})")
        self.ui.exportSelectedButton.setEnabled(checked_count > 0)

    def _explain_empty_plot(self, entries: list[SpectrumEntry]):
        """Say why checked spectra produced no lines.

        Without this the tab's four independent ways to hide a trace all
        fail the same way -- a blank plot -- leaving the user to guess
        which panel to go looking in.
        """
        count = sum(self._hidden_tally.values())
        if not self._hidden_tally:
            message = f"{len(entries)} spectrum/spectra checked, but nothing to plot."
        else:
            # Enum declaration order doubles as "most useful explanation
            # first" when several reasons apply at once.
            reason = min(
                self._hidden_tally,
                key=lambda r: (-self._hidden_tally[r], list(HiddenReason).index(r)),
            )
            traces = "trace" if count == 1 else "traces"
            message = f"{count} {traces} hidden by {reason.value}."
        self.plot_widget.ax.text(
            0.5, 0.5, message, transform=self.plot_widget.ax.transAxes,
            ha="center", va="center", fontsize=9, wrap=True, color="#666666",
        )

    def _build_plot_specs(self, entries: list[SpectrumEntry]) -> list[PlotSpec]:
        """Flatten the checked entries into one PlotSpec per line to draw,
        applying the global component panels, "Hide data", and each
        trace's own visibility override, and resolving legend labels."""
        checked_components = self._checked_hd_components()
        checked_fit_concepts = self._checked_fit_concepts()
        hide_data = self._hide_data_checkbox.isChecked()

        # with only one spectrum selected, the filename is redundant (it's
        # already obvious from the selection/plot title) — show just the
        # component name instead
        single_entry = len(entries) == 1
        multi_line = len(entries) > 1 or len(checked_components) > 1
        # the y-axis already names the sole component when it's Im/Re/Phase,
        # so repeating it on every line's legend would be redundant
        suppress_suffix = (
            len(checked_components) == 1
            and checked_components[0] in ("Imaginary", "Real", "Phase")
        )

        # Every candidate line is classified rather than filtered out
        # silently, so an empty plot can say which control emptied it.
        self._hidden_tally = Counter()
        specs: list[PlotSpec] = []
        for entry in entries:
            base_label = self._legend_base(entry, self._legend_fields)

            if entry.kind == "heterodyne":
                for component in _HD_COMPONENT_COLUMN:
                    style = entry.style_for(component)
                    reason = resolve_visibility(
                        style=style, component=component, is_fit=False,
                        hide_data=hide_data,
                        component_checked=component in checked_components,
                    )
                    if reason is not None:
                        self._hidden_tally[reason] += 1
                        continue
                    if single_entry:
                        label = _HD_LEGEND_LABEL[component]
                    elif suppress_suffix:
                        label = base_label
                    elif multi_line:
                        label = f"{base_label} ({_HD_LEGEND_LABEL[component]})"
                    else:
                        label = base_label
                    specs.append(PlotSpec(
                        entry=entry, component=component,
                        y_col=_HD_COMPONENT_COLUMN[component],
                        err_col=_HD_ERROR_COLUMN[component],
                        label=style.label or label, style=style, is_fit=False,
                    ))
            else:
                style = entry.style_for(AMPLITUDE_COMPONENT)
                # No panel gates a homodyne entry's single line.
                reason = resolve_visibility(
                    style=style, component=AMPLITUDE_COMPONENT, is_fit=False,
                    hide_data=hide_data, component_checked=True,
                )
                if reason is not None:
                    self._hidden_tally[reason] += 1
                else:
                    specs.append(PlotSpec(
                        entry=entry, component=None, y_col="Intensity", err_col=None,
                        label=style.label or base_label, style=style, is_fit=False,
                    ))

            # Reloaded fit's derived curves (fit total/real/imaginary, each
            # peak) -- per-entry and variable in count, so independent of
            # entry.kind's branch above. Gated first by the global "Fit
            # components" panel (default unchecked), then by the per-entry
            # Trace Properties visibility override (default visible).
            for column_name, display_label in entry.fit_components:
                style = entry.style_for(column_name)
                reason = resolve_visibility(
                    style=style, component=column_name, is_fit=True,
                    hide_data=hide_data,
                    component_checked=(
                        self._fit_component_concept(column_name) in checked_fit_concepts
                    ),
                )
                if reason is not None:
                    self._hidden_tally[reason] += 1
                    continue
                specs.append(PlotSpec(
                    entry=entry, component=None, y_col=column_name, err_col=None,
                    label=style.label or f"{base_label} ({display_label})",
                    style=style, is_fit=True,
                ))
        return specs

    def _draw_specs(self, specs: list[PlotSpec]) -> _AxisUsage:
        """Draw every spec, returning which quantities landed on each axis."""
        offset_step = self.ui.offsetSpectraSpinner.value()
        show_error = self.ui.hdCheckShowError.isChecked()
        markers_mode = self._markers_checkbox.isChecked()
        colors = self._assign_spec_colors(specs)
        # Offset is per *spectrum*, not per plotted line: every component
        # and fit curve of one entry shares its entry's slot, so enabling
        # a second HD component doesn't widen the spacing or push a fit
        # curve away from the data it was fit against.
        offset_slots = {}
        for spec in specs:
            offset_slots.setdefault(spec.entry, len(offset_slots))
        usage = _AxisUsage()

        for i, spec in enumerate(specs):
            entry, style = spec.entry, spec.style
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
                raw_y = data[spec.y_col].to_numpy()
                if spec.component == "Phase":
                    raw_y = wrap_phase_for_plot(
                        raw_y, self._phase_range_combo.currentData() == "0to360"
                    )
                is_secondary = style.axis == "secondary"
                # normalization is scoped to the primary axis — a secondary
                # axis is meant to show a trace in its own native units
                factor = 1.0 if is_secondary else self._normalize_factor(x, raw_y)
                y_offset = raw_y * factor + offset_slots[entry] * offset_step

                color = style.color or colors[i]
                target_ax = self.plot_widget.secondary_axis() if is_secondary else self.plot_widget.ax

                if markers_mode and not spec.is_fit and style.is_default():
                    # Global "show as markers" view -- only overrides traces
                    # still on their default style; anything customized via
                    # Trace Properties keeps its own explicit line/marker.
                    plot_kwargs = dict(
                        color=color, linestyle="None", marker="o",
                        markersize=self._plotting_settings.marker_size, label=spec.label,
                    )
                else:
                    plot_kwargs = dict(color=color, linestyle=style.linestyle, label=spec.label)
                    if style.marker is not None:
                        plot_kwargs["marker"] = style.marker
                    if style.markersize is not None:
                        plot_kwargs["markersize"] = style.markersize
                    if style.linewidth is not None:
                        plot_kwargs["linewidth"] = style.linewidth
                    if style.alpha is not None:
                        plot_kwargs["alpha"] = style.alpha
                target_ax.plot(x, y_offset, **plot_kwargs)

                if show_error and entry.kind == "heterodyne" and spec.err_col in data.columns:
                    y_err = data[spec.err_col].to_numpy() * factor
                    # scale the band's own alpha by the trace's alpha so a
                    # faded-out line fades its error band too, instead of
                    # exposing a separate error-band-specific style field
                    band_alpha = 0.25 * (style.alpha if style.alpha is not None else 1.0)
                    target_ax.fill_between(
                        x, y_offset - y_err, y_offset + y_err,
                        color=color, alpha=band_alpha, linewidth=0,
                    )

                if entry.kind == "heterodyne":
                    (usage.secondary_hd if is_secondary else usage.primary_hd).append(spec.component)
                elif is_secondary:
                    usage.secondary_amp = True
                else:
                    usage.primary_amp = True
            except Exception as e:
                logger.warning("Could not plot %s: %s", spec.label, e)
        return usage

    def _decorate_axes(self, entries: list[SpectrumEntry], usage: _AxisUsage):
        """Legend, axis labels and title, once the traces exist."""
        handles, labels = self.plot_widget.ax.get_legend_handles_labels()
        if self.plot_widget.ax2 is not None:
            h2, l2 = self.plot_widget.ax2.get_legend_handles_labels()
            handles, labels = handles + h2, labels + l2
        if len(handles) > 1 and self._legend_fields != ["None"]:
            self.plot_widget.ax.legend(handles, labels, fontsize=8)

        # determine x column — use Wavenumber if available, else Wavelength
        first_data = entries[0].spectrum.data
        first_x_col = "Wavenumber" if "Wavenumber" in first_data.columns else "Wavelength"
        x_label = "Wavenumber (cm$^{-1}$)" if first_x_col == "Wavenumber" else "Wavelength (nm)"

        primary_ylabel = self._ylabel_for(usage.primary_hd, usage.primary_amp)
        secondary_ylabel = (self._ylabel_for(usage.secondary_hd, usage.secondary_amp)
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

    # ── Metadata helpers ──────────────────────────────────────────────────────

    def _all_metadata_keys(self) -> list[str]:
        all_keys = set()
        for e in self._entries:
            all_keys.update(e.spectrum.metadata.keys())
        return sorted(all_keys)

    def _setup_legend_fields(self):
        self._legend_fields: list[str] = ["Filename"]
        self._update_legend_button_text()

    def _on_edit_legend_fields(self):
        """Opens LegendFieldsDialog to pick what the legend is built from
        -- Filename/None (each exclusive of everything else) or an
        ordered combination of metadata fields."""
        from sfg_app2.app.dialogs.legend_fields_dialog import LegendFieldsDialog
        dialog = LegendFieldsDialog(self._legend_fields, self._all_metadata_keys(), parent=self)
        if dialog.exec():
            self._legend_fields = dialog.result_fields()
            self._update_legend_button_text()
            self._refresh_plot()

    def _update_legend_button_text(self):
        self.ui.legendFieldButton.setText(" - ".join(self._legend_fields))

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
        for i in range(len(self._entries)):
            self.ui.spectraList.addItem(self._make_list_item(i))
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

    def _add_fit_component_columns(self, df, provenance: dict, kind: str) -> list[tuple[str, str]]:
        """If `provenance` carries a "Fit json:" header line (written by
        FittingTab's own export), reconstruct the FitModelSpec and add
        its derived curves as new columns directly on `df`, computed
        over its own Wavenumber column with the same evaluation
        functions FittingTab itself uses for its live preview. Returns
        the (column_name, display_label) pairs to store on the
        resulting SpectrumEntry.fit_components -- column_name doubles
        as the style_for() key. Returns [] if there's no fit (the
        common case)."""
        fit_payload = provenance_mod.parse_fit_json(provenance)
        if not fit_payload:
            return []
        fit_spec = fitting_mod.fit_model_spec_from_provenance_payload(fit_payload)
        if fit_spec is None or "Wavenumber" not in df.columns:
            return []

        omega = df["Wavenumber"].to_numpy(dtype=float)
        chi = fitting_mod.evaluate_chi(omega, fit_spec)
        components: list[tuple[str, str]] = []

        df["Fit (real)"] = chi.real
        components.append(("Fit (real)", "Fit (real)"))
        df["Fit (imaginary)"] = chi.imag
        components.append(("Fit (imaginary)", "Fit (imaginary)"))

        if kind == "heterodyne":
            df["Fit (homodyne)"] = np.abs(chi) ** 2
            components.append(("Fit (homodyne)", "Fit (homodyne)"))
        else:
            df["Fit (total)"] = fitting_mod.evaluate_homodyne(omega, fit_spec)
            components.append(("Fit (total)", "Fit (total)"))

        for i, peak in enumerate(fit_spec.peaks):
            col = f"Peak {i + 1}"
            df[col] = fitting_mod.evaluate_peak_component(omega, peak)
            components.append((col, col))

        return components

    def _on_add_from_file(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Load processed spectra", "",
            "CSV files (*.csv);;All files (*.*)"
        )
        if not paths:
            return

        from sfg_app2.processing.utils import resolve_role, select_pattern
        import pandas as pd

        patterns = self._get_active_patterns()
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
                if patterns:
                    from sfg_app2.processing.data_file import DataFile
                    # strip a "Keep Both" duplicate suffix (e.g. "sample1 (2)")
                    # and a Fitting-tab export's "_fit" suffix before parsing
                    # filename fields, so neither gets absorbed into the last
                    # underscore-separated field
                    metadata_stem = re.sub(r"\s\(\d+\)$", "", path.stem)
                    metadata_stem = re.sub(r"_fit$", "", metadata_stem, flags=re.IGNORECASE)
                    clean_stem, _, _ = resolve_role(
                        metadata_stem, role_kwargs["role_mode"], role_kwargs["role_values"]
                    )
                    fields = select_pattern(clean_stem, patterns)
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

                kind = provenance.get("kind")
                if kind is None:
                    # no/old-style header — fall back to sniffing columns
                    kind = ("heterodyne"
                            if {"Real", "Imaginary", "Phase", "Homodyne"}.issubset(df.columns)
                            else "homodyne")

                # a "Fit json:" header line (written by FittingTab's own
                # export) reconstructs into extra derived columns (fit
                # total/real/imaginary, each peak) added directly to df,
                # so they're plottable/stylable via the same per-entry
                # component machinery as Real/Imaginary/etc below
                fit_components = self._add_fit_component_columns(df, provenance, kind)

                spectrum = ProcessedSpectrum(
                    df,
                    metadata=merged_metadata,
                    history=provenance.get("history_list", ["loaded_from_file"]),
                )
                spectrum.provenance = provenance

                # the embedded "# Label:" header line (already parsed into
                # merged_metadata above) is authoritative -- path.stem is
                # only a fallback for files that never had one. Using
                # path.stem unconditionally here would leak a Fitting-tab
                # export's "_fit" filename suffix into the displayed label
                # even though the header itself is always clean.
                label = merged_metadata.get("label", path.stem)
                existing_idx = next(
                    (i for i, e in enumerate(self._entries) if e.label == label), None
                )
                if existing_idx is None:
                    entry = SpectrumEntry(spectrum, label, kind=kind)
                    entry.fit_components = fit_components
                    self._entries.append(entry)
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
                        f'"{label}" already exists in the Spectra Library with '
                        f'different data. Overwrite it?',
                        ["Overwrite", "Keep Both", "Skip"], remembered,
                    )
                    if choice == "Skip":
                        skipped += 1
                    elif choice == "Keep Both":
                        new_label = self._unique_label(label)
                        entry = SpectrumEntry(spectrum, new_label, kind=kind)
                        entry.fit_components = fit_components
                        self._entries.append(entry)
                        self.ui.spectraList.addItem(
                            self._make_list_item(len(self._entries) - 1)
                        )
                        added += 1
                        renamed += 1
                    else:  # Overwrite
                        entry = SpectrumEntry(spectrum, label, kind=kind)
                        entry.fit_components = fit_components
                        self._entries[existing_idx] = entry
                        # the overwritten row's own list-item text (e.g. its
                        # "(fitted)" suffix) isn't touched by replacing
                        # self._entries[existing_idx] alone -- find that
                        # row by its stored index (not by widget row
                        # number, which can differ after drag-reordering)
                        # and refresh its text in place.
                        for row in range(self.ui.spectraList.count()):
                            item = self.ui.spectraList.item(row)
                            if item.data(Qt.ItemDataRole.UserRole) == existing_idx:
                                item.setText(_entry_display_text(entry))
                                break
                        added += 1

            except Exception as e:
                logger.warning("Could not load %s: %s", path.name, e)
                failed += 1
        loading.close()

        if added:
            self._refresh_plot()

        msg_parts = []
        if added:
            msg_parts.append(f"{added} added")
        if renamed:
            msg_parts.append(f"{renamed} kept as a new copy (renamed)")
        if skipped:
            msg_parts.append(f"{skipped} duplicate(s) skipped")
        if failed:
            msg_parts.append(f"{failed} failed (see log: {LOG_FILE})")
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
        return provenance_mod.load_csv_skip_comments(path)

    @staticmethod
    def _parse_export_header(path: Path) -> tuple[list[str], dict, dict]:
        """Parse the # comment header written by _write_csv_with_provenance.
        Returns (raw_header_lines, provenance_dict, metadata_dict).
        Gracefully returns empty dicts if the file has no such header.
        """
        return provenance_mod.parse_export_header(path)

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
            msg += f"\n{failed} file(s) failed — see log for details:\n{LOG_FILE}"
        QMessageBox.information(self, "Export complete", msg)

    def _unique_path(self, path: Path) -> Path:
        n = 2
        candidate = path.parent / f"{path.stem} ({n}){path.suffix}"
        while candidate.exists():
            n += 1
            candidate = path.parent / f"{path.stem} ({n}){path.suffix}"
        return candidate

    def _csv_text_for(self, entry: SpectrumEntry) -> str:
        """The entry's CSV export as text, fit section included."""
        return provenance_mod.csv_with_provenance_text(
            entry.spectrum, entry.kind, entry.label,
            fit_section=self._fit_section_for(entry),
        )

    def _fit_section_for(self, entry: SpectrumEntry) -> list[str] | None:
        """Re-emit the entry's `# Fit json:` section, if it carries one.

        Without this a re-exported fitted entry silently drops its fit
        parameters and errors, since write_csv_with_provenance() only
        writes a fit section when explicitly given one.
        """
        payload = provenance_mod.parse_fit_json(getattr(entry.spectrum, "provenance", None) or {})
        if not payload:
            return None
        return provenance_mod.format_fit_section(
            payload["model"], payload.get("weighting"), payload.get("redchi"),
            payload.get("r_squared"), payload.get("aic"), payload.get("bic"),
            kind=payload.get("kind", entry.kind), param_errors=payload.get("param_errors"),
        )

    def _notebook_payload(self, entries: list[SpectrumEntry]) -> dict:
        """Flatten the current plot into the plain dict the notebook
        builder consumes.

        Colours, labels and offset slots are resolved here, by the same
        code that draws the figure, so the notebook starts from exactly
        what's on screen rather than re-deriving it.
        """
        specs = self._build_plot_specs(entries)
        colors = self._assign_spec_colors(specs)
        offset_slots: dict = {}
        for spec in specs:
            offset_slots.setdefault(spec.entry, len(offset_slots))

        usage = _AxisUsage()
        for spec in specs:
            if spec.entry.kind == "heterodyne":
                target = (usage.secondary_hd if spec.style.axis == "secondary"
                          else usage.primary_hd)
                target.append(spec.component)
            elif spec.style.axis == "secondary":
                usage.secondary_amp = True
            else:
                usage.primary_amp = True

        first_data = entries[0].spectrum.data
        x_is_wavenumber = "Wavenumber" in first_data.columns
        x_label = ("Wavenumber (cm$^{-1}$)" if x_is_wavenumber else "Wavelength (nm)")
        custom_x = self.ui.xAxisLabelEdit.text().strip()
        custom_y = self.ui.yAxisLabelEdit.text().strip()
        primary_ylabel = self._ylabel_for(usage.primary_hd, usage.primary_amp)
        secondary_ylabel = self._ylabel_for(usage.secondary_hd, usage.secondary_amp)

        markers_mode = self._markers_checkbox.isChecked()

        traces = []
        for spec, color in zip(specs, colors):
            style = spec.style
            # Same override _draw_specs applies, so the notebook reproduces
            # what's on screen rather than the underlying line style.
            as_markers = markers_mode and not spec.is_fit and style.is_default()
            traces.append({
                "entry": spec.entry.label,
                "column": spec.y_col,
                "err_column": spec.err_col,
                "legend": spec.label,
                "color": mpl.colors.to_hex(style.color or color, keep_alpha=False),
                "linestyle": "None" if as_markers else style.linestyle,
                "marker": "o" if as_markers else style.marker,
                "markersize": (self._plotting_settings.marker_size if as_markers
                               else style.markersize),
                "linewidth": style.linewidth,
                "alpha": style.alpha,
                "secondary": style.axis == "secondary",
                "is_fit": spec.is_fit,
                "is_phase": spec.component == "Phase",
                "offset_slot": offset_slots[spec.entry],
            })

        return {
            "title": f"{len(entries)} spectrum/spectra",
            "x_label": custom_x or x_label,
            "y_label": custom_y or primary_ylabel,
            "y_label2": secondary_ylabel or None,
            "normalization": {
                "mode": self.ui.normalizationComboBox.currentIndex(),
                "target": self.ui.doubleSpinBox.value(),
            },
            "offset_step": self.ui.offsetSpectraSpinner.value(),
            "x_range": self.plot_widget.get_x_range(),
            "invert_x": False,
            "phase_wrap_0_360": self._phase_range_combo.currentData() == "0to360",
            "show_error": self.ui.hdCheckShowError.isChecked(),
            "figsize": tuple(self.plot_widget.figure.get_size_inches()),
            "dpi": 150,
            "output_name": "figure",
            "output_format": "png",
            "entries": [
                {"label": e.label, "kind": e.kind, "csv": self._csv_text_for(e)}
                for e in entries
            ],
            "traces": traces,
        }

    def _on_export_notebook(self):
        entries = self._checked_entries()
        if not entries:
            QMessageBox.information(
                self, "Nothing to export",
                "Tick the spectra you want in the notebook first — it "
                "reproduces what's currently plotted.",
            )
            return

        path_str, _ = QFileDialog.getSaveFileName(
            self, "Export plotting notebook", "sfg_figure.ipynb",
            "Jupyter Notebook (*.ipynb)",
        )
        if not path_str:
            return
        path = Path(path_str)
        if path.suffix.lower() != ".ipynb":
            path = path.with_suffix(".ipynb")

        loading = show_loading(self, "Building notebook...")
        try:
            payload = self._notebook_payload(entries)
            payload["output_name"] = path.stem
            notebook_export.write_notebook(notebook_plotting.build(payload), path)
        except Exception as e:
            logger.error("Notebook export failed: %s", e, exc_info=True)
            QMessageBox.warning(self, "Couldn't export notebook", str(e))
            return
        finally:
            loading.close()

        size_kb = path.stat().st_size / 1024
        QMessageBox.information(
            self, "Notebook exported",
            f"Wrote {path.name} ({size_kb:.0f} KB) with {len(entries)} "
            f"spectrum/spectra embedded.\n\nIt runs as-is on Google Colab — "
            f"no files to upload, nothing to install.",
        )

    def _write_csv_with_provenance(self, entry: SpectrumEntry, out_path: Path):
        """Write a CSV with a commented provenance header, readable by pandas
        via pd.read_csv(path, comment='#'). Re-embeds the entry's `# Fit
        json:` section (if it has one) -- without this, re-exporting a
        fitted Library entry would silently drop its fit parameters/errors,
        since write_csv_with_provenance() only ever writes one when
        explicitly given one.
        """
        fit_section = None
        payload = provenance_mod.parse_fit_json(getattr(entry.spectrum, "provenance", None) or {})
        if payload:
            fit_section = provenance_mod.format_fit_section(
                payload["model"], payload.get("weighting"), payload.get("redchi"),
                payload.get("r_squared"), payload.get("aic"), payload.get("bic"),
                kind=payload.get("kind", entry.kind), param_errors=payload.get("param_errors"),
            )
        provenance_mod.write_csv_with_provenance(
            entry.spectrum, entry.kind, entry.label, out_path, fit_section=fit_section,
        )

    @staticmethod
    def _format_markers(markers) -> str:
        return provenance_mod.format_markers(markers)

    @staticmethod
    def _parse_markers(text: str | None) -> list[list[float]]:
        return provenance_mod.parse_markers(text)

    @staticmethod
    def _format_homodyne_provenance(provenance: dict) -> list[str]:
        return provenance_mod.format_homodyne_provenance(provenance)

    @staticmethod
    def _format_heterodyne_provenance(provenance: dict) -> list[str]:
        return provenance_mod.format_heterodyne_provenance(provenance)

    def _on_export_checked(self):
        self._export_entries(self._checked_entries())

    def _on_export_all(self):
        self._export_entries(self._ordered_entries())

    # ── Context menu ─────────────────────────────────

    def _on_context_menu(self, pos):
        item = self.ui.spectraList.itemAt(pos)
        if item is None:
            return

        # Act on the row actually clicked unless it's part of the current
        # selection (file-manager convention) -- otherwise right-clicking
        # one spectrum silently operates on whichever others happen to be
        # highlighted.
        if not item.isSelected():
            self.ui.spectraList.clearSelection()
            item.setSelected(True)
            self.ui.spectraList.setCurrentItem(item)

        selected = self._selected_entries()
        if not selected:
            return

        n = len(selected)
        label = f"{n} spectrum/spectra" if n > 1 else f"\"{selected[0].label}\""

        fitted = [e for e in selected if e.fit_components]

        menu = QMenu(self)
        metadata_action = menu.addAction(f"Review / Edit metadata — {label}")
        params_action = menu.addAction(f"View processing parameters — {label}")
        fit_params_action = None
        if fitted:
            fit_params_action = menu.addAction(f"View fit parameters — {label}")
        menu.addSeparator()
        trace_props_action = menu.addAction("Trace properties...")
        reset_styles_action = menu.addAction(f"Reset trace overrides — {label}")
        # A per-trace override can hide a line on its own, so there has to
        # be a way out that doesn't mean hunting through the dialog.
        reset_styles_action.setEnabled(
            any(_customized_components(entry) for entry in selected)
        )
        menu.addSeparator()
        remove_action = menu.addAction(f"Remove {label}")

        action = menu.exec(self.ui.spectraList.viewport().mapToGlobal(pos))

        if action == metadata_action:
            self._on_review_metadata(selected)
        elif action == params_action:
            self._on_view_processing_params(selected)
        elif fit_params_action is not None and action == fit_params_action:
            self._on_view_fit_parameters(fitted)
        elif action == trace_props_action:
            self._on_trace_properties(selected)
        elif action == reset_styles_action:
            self._on_reset_trace_styles(selected)
        elif action == remove_action:
            self._on_remove(selected)

    def _on_reset_trace_styles(self, entries: list[SpectrumEntry]):
        for entry in entries:
            entry.styles.clear()
        self._rebuild_list()
        self._refresh_plot()

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
            rows = [(component, component) for component in _HD_COMPONENT_COLUMN]
        else:
            rows = [(AMPLITUDE_COMPONENT, "Amplitude")]
        return rows + list(entry.fit_components)

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

    def _on_view_fit_parameters(self, entries: list[SpectrumEntry]):
        from sfg_app2.app.dialogs.fit_parameters_dialog import FitParametersDialog
        dialog = FitParametersDialog(entries, parent=self)
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
        self._refresh_plot()
        logger.info("Removed %d spectrum/spectra from results.", n)