from __future__ import annotations
import logging

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QListWidgetItem, QMessageBox,
    QButtonGroup, QAbstractItemView, QSizePolicy
)

from sfg_app2.app.ui.ui_process_review_tab import Ui_Form
from sfg_app2.app.widgets.spectrum_plot_widget import SpectrumPlotWidget
from sfg_app2.processing.baseline import subtract_background
from sfg_app2.processing.normalization import normalize

logger = logging.getLogger(__name__)


def _parse_offset(combo_text: str, params_text: str):
    """Convert combo selection + params string into an OffsetSpec."""
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

        # fix calibration frame vertical expansion
        self.ui.calibrationFrame.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )

        self._matched_sets: list = []
        self._cache: dict[int, dict] = {}

        self._setup_plot()
        self._setup_button_groups()
        self._setup_bg_correction()
        self._connect_signals()

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

    def _connect_signals(self):
        self.ui.matchedSetsListWidget.currentRowChanged.connect(self._on_set_selected)
        self.ui.matchedSetsListWidget.itemSelectionChanged.connect(self._refresh_plot)
        self.ui.singleViewRadio.toggled.connect(self._on_view_changed)
        self._step_group.buttonToggled.connect(
            lambda btn, checked: self._refresh_plot() if checked else None
        )
        self.ui.upconversionSpinBox.valueChanged.connect(self._on_upconversion_changed)
        self.ui.calibrateButton.clicked.connect(self._on_calibrate)
        self.ui.applyToSetButton.clicked.connect(self._on_apply_to_set)
        self.ui.applyToAllButton.clicked.connect(self._on_apply_to_all)
        self.ui.processAllButton.clicked.connect(self._on_process_all)
        self.ui.bgCorrectionGroupBox.toggled.connect(lambda _: self._refresh_plot())
        self.ui.reviewReferencesButton.clicked.connect(self._on_review_references)
        self.ui.signalOffsetCombo.currentTextChanged.connect(self._refresh_plot)
        self.ui.signalOffsetParamsEdit.textChanged.connect(self._refresh_plot)
        self.ui.refOffsetCombo.currentTextChanged.connect(self._refresh_plot)
        self.ui.refOffsetParamsEdit.textChanged.connect(self._refresh_plot)

    # ── Public API ─────────────────────────────────────────────────────────────

    def set_matched_sets(self, matched_sets: list):
        self._matched_sets = matched_sets
        self._cache.clear()
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
        self._refresh_plot()

    def _on_view_changed(self, single: bool):
        self.ui.matchedSetsListWidget.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection if single
            else QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self._refresh_plot()

    # ── Plot ──────────────────────────────────────────────────────────────────

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

        for idx in indices:
            self._plot_set(idx, step, label_prefix=not is_single)

        self.plot_widget.set_labels(
            xlabel="Wavenumber (cm⁻¹)" if step == "normalized" else "Wavelength (nm)",
            ylabel="Intensity",
            title=step.replace("_", " ").title(),
        )

    def _plot_set(self, idx: int, step: str, label_prefix: bool = False):
        m = self._matched_sets[idx]
        base = m.signal.path.stem if m.signal else f"Set {idx + 1}"
        bg_base = m.background.path.stem if m.background else None
        x_col = "Wavenumber" if step == "normalized" else "Wavelength"

        try:
            result = self._get_step(idx, step)
            if result is None:
                return

            if step in ("raw", "despiked", "averaged"):
                if step in ("raw", "despiked"):
                    # plot each frame of signal
                    for fid in result.data["Frame"].unique():
                        fd = result.frame(fid)
                        label = f"{base} F{fid}" if label_prefix else f"Frame {fid}"
                        self.plot_widget.plot(
                            fd["Wavelength"].to_numpy(),
                            fd["Intensity"].to_numpy(),
                            label=label, alpha=0.8,
                        )
                    # plot background frames
                    bg_result = self._get_bg_for_step(idx, step)
                    if bg_result is not None:
                        for fid in bg_result.data["Frame"].unique():
                            fd = bg_result.frame(fid)
                            label = (f"{bg_base} F{fid} (BG)"
                                    if label_prefix else f"BG Frame {fid}")
                            self.plot_widget.plot(
                                fd["Wavelength"].to_numpy(),
                                fd["Intensity"].to_numpy(),
                                label=label, linestyle="--", alpha=0.5,
                            )
                else:
                    # averaged — signal
                    fd = result.frame(1)
                    label = f"{base} (avg)" if label_prefix else "Signal (avg)"
                    self.plot_widget.plot(
                        fd["Wavelength"].to_numpy(),
                        fd["Intensity"].to_numpy(),
                        label=label,
                    )
                    # averaged background — with offset applied if correction enabled
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
            logger.warning("Could not plot set %d step '%s': %s", idx, step, e)


    def _get_bg_for_step(self, idx: int, step: str):
        """Return background data at the given step, from cache."""
        c = self._cache.get(idx, {})
        m = self._matched_sets[idx]
        if not m.background:
            return None
        if step == "raw":
            return m.background
        if step == "despiked":
            # ensure despiked cache is populated
            self._get_step(idx, "despiked")
            return self._cache.get(idx, {}).get("despiked_bg")
        return None


    def _get_adjusted_bg_avg(self, idx: int):
        """Return averaged background with offset applied if correction is active."""
        from sfg_app2.processing.baseline import apply_offset
        m = self._matched_sets[idx]
        if not m.background:
            return None
        c = self._cache.get(idx, {})
        # ensure despiked bg exists
        self._get_step(idx, "despiked")
        bg_despiked = c.get("despiked_bg", m.background)
        bg_avg = bg_despiked.average_spectrum()

        sig_offset, _ = self._current_offsets()
        if sig_offset is not None:
            return apply_offset(bg_avg, sig_offset)
        return bg_avg


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

    # ── Pipeline / cache ──────────────────────────────────────────────────────

    def _get_step(self, idx: int, step: str):
        if idx not in self._cache:
            self._cache[idx] = {}
        c = self._cache[idx]
        m = self._matched_sets[idx]

        if step == "raw":
            return m.signal

        if step == "despiked":
            if "despiked_signal" not in c:
                c["despiked_signal"] = m.signal.remove_cosmic_rays()
                if m.background:
                    c["despiked_bg"] = m.background.remove_cosmic_rays()
                if m.reference:
                    c["despiked_ref"] = m.reference.remove_cosmic_rays()
                if m.reference_background:
                    c["despiked_ref_bg"] = m.reference_background.remove_cosmic_rays()
            return c["despiked_signal"]

        if step == "averaged":
            self._get_step(idx, "despiked")
            if "averaged_signal" not in c:
                c["averaged_signal"] = c["despiked_signal"].average_spectrum()
            return c["averaged_signal"]

        if step == "bg_subtracted":
            self._get_step(idx, "averaged")
            sig_offset, ref_offset = self._current_offsets()

            # invalidate if offsets changed since last computation
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
                    ref_bg = c.get("despiked_ref_bg", m.reference_background).average_spectrum()
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

    # ── BG correction handlers ────────────────────────────────────────────────

    def _invalidate_bg_cache(self, indices: list[int]):
        for idx in indices:
            entry = self._cache.get(idx, {})
            for key in ("bg_subtracted", "normalized", "_sig_offset", "_ref_offset"):
                entry.pop(key, None)

    def _on_apply_to_set(self):
        row = self.ui.matchedSetsListWidget.currentRow()
        if row >= 0:
            self._invalidate_bg_cache([row])
            self._refresh_plot()

    def _on_apply_to_all(self):
        self._invalidate_bg_cache(list(range(len(self._matched_sets))))
        self._refresh_plot()

    # ── Upconversion ──────────────────────────────────────────────────────────

    def _on_upconversion_changed(self):
        # normalized cache invalidated lazily in _get_step via _upconversion_wl check
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

    # ── Process all ───────────────────────────────────────────────────────────

    def _on_process_all(self):
        from sfg_app2.processing.pipeline import PipelineConfig, process_batch
        sig_offset, ref_offset = self._current_offsets()
        config = PipelineConfig(
            run_despike=True,
            run_background=True,
            bg_offset=sig_offset,
            ref_bg_offset=ref_offset,
            run_normalize=True,
            run_upconvert=True,
            upconversion_wavelength=self.ui.upconversionSpinBox.value(),
        )
        try:
            results = process_batch(self._matched_sets, config)
            self.processing_complete.emit(results)
            QMessageBox.information(
                self, "Processing complete",
                f"{len(results)} set(s) processed successfully.",
            )
        except Exception as e:
            QMessageBox.critical(self, "Processing error", str(e))
            logger.error("Processing failed: %s", e)