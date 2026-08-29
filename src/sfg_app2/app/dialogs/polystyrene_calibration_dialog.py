from __future__ import annotations
import logging
import numpy as np
import pandas as pd

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QDoubleSpinBox, QComboBox, QDialogButtonBox, QMessageBox, QPushButton,
)

from sfg_app2.app.widgets.spectrum_plot_widget import SpectrumPlotWidget
from sfg_app2.processing.baseline import subtract_background
from sfg_app2.processing.processed_spectrum import ProcessedSpectrum
from sfg_app2.app.utils.loading_indicator import show_loading

logger = logging.getLogger(__name__)

_ps_material_cache = None


def _get_polystyrene_material():
    """Lazily construct and cache the polystyrene RefractiveIndexMaterial.
    The first call may trigger a one-time download of the refractiveindex.info
    database; subsequent calls (including across dialog instances in the same
    session) reuse the cached object."""
    global _ps_material_cache
    if _ps_material_cache is None:
        from refractiveindex import RefractiveIndexMaterial
        _ps_material_cache = RefractiveIndexMaterial(
            shelf="organic", book="polystyrene", page="Myers"
        )
    return _ps_material_cache


def find_best_upconversion_wavelength(
    ratio_wavelength: np.ndarray,
    ratio_intensity: np.ndarray,
    ps_material,
    wn_min: float = 2750.0,
    wn_max: float = 3150.0,
    candidates: np.ndarray | None = None,
) -> tuple[float | None, float]:
    """Scans candidate upconversion wavelengths, scoring each by the
    Pearson correlation between the measured SFG ratio curve and the
    reference polystyrene extinction spectrum over the fixed analysis
    window, and returns the best-scoring (wavelength, correlation).
    Returns (None, -inf) if no candidate produced a usable score.

    Pure/Qt-free so it can be unit-tested and reused independently of
    the dialog; `ps_material` is a RefractiveIndexMaterial (or anything
    exposing get_extinction_coefficient(wavenumber, unit="cm-1")).
    """
    if candidates is None:
        # common upconversion sources (515/532/800/1030 nm) all fall
        # well inside this range, but the scan isn't restricted to just
        # those -- any wavelength in [400, 1400] nm is considered.
        candidates = np.arange(400.0, 1400.0, 0.25)

    best_wl, best_score = None, -np.inf
    for wl in candidates:
        wavenumber = (1e7 / ratio_wavelength) - (1e7 / wl)
        mask = (
            (wavenumber >= wn_min) & (wavenumber <= wn_max)
            & np.isfinite(ratio_intensity)
        )
        if mask.sum() < 5:
            continue
        try:
            ps_ext = ps_material.get_extinction_coefficient(wavenumber[mask], unit="cm-1")
        except Exception:
            continue
        ratio_in_window = ratio_intensity[mask]
        if np.std(ratio_in_window) == 0 or np.std(ps_ext) == 0:
            continue
        score = np.corrcoef(ratio_in_window, ps_ext)[0, 1]
        if np.isfinite(score) and score > best_score:
            best_score, best_wl = score, float(wl)

    return best_wl, best_score


