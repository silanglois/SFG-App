from __future__ import annotations
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QTableWidget, QComboBox, QHeaderView,
    QDialogButtonBox,
)

from sfg_app2.processing.fitting import FitModelSpec, get_lineshape

# (display text, stored rule) -- "free" is never stored, it is the
# absence of a rule (see PeakInstance.amplitude_signs).
_RULE_CHOICES = [("free", "free"), ("+", "+"), ("−", "-")]


class SignConstraintsDialog(QDialog):
    """A peaks × polarizations grid of amplitude sign rules (+ / − / free).

    Works on a copy: rules() returns the edited per-peak dicts and the
    caller decides whether anything changed. Rules for polarizations not
    shown as columns are kept untouched, so editing one batch's columns
    never silently drops another set's rules.
    """

    def __init__(self, spec: FitModelSpec, polarizations: list[str], polarization_key: str,
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle("Amplitude sign constraints")
        self._spec = spec
        self._polarizations = list(polarizations)

        layout = QVBoxLayout(self)
        hint = QLabel(
            f"Force the sign of each peak's amplitude per value of "
            f"\"{polarization_key}\". \"+\" keeps the amplitude ≥ 0, \"−\" "
            f"keeps it ≤ 0, \"free\" leaves it unconstrained. Applies to "
            f"every fit of a spectrum with that value: Run fit, Batch "
            f"and Sequential."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self._table = QTableWidget(len(spec.peaks), len(self._polarizations))
        self._table.setHorizontalHeaderLabels(self._polarizations)
        self._table.setVerticalHeaderLabels([self._peak_label(i) for i in range(len(spec.peaks))])
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        for row, peak in enumerate(spec.peaks):
            for col, pol in enumerate(self._polarizations):
                combo = QComboBox()
                for text, rule in _RULE_CHOICES:
                    combo.addItem(text, userData=rule)
                idx = combo.findData(peak.amplitude_signs.get(pol, "free"))
                combo.setCurrentIndex(idx if idx >= 0 else 0)
                self._table.setCellWidget(row, col, combo)
        layout.addWidget(self._table)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        # Sized from the content so every polarization column is visible
        # without a horizontal scrollbar.
        self._table.resizeColumnsToContents()
        columns = sum(max(self._table.columnWidth(c), 80) for c in range(len(self._polarizations)))
        width = self._table.verticalHeader().sizeHint().width() + columns + 60
        height = self._table.horizontalHeader().sizeHint().height() + 34 * len(spec.peaks)
        self.resize(max(width, 360), height + 170)

    def _peak_label(self, i: int) -> str:
        peak = self._spec.peaks[i]
        center = peak.params.get("center")
        if center is None:
            return f"Peak {i + 1} ({get_lineshape(peak.lineshape_key).display_name})"
        return f"Peak {i + 1} @ {center.value:.0f}"

    def set_rule(self, row: int, polarization: str, rule: str):
        """Programmatic edit (tests)."""
        combo = self._table.cellWidget(row, self._polarizations.index(polarization))
        combo.setCurrentIndex(combo.findData(rule))

    def rules(self) -> list[dict[str, str]]:
        """One amplitude_signs dict per peak, in peak order."""
        out = []
        for row, peak in enumerate(self._spec.peaks):
            signs = {pol: rule for pol, rule in peak.amplitude_signs.items()
                     if pol not in self._polarizations}
            for col, pol in enumerate(self._polarizations):
                rule = self._table.cellWidget(row, col).currentData()
                if rule != "free":
                    signs[pol] = rule
            out.append(signs)
        return out
