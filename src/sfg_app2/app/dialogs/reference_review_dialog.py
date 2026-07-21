from __future__ import annotations
import logging

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QDialogButtonBox, QCheckBox, QScrollArea, QWidget
)
from PySide6.QtCore import Qt

from sfg_app2.app.widgets.spectrum_plot_widget import SpectrumPlotWidget

logger = logging.getLogger(__name__)


class ReferenceReviewDialog(QDialog):
    """Plot all references and their backgrounds together for review."""

    def __init__(self, matched_sets: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Reference Review")
        self.resize(900, 600)
        self._matched_sets = matched_sets
        self._checkboxes: list[tuple[QCheckBox, QCheckBox]] = []  # (ref_cb, ref_bg_cb)
        self._build_ui()
        self._refresh_plot()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # visibility controls — one row per unique reference
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMaximumHeight(130)
        inner = QWidget()
        controls_layout = QVBoxLayout(inner)
        controls_layout.setSpacing(2)

        seen_refs: set[str] = set()
        for i, m in enumerate(self._matched_sets):
            ref = m.reference
            ref_bg = m.reference_background
            if ref is None:
                self._checkboxes.append((None, None))
                continue

            ref_key = str(ref.path)
            # only add controls once per unique reference file
            if ref_key in seen_refs:
                self._checkboxes.append((None, None))
                continue
            seen_refs.add(ref_key)

            row = QHBoxLayout()
            row.addWidget(QLabel(ref.path.name + ":"))

            ref_cb = QCheckBox("Reference")
            ref_cb.setChecked(True)
            ref_cb.stateChanged.connect(self._refresh_plot)
            row.addWidget(ref_cb)

            ref_bg_cb = QCheckBox("Ref BG") if ref_bg else None
            if ref_bg_cb:
                ref_bg_cb.setChecked(True)
                ref_bg_cb.stateChanged.connect(self._refresh_plot)
                row.addWidget(ref_bg_cb)

            row.addStretch()
            controls_layout.addLayout(row)
            self._checkboxes.append((ref_cb, ref_bg_cb))

        controls_layout.addStretch()
        scroll.setWidget(inner)
        layout.addWidget(scroll)

        # plot
        self.plot_widget = SpectrumPlotWidget()
        layout.addWidget(self.plot_widget)

        # close button
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # ── Plot ──────────────────────────────────────────────────────────────────

    def _refresh_plot(self):
        self.plot_widget.clear()
        seen_refs: set[str] = set()
        cb_iter = iter(self._checkboxes)

        for m in self._matched_sets:
            ref_cb, ref_bg_cb = next(cb_iter)
            ref = m.reference
            ref_bg = m.reference_background

            if ref is None:
                continue

            ref_key = str(ref.path)
            if ref_key in seen_refs:
                continue
            seen_refs.add(ref_key)

            if ref_cb and ref_cb.isChecked():
                try:
                    avg = ref.average_spectrum().frame(1)
                    self.plot_widget.plot(
                        avg["Wavelength"].to_numpy(),
                        avg["Intensity"].to_numpy(),
                        label=ref.path.name,
                    )
                except Exception as e:
                    logger.warning("Could not plot reference %s: %s", ref.path.name, e)

            if ref_bg and ref_bg_cb and ref_bg_cb.isChecked():
                try:
                    avg_bg = ref_bg.average_spectrum().frame(1)
                    self.plot_widget.plot(
                        avg_bg["Wavelength"].to_numpy(),
                        avg_bg["Intensity"].to_numpy(),
                        label=f"{ref_bg.path.name} (BG)",
                        linestyle="--", alpha=0.7,
                    )
                except Exception as e:
                    logger.warning("Could not plot ref BG %s: %s", ref_bg.path.name, e)

        self.plot_widget.set_labels(
            xlabel="Wavelength (nm)",
            ylabel="Intensity",
            title="Reference & Reference Background Review",
        )