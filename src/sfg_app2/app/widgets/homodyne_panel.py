from __future__ import annotations
import logging

import matplotlib.pyplot as plt
from PySide6.QtCore import Signal, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QRadioButton, QButtonGroup, QCheckBox,
    QComboBox, QSpinBox, QDoubleSpinBox,
    QFrame, QSizePolicy, QGridLayout, QMessageBox,
    QTableWidget, QTableWidgetItem, QHeaderView,
)

from sfg_app2.app.widgets.spectrum_plot_widget import SpectrumPlotWidget
from sfg_app2.app.widgets.dockable_panels import DockablePlotPanel
from sfg_app2.app.widgets.frame_exclude_widget import FrameCheckStrip
from sfg_app2.app.utils.loading_indicator import show_loading
from sfg_app2.processing.baseline import subtract_background, apply_offset, fit_offset_from_markers
from sfg_app2.processing.normalization import normalize

logger = logging.getLogger(__name__)

DEFAULT_DESPIKE = {"window": 50, "threshold": 20.0}

COMPONENTS = ["signal", "background", "reference", "ref_background"]
COMPONENT_LABELS = {
    "signal": "Sample",
    "background": "Sample BG",
    "reference": "Reference",
    "ref_background": "Ref BG",
}
COMPONENT_LINESTYLE = {
    "signal": "-", "background": "--", "reference": ":", "ref_background": "-.",
}
COMPONENT_CACHE_KEYS = {
    "signal":         ["despiked_signal", "averaged_signal",
                       "bg_subtracted", "normalized"],
    "background":     ["despiked_bg", "averaged_bg", "bg_subtracted", "normalized"],
    "reference":      ["despiked_ref", "averaged_ref", "bg_subtracted_ref", "normalized"],
    "ref_background": ["despiked_ref_bg", "averaged_ref_bg", "bg_subtracted_ref", "normalized"],
}

STEPS = ["raw", "despiked", "averaged", "bg_subtracted", "normalized"]
STEP_LABELS = {
    "raw": "Raw", "despiked": "Despiked", "averaged": "Averaged",
    "bg_subtracted": "BG Subtracted", "normalized": "Normalized",
}
# which param section is active per step
STEP_SECTION = {
    "raw": None, "despiked": "despike", "averaged": None,
    "bg_subtracted": "bg_offset", "normalized": "bg_offset",
}


def _colors(n: int) -> list:
    prop_cycle = plt.rcParams["axes.prop_cycle"]
    colors = [p["color"] for p in prop_cycle]
    return [colors[i % len(colors)] for i in range(max(n, 1))]


