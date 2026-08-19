from __future__ import annotations
import logging

from matplotlib.pyplot import step
import numpy as np
from PySide6.QtCore import Signal, Qt, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QGroupBox, QPushButton, QRadioButton, QButtonGroup,
    QComboBox, QCheckBox, QSpinBox, QDoubleSpinBox,
    QFrame, QSizePolicy,
    QTableWidget, QTableWidgetItem, QHeaderView,
)

from sfg_app2.app.widgets.spectrum_plot_widget import SpectrumPlotWidget
from sfg_app2.app.widgets.collapsible_group_box import make_collapsible
from sfg_app2.app.widgets.frame_exclude_widget import FrameCheckStrip
from sfg_app2.app.utils.loading_indicator import show_loading
from sfg_app2.app.utils.phase_wrap import wrap_phase_for_plot
from sfg_app2.processing.baseline import fit_offset_from_markers, _resolve_offset

logger = logging.getLogger(__name__)

HD_STEPS = [
    "raw", "despiked", "averaged",
    "bg_smooth", "fft_filter", "ifft", "normalization",
]
HD_STEP_LABELS = {
    "raw":           "Raw",
    "despiked":      "Despiked",
    "averaged":      "Averaged",
    "bg_smooth":     "BG Subtraction",
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
        self._exclude_frames: dict[int, dict[str, set]] = {}
        self._last_step: str | None = None
        self._norm_lines: dict = {}
        self._norm_ax2 = None

        # background-offset markers — global (x, y) values, see
        # _build_bg_smooth_section()'s docstring
        self._bg_markers: list[tuple[float, float]] = []
        self._marker_just_picked = False

        # debounce timer for rapid signal firing
        self._redraw_timer = QTimer()
        self._redraw_timer.setSingleShot(True)
        self._redraw_timer.setInterval(50)          # ms — tune if needed
        self._redraw_timer.timeout.connect(self._refresh_plot)


        self._auto_process_timer = QTimer()
        self._auto_process_timer.setSingleShot(True)
        self._auto_process_timer.setInterval(400)   # 400ms — feels responsive but not jumpy
        self._auto_process_timer.timeout.connect(self._do_auto_process)
        self._auto_process_step: str | None = None

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(4, 4, 4, 4)
        main_layout.setSpacing(4)

        # ── Row 1: step selector ──────────────────────────────────────────────
        main_layout.addWidget(self._build_step_selector())

        # ── Row 2: component + apply row (hidden when not applicable) ─────────
        self._component_row = self._build_component_row()
        main_layout.addWidget(self._component_row)

        # ── Row 3: plot area (FFT window params sit beside it, not below —
        # that section can need up to 7 fields and got cramped/overflowed
        # when stacked in the same wide row as the other sections below) ──
        self.plot_widget = SpectrumPlotWidget()
        self.plot_widget.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.plot_widget.canvas.mpl_connect('button_press_event', self._on_plot_click)
        self.plot_widget.canvas.mpl_connect('pick_event', self._on_marker_pick)
        plot_row = QHBoxLayout()
        plot_row.addWidget(self.plot_widget, 1)

        # ── Row 4: param sections (collapsible, only one visible at a time) ───
        self._param_sections: dict[str, QGroupBox] = {}
        self._param_sections["despike"]        = self._build_despike_section()
        self._param_sections["exclude_frames"] = self._build_exclude_frames_section()
        self._param_sections["bg_smooth"]      = self._build_bg_smooth_section()
        self._param_sections["fft_window"]     = self._build_fft_window_section()
        self._param_sections["normalization"]  = self._build_normalization_section()

        plot_row.addWidget(self._param_sections["fft_window"])
        main_layout.addLayout(plot_row)

        for key, gb in self._param_sections.items():
            make_collapsible(gb)
            gb.setChecked(False)
            gb.setVisible(False)   # all hidden initially
            if key != "fft_window":
                main_layout.addWidget(gb)

        # make_collapsible's expand step shows *all* direct-child widgets of
        # the groupbox, which would undo our per-window-type field hiding
        # every time this section is (re-)expanded (e.g. switching to the
        # FFT step) — reapply the filter right after, once make_collapsible's
        # own toggled handler (connected above) has run
        self._param_sections["fft_window"].toggled.connect(
            lambda checked: self._update_fft_window_visibility() if checked else None
        )

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

        self._pair_label = QLabel("Pair:")
        self._pair_combo = QComboBox()
        self._pair_combo.addItems(["Sample pair", "Reference pair", "Both pairs"])
        self._pair_combo.setFixedWidth(120)
        self._pair_combo.setToolTip("Select which pair(s) to show in the plot")
        self._pair_combo.setCurrentIndex(2)   # default to both pairs

        self._source_label = QLabel("Show:")
        self._source_combo = QComboBox()
        self._source_combo.addItems(["Signal", "Background", "Both"])
        self._source_combo.setFixedWidth(110)
        self._source_combo.setToolTip("Select which component(s) to show in the plot")
        self._source_combo.setCurrentIndex(2)   # default to both

        self._view_label = QLabel("View:")
        self._view_combo = QComboBox()
        self._view_combo.addItems(["Signal + Background", "Subtracted result"])
        self._view_combo.setFixedWidth(170)
        self._view_combo.setToolTip("Select which view to show in the plot")

        self._comp_label = QLabel("Show:")
        self._comp_combo = QComboBox()
        self._comp_combo.addItems(["Sample", "Reference", "Both"])
        self._comp_combo.setFixedWidth(110)
        self._comp_combo.setToolTip("Select which component(s) to show in the plot")
        self._comp_combo.setCurrentIndex(2)   # default to both

        for w in [self._pair_label, self._pair_combo,
                self._source_label, self._source_combo,
                self._view_label, self._view_combo,
                self._comp_label, self._comp_combo]:
            layout.addWidget(w)

        layout.addStretch()

        self._process_btn = QPushButton("▶ Process all")
        self._process_btn.setToolTip("Run full pipeline from scratch")
        self._process_btn.setFixedWidth(110)
        layout.addWidget(self._process_btn)

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
            window_sb.setRange(3, 1001)
            window_sb.setSingleStep(10)
            window_sb.setValue(50)
            grid.addWidget(window_sb, row_idx, 1)

            threshold_sb = QDoubleSpinBox()
            threshold_sb.setRange(0.5, 10000.0)
            threshold_sb.setSingleStep(5.0)
            threshold_sb.setDecimals(1)
            threshold_sb.setValue(20.0)
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

    def _build_exclude_frames_section(self) -> QGroupBox:
        from PySide6.QtWidgets import QGridLayout
        gb = QGroupBox("Exclude frames")
        gb.setCheckable(True)
        gb.setChecked(False)
        grid = QGridLayout(gb)

        self._exclude_strips: dict[str, FrameCheckStrip] = {}
        for row_idx, (key, label) in enumerate([
            ("signal",        "Sample"),
            ("background",    "Sample BG"),
            ("reference",     "Reference"),
            ("ref_background","Ref BG"),
        ]):
            grid.addWidget(QLabel(label + ":"), row_idx, 0)
            strip = FrameCheckStrip()
            self._exclude_strips[key] = strip
            grid.addWidget(strip, row_idx, 1)

        return gb

    def _get_exclude_frames(self, idx: int, component: str) -> set:
        return self._exclude_frames.get(idx, {}).get(component, set())

    def _set_exclude_frames(self, idx: int, component: str, frames: set):
        if idx not in self._exclude_frames:
            self._exclude_frames[idx] = {}
        self._exclude_frames[idx][component] = set(frames)

    def _on_exclude_frames_changed(self, component: str):
        if self._matched_index < 0:
            return
        excluded = self._exclude_strips[component].excluded_frames()
        self._set_exclude_frames(self._matched_index, component, excluded)

        c = self._cache.get(self._matched_index, {})
        for step in ("averaged", "bg_smooth", "fft_filter", "ifft", "normalization"):
            c.pop(step, None)

        self._auto_process_from("averaged")

    # ── Background offset markers ────────────────────────────────────────────

    def _reload_bg_marker_table(self):
        self._bg_marker_table.blockSignals(True)
        self._bg_marker_table.setRowCount(len(self._bg_markers))
        for row, (x, y) in enumerate(self._bg_markers):
            self._bg_marker_table.setItem(row, 0, QTableWidgetItem(f"{x:.6g}"))
            self._bg_marker_table.setItem(row, 1, QTableWidgetItem(f"{y:.6g}"))
        self._bg_marker_table.blockSignals(False)

    def _add_bg_marker(self, x: float, y: float):
        self._bg_markers.append((float(x), float(y)))
        self._reload_bg_marker_table()
        self._auto_process_from("bg_smooth")

    def _remove_bg_marker(self, index: int):
        if 0 <= index < len(self._bg_markers):
            del self._bg_markers[index]
        self._reload_bg_marker_table()
        self._auto_process_from("bg_smooth")

    def _on_add_bg_marker_row(self):
        self._add_bg_marker(0.0, 0.0)

    def _on_remove_bg_marker_row(self):
        row = self._bg_marker_table.currentRow()
        if row >= 0:
            self._remove_bg_marker(row)

    def _on_clear_bg_markers(self):
        self._bg_markers.clear()
        self._reload_bg_marker_table()
        self._auto_process_from("bg_smooth")

    def _on_bg_marker_cell_changed(self, row: int, col: int):
        if row >= len(self._bg_markers):
            return
        item = self._bg_marker_table.item(row, col)
        try:
            val = float(item.text()) if item is not None else None
        except ValueError:
            val = None
        if val is None:
            self._reload_bg_marker_table()   # revert invalid text
            return
        x, y = self._bg_markers[row]
        self._bg_markers[row] = (val, y) if col == 0 else (x, val)
        self._auto_process_from("bg_smooth")

    def _on_marker_pick(self, event):
        if not getattr(event.artist, "_is_bg_marker", False):
            return
        if not len(event.ind):
            return
        self._marker_just_picked = True
        self._remove_bg_marker(event.ind[0])

    def _on_plot_click(self, event):
        if self._marker_just_picked:
            self._marker_just_picked = False
            return
        if event.inaxes != self.plot_widget.ax:
            return
        if (self._current_step() != "bg_smooth"
                or self._view_combo.currentText() != "Signal + Background"):
            return
        if event.xdata is None or event.ydata is None:
            return
        self._add_bg_marker(event.xdata, event.ydata)

    def _plot_bg_markers(self):
        if not self._bg_markers:
            return
        xs = [m[0] for m in self._bg_markers]
        ys = [m[1] for m in self._bg_markers]
        line, = self.plot_widget.ax.plot(
            xs, ys, marker="o", linestyle="none",
            markersize=8, markerfacecolor="black",
            markeredgecolor="white", markeredgewidth=1,
            picker=5, zorder=6, label="_nolegend_",
        )
        line._is_bg_marker = True

    def _fit_bg_offset(self, averaged):
        """averaged: hd_sfg.steps.AveragedData — its bg_avg/wavenumber are
        used as the curve the markers' residuals are fit against."""
        if not self._bg_markers:
            return None
        degree = self._bg_offset_degree.value()
        return fit_offset_from_markers(
            self._bg_markers, degree,
            averaged.wavenumber, averaged.bg_avg,
        )

    def _build_bg_smooth_section(self) -> QGroupBox:
        """The offset added to the averaged signal background before
        subtraction. Fit (least-squares, degree set by style) through
        markers placed by clicking the plot in the "Signal + Background"
        view, or editing the table — same marker-driven approach as
        HomodynePanel's background correction (see its
        _build_bg_offset_section() docstring for the "markers are global
        values" reasoning, which applies here too).
        """
        gb = QGroupBox("Background subtraction + edge window")
        gb.setCheckable(True)
        layout = QVBoxLayout(gb)

        edge_row = QHBoxLayout()
        edge_row.addWidget(QLabel("Edge low wn (pts):"))
        self._edge_right = QSpinBox()  # controls low-wn end
        self._edge_right.setRange(1, 1000)
        self._edge_right.setValue(15)
        edge_row.addWidget(self._edge_right)

        edge_row.addWidget(QLabel("Edge high wn (pts):"))
        self._edge_left = QSpinBox()   # controls high-wn end
        self._edge_left.setRange(1, 1000)
        self._edge_left.setValue(15)
        edge_row.addWidget(self._edge_left)
        edge_row.addStretch()
        layout.addLayout(edge_row)

        style_row = QHBoxLayout()
        style_row.addWidget(QLabel("BG offset degree:"))
        self._bg_offset_degree = QSpinBox()
        self._bg_offset_degree.setRange(0, 6)
        self._bg_offset_degree.setValue(0)
        self._bg_offset_degree.setToolTip("0 = constant, 1 = linear, 2+ = polynomial")
        style_row.addWidget(self._bg_offset_degree)
        style_row.addStretch()
        layout.addLayout(style_row)

        layout.addWidget(QLabel(
            "Markers (click the plot in \"Signal + Background\" view to add, "
            "click a marker to remove, or edit here):"
        ))
        self._bg_marker_table = QTableWidget(0, 2)
        self._bg_marker_table.setHorizontalHeaderLabels(["X", "Y"])
        self._bg_marker_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._bg_marker_table.verticalHeader().setVisible(False)
        self._bg_marker_table.setMaximumHeight(120)
        layout.addWidget(self._bg_marker_table)

        marker_btn_row = QHBoxLayout()
        self._add_bg_marker_btn = QPushButton("Add row")
        self._remove_bg_marker_btn = QPushButton("Remove selected")
        self._clear_bg_marker_btn = QPushButton("Clear all")
        marker_btn_row.addWidget(self._add_bg_marker_btn)
        marker_btn_row.addWidget(self._remove_bg_marker_btn)
        marker_btn_row.addWidget(self._clear_bg_marker_btn)
        marker_btn_row.addStretch()
        layout.addLayout(marker_btn_row)

        return gb

    # window type -> human-readable name, and which params each type reads
    # (see src/sfg_app2/processing/hd_sfg/windows.py:fft_mask_window)
    _FFT_WINDOW_TYPE_NAMES = {
        1: "Box-Car",
        2: "Box-Car + HG",
        3: "Double HG",
        4: "Masking HG",
    }
    _FFT_WINDOW_TYPE_PARAMS = {
        1: {"_fft_start", "_fft_end"},
        2: {"_fft_start", "_fft_end", "_hg_left"},
        3: {"_fft_start", "_fft_end", "_hg_left", "_hg_right"},
        4: {"_fft_start", "_fft_end", "_hg_left",
            "_mask_start", "_mask_end", "_mask_transition", "_mask_factor"},
    }

    def _build_fft_window_section(self) -> QGroupBox:
        from PySide6.QtWidgets import QGridLayout

        gb = QGroupBox("FFT filter window parameters")
        gb.setCheckable(True)
        outer = QVBoxLayout(gb)

        type_row = QHBoxLayout()
        type_row.addWidget(QLabel("Type:"))
        self._fft_window_type = QComboBox()
        self._fft_window_type.setToolTip(
            "1 — Box-Car: hard cutoff at Start/End, no taper.\n"
            "2 — Box-Car + HG: soft taper on the left edge only (HG L).\n"
            "3 — Double HG: soft taper on both edges (HG L and HG R).\n"
            "4 — Masking HG: type 2's left taper, plus an attenuated notch\n"
            "     region (Mask start/end/transition/factor) inside the passband."
        )
        for label, val in [
            ("1 — Box-Car", 1),
            ("2 — Box-Car + HG", 2),
            ("3 — Double HG", 3),
            ("4 — Masking HG", 4),
        ]:
            self._fft_window_type.addItem(label, userData=val)
        self._fft_window_type.setCurrentIndex(2)   # default to type 3
        type_row.addWidget(self._fft_window_type)
        type_row.addStretch()
        outer.addLayout(type_row)

        # form-style rows (label | spinbox), one per param, stacked
        # vertically — this section now lives in a narrow side column next
        # to the plot rather than a wide row, so there's no need to cram
        # everything horizontally
        grid = QGridLayout()

        # (label widget, spinbox widget, attr name) — attr name is looked up
        # against _FFT_WINDOW_TYPE_PARAMS to decide visibility per type
        self._fft_window_rows: list[tuple[QLabel, QWidget, str]] = []
        for row_idx, (label, attr, default, tooltip) in enumerate([
            ("Start (pts):", "_fft_start",  30, None),
            ("End (pts):",   "_fft_end",   110, None),
            ("HG L (pts):",  "_hg_left",    10, None),
            ("HG R (pts):",  "_hg_right",   10, None),
            ("Mask start (pts):", "_mask_start", 150,
             "Start of the attenuated region within the passband."),
            ("Mask end (pts):", "_mask_end", 160,
             "End of the attenuated region within the passband."),
            ("Mask transition (pts):", "_mask_transition", 5,
             "HG taper width into and out of the masked region."),
        ]):
            lbl = QLabel(label)
            sb = QSpinBox()
            sb.setRange(1, 1000)
            sb.setValue(default)
            if tooltip:
                lbl.setToolTip(tooltip)
                sb.setToolTip(tooltip)
            setattr(self, attr, sb)
            grid.addWidget(lbl, row_idx, 0)
            grid.addWidget(sb, row_idx, 1)
            self._fft_window_rows.append((lbl, sb, attr))

        mask_factor_row = len(self._fft_window_rows)
        mask_factor_lbl = QLabel("Mask factor:")
        mask_factor_tooltip = "Attenuation level inside the masked region (0-1)."
        mask_factor_lbl.setToolTip(mask_factor_tooltip)
        self._mask_factor = QDoubleSpinBox()
        self._mask_factor.setRange(0.0, 1.0)
        self._mask_factor.setDecimals(2)
        self._mask_factor.setSingleStep(0.01)
        self._mask_factor.setValue(0.08)
        self._mask_factor.setToolTip(mask_factor_tooltip)
        grid.addWidget(mask_factor_lbl, mask_factor_row, 0)
        grid.addWidget(self._mask_factor, mask_factor_row, 1)
        self._fft_window_rows.append((mask_factor_lbl, self._mask_factor, "_mask_factor"))

        outer.addLayout(grid)
        outer.addStretch()
        self._update_fft_window_visibility()
        return gb

    def _update_fft_window_visibility(self):
        window_type = self._fft_window_type.currentData()
        needed = self._FFT_WINDOW_TYPE_PARAMS.get(window_type, set())
        for lbl, widget, attr in self._fft_window_rows:
            visible = attr in needed
            lbl.setVisible(visible)
            widget.setVisible(visible)

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
        self._ref_exp.setValue(30.0)
        row1.addWidget(self._ref_exp)
        row1.addWidget(QLabel("Phase corr (°):"))
        self._phase_corr = QDoubleSpinBox()
        self._phase_corr.setRange(-360.0, 360.0)
        self._phase_corr.setSingleStep(2.0)
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

        row2.addWidget(QLabel("Phase range:"))
        self._phase_range_combo = QComboBox()
        self._phase_range_combo.addItem("[-180°, 180°]", userData="pm180")
        self._phase_range_combo.addItem("[0°, 360°)", userData="0to360")
        row2.addWidget(self._phase_range_combo)

        row2.addStretch()
        layout.addLayout(row2)

        return gb

    # ── Signal wiring ─────────────────────────────────────────────────────────

    def _connect_signals(self):
        # step selector
        for rb in self._step_radios.values():
            rb.toggled.connect(
                lambda checked, r=rb: self._on_step_changed() if checked else None
            )

        # view combos — just replot, no reprocess needed
        for widget in [self._pair_combo, self._source_combo,
                    self._view_combo, self._comp_combo]:
            widget.currentIndexChanged.connect(self._redraw_timer.start)

        # normalization checkboxes — just replot
        for cb in [self._cb_imag, self._cb_real,
                self._cb_homodyne, self._cb_phase, self._cb_errors]:
            cb.stateChanged.connect(self._redraw_timer.start)
        self._phase_range_combo.currentIndexChanged.connect(self._redraw_timer.start)

        # despike params → auto-reprocess from despike step
        for key in self._despike_params:
            self._despike_params[key]["window"].valueChanged.connect(
                lambda: self._auto_process_from("despiked")
            )
            self._despike_params[key]["threshold"].valueChanged.connect(
                lambda: self._auto_process_from("despiked")
            )

        # frame exclusion → auto-reprocess from averaged step
        for key in self._exclude_strips:
            self._exclude_strips[key].changed.connect(
                lambda k=key: self._on_exclude_frames_changed(k)
            )

        # bg subtraction params → auto-reprocess from bg_smooth step
        for sb in [self._edge_left, self._edge_right]:
            sb.valueChanged.connect(lambda: self._auto_process_from("bg_smooth"))
        self._bg_offset_degree.valueChanged.connect(
            lambda: self._auto_process_from("bg_smooth")
        )
        self._add_bg_marker_btn.clicked.connect(self._on_add_bg_marker_row)
        self._remove_bg_marker_btn.clicked.connect(self._on_remove_bg_marker_row)
        self._clear_bg_marker_btn.clicked.connect(self._on_clear_bg_markers)
        self._bg_marker_table.cellChanged.connect(self._on_bg_marker_cell_changed)

        # FFT params → auto-reprocess from fft_filter step
        for sb in [self._fft_start, self._fft_end, self._hg_left, self._hg_right,
                   self._mask_start, self._mask_end, self._mask_transition,
                   self._mask_factor]:
            sb.valueChanged.connect(lambda: self._auto_process_from("fft_filter"))
        self._fft_window_type.currentIndexChanged.connect(
            lambda: self._auto_process_from("fft_filter")
        )
        self._fft_window_type.currentIndexChanged.connect(
            self._update_fft_window_visibility
        )

        # normalization params → auto-reprocess from normalization step
        for sb in [self._sample_exp, self._ref_exp, self._phase_corr]:
            sb.valueChanged.connect(lambda: self._auto_process_from("normalization"))

        self._finish_btn.clicked.connect(self._on_finish)
        self._process_btn.clicked.connect(self._on_process)

    # ── Step change ───────────────────────────────────────────────────────────

    def _on_step_changed(self):
        step = self._current_step()

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

        self._component_row.setVisible(True)
        self._process_btn.setVisible(step != "normalization")
        self._finish_btn.setVisible(step == "normalization")

        section_key = STEP_SECTION.get(step)
        for key, gb in self._param_sections.items():
            gb.setVisible(key == section_key)
            if key == section_key:
                gb.setChecked(True)
        self._param_sections["exclude_frames"].setVisible(
            step in ("raw", "despiked", "averaged")
        )

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
        step_changed = step != self._last_step
        self._last_step = step

        cache = self._cache.get(self._matched_index, {})

        # normalization with existing lines — skip all clearing, update in place
        if step == "normalization" and self._norm_lines and not step_changed:
            if "normalization" in cache:
                try:
                    self._plot_normalization(cache["normalization"])
                except Exception as e:
                    logger.warning("Normalization plot failed: %s", e, exc_info=True)
            if self._cb_phase.isChecked():
                self.plot_widget.figure.tight_layout(rect=[0, 0, 1, 1])
            else:
                self.plot_widget.figure.tight_layout()
            self.plot_widget.canvas.draw_idle()
            return

        if step_changed:
            self.plot_widget.full_clear()
            self._norm_lines.clear()
            self._norm_ax2 = None
        else:
            self.plot_widget.soft_clear()

        if step == "raw":
            self._plot_raw()
            self.plot_widget.sync_x_range()
            self.plot_widget.canvas.draw_idle()
            return

        if step not in cache:
            if step in {"despiked", "averaged"}:
                self._plot_raw()
                self.plot_widget.ax.set_title(
                    f"{HD_STEP_LABELS[step]} — showing raw data. "
                    f"Adjust parameters — changes apply automatically."
                )
            else:
                self.plot_widget.set_labels(
                    title=f"{HD_STEP_LABELS[step]} — adjust parameters to compute"
                )
            self.plot_widget.sync_x_range()
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

        if step_changed:
            self.plot_widget.sync_x_range()
        else:
            self.plot_widget._apply_x_range()

        self.plot_widget.figure.tight_layout()
        self.plot_widget.canvas.draw_idle()

    def _component(self) -> str:
        return self._comp_combo.currentText().lower()   # "sample"/"reference"/"both"

    def _upconversion_wl(self) -> float:
        try:
            return self.window().process_review_tab.get_upconversion_wavelength()
        except Exception:
            return 1030.7

    def on_upconversion_changed(self) -> int:
        """Called by ProcessReviewTab when the shared upconversion
        wavelength spinbox changes. HD-SFG bakes the wavelength into the
        wavenumber axis during averaging itself, so every wavelength-
        dependent cached step (averaged and everything downstream) is
        invalidated for *every* matched set, not just the currently-viewed
        one — otherwise switching to a previously-processed set could
        silently show results computed with a stale wavelength. The
        currently-viewed set is re-run immediately if it had already been
        processed that far; other sets simply lose their downstream step
        radios (handled automatically by set_matched_set()'s existing
        cached-step check) until reprocessed. Returns how many *other*
        (not currently-viewed) sets were invalidated, so the caller can
        tell the user reprocessing is needed.
        """
        stale_others = 0
        for idx, c in self._cache.items():
            had_downstream = any(
                step in c for step in
                ("averaged", "bg_smooth", "fft_filter", "ifft", "normalization")
            )
            for step in ("averaged", "bg_smooth", "fft_filter", "ifft", "normalization"):
                c.pop(step, None)
            if had_downstream and idx != self._matched_index:
                stale_others += 1
        if "despiked" in self._cache.get(self._matched_index, {}):
            self._auto_process_from("averaged")
        return stale_others

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
            sig_role = "signal" if pair_label == "Sample" else "reference"
            bg_role  = "background" if pair_label == "Sample" else "ref_background"
            if self._show_signal() and sig_src:
                excluded = self._get_exclude_frames(self._matched_index, sig_role)
                for fid in sig_src.data["Frame"].unique():
                    fd = sig_src.frame(fid)
                    wn = wl_to_wn(fd["Wavelength"].to_numpy())
                    is_excluded = fid in excluded
                    self.plot_widget.ax.plot(
                        wn, fd["Intensity"].to_numpy(),
                        alpha=0.2 if is_excluded else 0.8,
                        linestyle=":" if is_excluded else "-",
                        label=f"{pair_label} sig F{fid}" + (" (excluded)" if is_excluded else ""),
                    )
            if self._show_background() and bg_src:
                excluded = self._get_exclude_frames(self._matched_index, bg_role)
                for fid in bg_src.data["Frame"].unique():
                    fd = bg_src.frame(fid)
                    wn = wl_to_wn(fd["Wavelength"].to_numpy())
                    is_excluded = fid in excluded
                    self.plot_widget.ax.plot(
                        wn, fd["Intensity"].to_numpy(),
                        linestyle=":" if is_excluded else "--",
                        alpha=0.2 if is_excluded else 0.6,
                        label=f"{pair_label} BG F{fid}" + (" (excluded)" if is_excluded else ""),
                    )
        self.plot_widget.set_labels(
            xlabel="Wavenumber (cm$^{-1}$)", ylabel="Intensity (counts)", title="Raw"
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
            sig_role = "signal" if pair_label == "Sample" else "reference"
            bg_role  = "background" if pair_label == "Sample" else "ref_background"
            if self._show_signal() and sig_src:
                excluded = self._get_exclude_frames(self._matched_index, sig_role)
                for fid in sig_src.data["Frame"].unique():
                    fd = sig_src.frame(fid)
                    wn = wl_to_wn(fd["Wavelength"].to_numpy())
                    is_excluded = fid in excluded
                    self.plot_widget.ax.plot(
                        wn, fd["Intensity"].to_numpy(),
                        alpha=0.2 if is_excluded else 0.8,
                        linestyle=":" if is_excluded else "-",
                        label=f"{pair_label} sig F{fid}" + (" (excluded)" if is_excluded else ""),
                    )
            if self._show_background() and bg_src:
                excluded = self._get_exclude_frames(self._matched_index, bg_role)
                for fid in bg_src.data["Frame"].unique():
                    fd = bg_src.frame(fid)
                    wn = wl_to_wn(fd["Wavelength"].to_numpy())
                    is_excluded = fid in excluded
                    self.plot_widget.ax.plot(
                        wn, fd["Intensity"].to_numpy(),
                        linestyle=":" if is_excluded else "--",
                        alpha=0.2 if is_excluded else 0.6,
                        label=f"{pair_label} BG F{fid}" + (" (excluded)" if is_excluded else ""),
                    )
        self.plot_widget.set_labels(
            xlabel="Wavenumber (cm$^{-1}$)", ylabel="Intensity (counts)", title="Despiked"
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
            xlabel="Wavenumber (cm$^{-1}$)", ylabel="Intensity (counts)", title="Averaged"
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
            self._plot_bg_markers()
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
            xlabel="Wavenumber (cm$^{-1}$)", ylabel="Intensity (counts)", title=title
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
        window_type = self._fft_window_type.currentData()
        type_name = self._FFT_WINDOW_TYPE_NAMES.get(window_type, "?")
        self.plot_widget.set_labels(
            xlabel="Time (ps)", ylabel="FFT amplitude, imaginary (a.u.)",
            title=f"FFT + filter window — {window_type}: {type_name}"
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
            xlabel="Wavenumber (cm$^{-1}$)", ylabel="Amplitude (a.u.)",
            title="iFFT result (frequency domain)"
        )

    def _plot_normalization(self, data):
        """Option 3 — update line data in place rather than recreating.
        Lines are created once and stored in self._norm_lines.
        """
        import numpy as np
        wn      = data.wavenumber
        use_avg = data.n_frames > 1
        show_err = self._cb_errors.isChecked()

        # ── First call: create all lines ─────────────────────────────────────────
        if not self._norm_lines:
            ax = self.plot_widget.ax
            self._norm_lines["imag"] = ax.plot(
                wn, np.zeros_like(wn), label=r"Im($\chi^{(2)}$)")[0]
            self._norm_lines["real"] = ax.plot(
                wn, np.zeros_like(wn), linestyle="--", label=r"Re($\chi^{(2)}$)")[0]
            self._norm_lines["homo"] = ax.plot(
                wn, np.zeros_like(wn), linestyle="-.", label="")[0]
            ax.axhline(0, color="gray", linewidth=0.5, linestyle="--")

            # twin axis for phase
            self._norm_ax2 = ax.twinx()
            self._norm_lines["phase"] = self._norm_ax2.plot(
                wn, np.zeros_like(wn), color="gray",
                linestyle=":", alpha=0.8, label="Phase (°)")[0]
            self._norm_lines["phase_fill"] = None
            self._norm_ax2.axhline(
                0, color="gray", linewidth=0.4, linestyle="--"   # 0° reference instead of 90°
            )
            self._norm_ax2.set_ylabel("Phase (°)", color="gray")

        # phase axis range depends on the current toggle, and the user can
        # change it after the first plot — so this is re-applied every call
        if self._phase_range_combo.currentData() == "0to360":
            self._norm_ax2.set_ylim(0, 360)
            self._norm_ax2.set_yticks([0, 45, 90, 135, 180, 225, 270, 315, 360])
        else:
            self._norm_ax2.set_ylim(-180, 180)
            self._norm_ax2.set_yticks([-180, -135, -90, -45, 0, 45, 90, 135, 180])

        # ── Update data and visibility ────────────────────────────────────────────
        ax = self.plot_widget.ax

        # imaginary
        y_imag = data.complex_chi_avg.imag if use_avg else data.complex_chi.imag
        self._norm_lines["imag"].set_ydata(y_imag)
        self._norm_lines["imag"].set_visible(self._cb_imag.isChecked())

        # real
        y_real = data.complex_chi_avg.real if use_avg else data.complex_chi.real
        self._norm_lines["real"].set_ydata(y_real)
        self._norm_lines["real"].set_visible(self._cb_real.isChecked())

        # homodyne — scaled to Im/Re amplitude
        y_homo = data.homodyne_avg if use_avg else data.homodyne
        ref_amp = max(
            np.abs(y_imag).max() if self._cb_imag.isChecked() else 0.0,
            np.abs(y_real).max() if self._cb_real.isChecked() else 0.0,
        )
        homo_max = np.abs(y_homo).max()
        scale = (ref_amp / homo_max) if ref_amp > 0 and homo_max > 0 else 1.0
        self._norm_lines["homo"].set_ydata(y_homo * scale)
        self._norm_lines["homo"].set_label(rf"$|\chi^{{(2)}}|^2$ (×{scale:.2e})")
        self._norm_lines["homo"].set_visible(self._cb_homodyne.isChecked())

        # phase
        y_phase = data.phase_avg if use_avg else data.phase
        y_phase = wrap_phase_for_plot(
            y_phase, self._phase_range_combo.currentData() == "0to360"
        )
        self._norm_lines["phase"].set_ydata(y_phase)
        self._norm_lines["phase"].set_visible(self._cb_phase.isChecked())
        self._norm_ax2.set_visible(self._cb_phase.isChecked())

        # ── Error bands — recreate each time (fill_between can't update in place)
        # remove old fills
        for coll in ax.collections[:]:
            coll.remove()
        for coll in self._norm_ax2.collections[:]:
            coll.remove()

        if show_err and use_avg:
            if self._cb_imag.isChecked():
                ax.fill_between(wn, y_imag - data.imag_err,
                                y_imag + data.imag_err, alpha=0.3,
                                color=self._norm_lines["imag"].get_color())
            if self._cb_real.isChecked():
                ax.fill_between(wn, y_real - data.real_err,
                                y_real + data.real_err, alpha=0.3,
                                color=self._norm_lines["real"].get_color())
            if self._cb_homodyne.isChecked():
                ax.fill_between(wn,
                                (y_homo - data.homodyne_err) * scale,
                                (y_homo + data.homodyne_err) * scale,
                                alpha=0.3,
                                color=self._norm_lines["homo"].get_color())
            if self._cb_phase.isChecked():
                self._norm_ax2.fill_between(
                    wn, y_phase - data.phase_err,
                    y_phase + data.phase_err,
                    alpha=0.2, color="gray"
                )

        # ── Legend ────────────────────────────────────────────────────────────────
        lines1 = [l for l in ax.get_lines()
                if l.get_visible() and l.get_label()
                and not l.get_label().startswith("_")]
        lines2 = [self._norm_lines["phase"]] if self._cb_phase.isChecked() else []
        all_lines  = lines1 + lines2
        all_labels = [l.get_label() for l in all_lines]
        if all_lines:
            ax.legend(all_lines, all_labels, fontsize=8)

        self.plot_widget.set_labels(
            xlabel="Wavenumber (cm$^{-1}$)",
            ylabel=r"$\chi^{(2)}$ (a.u.)",
            title="Normalized HD-SFG result"
        )

    # ── Apply / Process ───────────────────────────────────────────────────────

    def _auto_process_from(self, step: str):
        """Debounced auto-reprocess triggered by parameter changes.
        Only reprocesses if the affected step is already cached
        (i.e. user has already run the pipeline at least once).
        """
        cache = self._cache.get(self._matched_index, {})
        prior_step = {
            "despiked":      None,
            "averaged":      "despiked",
            "bg_smooth":     "averaged",
            "fft_filter":    "bg_smooth",
            "ifft":          "fft_filter",
            "normalization": "fft_filter",
        }.get(step)

        # only auto-reprocess if prior step is already computed
        if prior_step is None or prior_step in cache:
            self._auto_process_step = step
            self._auto_process_timer.start()


    def _do_auto_process(self):
        step = getattr(self, "_auto_process_step", None)
        if step:
            self._run_from_step(step, emit_result=False)

    def _on_process(self):
        """Run the full pipeline from scratch."""
        self._cache.pop(self._matched_index, None)
        loading = show_loading(self, "Processing...")
        try:
            self._run_from_step("despiked", emit_result=True)
        finally:
            loading.close()

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
                cfg.bg_offset = self._fit_bg_offset(c["averaged"])
                c["bg_smooth"] = step_bg_smooth(c["averaged"], cfg)
            if "fft_filter" not in c:
                fft_data = step_fft_filter(c["bg_smooth"], cfg)
                c["fft_filter"] = fft_data
                c["ifft"] = fft_data   # same data, different view
            if "normalization" not in c:
                result = step_normalize(c["fft_filter"], cfg)
                result.metadata   = self._matched_set.signal.metadata.copy()
                result.history    = ["hd_sfg_processing"]
                result.provenance = self._build_provenance(cfg, result.n_frames)
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

    def _build_provenance(self, cfg, n_frames: int) -> dict:
        """Captures the actual HD-SFG processing parameters used, for the
        CSV export provenance header (see ProcessedResultsTab)."""
        ms = self._matched_set

        def name(f):
            return f.path.name if f is not None else None

        def desp(key):
            p = self._despike_params[key]
            return {"window": p["window"].value(), "threshold": p["threshold"].value()}

        return {
            "kind": "heterodyne",
            "signal":               name(ms.signal),
            "background":           name(ms.background),
            "reference":            name(ms.reference),
            "reference_background": name(ms.reference_background),
            "despike": {
                "signal":               desp("signal"),
                "background":           desp("background"),
                "reference":            desp("reference"),
                "reference_background": desp("ref_background"),
            },
            "background_subtraction": {
                "bg_offset_degree":     self._bg_offset_degree.value(),
                "bg_offset_markers":    [list(pt) for pt in self._bg_markers],
                "bg_offset":            str(cfg.bg_offset) if cfg.bg_offset is not None else "None",
                "edge_left":            cfg.edge_left,
                "edge_right":           cfg.edge_right,
                "bg_smoothing_window":  cfg.bg_smoothing_window,
                "bg_smoothing_order":   cfg.bg_smoothing_order,
                "sig_smoothing_window": cfg.sig_smoothing_window,
                "sig_smoothing_order":  cfg.sig_smoothing_order,
            },
            "fft_filter": {
                "window_type":     cfg.window_type,
                "fft_start":       cfg.fft_start,
                "fft_end":         cfg.fft_end,
                "hg_left":         cfg.hg_left,
                "hg_right":        cfg.hg_right,
                "mask_start":      cfg.mask_start,
                "mask_end":        cfg.mask_end,
                "mask_transition": cfg.mask_transition,
                "mask_factor":     cfg.mask_factor,
            },
            "normalization": {
                "sample_exposure_s":    cfg.sample_exposure,
                "reference_exposure_s": cfg.reference_exposure,
                "phase_correction_deg": cfg.phase_correction_deg,
            },
            "upconversion": {"wavelength_nm": cfg.upconversion_wavelength},
            "n_frames": n_frames,
            "excluded_frames": {
                "signal":               sorted(self._get_exclude_frames(self._matched_index, "signal")),
                "background":           sorted(self._get_exclude_frames(self._matched_index, "background")),
                "reference":            sorted(self._get_exclude_frames(self._matched_index, "reference")),
                "reference_background": sorted(self._get_exclude_frames(self._matched_index, "ref_background")),
            },
        }

    # ── Config ────────────────────────────────────────────────────────────────

    def _current_config(self):
        from sfg_app2.processing.hd_sfg import HDSFGConfig
        return HDSFGConfig(
            upconversion_wavelength = self._upconversion_wl(),
            bg_smoothing_window     = 0,   # disabled
            bg_smoothing_order      = 0,
            sig_smoothing_window    = 0,   # disabled
            sig_smoothing_order     = 0,
            # bg_offset is resolved later, in _run_from_step(), once the
            # averaged background curve markers are fit against exists
            edge_left               = self._edge_left.value(),
            edge_right              = self._edge_right.value(),
            window_type             = self._fft_window_type.currentData(),
            fft_start               = self._fft_start.value(),
            fft_end                 = self._fft_end.value(),
            hg_left                 = self._hg_left.value(),
            hg_right                = self._hg_right.value(),
            mask_start               = self._mask_start.value(),
            mask_end                 = self._mask_end.value(),
            mask_transition          = self._mask_transition.value(),
            mask_factor              = self._mask_factor.value(),
            sample_exposure         = self._sample_exp.value(),
            reference_exposure      = self._ref_exp.value(),
            phase_correction_deg    = self._phase_corr.value(),
            exclude_frames          = self._exclude_frames.get(self._matched_index, {}),
        )

    def _current_step(self) -> str:
        for step, rb in self._step_radios.items():
            if rb.isChecked():
                return step
        return "raw"

    # ── Public API ────────────────────────────────────────────────────────────

    def redraw_for_style_change(self):
        """Called after the global plotting style changes. Forcing
        _last_step to None makes _refresh_plot() take its own
        full_clear() + _norm_lines/_norm_ax2 reset branch, so the Axes
        and every line (including the normalization step's reused
        Line2D objects) are recreated fresh under the new rcParams
        instead of keeping their pre-restyle appearance.
        """
        self._last_step = None
        self._refresh_plot()

    def reset(self):
        """Discard all cached processing results. Call whenever the
        underlying matched sets are replaced (e.g. re-run from Load/Match
        after correcting the match table) — otherwise a row index reused
        by a new/corrected MatchedSet would still show stale results
        computed from the previous file assignment.
        """
        self._cache.clear()
        self._exclude_frames.clear()
        self._matched_set = None
        self._matched_index = -1
        self._last_step = None
        self._norm_lines.clear()
        self._norm_ax2 = None
        self.plot_widget.full_clear()
        self.plot_widget.canvas.draw_idle()

    def set_matched_set(self, matched_set, index: int):
        self._matched_set   = matched_set
        self._matched_index = index
        self._last_step     = None
        self._norm_lines.clear()
        self._norm_ax2 = None

        sources = {
            "signal": matched_set.signal, "background": matched_set.background,
            "reference": matched_set.reference, "ref_background": matched_set.reference_background,
        } if matched_set else {}
        for component, strip in self._exclude_strips.items():
            source = sources.get(component)
            frame_ids = sorted(source.data["Frame"].unique()) if source else []
            strip.blockSignals(True)
            strip.set_frame_ids(frame_ids)
            strip.set_excluded_frames(self._get_exclude_frames(index, component))
            strip.blockSignals(False)

        cached = self._cache.get(index, {})
        for step, rb in self._step_radios.items():
            rb.setEnabled(step in {"raw", "despiked"} or step in cached)

        self._step_radios["despiked"].setChecked(True)
        self._on_step_changed()

        # auto-run despiking immediately if not already cached
        if "despiked" not in self._cache.get(index, {}):
            self._auto_process_step = "despiked"
            self._auto_process_timer.start()

    # --- helpers --------------------------------
    def _pair(self) -> str:
        return self._pair_combo.currentText().lower()   # "sample pair"/"reference pair"/"both pairs"

    def _source(self) -> str:
        return self._source_combo.currentText().lower() # "signal"/"background"/"both"

    def _comp(self) -> str:
        return self._comp_combo.currentText().lower()   # "sample"/"reference"/"both"