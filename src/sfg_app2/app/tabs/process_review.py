from __future__ import annotations
import logging

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QListWidgetItem, QMessageBox, QButtonGroup,
    QAbstractItemView, QSizePolicy, QFrame,
    QDoubleSpinBox, QSpinBox, QPushButton,
)

from sfg_app2.app.ui.ui_process_review_tab import Ui_Form
from sfg_app2.app.widgets.collapsible_group_box import make_collapsible
from sfg_app2.app.widgets.spectrum_plot_widget import SpectrumPlotWidget
from sfg_app2.processing.baseline import subtract_background
from sfg_app2.processing.normalization import normalize
from sfg_app2.processing.despike import detect_spikes

logger = logging.getLogger(__name__)

DEFAULT_DESPIKE = {"window": 20, "threshold": 500.0}

COMPONENTS = ["signal", "background", "reference", "ref_background"]
COMPONENT_LABELS = {
    "signal": "Sample",
    "background": "Sample BG",
    "reference": "Reference",
    "ref_background": "Ref BG",
}
COMPONENT_CACHE_KEYS = {
    "signal":         ["despiked_signal", "averaged_signal",
                       "bg_subtracted", "normalized"],
    "background":     ["despiked_bg", "bg_subtracted", "normalized"],
    "reference":      ["despiked_ref", "normalized"],
    "ref_background": ["despiked_ref_bg", "normalized"],
}


def _parse_offset(combo_text: str, params_text: str):
    if combo_text == "None":
        return None
    try:
        if combo_text == "Constant":
            return float(params_text)
        elif combo_text in ("Linear", "Polynomial"):
            return [float(x.strip()) for x in params_text.split(",")]
    except ValueError:
        logger.warning("Could not parse offset params '%s' — using None.", params_text)
        return None


