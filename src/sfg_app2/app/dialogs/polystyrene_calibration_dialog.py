from __future__ import annotations
import logging
import numpy as np
import pandas as pd

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QDoubleSpinBox, QComboBox, QDialogButtonBox, QMessageBox
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
                self, "Missing dependency",
                "The 'refractiveindex' package is required for calibration.\n"
                "Install it with:  uv add refractiveindex"
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
        controls.addStretch()
        layout.addLayout(controls)

        # plot — uses raw figure for twin axes
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
        ax1.set_xlim(2750, 3150)

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
        self.plot_widget.figure.tight_layout()
        self.plot_widget.canvas.draw()
        # update stored axes reference
        self.plot_widget.ax = ax1

    # ── OK ────────────────────────────────────────────────────────────────────

    def _on_ok(self):
        self.result_wavelength = self._wl_spinbox.value()
        self.accept()