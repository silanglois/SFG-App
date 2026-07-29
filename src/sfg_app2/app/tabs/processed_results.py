from __future__ import annotations
import logging
import csv
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt
import matplotlib as mpl

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QListWidgetItem, QFileDialog,
    QMessageBox, QAbstractItemView, QInputDialog, QMenu
)

from sfg_app2.app.ui.ui_processed_results_tab import Ui_Form
from sfg_app2.app.widgets.spectrum_plot_widget import SpectrumPlotWidget
from sfg_app2.app.widgets.collapsible_group_box import make_collapsible
from sfg_app2.processing.processed_spectrum import ProcessedSpectrum

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
    "Imaginary": "Imaginary",
    "Real": "Real",
    "Phase": "Phase",
    "|χ⁽²⁾|² (Homodyne)": r"$|\chi^{(2)}|^2$",
}


class SpectrumEntry:
    """Lightweight container binding a ProcessedSpectrum to a display label."""
    def __init__(self, spectrum: ProcessedSpectrum, label: str, kind: str = "homodyne"):
        self.spectrum = spectrum
        self.label = label
        self.kind = kind   # "homodyne" | "heterodyne"

    def __repr__(self):
        return f"SpectrumEntry({self.label})"


class ProcessedResultsTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.ui = Ui_Form()
        self.ui.setupUi(self)

        self._entries: list[SpectrumEntry] = []

        self._setup_plot()
        self._setup_list()
        self._setup_colormap_combo()
        self._setup_normalization()
        self._setup_hd_component_checkboxes()
        self._refresh_legend_field_options()
        self._connect_signals()

        make_collapsible(self.ui.visualizationParamsGroupBox)

    # ── Setup ─────────────────────────────────────────────────────────────────

    def _setup_plot(self):
        layout = QVBoxLayout(self.ui.plotWidget)
        layout.setContentsMargins(0, 0, 0, 0)
        self.plot_widget = SpectrumPlotWidget()
        layout.addWidget(self.plot_widget)

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

    def _checked_hd_components(self) -> list[str]:
        return [name for name, cb in self._hd_checkboxes.items() if cb.isChecked()]

    def _connect_signals(self):
        self.ui.addSpectraButton.clicked.connect(self._on_add_from_file)
        self.ui.pushButton.clicked.connect(self._on_sort_by_metadata)
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
        self.ui.legendFieldComboBox.currentIndexChanged.connect(self._refresh_plot)
        self.ui.spectraList.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.ui.spectraList.customContextMenuRequested.connect(self._on_context_menu)

    # ── Public API — called by MainWindow ─────────────────────────────────────

    def add_results(self, results: dict):
        from sfg_app2.processing.hd_sfg import HDSFGResult
        from sfg_app2.processing.processed_spectrum import ProcessedSpectrum

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
            if not self._entry_exists(label):
                self._entries.append(SpectrumEntry(spectrum, label, kind=kind))
                self.ui.spectraList.addItem(
                    self._make_list_item(len(self._entries) - 1)
                )

        self._refresh_legend_field_options()
        self._refresh_plot()

    # ── List management ───────────────────────────────────────────────────────

    def _entry_exists(self, label: str) -> bool:
        return any(e.label == label for e in self._entries)

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
            return 1.0 / ref if ref != 0 else 1.0
        if mode == 2:
            peak = np.nanmax(np.abs(y))
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

    def _refresh_plot(self):
        self.plot_widget.clear()
        entries = self._selected_entries()
        if not entries:
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
        # the y-axis already names the sole component when it's Im/Re/Phase,
        # so repeating it on every line's legend would be redundant
        suppress_suffix = (
            len(checked_components) == 1
            and checked_components[0] in ("Imaginary", "Real", "Phase")
        )
        show_error = self.ui.hdCheckShowError.isChecked()

        specs = []   # (entry, y_col, err_col, label)
        for entry in entries:
            base_label = self._legend_base(entry, legend_field)
            if entry.kind == "heterodyne":
                for component in checked_components:
                    y_col = _HD_COMPONENT_COLUMN[component]
                    err_col = _HD_ERROR_COLUMN[component]
                    if suppress_suffix:
                        label = base_label
                    elif multi_line:
                        label = f"{base_label} ({_HD_LEGEND_LABEL[component]})"
                    else:
                        label = base_label
                    specs.append((entry, y_col, err_col, label))
            else:
                specs.append((entry, "Intensity", None, base_label))

        colors = self._get_colors(len(specs))
        any_hd_plotted = False

        for i, (entry, y_col, err_col, label) in enumerate(specs):
            try:
                if entry.kind == "heterodyne":
                    # already one row per wavenumber point — bypass .frame(),
                    # which sorts by a "Wavelength" column heterodyne data
                    # doesn't have
                    data = entry.spectrum.data
                    x_col = "Wavenumber"
                    any_hd_plotted = True
                else:
                    data = entry.spectrum.frame(1)
                    x_col = "Wavenumber" if "Wavenumber" in data.columns else "Wavelength"

                x = data[x_col].to_numpy()
                raw_y = data[y_col].to_numpy()
                factor = self._normalize_factor(x, raw_y)
                y_offset = raw_y * factor + i * offset_step

                self.plot_widget.ax.plot(
                    x, y_offset,
                    color=colors[i],
                    label=label,
                )

                if show_error and entry.kind == "heterodyne" and err_col in data.columns:
                    y_err = data[err_col].to_numpy() * factor
                    self.plot_widget.ax.fill_between(
                        x, y_offset - y_err, y_offset + y_err,
                        color=colors[i], alpha=0.25, linewidth=0,
                    )
            except Exception as e:
                logger.warning("Could not plot %s: %s", label, e)

        if len(specs) > 1 and legend_field != "None":
            self.plot_widget.ax.legend(fontsize=8)

        if any_hd_plotted:
            ylabel = (_HD_YLABEL.get(checked_components[0], "Amplitude")
                      if len(checked_components) == 1 else "Amplitude")
        else:
            ylabel = ("Intensity" if self.ui.normalizationComboBox.currentIndex() == 0
                      else "Normalized Intensity")

        self.plot_widget.set_labels(
            xlabel=x_label,
            ylabel=ylabel,
            title=f"{len(entries)} spectrum/spectra",
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

        added, skipped, failed = 0, 0, 0
        for path_str in paths:
            path = Path(path_str)
            try:
                header_lines, provenance, metadata = self._parse_export_header(path)
                df = self._load_csv_skip_comments(path)

                # parse filename metadata if patterns are active
                # manual metadata from header always wins (update order matters)
                if pattern_map:
                    from sfg_app2.processing.data_file import DataFile
                    clean_stem, _ = resolve_role(
                        path.stem, role_kwargs["role_mode"], role_kwargs["role_values"]
                    )
                    n_parts = len(clean_stem.split("_"))
                    fields = pattern_map.get(n_parts)
                    if fields:
                        parsed = DataFile._parse_filename_metadata(path, fields)
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
                if not self._entry_exists(label):
                    self._entries.append(SpectrumEntry(spectrum, label, kind=kind))
                    self.ui.spectraList.addItem(
                        self._make_list_item(len(self._entries) - 1)
                    )
                    added += 1
                else:
                    skipped += 1
                    logger.info("Skipping duplicate: %s", label)

            except Exception as e:
                logger.warning("Could not load %s: %s", path.name, e)
                failed += 1

        if added:
            self._refresh_legend_field_options()
            self._refresh_plot()

        msg_parts = []
        if added:
            msg_parts.append(f"{added} added")
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
                "applied":          raw.get("despike", "").lower() == "applied",
                "window":           raw.get("window"),
                "threshold_factor": raw.get("threshold_factor"),
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

        exported, failed = 0, 0
        for entry in entries:
            try:
                out_path = Path(folder) / f"{entry.label}.csv"
                self._write_csv_with_provenance(entry, out_path)
                exported += 1
                logger.info("Exported %s → %s", entry.label, out_path)
            except Exception as e:
                logger.warning("Could not export %s: %s", entry.label, e)
                failed += 1

        msg = f"{exported} file(s) exported to {folder}."
        if failed:
            msg += f"\n{failed} file(s) failed — check terminal for details."
        QMessageBox.information(self, "Export complete", msg)


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

        # despike
        despike = provenance.get("despike", {})
        if despike.get("applied"):
            lines += [
                f"# Despike:              applied",
                f"#   window:             {despike.get('window', 'N/A')}",
                f"#   threshold_factor:   {despike.get('threshold_factor', 'N/A')}",
            ]
        else:
            lines.append("# Despike:              not applied")

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

        lines = []
        lines += comp("signal", "signal")
        lines += comp("background", "background")
        lines += comp("reference", "reference")
        lines += comp("reference_background", "reference_background")
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
        menu.addSeparator()
        remove_action = menu.addAction(f"Remove {label}")

        action = menu.exec(self.ui.spectraList.viewport().mapToGlobal(pos))

        if action == metadata_action:
            self._on_review_metadata(selected)
        elif action == remove_action:
            self._on_remove(selected)


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