class PolystyreneCalibrationDialog(QDialog):
    """Adjust upconversion wavelength by aligning SFG polystyrene spectrum
    against the known extinction coefficient from refractiveindex.info."""

    def __init__(self, matched_sets: list, initial_wavelength: float, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Polystyrene Calibration")
        self.resize(850, 550)
        self.result_wavelength = initial_wavelength
        self._matched_sets = matched_sets
        self._ratio_wavelength: np.ndarray | None = None
        self._ratio_intensity: np.ndarray | None = None

        self._check_refractiveindex()
        self._build_ui(initial_wavelength)
        self._connect_signals()
        loading = show_loading(self, "Computing calibration ratio...")
        try:
            self._compute_ratio()    # pre-compute ratio from initially selected set
        finally:
            loading.close()
        self._update_plot()

    # ── Dependency check ──────────────────────────────────────────────────────

    def _check_refractiveindex(self):
        try:
            import refractiveindex  # noqa: F401
        except ImportError:
            QMessageBox.critical(
                self, "Feature unavailable",
                "Polystyrene calibration is unavailable in this build "
                "(the 'refractiveindex' package is missing)."
            )
            raise

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self, initial_wavelength: float):
        layout = QVBoxLayout(self)

        # controls row
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Calibration set:"))

        self._set_combo = QComboBox()
        default_idx = 0
        found_default = False
        for i, m in enumerate(self._matched_sets):
            name = m.signal.path.name if m.signal else f"Set {i + 1}"
            self._set_combo.addItem(name)
            if not found_default:
                sig = m.signal
                text = (sig.metadata.get("sample", "") if sig else "") or (sig.path.stem if sig else "")
                if "polystyrene" in text.lower():
                    default_idx = i
                    found_default = True
        self._set_combo.setCurrentIndex(default_idx)
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
            "SFG ratio peaks with the reference polystyrene spectrum, scored over "
            "the plot's current visible x-range. Sets the spinbox above to its "
            "best guess -- still freely adjustable afterward."
        )
        self._auto_detect_btn.clicked.connect(self._on_auto_detect)
        controls.addWidget(self._auto_detect_btn)

        controls.addStretch()
        layout.addLayout(controls)

        # plot — uses raw figure for twin axes, so _update_plot() syncs
        # the widget's own x-range controls (min/max spinboxes, Reset,
        # Save plot) by hand after every rebuild, via set_x_range()/
        # _apply_x_range()/_compute_full_range() -- see _update_plot().
        # Those controls double as the polystyrene analysis window
        # (what auto-detect scores against), not just the visible zoom.
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

    def _connect_signals(self):
        self._wl_spinbox.valueChanged.connect(self._update_plot)
        self._set_combo.currentIndexChanged.connect(self._on_set_changed)

    # ── Calibration computation ───────────────────────────────────────────────

    def _on_set_changed(self, idx: int):
        loading = show_loading(self, "Computing calibration ratio...")
        try:
            self._compute_ratio()
        finally:
            loading.close()
        self._update_plot()

    def _compute_ratio(self):
        """Despike + background subtract both signal and reference,
        then compute quartz / polystyrene ratio."""
        idx = self._set_combo.currentIndex()
        if idx < 0 or idx >= len(self._matched_sets):
            return
        m = self._matched_sets[idx]
        if not m.is_complete():
            logger.warning("Selected calibration set is incomplete.")
            return

        try:
            sig = m.signal.remove_cosmic_rays().average_spectrum()
            bg = m.background.remove_cosmic_rays().average_spectrum()
            ref = m.reference.remove_cosmic_rays().average_spectrum()
            ref_bg = m.reference_background.remove_cosmic_rays().average_spectrum()

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
        wn_min, wn_max = x_range if x_range is not None else (2750.0, 3150.0)

        loading = show_loading(self, "Scanning for best upconversion wavelength...")
        try:
            ps = _get_polystyrene_material()
            best_wl, best_score = find_best_upconversion_wavelength(
                self._ratio_wavelength, self._ratio_intensity, ps,
                wn_min=wn_min, wn_max=wn_max,
            )
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
            f"Best match: {best_wl:.2f} nm (correlation {best_score:.2f}). "
            "Check the plot and fine-tune manually if needed."
        )

    def _update_plot(self):
        """Replot with current upconversion wavelength — called on every spinbox change."""
        wl = self._wl_spinbox.value()

        if self._ratio_wavelength is None or self._ratio_intensity is None:
            return

        # upconvert wavelength → wavenumber
        wavenumber = (1e7 / self._ratio_wavelength) - (1e7 / wl)

        # get polystyrene extinction coefficient
        try:
            loading = (
                show_loading(self, "Loading polystyrene reference data (first time only)...")
                if _ps_material_cache is None else None
            )
            try:
                ps = _get_polystyrene_material()
                ps_ext = ps.get_extinction_coefficient(wavenumber, unit="cm-1")
            finally:
                if loading is not None:
                    loading.close()
        except Exception as e:
            logger.warning("Could not load polystyrene data: %s", e)
            ps_ext = None

        # rebuild twin-axis plot manually via the figure
        self.plot_widget.figure.clear()
        ax1 = self.plot_widget.figure.add_subplot(111)
        ax1.plot(
            wavenumber, self._ratio_intensity,
            color="steelblue", label="Quartz / Polystyrene (SFG)",
        )
        ax1.set_xlabel("Wavenumber (cm$^{-1}$)")
        ax1.set_ylabel("SFG Intensity ratio (a.u.)", color="steelblue")

        if ps_ext is not None:
            ax2 = ax1.twinx()
            ax2.plot(
                wavenumber, ps_ext,
                color="firebrick", linestyle="--",
                label="Polystyrene k (Myers)",
            )
            ax2.set_ylabel("Extinction coefficient k", color="firebrick")
            # combined legend
            lines = ax1.get_lines() + ax2.get_lines()
            labels = [l.get_label() for l in lines]
            ax1.legend(lines, labels, fontsize=8)

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
        self.accept()