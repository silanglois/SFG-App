from __future__ import annotations
import logging

import numpy as np
from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QGroupBox, QPushButton, QRadioButton, QButtonGroup,
    QComboBox, QCheckBox, QSpinBox, QDoubleSpinBox,
    QFrame, QSizePolicy
)

from sfg_app2.app.widgets.spectrum_plot_widget import SpectrumPlotWidget
from sfg_app2.app.widgets.collapsible_group_box import make_collapsible

logger = logging.getLogger(__name__)

HD_STEPS = [
    "raw", "despiked", "averaged",
    "bg_smooth", "fft_filter", "ifft", "normalization",
]
HD_STEP_LABELS = {
    "raw":           "Raw",
    "despiked":      "Despiked",
    "averaged":      "Averaged",
    "bg_smooth":     "BG + Subtraction",
    "fft_filter":    "FFT + Filter",
    "ifft":          "iFFT",
    "normalization": "Normalization",
}
TIME_DOMAIN_STEPS = {"fft_filter"}

# which param section opens automatically per step
STEP_SECTION = {
    "raw":           None,
    "despiked":      "despike",
    "averaged":      None,
    "bg_smooth":     "bg_smooth",
    "fft_filter":    "fft_window",
    "ifft":          None,
    "normalization": "normalization",
}

# steps that support sample/ref/both selector
COMPONENT_STEPS = {
    "raw", "despiked", "averaged",
    "bg_smooth", "fft_filter", "ifft",
}