class ProcessReviewTab(QWidget):
    processing_complete = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.ui = Ui_Form()
        self.ui.setupUi(self)

        self.ui.calibrationFrame.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )

        self._matched_sets: list = []
        self._cache: dict[int, dict] = {}
        self._despike_configs: dict[int, dict] = {}   # per-set despike params

        self._setup_plot()
        self._setup_button_groups()
        self._setup_bg_correction()
        self._setup_despike_panel()
        self._connect_signals()

        from sfg_app2.app.widgets.collapsible_group_box import make_collapsible
        make_collapsible(self.ui.bgCorrectionGroupBox)

    # ── Setup ─────────────────────────────────────────────────────────────────

    def _setup_plot(self):
        layout = QVBoxLayout(self.ui.plotPlaceholder)
        layout.setContentsMargins(0, 0, 0, 0)
        self.plot_widget = SpectrumPlotWidget()
        layout.addWidget(self.plot_widget)

    def _setup_button_groups(self):
        self._view_group = QButtonGroup(self)
        self._view_group.addButton(self.ui.singleViewRadio)
        self._view_group.addButton(self.ui.compareViewRadio)

        self._step_group = QButtonGroup(self)
        self._step_group.addButton(self.ui.rawStepRadio)
        self._step_group.addButton(self.ui.despikedStepRadio)
        self._step_group.addButton(self.ui.averagedStepRadio)
        self._step_group.addButton(self.ui.bgSubtractedStepRadio)
        self._step_group.addButton(self.ui.normalizedStepRadio)

    def _setup_bg_correction(self):
        self.ui.signalOffsetParamsEdit.setEnabled(False)
        self.ui.refOffsetParamsEdit.setEnabled(False)
        self.ui.signalOffsetCombo.currentTextChanged.connect(
            lambda t: self.ui.signalOffsetParamsEdit.setEnabled(t != "None")
        )
        self.ui.refOffsetCombo.currentTextChanged.connect(
            lambda t: self.ui.refOffsetParamsEdit.setEnabled(t != "None")
        )

    def _setup_despike_panel(self):
        self._despike_frame = QFrame()
        self._despike_frame.setFrameShape(QFrame.Shape.StyledPanel)
        self._despike_frame.setFrameShadow(QFrame.Shadow.Raised)
        self._despike_frame.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self._despike_frame.setVisible(False)

        from PySide6.QtWidgets import QComboBox
        row1 = QHBoxLayout()

        row1.addWidget(QLabel("Component:"))
        self._despike_component_combo = QComboBox()
        for key in COMPONENTS:
            self._despike_component_combo.addItem(COMPONENT_LABELS[key], userData=key)
        row1.addWidget(self._despike_component_combo)

        row1.addWidget(QLabel("Window:"))
        self._despike_window_spin = QSpinBox()
        self._despike_window_spin.setRange(3, 101)
        self._despike_window_spin.setSingleStep(2)
        self._despike_window_spin.setValue(DEFAULT_DESPIKE["window"])
        self._despike_window_spin.setToolTip(
            "Size of the sliding median window — larger = smoother baseline."
        )
        row1.addWidget(self._despike_window_spin)

        row1.addWidget(QLabel("Threshold:"))
        self._despike_threshold_spin = QDoubleSpinBox()
        self._despike_threshold_spin.setRange(0.5, 10000.0)
        self._despike_threshold_spin.setSingleStep(10.0)
        self._despike_threshold_spin.setDecimals(1)
        self._despike_threshold_spin.setValue(DEFAULT_DESPIKE["threshold"])
        self._despike_threshold_spin.setToolTip(
            "Points further than threshold × local MAD are flagged as spikes. "
            "Lower = more aggressive."
        )
        row1.addWidget(self._despike_threshold_spin)
        row1.addStretch()

        self._despike_apply_set_btn = QPushButton("Apply to this set")
        self._despike_apply_all_btn = QPushButton("Apply to all")
        row1.addWidget(self._despike_apply_set_btn)
        row1.addWidget(self._despike_apply_all_btn)

        self._despike_status_label = QLabel("")
        self._despike_status_label.setStyleSheet("color: darkorange;")

        frame_layout = QVBoxLayout(self._despike_frame)
        frame_layout.setContentsMargins(6, 4, 6, 4)
        frame_layout.addLayout(row1)
        frame_layout.addWidget(self._despike_status_label)

        right_layout = self.ui.rightPanelWidget.layout()
        right_layout.insertWidget(1, self._despike_frame)

    def _connect_signals(self):
        self.ui.matchedSetsListWidget.currentRowChanged.connect(self._on_set_selected)
        self.ui.matchedSetsListWidget.itemSelectionChanged.connect(self._refresh_plot)
        self.ui.singleViewRadio.toggled.connect(self._on_view_changed)
        self._step_group.buttonToggled.connect(
            lambda btn, checked: self._on_step_changed() if checked else None
        )
        self.ui.upconversionSpinBox.valueChanged.connect(self._on_upconversion_changed)
        self.ui.calibrateButton.clicked.connect(self._on_calibrate)
        self.ui.applyToSetButton.clicked.connect(self._on_apply_bg_to_set)
        self.ui.applyToAllButton.clicked.connect(self._on_apply_bg_to_all)
        self.ui.signalOffsetCombo.currentTextChanged.connect(self._refresh_plot)
        self.ui.signalOffsetParamsEdit.textChanged.connect(self._refresh_plot)
        self.ui.refOffsetCombo.currentTextChanged.connect(self._refresh_plot)
        self.ui.refOffsetParamsEdit.textChanged.connect(self._refresh_plot)
        self.ui.processAllButton.clicked.connect(self._on_process_all)
        self.ui.bgCorrectionGroupBox.toggled.connect(lambda _: self._refresh_plot())
        self.ui.reviewReferencesButton.clicked.connect(self._on_review_references)
        self.ui.processSelectedButton.clicked.connect(self._on_process_selected)

        # despike panel
        self._despike_window_spin.valueChanged.connect(self._on_despike_params_changed)
        self._despike_threshold_spin.valueChanged.connect(self._on_despike_params_changed)
        self._despike_apply_set_btn.clicked.connect(self._on_apply_despike_to_set)
        self._despike_apply_all_btn.clicked.connect(self._on_apply_despike_to_all)
        self._despike_component_combo.currentIndexChanged.connect(
            self._on_despike_component_changed
        )

    # def _setup_collapsible_groupbox(self):
    #     """Make bgCorrectionGroupBox collapse when unchecked rather than
    #     just disabling its contents."""
    #     gb = self.ui.bgCorrectionGroupBox
    #     # initial state — collapsed since checked=False in Designer
    #     self._set_groupbox_collapsed(gb, not gb.isChecked())
    #     gb.toggled.connect(lambda checked: self._set_groupbox_collapsed(gb, not checked))

    @staticmethod
    def _set_groupbox_collapsed(groupbox, collapsed: bool):
        """Show/hide all direct children and let the groupbox shrink."""
        for child in groupbox.findChildren(
            __import__("PySide6.QtWidgets", fromlist=["QWidget"]).QWidget,
            options=__import__("PySide6.QtCore", fromlist=["Qt"]).Qt.FindChildOption.FindDirectChildrenOnly
        ):
            child.setVisible(not collapsed)

        if collapsed:
            groupbox.setMaximumHeight(groupbox.sizeHint().height())
            groupbox.setSizePolicy(
                __import__("PySide6.QtWidgets", fromlist=["QSizePolicy"]).QSizePolicy.Policy.Preferred,
                __import__("PySide6.QtWidgets", fromlist=["QSizePolicy"]).QSizePolicy.Policy.Fixed,
            )
        else:
            groupbox.setMaximumHeight(16777215)  # Qt's QWIDGETSIZE_MAX
            groupbox.setSizePolicy(
                __import__("PySide6.QtWidgets", fromlist=["QSizePolicy"]).QSizePolicy.Policy.Preferred,
                __import__("PySide6.QtWidgets", fromlist=["QSizePolicy"]).QSizePolicy.Policy.Preferred,
            )

    # ── Public API ────────────────────────────────────────────────────────────

    def set_matched_sets(self, matched_sets: list):
        self._matched_sets = matched_sets
        self._cache.clear()
        self._despike_configs.clear()
        self._populate_list()

    def get_upconversion_wavelength(self) -> float:
        return self.ui.upconversionSpinBox.value()

    # ── List ──────────────────────────────────────────────────────────────────

    def _populate_list(self):
        self.ui.matchedSetsListWidget.clear()
        for i, m in enumerate(self._matched_sets):
            complete = m.is_complete()
            name = m.signal.path.name if m.signal else f"Set {i + 1}"
            item = QListWidgetItem(f"{'✓' if complete else '✗'} {name}")
            item.setForeground(
                Qt.GlobalColor.darkGreen if complete else Qt.GlobalColor.red
            )
            self.ui.matchedSetsListWidget.addItem(item)

    def _on_set_selected(self, row: int):
        if row < 0 or row >= len(self._matched_sets):
            self.ui.setStatusLabel.setText("")
            return
        m = self._matched_sets[row]
        def name(f): return f.path.name if f else "—"
        self.ui.setStatusLabel.setText(
            f"Signal:  {name(m.signal)}\n"
            f"BG:      {name(m.background)}\n"
            f"Ref:     {name(m.reference)}\n"
            f"Ref BG:  {name(m.reference_background)}"
        )
        # load this set's despike config into the panel
        cfg = self._get_despike_cfg(row, self._current_component())
        self._despike_window_spin.blockSignals(True)
        self._despike_threshold_spin.blockSignals(True)
        self._despike_window_spin.setValue(cfg["window"])
        self._despike_threshold_spin.setValue(cfg["threshold"])
        self._despike_window_spin.blockSignals(False)
        self._despike_threshold_spin.blockSignals(False)
        self._refresh_plot()

    def _on_view_changed(self, single: bool):
        self.ui.matchedSetsListWidget.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection if single
            else QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self._refresh_plot()

    # ── Step selector ─────────────────────────────────────────────────────────

    def _on_step_changed(self):
        is_despike = self.ui.despikedStepRadio.isChecked()
        self._despike_frame.setVisible(is_despike)
        self._refresh_plot()

    def _current_step(self) -> str:
        for radio, name in [
            (self.ui.rawStepRadio, "raw"),
            (self.ui.despikedStepRadio, "despiked"),
            (self.ui.averagedStepRadio, "averaged"),
            (self.ui.bgSubtractedStepRadio, "bg_subtracted"),
            (self.ui.normalizedStepRadio, "normalized"),
        ]:
            if radio.isChecked():
                return name
        return "raw"

    # ── Despike panel ─────────────────────────────────────────────────────────

    def _get_despike_cfg(self, idx: int, component: str) -> dict:
        return self._despike_configs.get(idx, {}).get(component, DEFAULT_DESPIKE.copy())

    def _set_despike_cfg(self, idx: int, component: str, cfg: dict):
        if idx not in self._despike_configs:
            self._despike_configs[idx] = {}
        self._despike_configs[idx][component] = cfg.copy()

    def _current_component(self) -> str:
        return self._despike_component_combo.currentData()

    def _current_despike_config(self) -> dict:
        return {
            "window": self._despike_window_spin.value(),
            "threshold": self._despike_threshold_spin.value(),
        }

    def _on_despike_params_changed(self):
        row = self.ui.matchedSetsListWidget.currentRow()
        if row >= 0:
            component = self._current_component()
            # save FIRST so _get_step uses new values when it recomputes
            self._set_despike_cfg(row, component, self._current_despike_config())
            self._invalidate_component_cache([row], component)
        self._refresh_plot()

    def _on_apply_despike_to_set(self):
        row = self.ui.matchedSetsListWidget.currentRow()
        if row >= 0:
            component = self._current_component()
            self._set_despike_cfg(row, component, self._current_despike_config())
            self._invalidate_component_cache([row], component)
            self._refresh_plot()

    def _on_apply_despike_to_all(self):
        cfg = self._current_despike_config()
        component = self._current_component()
        for i in range(len(self._matched_sets)):
            self._set_despike_cfg(i, component, cfg)
        self._invalidate_component_cache(
            list(range(len(self._matched_sets))), component
        )
        self._refresh_plot()

    def _invalidate_component_cache(self, indices: list[int], component: str):
        """Invalidate only the cache entries affected by one component's despike change."""
        keys = COMPONENT_CACHE_KEYS.get(component, [])
        for idx in indices:
            c = self._cache.get(idx, {})
            for key in keys:
                c.pop(key, None)

    # keep old _invalidate_despike_cache for full reset (used in set_matched_sets)
    def _invalidate_despike_cache(self, indices: list[int]):
        for idx in indices:
            self._cache.pop(idx, None)

    def _update_despike_status(self, total_spikes: int, n_frames: int):
        if total_spikes == 0:
            self._despike_status_label.setText("✓ No spikes detected.")
            self._despike_status_label.setStyleSheet("color: green;")
        else:
            self._despike_status_label.setText(
                f"⚠ {total_spikes} spike(s) detected across {n_frames} frame(s)."
            )
            self._despike_status_label.setStyleSheet("color: darkorange;")

    def _on_despike_component_changed(self):
        """Load params for newly selected component, replot with its spike markers."""
        row = self.ui.matchedSetsListWidget.currentRow()
        if row < 0:
            return
        cfg = self._get_despike_cfg(row, self._current_component())
        self._despike_window_spin.blockSignals(True)
        self._despike_threshold_spin.blockSignals(True)
        self._despike_window_spin.setValue(cfg["window"])
        self._despike_threshold_spin.setValue(cfg["threshold"])
        self._despike_window_spin.blockSignals(False)
        self._despike_threshold_spin.blockSignals(False)
        self._refresh_plot()

    # ── Plot ──────────────────────────────────────────────────────────────────

    def _refresh_plot(self):
        self.plot_widget.clear()
        step = self._current_step()
        is_single = self.ui.singleViewRadio.isChecked()

        indices = (
            [self.ui.matchedSetsListWidget.currentRow()]
            if is_single
            else [i.row() for i in self.ui.matchedSetsListWidget.selectedIndexes()]
        )
        indices = [i for i in indices if 0 <= i < len(self._matched_sets)]
        if not indices:
            return

        total_spikes = 0
        spike_frames = 0

        for idx in indices:
            spikes, frames = self._plot_set(idx, step, label_prefix=not is_single)
            total_spikes += spikes
            spike_frames += frames

        if step == "despiked":
            self._update_despike_status(total_spikes, spike_frames)

        self.plot_widget.set_labels(
            xlabel="Wavenumber (cm⁻¹)" if step == "normalized" else "Wavelength (nm)",
            ylabel="Intensity",
            title=step.replace("_", " ").title(),
        )

    def _plot_set(self, idx: int, step: str, label_prefix: bool = False) -> tuple[int, int]:
        """Plot one matched set at the given step.
        Returns (total_spikes, spike_frame_count) for the despike status label.
        """
        m = self._matched_sets[idx]
        base = m.signal.path.stem if m.signal else f"Set {idx + 1}"
        bg_base = m.background.path.stem if m.background else None
        x_col = "Wavenumber" if step == "normalized" else "Wavelength"
        total_spikes, spike_frames = 0, 0

        try:
            result = self._get_step(idx, step)
            if result is None:
                return 0, 0

            if step == "raw":
                for fid in result.data["Frame"].unique():
                    fd = result.frame(fid)
                    label = f"{base} F{fid}" if label_prefix else f"Frame {fid}"
                    self.plot_widget.plot(
                        fd["Wavelength"].to_numpy(),
                        fd["Intensity"].to_numpy(),
                        label=label, alpha=0.8,
                    )

            elif step == "despiked":
                component = self._current_component()
                component_label = COMPONENT_LABELS[component]

                # pick raw and despiked source for selected component
                raw_source = {
                    "signal":         m.signal,
                    "background":     m.background,
                    "reference":      m.reference,
                    "ref_background": m.reference_background,
                }.get(component)

                cache_key = {
                    "signal":         "despiked_signal",
                    "background":     "despiked_bg",
                    "reference":      "despiked_ref",
                    "ref_background": "despiked_ref_bg",
                }.get(component)

                if raw_source is None:
                    self._despike_status_label.setText(
                        f"⚠ No {component_label} file in this set."
                    )
                    self._despike_status_label.setStyleSheet("color: gray;")
                    return 0, 0

                # ensure cache populated
                self._get_step(idx, "despiked")
                despiked_source = self._cache.get(idx, {}).get(cache_key)
                cfg = self._get_despike_cfg(idx, component)

                for fid in raw_source.data["Frame"].unique():
                    fd_raw = raw_source.frame(fid)
                    wl = fd_raw["Wavelength"].to_numpy()
                    intensity_raw = fd_raw["Intensity"].to_numpy()
                    frame_label = (f"{base} {component_label} F{fid}"
                                if label_prefix else f"{component_label} F{fid}")

                    self.plot_widget.plot(
                        wl, intensity_raw,
                        label=f"{frame_label} (raw)",
                        alpha=0.3, linestyle="--",
                    )

                    mask = detect_spikes(
                        intensity_raw,
                        window=cfg["window"],
                        threshold_factor=cfg["threshold"],
                    )
                    n_spikes = int(mask.sum())
                    if n_spikes > 0:
                        total_spikes += n_spikes
                        spike_frames += 1
                        self.plot_widget.ax.scatter(
                            wl[mask], intensity_raw[mask],
                            color="red", marker="x", s=80, zorder=5,
                            label=f"{frame_label} spikes",
                        )

                    if despiked_source is not None:
                        fd_clean = despiked_source.frame(fid)
                        self.plot_widget.plot(
                            fd_clean["Wavelength"].to_numpy(),
                            fd_clean["Intensity"].to_numpy(),
                            label=frame_label, alpha=0.9,
                        )

            elif step == "averaged":
                fd = result.frame(1)
                label = f"{base} (avg)" if label_prefix else "Signal (avg)"
                self.plot_widget.plot(
                    fd["Wavelength"].to_numpy(),
                    fd["Intensity"].to_numpy(),
                    label=label,
                )
                bg_avg = self._get_adjusted_bg_avg(idx)
                if bg_avg is not None:
                    fd_bg = bg_avg.frame(1)
                    label_bg = (f"{bg_base} (BG avg)"
                                if label_prefix else "Background (avg)")
                    self.plot_widget.plot(
                        fd_bg["Wavelength"].to_numpy(),
                        fd_bg["Intensity"].to_numpy(),
                        label=label_bg, linestyle="--", alpha=0.7,
                    )

            elif step in ("bg_subtracted", "normalized"):
                fd = result.frame(1)
                self.plot_widget.plot(
                    fd[x_col].to_numpy(),
                    fd["Intensity"].to_numpy(),
                    label=base if label_prefix else None,
                )

        except Exception as e:
            logger.warning("Could not plot set %d step '%s': %s", idx, step, e, exc_info=True)
            return 0, 0

        self.plot_widget.canvas.draw()
        return total_spikes, spike_frames

    # ── Pipeline / cache ──────────────────────────────────────────────────────

    def _get_step(self, idx: int, step: str):
        if idx not in self._cache:
            self._cache[idx] = {}
        c = self._cache[idx]
        m = self._matched_sets[idx]
        cfg = self._despike_configs.get(idx, DEFAULT_DESPIKE)

        if step == "raw":
            return m.signal

        if step == "despiked":
            cfg_sig = self._get_despike_cfg(idx, "signal")
            cfg_bg  = self._get_despike_cfg(idx, "background")
            cfg_ref = self._get_despike_cfg(idx, "reference")
            cfg_rbg = self._get_despike_cfg(idx, "ref_background")

            if "despiked_signal" not in c:
                c["despiked_signal"] = m.signal.remove_cosmic_rays(
                    window=cfg_sig["window"],
                    threshold_factor=cfg_sig["threshold"],
                )
            if m.background and "despiked_bg" not in c:
                c["despiked_bg"] = m.background.remove_cosmic_rays(
                    window=cfg_bg["window"],
                    threshold_factor=cfg_bg["threshold"],
                )
            if m.reference and "despiked_ref" not in c:
                c["despiked_ref"] = m.reference.remove_cosmic_rays(
                    window=cfg_ref["window"],
                    threshold_factor=cfg_ref["threshold"],
                )
            if m.reference_background and "despiked_ref_bg" not in c:
                c["despiked_ref_bg"] = m.reference_background.remove_cosmic_rays(
                    window=cfg_rbg["window"],
                    threshold_factor=cfg_rbg["threshold"],
                )
            return c["despiked_signal"]

        if step == "averaged":
            self._get_step(idx, "despiked")
            if "averaged_signal" not in c:
                c["averaged_signal"] = c["despiked_signal"].average_spectrum()
            return c["averaged_signal"]

        if step == "bg_subtracted":
            self._get_step(idx, "averaged")
            sig_offset, ref_offset = self._current_offsets()
            if (c.get("_sig_offset") != sig_offset or
                    c.get("_ref_offset") != ref_offset):
                c.pop("bg_subtracted", None)
                c.pop("normalized", None)
            if "bg_subtracted" not in c:
                if not m.background:
                    return c.get("averaged_signal")
                bg_avg = c.get("despiked_bg", m.background).average_spectrum()
                c["bg_subtracted"] = subtract_background(
                    c["averaged_signal"], bg_avg, offset=sig_offset,
                )
                c["_sig_offset"] = sig_offset
                c["_ref_offset"] = ref_offset
            return c["bg_subtracted"]

        if step == "normalized":
            self._get_step(idx, "bg_subtracted")
            wl = self.ui.upconversionSpinBox.value()
            if "normalized" not in c or c.get("_upconversion_wl") != wl:
                bg_sub = c.get("bg_subtracted") or c.get("averaged_signal")
                if not bg_sub or not m.reference:
                    return bg_sub
                ref = c.get("despiked_ref", m.reference).average_spectrum()
                _, ref_offset = self._current_offsets()
                if m.reference_background:
                    ref_bg = c.get("despiked_ref_bg",
                                   m.reference_background).average_spectrum()
                    ref = subtract_background(ref, ref_bg, offset=ref_offset)
                c["normalized"] = normalize(bg_sub, ref).upconvert_to_wavenumber(wl)
                c["_upconversion_wl"] = wl
            return c["normalized"]

        return None

    def _current_offsets(self):
        if not self.ui.bgCorrectionGroupBox.isChecked():
            return None, None
        return (
            _parse_offset(
                self.ui.signalOffsetCombo.currentText(),
                self.ui.signalOffsetParamsEdit.text(),
            ),
            _parse_offset(
                self.ui.refOffsetCombo.currentText(),
                self.ui.refOffsetParamsEdit.text(),
            ),
        )

    def _get_bg_for_step(self, idx: int, step: str):
        c = self._cache.get(idx, {})
        m = self._matched_sets[idx]
        if not m.background:
            return None
        if step == "raw":
            return m.background
        if step == "despiked":
            self._get_step(idx, "despiked")
            return self._cache.get(idx, {}).get("despiked_bg")
        return None

    def _get_adjusted_bg_avg(self, idx: int):
        from sfg_app2.processing.baseline import apply_offset
        m = self._matched_sets[idx]
        if not m.background:
            return None
        c = self._cache.get(idx, {})
        self._get_step(idx, "despiked")
        bg_despiked = c.get("despiked_bg", m.background)
        bg_avg = bg_despiked.average_spectrum()
        sig_offset, _ = self._current_offsets()
        if sig_offset is not None:
            return apply_offset(bg_avg, sig_offset)
        return bg_avg

    # ── BG correction ─────────────────────────────────────────────────────────

    def _invalidate_bg_cache(self, indices: list[int]):
        for idx in indices:
            entry = self._cache.get(idx, {})
            for key in ("bg_subtracted", "normalized",
                        "_sig_offset", "_ref_offset"):
                entry.pop(key, None)

    def _on_apply_bg_to_set(self):
        row = self.ui.matchedSetsListWidget.currentRow()
        if row >= 0:
            self._invalidate_bg_cache([row])
            self._refresh_plot()

    def _on_apply_bg_to_all(self):
        self._invalidate_bg_cache(list(range(len(self._matched_sets))))
        self._refresh_plot()

    # ── Upconversion ──────────────────────────────────────────────────────────

    def _on_upconversion_changed(self):
        if self._current_step() == "normalized":
            self._refresh_plot()

    # ── Calibration ───────────────────────────────────────────────────────────

    def _on_calibrate(self):
        from sfg_app2.app.dialogs.polystyrene_calibration_dialog import (
            PolystyreneCalibrationDialog
        )
        if not self._matched_sets:
            QMessageBox.information(self, "No data", "Load and match files first.")
            return
        dialog = PolystyreneCalibrationDialog(
            matched_sets=self._matched_sets,
            initial_wavelength=self.ui.upconversionSpinBox.value(),
            parent=self,
        )
        if dialog.exec():
            self.ui.upconversionSpinBox.setValue(dialog.result_wavelength)

    # ── Reference review ──────────────────────────────────────────────────────

    def _on_review_references(self):
        if not self._matched_sets:
            QMessageBox.information(self, "No data", "No matched sets loaded.")
            return
        from sfg_app2.app.dialogs.reference_review_dialog import ReferenceReviewDialog
        dialog = ReferenceReviewDialog(
            matched_sets=self._matched_sets,
            parent=self,
        )
        dialog.exec()

    # ── Process all ───────────────────────────────────────────────────────────

    def _on_process_selected(self):
        selected_rows = [
            self.ui.matchedSetsListWidget.row(item)
            for item in self.ui.matchedSetsListWidget.selectedItems()
        ]
        if not selected_rows:
            QMessageBox.information(
                self, "Nothing selected",
                "Select one or more sets from the list first."
            )
            return
        selected_sets = [self._matched_sets[i] for i in selected_rows
                        if i < len(self._matched_sets)]
        self._run_processing(selected_sets, selected_rows)

    def _on_process_all(self):
        self._run_processing(
            self._matched_sets,
            list(range(len(self._matched_sets)))
        )

    def _run_processing(self, sets: list, indices: list[int]):
        """Shared processing logic for both process-selected and process-all."""
        from sfg_app2.processing.pipeline import PipelineConfig, process_batch
        sig_offset, ref_offset = self._current_offsets()
        wl = self.ui.upconversionSpinBox.value()

        configs = {}
        for i in indices:
            m = self._matched_sets[i]
            if not m.signal:
                continue
            cfg_sig = self._get_despike_cfg(i, "signal")
            configs[m.signal.path.name] = PipelineConfig(
                run_despike=True,
                despike_window=cfg_sig["window"],
                despike_threshold=cfg_sig["threshold"],
                run_background=True,
                bg_offset=sig_offset,
                ref_bg_offset=ref_offset,
                run_normalize=True,
                run_upconvert=True,
                upconversion_wavelength=wl,
            )

        default_cfg = PipelineConfig(
            run_despike=True,
            despike_window=DEFAULT_DESPIKE["window"],
            despike_threshold=DEFAULT_DESPIKE["threshold"],
            run_background=True,
            bg_offset=sig_offset,
            ref_bg_offset=ref_offset,
            run_normalize=True,
            run_upconvert=True,
            upconversion_wavelength=wl,
        )

        try:
            results = process_batch(sets, default_cfg, configs)
            self.processing_complete.emit(results)
            QMessageBox.information(
                self, "Processing complete",
                f"{len(results)}/{len(sets)} set(s) processed successfully.",
            )
        except Exception as e:
            QMessageBox.critical(self, "Processing error", str(e))
            logger.error("Processing failed: %s", e)