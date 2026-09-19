from __future__ import annotations
import logging
import numpy as np
import pandas as pd

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QFileDialog,
    QDoubleSpinBox, QComboBox, QDialogButtonBox, QMessageBox, QPushButton,
)

from sfg_app2.app.widgets.spectrum_plot_widget import SpectrumPlotWidget
from sfg_app2.processing.baseline import subtract_background
from sfg_app2.processing.processed_spectrum import ProcessedSpectrum
from sfg_app2.processing import calibration as calib
from sfg_app2.app.utils.calibration_settings import (
    CURVE, LINES, MATERIAL, CalibrationConfig, CalibrationSettings,
)
from sfg_app2.app.utils.loading_indicator import show_loading

logger = logging.getLogger(__name__)


class CalibrationDialog(QDialog):
    """Pin down the upconversion wavelength against a known reference.

    Polystyrene's tabulated extinction is the default and the original
    method, but the reference can equally be another tabulated
    material, a curve from a file, or just a list of known line
    positions — which is the only option that needs no reference
    database at all.
    """

    def __init__(self, matched_sets: list, initial_wavelength: float,
                 settings: CalibrationSettings | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Calibration")
        self.resize(900, 600)
        self.result_wavelength = initial_wavelength
        self._matched_sets = matched_sets
        self._settings = settings or CalibrationSettings()
        self._config = self._settings.config
        self._ratio_wavelength: np.ndarray | None = None
        self._ratio_intensity: np.ndarray | None = None

        self._build_ui(initial_wavelength)
        self._connect_signals()
        self._apply_mode_visibility()
        loading = show_loading(self, "Computing calibration ratio...")
        try:
            self._compute_ratio()    # pre-compute ratio from initially selected set
        finally:
            loading.close()
        self._update_plot()

    # ── Reference ─────────────────────────────────────────────────────────────

    def _current_config(self) -> CalibrationConfig:
        lines = []
        for chunk in self._lines_edit.text().replace(";", ",").split(","):
            chunk = chunk.strip()
            if not chunk:
                continue
            try:
                lines.append(float(chunk))
            except ValueError:
                continue
        return CalibrationConfig(
            kind=self._mode_combo.currentData(),
            shelf=self._shelf_edit.text().strip() or calib.POLYSTYRENE[0],
            book=self._book_edit.text().strip() or calib.POLYSTYRENE[1],
            page=self._page_edit.text().strip() or calib.POLYSTYRENE[2],
            curve_path=self._curve_edit.text().strip(),
            lines=lines,
            wn_min=self._config.wn_min,
            wn_max=self._config.wn_max,
        )

    def _reference(self):
        """The reference to sample, or None in line mode. Returns None
        and warns rather than raising -- a half-typed material name
        shouldn't take the dialog down."""
        try:
            return self._current_config().build_reference()
        except ImportError:
            QMessageBox.warning(
                self, "Reference unavailable",
                "Tabulated materials need the 'refractiveindex' package, "
                "which is missing from this build. A reference curve from "
                "a file, or a list of known line positions, will still work."
            )
        except Exception as e:
            logger.warning("Could not build the reference: %s", e)
        return None

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self, initial_wavelength: float):
        layout = QVBoxLayout(self)

        # controls row
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Calibration set:"))

        self._set_combo = QComboBox()
        for i, m in enumerate(self._matched_sets):
            self._set_combo.addItem(m.signal.path.name if m.signal else f"Set {i + 1}")
        self._set_combo.setCurrentIndex(self._default_set_index())
        controls.addWidget(self._set_combo)

        controls.addWidget(QLabel("Upconversion wavelength:"))
        self._wl_spinbox = QDoubleSpinBox()
        self._wl_spinbox.setRange(400.0, 1400.0)
        self._wl_spinbox.setDecimals(2)
        self._wl_spinbox.setSingleStep(0.1)
        self._wl_spinbox.setSuffix(" nm")
        self._wl_spinbox.setValue(initial_wavelength)
        controls.addWidget(self._wl_spinbox)

        self._auto_detect_btn = QPushButton("Auto-detect")
        self._auto_detect_btn.setToolTip(
            "Scan for the upconversion wavelength that best aligns the measured "
            "SFG ratio peaks with the chosen reference, scored over "
            "the plot's current visible x-range. Sets the spinbox above to its "
            "best guess -- still freely adjustable afterward."
        )
        self._auto_detect_btn.clicked.connect(self._on_auto_detect)
        controls.addWidget(self._auto_detect_btn)

        controls.addStretch()
        layout.addLayout(controls)
        layout.addLayout(self._build_reference_row())

        # plot — uses raw figure for twin axes, so _update_plot() syncs
        # the widget's own x-range controls (min/max spinboxes, Reset,
        # Save plot) by hand after every rebuild, via set_x_range()/
        # _apply_x_range()/_compute_full_range() -- see _update_plot().
        # Those controls double as the analysis window (what
        # auto-detect scores against), not just the visible zoom.
        self.plot_widget = SpectrumPlotWidget()
        layout.addWidget(self.plot_widget)

        # buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_ok)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _default_set_index(self) -> int:
        """Preselect the set that looks like the reference material.

        Matched on the configured reference's own name rather than the
        literal string "polystyrene", so choosing a different material
        preselects a different set.
        """
        needle = (self._config.book or self._config.display_name()).lower()
        for i, m in enumerate(self._matched_sets):
            sig = m.signal
            if sig is None:
                continue
            text = (sig.metadata.get("sample", "") or sig.path.stem or "").lower()
            if needle and needle in text:
                return i
        return 0

    def _build_reference_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(QLabel("Reference:"))

        self._mode_combo = QComboBox()
        self._mode_combo.addItem("Tabulated material", MATERIAL)
        self._mode_combo.addItem("Curve from file", CURVE)
        self._mode_combo.addItem("Known line positions", LINES)
        self._mode_combo.setCurrentIndex(
            max(self._mode_combo.findData(self._config.kind), 0))
        row.addWidget(self._mode_combo)

        self._shelf_edit = QLineEdit(self._config.shelf)
        self._book_edit = QLineEdit(self._config.book)
        self._page_edit = QLineEdit(self._config.page)
        for widget, tip, width in (
            (self._shelf_edit, "refractiveindex.info shelf, e.g. 'organic'", 90),
            (self._book_edit, "Material, e.g. 'polystyrene'", 130),
            (self._page_edit, "Dataset/author page, e.g. 'Myers'", 110),
        ):
            widget.setToolTip(tip)
            widget.setFixedWidth(width)
            row.addWidget(widget)

        self._curve_edit = QLineEdit(self._config.curve_path)
        self._curve_edit.setPlaceholderText("two columns: wavenumber, value")
        row.addWidget(self._curve_edit, 1)
        self._browse_btn = QPushButton("Browse...")
        self._browse_btn.clicked.connect(self._on_browse_curve)
        row.addWidget(self._browse_btn)

        self._lines_edit = QLineEdit(
            ", ".join(f"{v:g}" for v in self._config.lines))
        self._lines_edit.setPlaceholderText(
            "known wavenumbers, e.g. 2850, 2880, 2920")
        self._lines_edit.setToolTip(
            "Literature peak positions in cm-1. The scan lines the measured "
            "peaks up with these, so no reference database is needed."
        )
        row.addWidget(self._lines_edit, 1)
        return row

    def _apply_mode_visibility(self):
        kind = self._mode_combo.currentData()
        for widget in (self._shelf_edit, self._book_edit, self._page_edit):
            widget.setVisible(kind == MATERIAL)
        for widget in (self._curve_edit, self._browse_btn):
            widget.setVisible(kind == CURVE)
        self._lines_edit.setVisible(kind == LINES)

    def _on_browse_curve(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose a reference curve", "",
            "Reference data (*.csv *.txt *.dat);;All files (*)")
        if path:
            self._curve_edit.setText(path)
            self._update_plot()

    def _on_reference_changed(self):
        self._apply_mode_visibility()
        self._update_plot()

    def _connect_signals(self):
        self._wl_spinbox.valueChanged.connect(self._update_plot)
        self._set_combo.currentIndexChanged.connect(self._on_set_changed)
        self._mode_combo.currentIndexChanged.connect(self._on_reference_changed)
        for widget in (self._shelf_edit, self._book_edit, self._page_edit,
                       self._curve_edit, self._lines_edit):
            widget.editingFinished.connect(self._update_plot)

    # ── Calibration computation ───────────────────────────────────────────────

    def _on_set_changed(self, idx: int):
        loading = show_loading(self, "Computing calibration ratio...")
        try:
            self._compute_ratio()
        finally:
            loading.close()
        self._update_plot()

    def _compute_ratio(self):
        """Background subtract both signal and reference (with
        per-component despiking, see below), then form the
        reference / sample intensity ratio the scan works on."""
        idx = self._set_combo.currentIndex()
        if idx < 0 or idx >= len(self._matched_sets):
            return
        m = self._matched_sets[idx]
        if not m.is_complete():
            logger.warning("Selected calibration set is incomplete.")
            return

        try:
            # Despike params are chosen per-component rather than
            # uniformly (this call path is disconnected from the visible
            # despike dock controls entirely, so these are the only
            # despiking applied here): the sample signal is left
            # undespiked entirely; the reference keeps the
            # window=20/threshold=50 already tuned for it; both
            # backgrounds use a wider, gentler window=150/threshold=10
            # instead.
            sig = m.signal.average_spectrum()
            bg = m.background.remove_cosmic_rays(window=150, threshold_factor=10).average_spectrum()
            ref = m.reference.remove_cosmic_rays(window=20, threshold_factor=50).average_spectrum()
            ref_bg = m.reference_background.remove_cosmic_rays(window=150, threshold_factor=10).average_spectrum()

            sig_corr = subtract_background(sig, bg)
            ref_corr = subtract_background(ref, ref_bg)

            sig_int = sig_corr.frame(1)["Intensity"].to_numpy()
            ref_int = ref_corr.frame(1)["Intensity"].to_numpy()
            self._ratio_wavelength = sig_corr.frame(1)["Wavelength"].to_numpy()

            # avoid division by zero
            with np.errstate(divide="ignore", invalid="ignore"):
                self._ratio_intensity = np.where(
                    sig_int != 0, ref_int / sig_int, np.nan
                )
        except Exception as e:
            logger.error("Calibration ratio computation failed: %s", e)
            self._ratio_wavelength = None
            self._ratio_intensity = None

    def _on_auto_detect(self):
        """Scans candidate upconversion wavelengths (see
        find_best_upconversion_wavelength) and sets the spinbox to the
        best-scoring one. The user still sees the resulting plot and
        can freely override it afterward -- this never applies without
        that visual check."""
        if self._ratio_wavelength is None or self._ratio_intensity is None:
            QMessageBox.information(
                self, "No data", "Select a calibration set first."
            )
            return

        x_range = self.plot_widget.get_x_range()
        wn_min, wn_max = x_range if x_range is not None else calib.DEFAULT_WINDOW
        config = self._current_config()

        if config.kind == LINES and not config.lines:
            QMessageBox.information(
                self, "No reference lines",
                "Enter the known line positions (in cm-1) to match against."
            )
            return

        loading = show_loading(self, "Scanning for best upconversion wavelength...")
        try:
            if config.kind == LINES:
                best_wl, score = calib.find_upconversion_from_lines(
                    self._ratio_wavelength, self._ratio_intensity, config.lines,
                    wn_min=wn_min, wn_max=wn_max,
                )
                # This one scores as an RMS distance, so it reads the
                # opposite way round to the correlation.
                summary = f"lines matched to within {score:.1f} cm⁻¹"
            else:
                reference = self._reference()
                if reference is None:
                    return
                best_wl, score = calib.find_best_upconversion_wavelength(
                    self._ratio_wavelength, self._ratio_intensity, reference,
                    wn_min=wn_min, wn_max=wn_max,
                )
                summary = f"correlation {score:.2f}"
        except Exception as e:
            logger.error("Auto-detect failed: %s", e, exc_info=True)
            QMessageBox.warning(self, "Auto-detect failed", str(e))
            return
        finally:
            loading.close()

        if best_wl is None:
            QMessageBox.information(
                self, "Auto-detect failed",
                "Could not find a good alignment across the scanned "
                "wavelength range (400-1400 nm). Try adjusting manually."
            )
            return

        self._wl_spinbox.setValue(best_wl)   # triggers _update_plot via valueChanged
        QMessageBox.information(
            self, "Auto-detect complete",
            f"Best match: {best_wl:.2f} nm ({summary}). "
            "Check the plot and fine-tune manually if needed."
        )

    def _update_plot(self):
        """Replot with current upconversion wavelength — called on every spinbox change."""
        wl = self._wl_spinbox.value()

        if self._ratio_wavelength is None or self._ratio_intensity is None:
            return

        # upconvert wavelength → wavenumber
        wavenumber = calib.to_wavenumber(self._ratio_wavelength, wl)
        config = self._current_config()

        reference_values = None
        if config.kind != LINES:
            loading = show_loading(self, "Loading reference data...")
            try:
                reference = self._reference()
                if reference is not None:
                    reference_values = reference.sample(wavenumber)
            except Exception as e:
                logger.warning("Could not sample the reference: %s", e)
            finally:
                loading.close()

        # rebuild twin-axis plot manually via the figure
        self.plot_widget.figure.clear()
        ax1 = self.plot_widget.figure.add_subplot(111)
        ax1.plot(
            wavenumber, self._ratio_intensity,
            color="steelblue", label="Reference / sample (SFG)",
        )
        ax1.set_xlabel("Wavenumber (cm$^{-1}$)")
        ax1.set_ylabel("SFG Intensity ratio (a.u.)", color="steelblue")

        if reference_values is not None:
            ax2 = ax1.twinx()
            ax2.plot(
                wavenumber, reference_values,
                color="firebrick", linestyle="--",
                label=config.display_name(),
            )
            ax2.set_ylabel("Reference absorption", color="firebrick")
            lines = ax1.get_lines() + ax2.get_lines()
            ax1.legend(lines, [l.get_label() for l in lines], fontsize=8)
        elif config.kind == LINES and config.lines:
            # No curve to overlay: show where the known lines fall, and
            # where the peaks actually landed, which is what the user is
            # lining up by eye.
            for i, position in enumerate(config.lines):
                ax1.axvline(position, color="firebrick", linestyle="--",
                            alpha=0.8, label="Known lines" if i == 0 else None)
            found = calib.detect_peaks(wavenumber, self._ratio_intensity)
            for i, position in enumerate(found):
                ax1.axvline(position, color="seagreen", linestyle=":",
                            alpha=0.6, label="Detected peaks" if i == 0 else None)
            ax1.legend(fontsize=8)

        ax1.set_title(f"Upconversion: {wl:.2f} nm")

        # Keep the plot widget's own range controls in sync with axes
        # that get fully rebuilt on every redraw. _compute_full_range()
        # refreshes what "Reset" restores to (the whole measured
        # spectrum, not just the analysis window). First call ever:
        # seed the familiar default 2750-3150 window. Every later call
        # (wavelength or set changed): re-apply whatever's currently
        # dialed into the spinboxes, so zooming/picking a region
        # doesn't get silently reset on every tweak.
        self.plot_widget._compute_full_range()
        if self.plot_widget.get_x_range() is None:
            self.plot_widget.set_x_range(2750.0, 3150.0)
        else:
            self.plot_widget._apply_x_range()

        self.plot_widget.figure.tight_layout()
        self.plot_widget.canvas.draw()
        # update stored axes reference
        self.plot_widget.ax = ax1

    # ── OK ────────────────────────────────────────────────────────────────────

    def _on_ok(self):
        self.result_wavelength = self._wl_spinbox.value()
        # Remember the reference: re-entering a list of literature line
        # positions, or re-finding a curve file, every session is the
        # main friction in using anything other than the default.
        config = self._current_config()
        x_range = self.plot_widget.get_x_range()
        if x_range is not None:
            config.wn_min, config.wn_max = x_range
        self._settings.set_config(config)
        self.accept()