class HDSFGPanel(QWidget):
    """Right panel for heterodyne sets in the Process/Review tab."""

    processing_complete = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)

        self._matched_set  = None
        self._matched_index: int = -1

        # per-step cache — keyed by matched_set_index
        # each entry: dict with keys matching HD_STEPS
        self._cache: dict[int, dict] = {}

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(4, 4, 4, 4)
        main_layout.setSpacing(4)

        # ── Row 1: step selector ──────────────────────────────────────────────
        main_layout.addWidget(self._build_step_selector())

        # ── Row 2: component + apply row (hidden when not applicable) ─────────
        self._component_row = self._build_component_row()
        main_layout.addWidget(self._component_row)

        # ── Row 3: plot area ──────────────────────────────────────────────────
        self.plot_widget = SpectrumPlotWidget()
        self.plot_widget.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        main_layout.addWidget(self.plot_widget)

        # ── Row 4: param sections (collapsible, only one visible at a time) ───
        self._param_sections: dict[str, QGroupBox] = {}
        self._param_sections["despike"]       = self._build_despike_section()
        self._param_sections["bg_smooth"]     = self._build_bg_smooth_section()
        self._param_sections["fft_window"]    = self._build_fft_window_section()
        self._param_sections["normalization"] = self._build_normalization_section()

        for gb in self._param_sections.values():
            make_collapsible(gb)
            gb.setChecked(False)
            gb.setVisible(False)   # all hidden initially
            main_layout.addWidget(gb)

        self._connect_signals()
        self._on_step_changed()

    # ── Step selector ─────────────────────────────────────────────────────────

    def _build_step_selector(self) -> QFrame:
        frame = QFrame()
        frame.setFrameShape(QFrame.Shape.StyledPanel)
        frame.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.addWidget(QLabel("Step:"))

        self._step_group  = QButtonGroup(self)
        self._step_radios: dict[str, QRadioButton] = {}
        for step in HD_STEPS:
            rb = QRadioButton(HD_STEP_LABELS[step])
            rb.setEnabled(step == "raw")
            self._step_radios[step] = rb
            self._step_group.addButton(rb)
            layout.addWidget(rb)

        self._step_radios["raw"].setChecked(True)
        return frame

    # ── Component + apply row ─────────────────────────────────────────────────

    def _build_component_row(self) -> QFrame:
        frame = QFrame()
        frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(4, 0, 4, 0)

        # --- raw / despiked / averaged ---
        self._pair_label = QLabel("Pair:")
        self._pair_combo = QComboBox()
        self._pair_combo.addItems(["Sample pair", "Reference pair", "Both pairs"])
        self._pair_combo.setFixedWidth(120)

        self._source_label = QLabel("Show:")
        self._source_combo = QComboBox()
        self._source_combo.addItems(["Signal", "Background", "Both"])
        self._source_combo.setFixedWidth(110)

        # --- bg subtraction ---
        self._view_label = QLabel("View:")
        self._view_combo = QComboBox()
        self._view_combo.addItems(["Signal + Background", "Subtracted result"])
        self._view_combo.setFixedWidth(170)

        # --- fft_filter / ifft ---
        self._comp_label = QLabel("Show:")
        self._comp_combo = QComboBox()
        self._comp_combo.addItems(["Sample", "Reference", "Both"])
        self._comp_combo.setFixedWidth(110)

        for w in [self._pair_label, self._pair_combo,
                self._source_label, self._source_combo,
                self._view_label, self._view_combo,
                self._comp_label, self._comp_combo]:
            layout.addWidget(w)

        layout.addStretch()

        self._apply_btn = QPushButton("Apply")
        self._apply_btn.setFixedWidth(80)
        layout.addWidget(self._apply_btn)

        # Finish button — normalization step only
        self._finish_btn = QPushButton("✓ Send to Results")
        self._finish_btn.setVisible(False)
        layout.addWidget(self._finish_btn)

        return frame

    # ── Param section builders ────────────────────────────────────────────────

    def _build_despike_section(self) -> QGroupBox:
        from PySide6.QtWidgets import QGridLayout
        gb = QGroupBox("Despike parameters")
        gb.setCheckable(True)
        grid = QGridLayout(gb)

        # headers
        grid.addWidget(QLabel(""), 0, 0)
        grid.addWidget(QLabel("Window"), 0, 1)
        grid.addWidget(QLabel("Threshold"), 0, 2)

        self._despike_params: dict[str, dict] = {}
        for row_idx, (key, label) in enumerate([
            ("signal",       "Sample"),
            ("background",   "Sample BG"),
            ("reference",    "Reference"),
            ("ref_background","Ref BG"),
        ], start=1):
            grid.addWidget(QLabel(label + ":"), row_idx, 0)

            window_sb = QSpinBox()
            window_sb.setRange(3, 101)
            window_sb.setSingleStep(2)
            window_sb.setValue(20)
            grid.addWidget(window_sb, row_idx, 1)

            threshold_sb = QDoubleSpinBox()
            threshold_sb.setRange(0.5, 10000.0)
            threshold_sb.setSingleStep(10.0)
            threshold_sb.setDecimals(1)
            threshold_sb.setValue(15.0)
            grid.addWidget(threshold_sb, row_idx, 2)

            self._despike_params[key] = {
                "window":    window_sb,
                "threshold": threshold_sb,
            }

        return gb


    def _get_despike_params(self, key: str):
        from sfg_app2.processing.hd_sfg.steps import DeSpikeParams
        p = self._despike_params[key]
        return DeSpikeParams(
            window=p["window"].value(),
            threshold=p["threshold"].value(),
        )

    def _build_bg_smooth_section(self) -> QGroupBox:
        gb = QGroupBox("Background subtraction + edge window")
        gb.setCheckable(True)
        layout = QHBoxLayout(gb)

        layout.addWidget(QLabel("BG offset:"))
        self._bg_offset = QDoubleSpinBox()
        self._bg_offset.setRange(-10000.0, 10000.0)
        self._bg_offset.setValue(30.0)
        layout.addWidget(self._bg_offset)

        layout.addWidget(QLabel("Edge high wn (pts):"))
        self._edge_left = QSpinBox()   # controls high-wn end
        self._edge_left.setRange(1, 500)
        self._edge_left.setValue(4)
        layout.addWidget(self._edge_left)

        layout.addWidget(QLabel("Edge low wn (pts):"))
        self._edge_right = QSpinBox()  # controls low-wn end
        self._edge_right.setRange(1, 500)
        self._edge_right.setValue(100)
        layout.addWidget(self._edge_right)

        layout.addStretch()
        return gb

    def _build_fft_window_section(self) -> QGroupBox:
        gb = QGroupBox("FFT filter window parameters")
        gb.setCheckable(True)
        layout = QHBoxLayout(gb)
        layout.addWidget(QLabel("Type:"))
        self._fft_window_type = QComboBox()
        for label, val in [
            ("1 — Box-Car", 1),
            ("2 — Box-Car + HG", 2),
            ("3 — Double HG", 3),
            ("4 — Masking HG", 4),
        ]:
            self._fft_window_type.addItem(label, userData=val)
        self._fft_window_type.setCurrentIndex(1)
        layout.addWidget(self._fft_window_type)
        for label, attr, default in [
            ("Start (pts):", "_fft_start",  35),
            ("End (pts):",   "_fft_end",   100),
            ("HG L (pts):",  "_hg_left",    10),
            ("HG R (pts):",  "_hg_right",   10),
        ]:
            layout.addWidget(QLabel(label))
            sb = QSpinBox()
            sb.setRange(1, 1000)
            sb.setValue(default)
            setattr(self, attr, sb)
            layout.addWidget(sb)
        layout.addStretch()
        return gb

    def _build_normalization_section(self) -> QGroupBox:
        gb = QGroupBox("Normalization parameters")
        gb.setCheckable(True)
        layout = QVBoxLayout(gb)

        # exposure + phase row
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Sample exp (s):"))
        self._sample_exp = QDoubleSpinBox()
        self._sample_exp.setRange(0.001, 100000.0)
        self._sample_exp.setValue(300.0)
        row1.addWidget(self._sample_exp)
        row1.addWidget(QLabel("Ref exp (s):"))
        self._ref_exp = QDoubleSpinBox()
        self._ref_exp.setRange(0.001, 100000.0)
        self._ref_exp.setValue(1.0)
        row1.addWidget(self._ref_exp)
        row1.addWidget(QLabel("Phase corr (°):"))
        self._phase_corr = QDoubleSpinBox()
        self._phase_corr.setRange(-360.0, 360.0)
        self._phase_corr.setSingleStep(1.0)
        self._phase_corr.setValue(0.0)
        row1.addWidget(self._phase_corr)
        row1.addStretch()
        layout.addLayout(row1)

        # component checkboxes row
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Plot:"))
        self._cb_imag     = QCheckBox("Im(χ⁽²⁾)")
        self._cb_real     = QCheckBox("Re(χ⁽²⁾)")
        self._cb_homodyne = QCheckBox("|χ⁽²⁾|²")
        self._cb_phase    = QCheckBox("Phase")
        self._cb_errors   = QCheckBox("Show errors")
        self._cb_imag.setChecked(True)
        self._cb_real.setChecked(True)
        for cb in [self._cb_imag, self._cb_real,
                   self._cb_homodyne, self._cb_phase, self._cb_errors]:
            row2.addWidget(cb)
        row2.addStretch()
        layout.addLayout(row2)

        return gb

    # ── Signal wiring ─────────────────────────────────────────────────────────

    def _connect_signals(self):
        for rb in self._step_radios.values():
            rb.toggled.connect(
                lambda checked, r=rb: self._on_step_changed() if checked else None
            )
        self._pair_combo.currentIndexChanged.connect(self._refresh_plot)
        self._source_combo.currentIndexChanged.connect(self._refresh_plot)
        self._view_combo.currentIndexChanged.connect(self._refresh_plot)
        self._comp_combo.currentIndexChanged.connect(self._refresh_plot)
        self._apply_btn.clicked.connect(self._on_apply)
        self._finish_btn.clicked.connect(self._on_finish)
        for cb in [self._cb_imag, self._cb_real,
                self._cb_homodyne, self._cb_phase, self._cb_errors]:
            cb.stateChanged.connect(self._refresh_plot)

    # ── Step change ───────────────────────────────────────────────────────────

    def _on_step_changed(self):
        step = self._current_step()

        # which widgets are visible in the component row
        pair_source_steps = {"raw", "despiked", "averaged"}
        view_steps        = {"bg_smooth"}
        comp_steps        = {"fft_filter", "ifft"}

        self._pair_label.setVisible(step in pair_source_steps)
        self._pair_combo.setVisible(step in pair_source_steps)
        self._source_label.setVisible(step in pair_source_steps)
        self._source_combo.setVisible(step in pair_source_steps)
        self._view_label.setVisible(step in view_steps)
        self._view_combo.setVisible(step in view_steps)
        self._comp_label.setVisible(step in comp_steps)
        self._comp_combo.setVisible(step in comp_steps)

        # component row visible for all steps except raw (no apply needed there)
        no_apply_steps = {"raw", "ifft", "normalization"}
        self._apply_btn.setVisible(step not in no_apply_steps)
        self._finish_btn.setVisible(step == "normalization")

        # param sections
        section_key = STEP_SECTION.get(step)
        for key, gb in self._param_sections.items():
            gb.setVisible(key == section_key)
            if key == section_key:
                gb.setChecked(True)

        self._refresh_plot()

    def _on_finish(self):
        c = self._cache.get(self._matched_index, {})
        if "normalization" in c and self._matched_set:
            self.processing_complete.emit(
                {self._matched_set.signal.path.name: c["normalization"]}
            )

    # ── Plot ──────────────────────────────────────────────────────────────────

    def _refresh_plot(self):
        step = self._current_step()
        self.plot_widget.full_clear()

        if step == "raw":
            self._plot_raw()
            self.plot_widget.canvas.draw_idle()
            return

        cache = self._cache.get(self._matched_index, {})

        if step not in cache:
            # fall through to raw for steps that benefit from a preview
            if step in {"despiked", "averaged"}:
                self._plot_raw()
                self.plot_widget.ax.set_title(
                    f"{HD_STEP_LABELS[step]} — showing raw data. "
                    f"Adjust parameters and click Apply."
                )
            else:
                self.plot_widget.set_labels(
                    title=f"{HD_STEP_LABELS[step]} — click Apply to compute"
                )
            self.plot_widget.canvas.draw_idle()
            return

        try:
            plotter = {
                "despiked":      self._plot_despiked,
                "averaged":      self._plot_averaged,
                "bg_smooth":     self._plot_bg_smooth,
                "fft_filter":    self._plot_fft_filter,
                "ifft":          self._plot_ifft,
                "normalization": self._plot_normalization,
            }.get(step)
            if plotter:
                plotter(cache[step])
        except Exception as e:
            logger.warning("HD-SFG plot failed at '%s': %s", step, e, exc_info=True)

        self.plot_widget.canvas.draw_idle()

    def _component(self) -> str:
        return self._comp_combo.currentText().lower()   # "sample"/"reference"/"both"

    def _upconversion_wl(self) -> float:
        try:
            return self.window().process_review_tab.get_upconversion_wavelength()
        except Exception:
            return 1030.7

    # ── Per-step plotters ─────────────────────────────────────────────────────

    def _show_sample(self) -> bool:
        p = self._pair_combo.currentText().lower()
        return "sample" in p or "both" in p

    def _show_reference(self) -> bool:
        p = self._pair_combo.currentText().lower()
        return "reference" in p or "both" in p

    def _show_signal(self) -> bool:
        return self._source_combo.currentText().lower() in ("signal", "both")

    def _show_background(self) -> bool:
        return self._source_combo.currentText().lower() in ("background", "both")

    def _plot_raw(self):
        if self._matched_set is None:
            return
        wl_to_wn = lambda wl: (1e7 / wl) - (1e7 / self._upconversion_wl())
        pair = self._pair()
        source = self._source()

        pairs = []
        if self._show_sample():
            pairs.append(("Sample", self._matched_set.signal,
                                self._matched_set.background))
        if self._show_reference():
            pairs.append(("Ref", self._matched_set.reference,
                                self._matched_set.reference_background))

        for pair_label, sig_src, bg_src in pairs:
            if self._show_signal() and sig_src:
                for fid in sig_src.data["Frame"].unique():
                    fd = sig_src.frame(fid)
                    wn = wl_to_wn(fd["Wavelength"].to_numpy())
                    self.plot_widget.ax.plot(
                        wn, fd["Intensity"].to_numpy(),
                        alpha=0.8, label=f"{pair_label} sig F{fid}"
                    )
            if self._show_background() and bg_src:
                for fid in bg_src.data["Frame"].unique():
                    fd = bg_src.frame(fid)
                    wn = wl_to_wn(fd["Wavelength"].to_numpy())
                    self.plot_widget.ax.plot(
                        wn, fd["Intensity"].to_numpy(),
                        linestyle="--", alpha=0.6, label=f"{pair_label} BG F{fid}"
                    )
        self.plot_widget.set_labels(
            xlabel="Wavenumber (cm⁻¹)", ylabel="Intensity", title="Raw"
        )


    def _plot_despiked(self, data):
        wl_to_wn = lambda wl: (1e7 / wl) - (1e7 / self._upconversion_wl())
        pair = self._pair()
        source = self._source()

        pairs = []
        if self._show_sample():
            pairs.append(("Sample", data.signal, data.background))
        if self._show_reference():
            pairs.append(("Ref", data.reference, data.ref_background))

        for pair_label, sig_src, bg_src in pairs:
            if self._show_signal() and sig_src:
                for fid in sig_src.data["Frame"].unique():
                    fd = sig_src.frame(fid)
                    wn = wl_to_wn(fd["Wavelength"].to_numpy())
                    self.plot_widget.ax.plot(
                        wn, fd["Intensity"].to_numpy(),
                        alpha=0.8, label=f"{pair_label} sig F{fid}"
                    )
            if self._show_background() and bg_src:
                for fid in bg_src.data["Frame"].unique():
                    fd = bg_src.frame(fid)
                    wn = wl_to_wn(fd["Wavelength"].to_numpy())
                    self.plot_widget.ax.plot(
                        wn, fd["Intensity"].to_numpy(),
                        linestyle="--", alpha=0.6, label=f"{pair_label} BG F{fid}"
                    )
        self.plot_widget.set_labels(
            xlabel="Wavenumber (cm⁻¹)", ylabel="Intensity", title="Despiked"
        )


    def _plot_averaged(self, data):
        pair = self._pair()
        source = self._source()
        wn = data.wavenumber

        pairs = []
        if self._show_sample():
            pairs.append(("Sample", data.sig_avg, data.bg_avg))
        if self._show_reference():
            pairs.append(("Ref", data.ref_avg, data.ref_bg_avg))

        for pair_label, sig_y, bg_y in pairs:
            if self._show_signal() and sig_y is not None:
                self.plot_widget.ax.plot(wn, sig_y, label=f"{pair_label} signal")
            if self._show_background() and bg_y is not None:
                self.plot_widget.ax.plot(wn, bg_y, linestyle="--",
                                        alpha=0.7, label=f"{pair_label} BG")
        self.plot_widget.set_labels(
            xlabel="Wavenumber (cm⁻¹)", ylabel="Intensity", title="Averaged"
        )

    def _plot_bg_smooth(self, data):
        """data = BGSubtractedData"""
        wn = data.wavenumber
        view = self._view_combo.currentText()

        if view == "Signal + Background":
            self.plot_widget.ax.plot(wn, data.sig_sm,
                                    label="Signal (smoothed)")
            self.plot_widget.ax.plot(wn, data.bg_sm,
                                    linestyle="--", alpha=0.7,
                                    label="Background (smoothed)")
            self.plot_widget.ax.plot(wn, data.ref_sm,
                                    alpha=0.6, label="Reference (smoothed)")
            self.plot_widget.ax.plot(wn, data.ref_bg_sm,
                                    linestyle="--", alpha=0.5,
                                    label="Ref BG (smoothed)")
            title = "BG Subtraction — Signal + Background"
        else:
            # subtracted result + edge window mask on twin axis
            self.plot_widget.ax.plot(wn, data.sig_delta_windowed,
                                    label="Sample delta (windowed)")
            self.plot_widget.ax.plot(wn, data.ref_delta_windowed,
                                    linestyle="--", alpha=0.7,
                                    label="Ref delta (windowed)")
            self.plot_widget.ax.plot(wn, data.sig_delta,
                                    alpha=0.3, linestyle=":",
                                    label="Sample delta (raw)")
            ax2 = self.plot_widget.ax.twinx()
            ax2.plot(wn, data.edge_win, color="gray",
                    linewidth=0.8, linestyle=":", label="Edge window")
            ax2.set_ylabel("Window weight", color="gray")
            ax2.set_ylim(-0.1, 1.3)
            lines1, labels1 = self.plot_widget.ax.get_legend_handles_labels()
            lines2, labels2 = ax2.get_legend_handles_labels()
            self.plot_widget.ax.legend(
                lines1 + lines2, labels1 + labels2, fontsize=8
            )
            title = "BG Subtraction — Subtracted result + edge window"

        self.plot_widget.ax.axhline(0, color="gray", linewidth=0.5)
        self.plot_widget.set_labels(
            xlabel="Wavenumber (cm⁻¹)", ylabel="Intensity", title=title
        )

    def _plot_fft_filter(self, data):
        """data = FFTFilterData — time domain."""
        comp = self._component()
        t = data.time_axis *1e12  # convert to ps
        if comp in ("sample", "both"):
            self.plot_widget.ax.plot(t, data.sig_fft.imag,
                                     label="Signal FFT (imag)")
        if comp in ("reference", "both"):
            self.plot_widget.ax.plot(t, data.ref_fft.imag,
                                     linestyle="--", alpha=0.7,
                                     label="Reference FFT (imag)")
        # mask on twin axis
        ax2 = self.plot_widget.ax.twinx()
        ax2.plot(t, data.fft_mask, color="firebrick",
                 linewidth=0.8, linestyle=":", label="FFT mask")
        ax2.set_ylabel("Mask weight", color="firebrick")
        ax2.set_ylim(-0.1, 1.3)
        lines1, labels1 = self.plot_widget.ax.get_legend_handles_labels()
        lines2, labels2 = ax2.get_legend_handles_labels()
        self.plot_widget.ax.legend(lines1 + lines2, labels1 + labels2, fontsize=8)
        self.plot_widget.set_labels(
            xlabel="Time (ps)", ylabel="FFT amplitude (imag)",
            title="FFT + filter window"
        )

    def _plot_ifft(self, data):
        """data = FFTFilterData — wavenumber domain iFFT."""
        comp = self._component()
        wn = data.wavenumber
        if comp in ("sample", "both"):
            self.plot_widget.ax.plot(wn, data.sig_ifft.imag,
                                     label="Signal iFFT (imag)")
            self.plot_widget.ax.plot(wn, data.sig_ifft.real,
                                     linestyle="--", label="Signal iFFT (real)")
        if comp in ("reference", "both"):
            self.plot_widget.ax.plot(wn, data.ref_ifft.imag,
                                     alpha=0.7, label="Reference iFFT (imag)")
        self.plot_widget.ax.axhline(0, color="gray", linewidth=0.5)
        self.plot_widget.set_labels(
            xlabel="Wavenumber (cm⁻¹)", ylabel="Amplitude",
            title="iFFT result (frequency domain)"
        )

    def _plot_normalization(self, data):
        wn = data.wavenumber
        show_err = self._cb_errors.isChecked()
        use_avg  = data.n_frames > 1
        has_phase_or_homo = self._cb_homodyne.isChecked() or self._cb_phase.isChecked()
        ax2 = None   # secondary axis — created on demand

        def get_ax2():
            nonlocal ax2
            if ax2 is None:
                ax2 = self.plot_widget.ax.twinx()
                ax2.set_ylabel("|χ⁽²⁾|² / Phase (°)", color="gray")
            return ax2

        if self._cb_imag.isChecked():
            y = data.complex_chi_avg.imag if use_avg else data.complex_chi.imag
            self.plot_widget.ax.plot(wn, y, label="Im(χ⁽²⁾)")
            if show_err and use_avg:
                self.plot_widget.ax.fill_between(
                    wn, y - data.imag_err, y + data.imag_err, alpha=0.3
                )

        if self._cb_real.isChecked():
            y = data.complex_chi_avg.real if use_avg else data.complex_chi.real
            self.plot_widget.ax.plot(wn, y, linestyle="--", label="Re(χ⁽²⁾)")
            if show_err and use_avg:
                self.plot_widget.ax.fill_between(
                    wn, y - data.real_err, y + data.real_err, alpha=0.3
                )

        if self._cb_homodyne.isChecked():
            y = data.homodyne_avg if use_avg else data.homodyne

            # find the max amplitude of whatever is already plotted (Im and/or Re)
            ref_amp = 0.0
            if self._cb_imag.isChecked():
                imag = data.complex_chi_avg.imag if use_avg else data.complex_chi.imag
                ref_amp = max(ref_amp, np.abs(imag).max())
            if self._cb_real.isChecked():
                real = data.complex_chi_avg.real if use_avg else data.complex_chi.real
                ref_amp = max(ref_amp, np.abs(real).max())

            # compute scale factor so homodyne fits same amplitude range
            homo_max = np.abs(y).max()
            if ref_amp > 0 and homo_max > 0:
                scale = ref_amp / homo_max
            else:
                scale = 1.0

            self.plot_widget.ax.plot(
                wn, y * scale, linestyle="-.",
                label=f"|χ⁽²⁾|² (×{scale:.2e})"   # label tells user what scaling was applied
            )
            if show_err and use_avg:
                self.plot_widget.ax.fill_between(
                    wn,
                    (y - data.homodyne_err) * scale,
                    (y + data.homodyne_err) * scale,
                    alpha=0.3
                )

        if self._cb_phase.isChecked():
            y = data.phase_avg if use_avg else data.phase
            get_ax2().plot(wn, y, color="gray", linestyle=":",
                        alpha=0.8, label="Phase (°)")
            get_ax2().axhline(90, color="gray", linewidth=0.4, linestyle="--")
            if show_err and use_avg:
                get_ax2().fill_between(
                    wn, y - data.phase_err, y + data.phase_err,
                    alpha=0.2, color="gray"
                )

        # combined legend
        lines1, labels1 = self.plot_widget.ax.get_legend_handles_labels()
        if ax2:
            lines2, labels2 = ax2.get_legend_handles_labels()
            self.plot_widget.ax.legend(
                lines1 + lines2, labels1 + labels2, fontsize=8
            )
        elif lines1:
            self.plot_widget.ax.legend(fontsize=8)

        self.plot_widget.ax.axhline(0, color="gray", linewidth=0.5, linestyle="--")
        self.plot_widget.set_labels(
            xlabel="Wavenumber (cm⁻¹)",
            ylabel="χ⁽²⁾ (arb. units)",
            title="Normalized HD-SFG result"
        )

    # ── Apply / Process ───────────────────────────────────────────────────────

    def _on_apply(self):
        """Run only the current step (and invalidate later steps)."""
        step = self._current_step()
        if step == "raw":
            self._refresh_plot()
            return
        self._run_from_step(step, emit_result=False)

    def _on_process(self):
        """Run the full pipeline from scratch."""
        self._cache.pop(self._matched_index, None)
        self._run_from_step("despiked", emit_result=True)

    def _run_from_step(self, from_step: str, emit_result: bool = False):
        """Run pipeline from from_step onward, using cached results for earlier steps."""
        from sfg_app2.processing.hd_sfg.steps import (
            step_despike, step_average, step_bg_smooth,
            step_fft_filter, step_normalize,
        )
        if self._matched_set is None or not self._matched_set.is_complete():
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Incomplete set",
                                "This set needs all four files to process.")
            return

        idx = self._matched_index
        if idx not in self._cache:
            self._cache[idx] = {}
        c = self._cache[idx]

        # invalidate from_step and all later steps
        order = ["despiked", "averaged", "bg_smooth",
                 "fft_filter", "ifft", "normalization"]
        invalidate = False
        for s in order:
            if s == from_step:
                invalidate = True
            if invalidate:
                c.pop(s, None)

        try:
            cfg = self._current_config()

            if "despiked" not in c:
                c["despiked"] = step_despike(
                    self._matched_set,
                    sig_params    = self._get_despike_params("signal"),
                    bg_params     = self._get_despike_params("background"),
                    ref_params    = self._get_despike_params("reference"),
                    ref_bg_params = self._get_despike_params("ref_background"),
                )
            if "averaged" not in c:
                c["averaged"] = step_average(c["despiked"], cfg)
            if "bg_smooth" not in c:
                c["bg_smooth"] = step_bg_smooth(c["averaged"], cfg)
            if "fft_filter" not in c:
                fft_data = step_fft_filter(c["bg_smooth"], cfg)
                c["fft_filter"] = fft_data
                c["ifft"] = fft_data   # same data, different view
            if "normalization" not in c:
                result = step_normalize(c["fft_filter"], cfg)
                result.metadata = self._matched_set.signal.metadata.copy()
                result.history  = ["hd_sfg_processing"]
                c["normalization"] = result

        except Exception as e:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "Processing error", str(e))
            logger.error("HD-SFG step failed: %s", e, exc_info=True)
            return

        order = ["despiked", "averaged", "bg_smooth",
                "fft_filter", "ifft", "normalization"]
        enabled = {"raw"}
        for i, s in enumerate(order):
            if s in c:
                enabled.add(s)
                if i + 1 < len(order):
                    enabled.add(order[i + 1])   # next step becomes available

        for step, rb in self._step_radios.items():
            rb.setEnabled(step in enabled)

        self._refresh_plot()

        # emit result for Results tab
        if emit_result and "normalization" in c:
            self.processing_complete.emit(
                {self._matched_set.signal.path.name: c["normalization"]}
            )

    # ── Config ────────────────────────────────────────────────────────────────

    def _current_config(self):
        from sfg_app2.processing.hd_sfg import HDSFGConfig
        return HDSFGConfig(
            upconversion_wavelength = self._upconversion_wl(),
            bg_smoothing_window     = 0,   # disabled
            bg_smoothing_order      = 0,
            sig_smoothing_window    = 0,   # disabled
            sig_smoothing_order     = 0,
            bg_offset               = self._bg_offset.value(),
            edge_left               = self._edge_left.value(),
            edge_right              = self._edge_right.value(),
            window_type             = self._fft_window_type.currentData(),
            fft_start               = self._fft_start.value(),
            fft_end                 = self._fft_end.value(),
            hg_left                 = self._hg_left.value(),
            hg_right                = self._hg_right.value(),
            sample_exposure         = self._sample_exp.value(),
            reference_exposure      = self._ref_exp.value(),
            phase_correction_deg    = self._phase_corr.value(),
        )

    def _current_step(self) -> str:
        for step, rb in self._step_radios.items():
            if rb.isChecked():
                return step
        return "raw"

    # ── Public API ────────────────────────────────────────────────────────────

    def set_matched_set(self, matched_set, index: int):
        self._matched_set   = matched_set
        self._matched_index = index

        cached = self._cache.get(index, {})

        for step, rb in self._step_radios.items():
            # raw always enabled, despiked always enabled (params needed but no prior step),
            # rest only if cached
            rb.setEnabled(
                step in {"raw", "despiked"} or step in cached
            )

        self._step_radios["raw"].setChecked(True)
        self._on_step_changed()

    # --- helpers --------------------------------
    def _pair(self) -> str:
        return self._pair_combo.currentText().lower()   # "sample pair"/"reference pair"/"both pairs"

    def _source(self) -> str:
        return self._source_combo.currentText().lower() # "signal"/"background"/"both"

    def _comp(self) -> str:
        return self._comp_combo.currentText().lower()   # "sample"/"reference"/"both"