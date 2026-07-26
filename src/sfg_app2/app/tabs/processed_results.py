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


class SpectrumEntry:
    """Lightweight container binding a ProcessedSpectrum to a display label."""
    def __init__(self, spectrum: ProcessedSpectrum, label: str):
        self.spectrum = spectrum
        self.label = label

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
        self._connect_signals()

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
        self.ui.spectraList.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.ui.spectraList.customContextMenuRequested.connect(self._on_context_menu)

    # ── Public API — called by MainWindow ─────────────────────────────────────

    def add_results(self, results: dict):
        from sfg_app2.processing.hd_sfg import HDSFGResult
        from sfg_app2.processing.processed_spectrum import ProcessedSpectrum
        import pandas as pd

        for filename, spectrum in results.items():
            # convert HDSFGResult to ProcessedSpectrum for display
            if isinstance(spectrum, HDSFGResult):
                df = spectrum.to_dataframe()
                df["Frame"] = 1
                # use Imaginary as the primary Intensity column for plotting
                df = df.rename(columns={"Imaginary": "Intensity"})
                ps = ProcessedSpectrum(
                    df,
                    metadata  = spectrum.metadata,
                    history   = spectrum.history,
                )
                ps.provenance = spectrum.provenance
                spectrum = ps

            label = Path(filename).stem
            if not self._entry_exists(label):
                self._entries.append(SpectrumEntry(spectrum, label))
                self.ui.spectraList.addItem(
                    self._make_list_item(len(self._entries) - 1)
                )

        self._refresh_plot()

    # ── List management ───────────────────────────────────────────────────────

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

    def _normalize(self, x: np.ndarray, y: np.ndarray) -> np.ndarray:
        mode = self.ui.normalizationComboBox.currentIndex()
        if mode == 0:
            return y
        if mode == 1:
            target_wn = self.ui.doubleSpinBox.value()
            idx = np.argmin(np.abs(x - target_wn))
            ref = y[idx]
            return y / ref if ref != 0 else y
        if mode == 2:
            peak = np.nanmax(np.abs(y))
            return y / peak if peak != 0 else y
        return y

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

    def _refresh_plot(self):
        self.plot_widget.clear()
        entries = self._selected_entries()
        if not entries:
            return

        colors = self._get_colors(len(entries))
        offset_step = self.ui.offsetSpectraSpinner.value()

        # determine x column — use Wavenumber if available, else Wavelength
        first_data = entries[0].spectrum.data
        x_col = "Wavenumber" if "Wavenumber" in first_data.columns else "Wavelength"
        x_label = "Wavenumber (cm$^{-1}$)" if x_col == "Wavenumber" else "Wavelength (nm)"

        for i, entry in enumerate(entries):
            try:
                data = entry.spectrum.frame(1)
                x = data[x_col].to_numpy()
                y = self._normalize(x, data["Intensity"].to_numpy())
                y_offset = y + i * offset_step

                self.plot_widget.ax.plot(
                    x, y_offset,
                    color=colors[i],
                    label=entry.label,
                )
            except Exception as e:
                logger.warning("Could not plot %s: %s", entry.label, e)

        if len(entries) > 1:
            self.plot_widget.ax.legend(fontsize=8)

        self.plot_widget.set_labels(
            xlabel=x_label,
            ylabel="Intensity" if self.ui.normalizationComboBox.currentIndex() == 0
                   else "Normalized Intensity",
            title=f"{len(entries)} spectrum/spectra",
        )

    # ── Sort by metadata ──────────────────────────────────────────────────────

    def _on_sort_by_metadata(self):
        if not self._entries:
            return

        # collect all available metadata keys across all spectra
        all_keys = set()
        for e in self._entries:
            all_keys.update(e.spectrum.metadata.keys())
        all_keys = sorted(all_keys)

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

    def _on_add_from_file(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Load processed spectra", "",
            "CSV files (*.csv);;All files (*.*)"
        )
        if not paths:
            return

        from sfg_app2.processing.utils import _strip_role_suffix, DEFAULT_ROLE_SUFFIXES
        import pandas as pd

        patterns = self._get_active_patterns()
        pattern_map = {len(p): p for p in patterns} if patterns else {}

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
                    clean_stem, role = _strip_role_suffix(path.stem, DEFAULT_ROLE_SUFFIXES)
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

                label = path.stem
                if not self._entry_exists(label):
                    self._entries.append(SpectrumEntry(spectrum, label))
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
        import json
        from datetime import datetime

        spectrum = entry.spectrum
        provenance = getattr(spectrum, "provenance", None) or \
                    _build_provenance_from_history(spectrum)

        header_lines = [
            f"# SFG-App export",
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

        # despike
        despike = provenance.get("despike", {})
        if despike.get("applied"):
            header_lines += [
                f"# Despike:              applied",
                f"#   window:             {despike.get('window', 'N/A')}",
                f"#   threshold_factor:   {despike.get('threshold_factor', 'N/A')}",
            ]
        else:
            header_lines.append("# Despike:              not applied")

        # background subtraction
        bg = provenance.get("background_subtraction", {})
        if bg.get("applied"):
            header_lines += [
                f"# Background subtraction: applied",
                f"#   signal offset:      {bg.get('signal_offset', 'None')}",
                f"#   ref offset:         {bg.get('ref_offset', 'None')}",
            ]
        else:
            header_lines.append("# Background subtraction: not applied")

        # normalization
        norm = provenance.get("normalization", {})
        header_lines.append(
            f"# Normalization:        {'applied' if norm.get('applied') else 'not applied'}"
        )

        # upconversion
        upconv = provenance.get("upconversion", {})
        if upconv.get("applied"):
            header_lines += [
                f"# Upconversion:         applied",
                f"#   wavelength:         {upconv.get('wavelength_nm', 'N/A')} nm",
            ]
        else:
            header_lines.append("# Upconversion:         not applied")

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
        self._refresh_plot()
        logger.info("Removed %d spectrum/spectra from results.", n)