from __future__ import annotations
import logging

import matplotlib.pyplot as plt
from PySide6.QtCore import Signal, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QGroupBox, QPushButton, QRadioButton, QButtonGroup,
    QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit,
    QFrame, QSizePolicy, QGridLayout, QMessageBox,
)

from sfg_app2.app.widgets.spectrum_plot_widget import SpectrumPlotWidget
from sfg_app2.app.widgets.collapsible_group_box import make_collapsible
from sfg_app2.processing.baseline import subtract_background
from sfg_app2.processing.normalization import normalize

logger = logging.getLogger(__name__)

DEFAULT_DESPIKE = {"window": 20, "threshold": 500.0}

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
    "reference":      ["despiked_ref", "averaged_ref", "normalized"],
    "ref_background": ["despiked_ref_bg", "averaged_ref_bg", "normalized"],
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


def _colors(n: int) -> list:
    prop_cycle = plt.rcParams["axes.prop_cycle"]
    colors = [p["color"] for p in prop_cycle]
    return [colors[i % len(colors)] for i in range(max(n, 1))]


class HomodynePanel(QWidget):
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
        main_layout.addWidget(self.plot_widget)

        self._param_sections: dict[str, QGroupBox] = {}
        self._param_sections["despike"] = self._build_despike_section()
        self._param_sections["bg_offset"] = self._build_bg_offset_section()
        for gb in self._param_sections.values():
            make_collapsible(gb)
            gb.setVisible(False)
            main_layout.addWidget(gb)

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

        for w in [self._pair_label, self._pair_combo,
                  self._source_label, self._source_combo]:
            layout.addWidget(w)
        layout.addStretch()

        self._process_btn = QPushButton("▶ Process")
        self._process_btn.setToolTip(
            "Run the full pipeline from scratch for the selected set(s)"
        )
        layout.addWidget(self._process_btn)

        self._finish_btn = QPushButton("✓ Send to Results")
        self._finish_btn.setVisible(False)
        layout.addWidget(self._finish_btn)

        return frame

    def _build_despike_section(self) -> QGroupBox:
        gb = QGroupBox("Despike parameters")
        gb.setCheckable(True)
        grid = QGridLayout(gb)

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

        return gb

    def _build_bg_offset_section(self) -> QGroupBox:
        gb = QGroupBox("Background Correction")
        gb.setCheckable(True)
        gb.setChecked(False)
        layout = QGridLayout(gb)

        layout.addWidget(QLabel("Signal BG offset:"), 0, 0)
        self._sig_offset_combo = QComboBox()
        self._sig_offset_combo.addItems(["None", "Constant", "Linear", "Polynomial"])
        layout.addWidget(self._sig_offset_combo, 0, 1)
        self._sig_offset_params = QLineEdit("0")
        layout.addWidget(self._sig_offset_params, 0, 2)

        layout.addWidget(QLabel("Ref BG offset:"), 1, 0)
        self._ref_offset_combo = QComboBox()
        self._ref_offset_combo.addItems(["None", "Constant", "Linear", "Polynomial"])
        layout.addWidget(self._ref_offset_combo, 1, 1)
        self._ref_offset_params = QLineEdit("0")
        layout.addWidget(self._ref_offset_params, 1, 2)

        self._sig_offset_params.setEnabled(False)
        self._ref_offset_params.setEnabled(False)

        self._bg_group = gb
        return gb

    # ── Signal wiring ─────────────────────────────────────────────────────────

    def _connect_signals(self):
        for rb in self._step_radios.values():
            rb.toggled.connect(lambda checked: self._on_step_changed() if checked else None)

        self._pair_combo.currentIndexChanged.connect(self._refresh_plot)
        self._source_combo.currentIndexChanged.connect(self._refresh_plot)

        for key in COMPONENTS:
            self._despike_widgets[key]["window"].valueChanged.connect(
                lambda _v, k=key: self._on_despike_changed(k)
            )
            self._despike_widgets[key]["threshold"].valueChanged.connect(
                lambda _v, k=key: self._on_despike_changed(k)
            )

        self._sig_offset_combo.currentTextChanged.connect(
            lambda t: self._sig_offset_params.setEnabled(t != "None")
        )
        self._ref_offset_combo.currentTextChanged.connect(
            lambda t: self._ref_offset_params.setEnabled(t != "None")
        )
        for w in (self._sig_offset_combo, self._ref_offset_combo):
            w.currentTextChanged.connect(self._on_bg_offset_changed)
        for w in (self._sig_offset_params, self._ref_offset_params):
            w.textChanged.connect(self._on_bg_offset_changed)
        self._bg_group.toggled.connect(lambda _checked: self._on_bg_offset_changed())

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
        show_combos = step in ("raw", "despiked", "averaged")
        self._pair_label.setVisible(show_combos)
        self._pair_combo.setVisible(show_combos)
        self._source_label.setVisible(show_combos)
        self._source_combo.setVisible(show_combos)

        self._process_btn.setVisible(step != "normalized")
        self._finish_btn.setVisible(step == "normalized")

        section_key = STEP_SECTION.get(step)
        for key, gb in self._param_sections.items():
            gb.setVisible(key == section_key)
        if section_key == "despike":
            # auto-expand despike on entry; bg_offset's checked state is left
            # alone since it doubles as "actually apply this correction"
            self._param_sections["despike"].setChecked(True)

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

    # ── Background offset ────────────────────────────────────────────────────

    def _current_offsets(self):
        if not self._bg_group.isChecked():
            return None, None
        return (
            _parse_offset(
                self._sig_offset_combo.currentText(), self._sig_offset_params.text()
            ),
            _parse_offset(
                self._ref_offset_combo.currentText(), self._ref_offset_params.text()
            ),
        )

    def _on_bg_offset_changed(self):
        for idx in range(len(self._matched_sets)):
            c = self._cache.get(idx, {})
            for key in ("bg_subtracted", "normalized", "_sig_offset", "_ref_offset"):
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
                c["averaged_signal"] = c["despiked_signal"].average_spectrum()
            if "despiked_bg" in c and "averaged_bg" not in c:
                c["averaged_bg"] = c["despiked_bg"].average_spectrum()
            if "despiked_ref" in c and "averaged_ref" not in c:
                c["averaged_ref"] = c["despiked_ref"].average_spectrum()
            if "despiked_ref_bg" in c and "averaged_ref_bg" not in c:
                c["averaged_ref_bg"] = c["despiked_ref_bg"].average_spectrum()
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
                    c["bg_subtracted"] = c.get("averaged_signal")
                else:
                    bg_avg = c.get("averaged_bg") or m.background.average_spectrum()
                    c["bg_subtracted"] = subtract_background(
                        c["averaged_signal"], bg_avg, offset=sig_offset,
                    )
                c["_sig_offset"] = sig_offset
                c["_ref_offset"] = ref_offset
            return c["bg_subtracted"]

        if step == "normalized":
            self._get_step(idx, "bg_subtracted")
            wl = self._upconversion_wl()
            if "normalized" not in c or c.get("_upconversion_wl") != wl:
                bg_sub = c.get("bg_subtracted") or c.get("averaged_signal")
                if not bg_sub or not m.reference:
                    return bg_sub
                ref = c.get("averaged_ref") or m.reference.average_spectrum()
                _, ref_offset = self._current_offsets()
                if m.reference_background:
                    ref_bg = c.get("averaged_ref_bg") or m.reference_background.average_spectrum()
                    ref = subtract_background(ref, ref_bg, offset=ref_offset)
                c["normalized"] = normalize(bg_sub, ref).upconvert_to_wavenumber(wl)
                c["_upconversion_wl"] = wl
            return c["normalized"]

        return None

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

        if self._selected_indices:
            colors = _colors(len(self._selected_indices))
            for i, idx in enumerate(self._selected_indices):
                try:
                    self._plot_one_set(idx, step, colors[i])
                except Exception as e:
                    logger.warning(
                        "Could not plot set %d step '%s': %s", idx, step, e, exc_info=True,
                    )

        handles, _ = self.plot_widget.ax.get_legend_handles_labels()
        if handles:
            self.plot_widget.ax.legend(fontsize=8)

        xlabel = "Wavenumber (cm$^{-1}$)" if step == "normalized" else "Wavelength (nm)"
        self.plot_widget.set_labels(xlabel=xlabel, ylabel="Intensity", title=STEP_LABELS[step])
        self.plot_widget.sync_x_range()
        self.plot_widget.canvas.draw_idle()

    def _plot_one_set(self, idx: int, step: str, color):
        m = self._matched_sets[idx]
        label = m.signal.path.stem if m.signal else f"Set {idx + 1}"

        if step in ("raw", "despiked", "averaged"):
            self._plot_multi_component(idx, step, label, color)
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
                for fid in data.data["Frame"].unique():
                    fd = data.frame(fid)
                    self.plot_widget.ax.plot(
                        fd["Wavelength"].to_numpy(), fd["Intensity"].to_numpy(),
                        color=color, linestyle=linestyle, alpha=0.85,
                        label=f"{label} — {comp_label} F{fid}",
                    )

    # ── Process / Send to Results ────────────────────────────────────────────

    def _on_process(self):
        if not self._selected_indices:
            QMessageBox.information(
                self, "Nothing selected", "Select one or more matched sets first."
            )
            return

        errors = []
        for idx in self._selected_indices:
            self._cache.pop(idx, None)
            try:
                self._get_step(idx, "normalized")
            except Exception as e:
                name = self._matched_sets[idx].signal.path.name \
                    if self._matched_sets[idx].signal else f"Set {idx + 1}"
                errors.append(f"{name}: {e}")
                logger.error("Processing failed for set %d: %s", idx, e, exc_info=True)

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

    def set_matched_sets(self, matched_sets: list):
        self._matched_sets = matched_sets
        self._cache.clear()
        self._despike_configs.clear()
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
        self._recompute_and_refresh()

    def reset(self):
        self._matched_sets = []
        self._cache.clear()
        self._despike_configs.clear()
        self._selected_indices = []
        self.plot_widget.full_clear()
        self.plot_widget.canvas.draw_idle()