class HomodynePanel(QWidget, DockablePlotPanel):
    """Right panel for homodyne sets in the Process/Review tab.

    Mirrors HDSFGPanel's UX (live per-component despike grid, sample/
    reference x signal/background plot selectors, a step selector, and a
    Process/Send-to-Results button split) but operates over whichever
    matched set(s) are currently selected in the list — 1 in single mode,
    N in compare mode. Any parameter change broadcasts to every currently
    selected set (except background offset, which is a single value
    applied to every matched set regardless of selection).
    """

    processing_complete = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)

        self._matched_sets: list = []
        self._selected_indices: list[int] = []
        self._cache: dict[int, dict] = {}
        self._despike_configs: dict[int, dict] = {}
        self._exclude_frames: dict[int, dict[str, set]] = {}

        # background-offset markers — global (x, y) points shared across
        # every matched set: each set's offset curve is a least-squares fit
        # of the chosen style through (marker_y - that_set's_own_bg(marker_x)),
        # so the same markers yield a different offset curve per set. See
        # _fit_offset().
        self._sig_markers: list[tuple[float, float]] = []
        self._ref_markers: list[tuple[float, float]] = []
        self._marker_just_picked = False

        self._recompute_timer = QTimer(self)
        self._recompute_timer.setSingleShot(True)
        self._recompute_timer.setInterval(300)
        self._recompute_timer.timeout.connect(self._recompute_and_refresh)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(4, 4, 4, 4)
        main_layout.setSpacing(4)

        main_layout.addWidget(self._build_step_selector())

        self._component_row = self._build_component_row()
        main_layout.addWidget(self._component_row)

        self.plot_widget = SpectrumPlotWidget()
        self.plot_widget.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.plot_widget.canvas.mpl_connect('button_press_event', self._on_plot_click)
        self.plot_widget.canvas.mpl_connect('pick_event', self._on_marker_pick)

        self._init_dock_area(self.plot_widget)
        self._add_dock("despike", "Despike parameters", self._build_despike_section())
        self._add_dock("exclude_frames", "Exclude frames", self._build_exclude_frames_section())
        self._add_dock("bg_offset", "Background Correction", self._build_bg_offset_section())
        main_layout.addWidget(self._dock_main_window)

        self._connect_signals()
        self._on_step_changed()

    # ── UI builders ───────────────────────────────────────────────────────────

    def _build_step_selector(self) -> QFrame:
        frame = QFrame()
        frame.setFrameShape(QFrame.Shape.StyledPanel)
        frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.addWidget(QLabel("Step:"))

        self._step_group = QButtonGroup(self)
        self._step_radios: dict[str, QRadioButton] = {}
        for step in STEPS:
            rb = QRadioButton(STEP_LABELS[step])
            self._step_radios[step] = rb
            self._step_group.addButton(rb)
            layout.addWidget(rb)
        self._step_radios["raw"].setChecked(True)
        return frame

    def _build_component_row(self) -> QFrame:
        frame = QFrame()
        frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(4, 0, 4, 0)

        self._pair_label = QLabel("Pair:")
        self._pair_combo = QComboBox()
        self._pair_combo.addItems(["Sample pair", "Reference pair", "Both pairs"])
        self._pair_combo.setCurrentIndex(2)
        self._pair_combo.setToolTip("Select which pair(s) to show in the plot")

        self._source_label = QLabel("Show:")
        self._source_combo = QComboBox()
        self._source_combo.addItems(["Signal", "Background", "Both"])
        self._source_combo.setCurrentIndex(2)
        self._source_combo.setToolTip("Select which component(s) to show in the plot")

        self._view_label = QLabel("View:")
        self._view_combo = QComboBox()
        self._view_combo.addItems(["Subtracted result", "Signal + Background"])
        self._view_combo.setToolTip(
            "Show the background-subtracted result, or the pre-subtraction "
            "signal and background together"
        )

        for w in [self._pair_label, self._pair_combo,
                  self._source_label, self._source_combo,
                  self._view_label, self._view_combo]:
            layout.addWidget(w)
        layout.addStretch()

        self._legend_label = QLabel("Legend:")
        self._legend_combo = QComboBox()
        self._legend_combo.addItems(["No legend", "Minimized legend", "Full legend"])
        self._legend_combo.setCurrentIndex(2)
        self._legend_combo.setToolTip(
            "Minimized legend shows one entry per matched set (its filename), "
            "matching the set's plot color"
        )
        layout.addWidget(self._legend_label)
        layout.addWidget(self._legend_combo)

        self._process_btn = QPushButton("▶ Process")
        self._process_btn.setToolTip(
            "Run the full pipeline from scratch for the selected set(s)"
        )
        layout.addWidget(self._process_btn)

        self._finish_btn = QPushButton("✓ Send to Results")
        self._finish_btn.setVisible(False)
        layout.addWidget(self._finish_btn)

        return frame

    def _build_despike_section(self) -> QWidget:
        w = QWidget()
        grid = QGridLayout(w)

        grid.addWidget(QLabel(""), 0, 0)
        grid.addWidget(QLabel("Window"), 0, 1)
        grid.addWidget(QLabel("Threshold"), 0, 2)

        self._despike_widgets: dict[str, dict] = {}
        for row_idx, key in enumerate(COMPONENTS, start=1):
            grid.addWidget(QLabel(COMPONENT_LABELS[key] + ":"), row_idx, 0)

            window_sb = QSpinBox()
            window_sb.setRange(3, 1001)
            window_sb.setSingleStep(2)
            window_sb.setValue(DEFAULT_DESPIKE["window"])
            window_sb.setToolTip(
                "Size of the sliding median window — larger = smoother baseline."
            )
            grid.addWidget(window_sb, row_idx, 1)

            threshold_sb = QDoubleSpinBox()
            threshold_sb.setRange(0.5, 10000.0)
            threshold_sb.setSingleStep(10.0)
            threshold_sb.setDecimals(1)
            threshold_sb.setValue(DEFAULT_DESPIKE["threshold"])
            threshold_sb.setToolTip(
                "Points further than threshold x local MAD are flagged as spikes. "
                "Lower = more aggressive."
            )
            grid.addWidget(threshold_sb, row_idx, 2)

            self._despike_widgets[key] = {"window": window_sb, "threshold": threshold_sb}

        return w

    def _build_exclude_frames_section(self) -> QWidget:
        w = QWidget()
        grid = QGridLayout(w)

        self._exclude_strips: dict[str, FrameCheckStrip] = {}
        for row_idx, key in enumerate(COMPONENTS):
            grid.addWidget(QLabel(COMPONENT_LABELS[key] + ":"), row_idx, 0)
            strip = FrameCheckStrip()
            self._exclude_strips[key] = strip
            grid.addWidget(strip, row_idx, 1)

        return w

    def _build_bg_offset_section(self) -> QWidget:
        """The offset added to the averaged background before subtraction.
        Rather than typing coefficients blind, the offset curve is fit
        (least-squares, degree set by the chosen style) through markers you
        place — by clicking the plot in the "Signal + Background" view, or
        editing the table below. Markers are global (x, y) values, not tied
        to one matched set's curve: for each set, the fit is computed
        against *that set's own* averaged background (see _fit_offset()),
        so the same markers naturally produce a different curve per set.

        Whether the correction is actually applied is a separate concern
        from whether this dock is open/closed — _bg_apply_checkbox carries
        that, so closing the dock to reduce clutter can never silently
        disable a correction you'd turned on.
        """
        w = QWidget()
        layout = QVBoxLayout(w)

        self._bg_apply_checkbox = QCheckBox("Apply background correction")
        layout.addWidget(self._bg_apply_checkbox)

        target_row = QHBoxLayout()
        target_row.addWidget(QLabel("Editing markers for:"))
        self._offset_target_combo = QComboBox()
        self._offset_target_combo.addItems(["Signal", "Reference"])
        target_row.addWidget(self._offset_target_combo)
        target_row.addStretch()
        layout.addLayout(target_row)

        self._offset_degree_spin: dict[str, QSpinBox] = {}
        for target, label in (("signal", "Signal BG"), ("reference", "Ref BG")):
            row = QHBoxLayout()
            row.addWidget(QLabel(f"{label} degree:"))
            degree_spin = QSpinBox()
            degree_spin.setRange(0, 6)
            degree_spin.setValue(0)
            degree_spin.setToolTip("0 = constant, 1 = linear, 2+ = polynomial")
            row.addWidget(degree_spin)
            row.addStretch()
            layout.addLayout(row)
            self._offset_degree_spin[target] = degree_spin

        layout.addWidget(QLabel(
            "Markers (click the plot in \"Signal + Background\" view to add, "
            "click a marker to remove, or edit here):"
        ))
        self._marker_table = QTableWidget(0, 2)
        self._marker_table.setHorizontalHeaderLabels(["X", "Y"])
        self._marker_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._marker_table.verticalHeader().setVisible(False)
        self._marker_table.setMaximumHeight(120)
        layout.addWidget(self._marker_table)

        marker_btn_row = QHBoxLayout()
        self._add_marker_btn = QPushButton("Add row")
        self._remove_marker_btn = QPushButton("Remove selected")
        self._clear_marker_btn = QPushButton("Clear all")
        marker_btn_row.addWidget(self._add_marker_btn)
        marker_btn_row.addWidget(self._remove_marker_btn)
        marker_btn_row.addWidget(self._clear_marker_btn)
        marker_btn_row.addStretch()
        layout.addLayout(marker_btn_row)

        return w

    # ── Signal wiring ─────────────────────────────────────────────────────────

    def _connect_signals(self):
        for rb in self._step_radios.values():
            rb.toggled.connect(lambda checked: self._on_step_changed() if checked else None)

        self._pair_combo.currentIndexChanged.connect(self._refresh_plot)
        self._source_combo.currentIndexChanged.connect(self._refresh_plot)
        self._view_combo.currentIndexChanged.connect(self._refresh_plot)
        self._legend_combo.currentIndexChanged.connect(self._refresh_plot)

        for key in COMPONENTS:
            self._despike_widgets[key]["window"].valueChanged.connect(
                lambda _v, k=key: self._on_despike_changed(k)
            )
            self._despike_widgets[key]["threshold"].valueChanged.connect(
                lambda _v, k=key: self._on_despike_changed(k)
            )

        for key in COMPONENTS:
            self._exclude_strips[key].changed.connect(
                lambda k=key: self._on_exclude_frames_changed(k)
            )

        for spin in self._offset_degree_spin.values():
            spin.valueChanged.connect(self._on_bg_offset_changed)
        self._offset_target_combo.currentTextChanged.connect(lambda _t: self._reload_marker_table())
        self._add_marker_btn.clicked.connect(self._on_add_marker_row)
        self._remove_marker_btn.clicked.connect(self._on_remove_marker_row)
        self._clear_marker_btn.clicked.connect(self._on_clear_markers)
        self._marker_table.cellChanged.connect(self._on_marker_cell_changed)
        self._bg_apply_checkbox.toggled.connect(lambda _checked: self._on_bg_offset_changed())

        self._process_btn.clicked.connect(self._on_process)
        self._finish_btn.clicked.connect(self._on_finish)

    # ── Step change ───────────────────────────────────────────────────────────

    def _current_step(self) -> str:
        for step, rb in self._step_radios.items():
            if rb.isChecked():
                return step
        return "raw"

    def _on_step_changed(self):
        step = self._current_step()
        show_pair = step in ("raw", "despiked", "averaged", "bg_subtracted")
        show_source = step in ("raw", "despiked", "averaged")
        show_view = step == "bg_subtracted"
        self._pair_label.setVisible(show_pair)
        self._pair_combo.setVisible(show_pair)
        self._source_label.setVisible(show_source)
        self._source_combo.setVisible(show_source)
        self._view_label.setVisible(show_view)
        self._view_combo.setVisible(show_view)

        self._process_btn.setVisible(step != "normalized")
        self._finish_btn.setVisible(step == "normalized")

        section_key = STEP_SECTION.get(step)
        visible = {section_key} if section_key else set()
        if step in ("raw", "despiked", "averaged"):
            visible.add("exclude_frames")
        self._set_dock_visibility(visible, focus_key=section_key)

        self._recompute_and_refresh()

    # ── Despike ───────────────────────────────────────────────────────────────

    def _get_despike_cfg(self, idx: int, component: str) -> dict:
        return self._despike_configs.get(idx, {}).get(component, DEFAULT_DESPIKE.copy())

    def _set_despike_cfg(self, idx: int, component: str, cfg: dict):
        if idx not in self._despike_configs:
            self._despike_configs[idx] = {}
        self._despike_configs[idx][component] = cfg.copy()

    def _invalidate_component_cache(self, indices: list[int], component: str):
        keys = COMPONENT_CACHE_KEYS.get(component, [])
        for idx in indices:
            c = self._cache.get(idx, {})
            for key in keys:
                c.pop(key, None)

    # ── Frame exclusion ──────────────────────────────────────────────────────

    def _get_exclude_frames(self, idx: int, component: str) -> set:
        return self._exclude_frames.get(idx, {}).get(component, set())

    def _set_exclude_frames(self, idx: int, component: str, frames: set):
        if idx not in self._exclude_frames:
            self._exclude_frames[idx] = {}
        self._exclude_frames[idx][component] = set(frames)

    def _on_exclude_frames_changed(self, component: str):
        if not self._selected_indices:
            return
        excluded = self._exclude_strips[component].excluded_frames()
        for idx in self._selected_indices:
            self._set_exclude_frames(idx, component, excluded)
        self._invalidate_component_cache(self._selected_indices, component)
        self._recompute_timer.start()

    def _on_despike_changed(self, component: str):
        if not self._selected_indices:
            return
        cfg = {
            "window": self._despike_widgets[component]["window"].value(),
            "threshold": self._despike_widgets[component]["threshold"].value(),
        }
        for idx in self._selected_indices:
            self._set_despike_cfg(idx, component, cfg)
        self._invalidate_component_cache(self._selected_indices, component)
        self._recompute_timer.start()

    # ── Background offset markers ────────────────────────────────────────────

    def _markers_for(self, target: str) -> list[tuple[float, float]]:
        return self._sig_markers if target == "signal" else self._ref_markers

    def _current_target(self) -> str:
        return self._offset_target_combo.currentText().lower()

    def _reload_marker_table(self):
        markers = self._markers_for(self._current_target())
        self._marker_table.blockSignals(True)
        self._marker_table.setRowCount(len(markers))
        for row, (x, y) in enumerate(markers):
            self._marker_table.setItem(row, 0, QTableWidgetItem(f"{x:.6g}"))
            self._marker_table.setItem(row, 1, QTableWidgetItem(f"{y:.6g}"))
        self._marker_table.blockSignals(False)

    def _add_marker(self, target: str, x: float, y: float):
        self._markers_for(target).append((float(x), float(y)))
        if target == self._current_target():
            self._reload_marker_table()
        self._on_bg_offset_changed()

    def _remove_marker(self, target: str, index: int):
        markers = self._markers_for(target)
        if 0 <= index < len(markers):
            del markers[index]
        if target == self._current_target():
            self._reload_marker_table()
        self._on_bg_offset_changed()

    def _clear_markers(self, target: str):
        self._markers_for(target).clear()
        if target == self._current_target():
            self._reload_marker_table()
        self._on_bg_offset_changed()

    def _on_add_marker_row(self):
        self._add_marker(self._current_target(), 0.0, 0.0)

    def _on_remove_marker_row(self):
        row = self._marker_table.currentRow()
        if row >= 0:
            self._remove_marker(self._current_target(), row)

    def _on_clear_markers(self):
        self._clear_markers(self._current_target())

    def _on_marker_cell_changed(self, row: int, col: int):
        target = self._current_target()
        markers = self._markers_for(target)
        if row >= len(markers):
            return
        item = self._marker_table.item(row, col)
        try:
            val = float(item.text()) if item is not None else None
        except ValueError:
            val = None
        if val is None:
            self._reload_marker_table()   # revert invalid text
            return
        x, y = markers[row]
        markers[row] = (val, y) if col == 0 else (x, val)
        self._on_bg_offset_changed()

    def _on_marker_pick(self, event):
        target = getattr(event.artist, "_marker_target", None)
        if target is None or not self._bg_apply_checkbox.isChecked():
            return
        if not len(event.ind):
            return
        self._marker_just_picked = True
        self._remove_marker(target, event.ind[0])

    def _on_plot_click(self, event):
        if self._marker_just_picked:
            self._marker_just_picked = False
            return
        if event.inaxes != self.plot_widget.ax or not self._bg_apply_checkbox.isChecked():
            return
        if (self._current_step() != "bg_subtracted"
                or self._view_combo.currentText() != "Signal + Background"):
            return
        if event.xdata is None or event.ydata is None:
            return
        self._add_marker(self._current_target(), event.xdata, event.ydata)

    def _plot_offset_markers(self):
        ax = self.plot_widget.ax
        style = {"signal": ("black", "o"), "reference": ("dimgray", "s")}
        targets = []
        if self._show_sample():
            targets.append("signal")
        if self._show_reference():
            targets.append("reference")
        for target in targets:
            markers = self._markers_for(target)
            if not markers:
                continue
            color, marker = style[target]
            xs = [m[0] for m in markers]
            ys = [m[1] for m in markers]
            line, = ax.plot(
                xs, ys, marker=marker, linestyle="none",
                markersize=8, markerfacecolor=color,
                markeredgecolor="white", markeredgewidth=1,
                picker=5, zorder=6, label="_nolegend_",
            )
            line._marker_target = target

    # ── Background offset ────────────────────────────────────────────────────

    def _current_offsets(self, idx: int | None = None):
        if not self._bg_apply_checkbox.isChecked():
            return None, None
        return (
            self._fit_offset(idx, "signal"),
            self._fit_offset(idx, "reference"),
        )

    def _fit_offset(self, idx: int | None, target: str):
        if idx is None:
            return None
        markers = self._markers_for(target)
        if not markers:
            return None
        c = self._cache.get(idx, {})
        bg_data = c.get("averaged_bg" if target == "signal" else "averaged_ref_bg")
        if bg_data is None:
            return None
        bg_frame = bg_data.frame(1)
        degree = self._offset_degree_spin[target].value()
        return fit_offset_from_markers(
            markers, degree,
            bg_frame["Wavelength"].to_numpy(), bg_frame["Intensity"].to_numpy(),
        )

    def _on_bg_offset_changed(self):
        for idx in range(len(self._matched_sets)):
            c = self._cache.get(idx, {})
            for key in ("bg_subtracted", "bg_subtracted_ref", "normalized",
                        "_sig_offset", "_ref_offset"):
                c.pop(key, None)
        self._recompute_timer.start()

    def on_upconversion_changed(self):
        """Called by ProcessReviewTab when the shared upconversion
        wavelength spinbox changes."""
        for idx in range(len(self._matched_sets)):
            c = self._cache.get(idx, {})
            c.pop("normalized", None)
            c.pop("_upconversion_wl", None)
        if self._current_step() == "normalized":
            self._recompute_and_refresh()

    def _upconversion_wl(self) -> float:
        try:
            return self.window().process_review_tab.get_upconversion_wavelength()
        except Exception:
            return 1030.7

    # ── Pipeline / cache ──────────────────────────────────────────────────────

    def _get_step(self, idx: int, step: str):
        if idx not in self._cache:
            self._cache[idx] = {}
        c = self._cache[idx]
        m = self._matched_sets[idx]

        if step == "raw":
            return m.signal

        if step == "despiked":
            cfg_sig = self._get_despike_cfg(idx, "signal")
            cfg_bg  = self._get_despike_cfg(idx, "background")
            cfg_ref = self._get_despike_cfg(idx, "reference")
            cfg_rbg = self._get_despike_cfg(idx, "ref_background")

            if "despiked_signal" not in c:
                c["despiked_signal"] = m.signal.remove_cosmic_rays(
                    window=cfg_sig["window"], threshold_factor=cfg_sig["threshold"],
                )
            if m.background and "despiked_bg" not in c:
                c["despiked_bg"] = m.background.remove_cosmic_rays(
                    window=cfg_bg["window"], threshold_factor=cfg_bg["threshold"],
                )
            if m.reference and "despiked_ref" not in c:
                c["despiked_ref"] = m.reference.remove_cosmic_rays(
                    window=cfg_ref["window"], threshold_factor=cfg_ref["threshold"],
                )
            if m.reference_background and "despiked_ref_bg" not in c:
                c["despiked_ref_bg"] = m.reference_background.remove_cosmic_rays(
                    window=cfg_rbg["window"], threshold_factor=cfg_rbg["threshold"],
                )
            return c["despiked_signal"]

        if step == "averaged":
            self._get_step(idx, "despiked")
            if "averaged_signal" not in c:
                c["averaged_signal"] = c["despiked_signal"].average_spectrum(
                    exclude_frames=self._get_exclude_frames(idx, "signal"))
            if "despiked_bg" in c and "averaged_bg" not in c:
                c["averaged_bg"] = c["despiked_bg"].average_spectrum(
                    exclude_frames=self._get_exclude_frames(idx, "background"))
            if "despiked_ref" in c and "averaged_ref" not in c:
                c["averaged_ref"] = c["despiked_ref"].average_spectrum(
                    exclude_frames=self._get_exclude_frames(idx, "reference"))
            if "despiked_ref_bg" in c and "averaged_ref_bg" not in c:
                c["averaged_ref_bg"] = c["despiked_ref_bg"].average_spectrum(
                    exclude_frames=self._get_exclude_frames(idx, "ref_background"))
            return c["averaged_signal"]

        if step == "bg_subtracted":
            self._get_step(idx, "averaged")
            sig_offset, ref_offset = self._current_offsets(idx)
            if (c.get("_sig_offset") != sig_offset or
                    c.get("_ref_offset") != ref_offset):
                c.pop("bg_subtracted", None)
                c.pop("bg_subtracted_ref", None)
                c.pop("normalized", None)
            if "bg_subtracted" not in c:
                if not m.background:
                    c["bg_subtracted"] = c.get("averaged_signal")
                else:
                    bg_avg = c.get("averaged_bg") or m.background.average_spectrum(
                        exclude_frames=self._get_exclude_frames(idx, "background"))
                    c["bg_subtracted"] = subtract_background(
                        c["averaged_signal"], bg_avg, offset=sig_offset,
                    )
                c["_sig_offset"] = sig_offset
                c["_ref_offset"] = ref_offset
            if "bg_subtracted_ref" not in c and m.reference:
                if not m.reference_background:
                    c["bg_subtracted_ref"] = c.get("averaged_ref")
                else:
                    ref_bg_avg = c.get("averaged_ref_bg") or m.reference_background.average_spectrum(
                        exclude_frames=self._get_exclude_frames(idx, "ref_background"))
                    c["bg_subtracted_ref"] = subtract_background(
                        c["averaged_ref"], ref_bg_avg, offset=ref_offset,
                    )
            return c["bg_subtracted"]

        if step == "normalized":
            self._get_step(idx, "bg_subtracted")
            wl = self._upconversion_wl()
            if "normalized" not in c or c.get("_upconversion_wl") != wl:
                bg_sub = c.get("bg_subtracted") or c.get("averaged_signal")
                if not bg_sub or not m.reference:
                    return bg_sub
                ref = c.get("averaged_ref") or m.reference.average_spectrum(
                    exclude_frames=self._get_exclude_frames(idx, "reference"))
                _, ref_offset = self._current_offsets(idx)
                if m.reference_background:
                    ref_bg = c.get("averaged_ref_bg") or m.reference_background.average_spectrum(
                        exclude_frames=self._get_exclude_frames(idx, "ref_background"))
                    ref = subtract_background(ref, ref_bg, offset=ref_offset)
                c["normalized"] = normalize(bg_sub, ref).upconvert_to_wavenumber(wl)
                c["normalized"].provenance = self._build_provenance(idx, wl)
                c["_upconversion_wl"] = wl
            return c["normalized"]

        return None

    def _build_provenance(self, idx: int, wl: float) -> dict:
        """Snapshot of the parameters actually used to produce the
        'normalized' result for this set — attached to the final
        ProcessedSpectrum so it can be inspected/exported later."""
        m = self._matched_sets[idx]
        sig_offset, ref_offset = self._current_offsets(idx)
        return {
            "signal":               m.signal.path.name if m.signal else None,
            "background":           m.background.path.name if m.background else None,
            "reference":            m.reference.path.name if m.reference else None,
            "reference_background": m.reference_background.path.name if m.reference_background else None,
            "despike": {
                "signal":               self._get_despike_cfg(idx, "signal"),
                "background":           self._get_despike_cfg(idx, "background"),
                "reference":            self._get_despike_cfg(idx, "reference"),
                "reference_background": self._get_despike_cfg(idx, "ref_background"),
            },
            "background_subtraction": {
                "applied":              self._bg_apply_checkbox.isChecked(),
                "signal_offset_degree": self._offset_degree_spin["signal"].value(),
                "signal_offset_markers": [list(pt) for pt in self._sig_markers],
                "signal_offset":        str(sig_offset) if sig_offset is not None else "None",
                "ref_offset_degree":    self._offset_degree_spin["reference"].value(),
                "ref_offset_markers":   [list(pt) for pt in self._ref_markers],
                "ref_offset":           str(ref_offset) if ref_offset is not None else "None",
            },
            "normalization":  {"applied": m.reference is not None},
            "upconversion":   {"applied": m.reference is not None,
                                "wavelength_nm": wl if m.reference is not None else None},
            "excluded_frames": {
                "signal":               sorted(self._get_exclude_frames(idx, "signal")),
                "background":           sorted(self._get_exclude_frames(idx, "background")),
                "reference":            sorted(self._get_exclude_frames(idx, "reference")),
                "reference_background": sorted(self._get_exclude_frames(idx, "ref_background")),
            },
        }

    def _recompute_and_refresh(self):
        step = self._current_step()
        for idx in self._selected_indices:
            try:
                self._get_step(idx, step)
            except Exception as e:
                logger.warning(
                    "Could not compute step '%s' for set %d: %s", step, idx, e,
                )
        self._refresh_plot()

    # ── Plot ──────────────────────────────────────────────────────────────────

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

    def _refresh_plot(self):
        step = self._current_step()
        self.plot_widget.full_clear()
        self._legend_entries: list[tuple] = []

        if self._selected_indices:
            colors = _colors(len(self._selected_indices))
            for i, idx in enumerate(self._selected_indices):
                m = self._matched_sets[idx]
                label = m.signal.path.stem if m.signal else f"Set {idx + 1}"
                try:
                    self._plot_one_set(idx, step, colors[i], label)
                    self._legend_entries.append((colors[i], label))
                except Exception as e:
                    logger.warning(
                        "Could not plot set %d step '%s': %s", idx, step, e, exc_info=True,
                    )

        if step == "bg_subtracted" and self._view_combo.currentText() == "Signal + Background":
            self._plot_offset_markers()

        self._apply_legend()

        xlabel = "Wavenumber (cm$^{-1}$)" if step == "normalized" else "Wavelength (nm)"
        ylabel = "Intensity (a.u.)" if step == "normalized" else "Intensity (counts)"
        self.plot_widget.set_labels(xlabel=xlabel, ylabel=ylabel, title=STEP_LABELS[step])
        self.plot_widget.sync_x_range()
        self.plot_widget.canvas.draw_idle()

    def _apply_legend(self):
        mode = self._legend_combo.currentText()
        ax = self.plot_widget.ax
        if mode == "No legend":
            return
        if mode == "Minimized legend":
            if self._legend_entries:
                import matplotlib.lines as mlines
                proxies = [
                    mlines.Line2D([], [], color=c, label=l)
                    for c, l in self._legend_entries
                ]
                ax.legend(handles=proxies, fontsize=8)
            return
        handles, _ = ax.get_legend_handles_labels()
        if handles:
            ax.legend(fontsize=8)

    def _plot_one_set(self, idx: int, step: str, color, label: str):
        if step in ("raw", "despiked", "averaged"):
            self._plot_multi_component(idx, step, label, color)
            return

        if step == "bg_subtracted":
            if self._view_combo.currentText() == "Signal + Background":
                self._plot_bg_averaged_view(idx, label, color)
            else:
                self._plot_bg_subtracted_result(idx, label, color)
            return

        result = self._get_step(idx, step)
        if result is None:
            return
        x_col = "Wavenumber" if step == "normalized" else "Wavelength"
        fd = result.frame(1)
        self.plot_widget.ax.plot(
            fd[x_col].to_numpy(), fd["Intensity"].to_numpy(),
            color=color, label=label,
        )

    def _plot_multi_component(self, idx: int, step: str, label: str, color):
        m = self._matched_sets[idx]
        if step != "raw":
            self._get_step(idx, step)
        c = self._cache.get(idx, {})

        sources = {
            "signal":         (m.signal, "despiked_signal", "averaged_signal"),
            "background":     (m.background, "despiked_bg", "averaged_bg"),
            "reference":      (m.reference, "despiked_ref", "averaged_ref"),
            "ref_background": (m.reference_background, "despiked_ref_bg", "averaged_ref_bg"),
        }

        enabled_components = []
        if self._show_sample():
            if self._show_signal():
                enabled_components.append("signal")
            if self._show_background():
                enabled_components.append("background")
        if self._show_reference():
            if self._show_signal():
                enabled_components.append("reference")
            if self._show_background():
                enabled_components.append("ref_background")

        for component in enabled_components:
            raw_source, despiked_key, averaged_key = sources[component]
            if raw_source is None:
                continue

            if step == "raw":
                data = raw_source
            elif step == "despiked":
                data = c.get(despiked_key)
            else:
                data = c.get(averaged_key)
            if data is None:
                continue

            linestyle = COMPONENT_LINESTYLE[component]
            comp_label = COMPONENT_LABELS[component]

            if step == "averaged":
                fd = data.frame(1)
                self.plot_widget.ax.plot(
                    fd["Wavelength"].to_numpy(), fd["Intensity"].to_numpy(),
                    color=color, linestyle=linestyle,
                    label=f"{label} — {comp_label}",
                )
            else:
                excluded = self._get_exclude_frames(idx, component)
                for fid in data.data["Frame"].unique():
                    fd = data.frame(fid)
                    is_excluded = fid in excluded
                    self.plot_widget.ax.plot(
                        fd["Wavelength"].to_numpy(), fd["Intensity"].to_numpy(),
                        color=color,
                        linestyle=":" if is_excluded else linestyle,
                        alpha=0.25 if is_excluded else 0.85,
                        label=f"{label} — {comp_label} F{fid}" + (" (excluded)" if is_excluded else ""),
                    )

    def _plot_bg_subtracted_result(self, idx: int, label: str, color):
        """'Subtracted result' view at the bg_subtracted step: the single
        background-subtracted curve for whichever pair(s) are selected."""
        self._get_step(idx, "bg_subtracted")
        c = self._cache.get(idx, {})

        if self._show_sample():
            sig_result = c.get("bg_subtracted")
            if sig_result is not None:
                fd = sig_result.frame(1)
                self.plot_widget.ax.plot(
                    fd["Wavelength"].to_numpy(), fd["Intensity"].to_numpy(),
                    color=color, linestyle=COMPONENT_LINESTYLE["signal"],
                    label=f"{label} — {COMPONENT_LABELS['signal']} (subtracted)",
                )
        if self._show_reference():
            ref_result = c.get("bg_subtracted_ref")
            if ref_result is not None:
                fd = ref_result.frame(1)
                self.plot_widget.ax.plot(
                    fd["Wavelength"].to_numpy(), fd["Intensity"].to_numpy(),
                    color=color, linestyle=COMPONENT_LINESTYLE["reference"],
                    label=f"{label} — {COMPONENT_LABELS['reference']} (subtracted)",
                )

    def _plot_bg_averaged_view(self, idx: int, label: str, color):
        """'Signal + Background' view at the bg_subtracted step: both
        pre-subtraction averaged traces for whichever pair(s) are selected,
        regardless of the (hidden, possibly stale) source combo. The
        background trace has the current offset applied (via apply_offset,
        the same helper subtract_background uses internally) so this view
        lets you visually check the offset before it's baked into the
        subtracted result."""
        self._get_step(idx, "bg_subtracted")
        c = self._cache.get(idx, {})
        sig_offset, ref_offset = self._current_offsets(idx)

        pairs = []
        if self._show_sample():
            pairs.append(("signal", "background", "averaged_signal", "averaged_bg", sig_offset))
        if self._show_reference():
            pairs.append(("reference", "ref_background", "averaged_ref", "averaged_ref_bg", ref_offset))

        for sig_comp, bg_comp, sig_key, bg_key, offset in pairs:
            sig_data = c.get(sig_key)
            if sig_data is not None:
                fd = sig_data.frame(1)
                self.plot_widget.ax.plot(
                    fd["Wavelength"].to_numpy(), fd["Intensity"].to_numpy(),
                    color=color, linestyle=COMPONENT_LINESTYLE[sig_comp],
                    label=f"{label} — {COMPONENT_LABELS[sig_comp]}",
                )
            bg_data = c.get(bg_key)
            if bg_data is not None:
                bg_data = apply_offset(bg_data, offset)
                fd = bg_data.frame(1)
                self.plot_widget.ax.plot(
                    fd["Wavelength"].to_numpy(), fd["Intensity"].to_numpy(),
                    color=color, linestyle=COMPONENT_LINESTYLE[bg_comp], alpha=0.7,
                    label=f"{label} — {COMPONENT_LABELS[bg_comp]}",
                )

    # ── Process / Send to Results ────────────────────────────────────────────

    def _on_process(self):
        if not self._selected_indices:
            QMessageBox.information(
                self, "Nothing selected", "Select one or more matched sets first."
            )
            return

        errors = []
        loading = show_loading(self, "Processing...")
        try:
            for idx in self._selected_indices:
                self._cache.pop(idx, None)
                try:
                    self._get_step(idx, "normalized")
                except Exception as e:
                    name = self._matched_sets[idx].signal.path.name \
                        if self._matched_sets[idx].signal else f"Set {idx + 1}"
                    errors.append(f"{name}: {e}")
                    logger.error("Processing failed for set %d: %s", idx, e, exc_info=True)
        finally:
            loading.close()

        self._refresh_plot()
        if errors:
            QMessageBox.critical(self, "Processing error", "\n".join(errors))

    def _on_finish(self):
        if not self._selected_indices:
            QMessageBox.information(
                self, "Nothing selected", "Select one or more matched sets first."
            )
            return

        results = {}
        skipped = []
        for idx in self._selected_indices:
            c = self._cache.get(idx, {})
            m = self._matched_sets[idx]
            name = m.signal.path.name if m.signal else f"Set {idx + 1}"
            if "normalized" in c and m.signal:
                results[m.signal.path.name] = c["normalized"]
            else:
                skipped.append(name)

        if not results:
            QMessageBox.information(
                self, "Nothing to send",
                "None of the selected set(s) have been processed yet. "
                "Click \"▶ Process\" first."
            )
            return

        if skipped:
            QMessageBox.information(
                self, "Some sets skipped",
                f"{len(skipped)} selected set(s) not yet processed, skipped:\n"
                + "\n".join(skipped)
            )

        self.processing_complete.emit(results)

    # ── Public API ────────────────────────────────────────────────────────────

    def redraw_for_style_change(self):
        """Called after the global plotting style changes. _refresh_plot()
        already calls plot_widget.full_clear() unconditionally, so simply
        re-invoking it is enough to pick up the new rcParams."""
        self._refresh_plot()

    def set_matched_sets(self, matched_sets: list):
        self._matched_sets = matched_sets
        self._cache.clear()
        self._despike_configs.clear()
        self._exclude_frames.clear()
        self._selected_indices = []
        self.plot_widget.full_clear()
        self.plot_widget.canvas.draw_idle()

    def set_selection(self, indices: list[int]):
        self._selected_indices = [
            i for i in indices if 0 <= i < len(self._matched_sets)
        ]
        if self._selected_indices:
            first = self._selected_indices[0]
            for component in COMPONENTS:
                cfg = self._get_despike_cfg(first, component)
                widgets = self._despike_widgets[component]
                widgets["window"].blockSignals(True)
                widgets["threshold"].blockSignals(True)
                widgets["window"].setValue(cfg["window"])
                widgets["threshold"].setValue(cfg["threshold"])
                widgets["window"].blockSignals(False)
                widgets["threshold"].blockSignals(False)

            m = self._matched_sets[first]
            sources = {
                "signal": m.signal, "background": m.background,
                "reference": m.reference, "ref_background": m.reference_background,
            }
            for component in COMPONENTS:
                strip = self._exclude_strips[component]
                source = sources[component]
                frame_ids = sorted(source.data["Frame"].unique()) if source else []
                strip.blockSignals(True)
                strip.set_frame_ids(frame_ids)
                strip.set_excluded_frames(self._get_exclude_frames(first, component))
                strip.blockSignals(False)
        self._recompute_and_refresh()

    def reset(self):
        self._matched_sets = []
        self._cache.clear()
        self._despike_configs.clear()
        self._exclude_frames.clear()
        self._selected_indices = []
        self.plot_widget.full_clear()
        self.plot_widget.canvas.draw_idle()
