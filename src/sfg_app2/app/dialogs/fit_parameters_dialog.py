# src/sfg_app2/app/dialogs/fit_parameters_dialog.py
from __future__ import annotations
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget,
    QTableWidgetItem, QPushButton, QLabel, QDialogButtonBox,
    QHeaderView, QApplication,
)
from PySide6.QtCore import Qt

from sfg_app2.processing import provenance as provenance_mod
from sfg_app2.processing.fitting import (
    fit_model_spec_from_provenance_payload, describe_local_params,
)


def _fmt(value, digits: str = "6g") -> str:
    return "N/A" if value is None else f"{value:{digits}}"


class FitParametersDialog(QDialog):
    """Read-only step-through viewer of a fitted Results-tab entry's fit
    parameters (value + error) and fit-quality metrics -- one entry at a
    time, prev/next navigation (mirrors ProcessingParamsDialog's
    structure). `entries` is expected to already be filtered to entries
    that actually carry fit data (non-empty `fit_components`)."""

    def __init__(self, entries: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Fit Parameters")
        self.resize(480, 450)

        self._entries = entries
        self._current = 0

        layout = QVBoxLayout(self)

        self._label = QLabel()
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._label)

        self._quality_label = QLabel()
        self._quality_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._quality_label)

        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels(["Parameter", "Value", "Error"])
        self._table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self._table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self._table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents
        )
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self._table)

        nav_layout = QHBoxLayout()
        self._prev_button = QPushButton("← Previous")
        self._next_button = QPushButton("Next →")
        self._counter_label = QLabel()
        self._counter_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._prev_button.clicked.connect(self._on_prev)
        self._next_button.clicked.connect(self._on_next)
        nav_layout.addWidget(self._prev_button)
        nav_layout.addWidget(self._counter_label)
        nav_layout.addWidget(self._next_button)
        layout.addLayout(nav_layout)

        bottom_layout = QHBoxLayout()
        self._copy_button = QPushButton("Copy to clipboard")
        self._copy_button.clicked.connect(self._on_copy_to_clipboard)
        bottom_layout.addWidget(self._copy_button)
        bottom_layout.addStretch()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.accept)
        bottom_layout.addWidget(buttons)
        layout.addLayout(bottom_layout)

        self._load_current()

    def _on_prev(self):
        self._current = max(0, self._current - 1)
        self._load_current()

    def _on_next(self):
        self._current = min(len(self._entries) - 1, self._current + 1)
        self._load_current()

    def _current_payload(self) -> dict | None:
        entry = self._entries[self._current]
        provenance = getattr(entry.spectrum, "provenance", None) or {}
        return provenance_mod.parse_fit_json(provenance)

    def _load_current(self):
        entry = self._entries[self._current]
        self._label.setText(f"{entry.label}  ({entry.kind})")
        self._counter_label.setText(f"{self._current + 1} / {len(self._entries)}")
        self._prev_button.setEnabled(self._current > 0)
        self._next_button.setEnabled(self._current < len(self._entries) - 1)

        payload = self._current_payload()
        spec = fit_model_spec_from_provenance_payload(payload)

        self._table.setRowCount(0)
        if payload is None or spec is None:
            self._quality_label.setText("No fit parameters found for this entry.")
            self._copy_button.setEnabled(False)
            return
        self._copy_button.setEnabled(True)

        self._quality_label.setText(
            f"redchi = {_fmt(payload.get('redchi'))}   "
            f"R² = {_fmt(payload.get('r_squared'), '.4f')}   "
            f"AIC = {_fmt(payload.get('aic'))}   "
            f"BIC = {_fmt(payload.get('bic'))}   "
            f"weighting = {payload.get('weighting') or 'none'}"
        )

        param_errors = payload.get("param_errors") or {}
        local_values = dict(_local_param_values(spec))
        for row, (local_key, param_label) in enumerate(describe_local_params(spec)):
            self._table.insertRow(row)
            self._table.setItem(row, 0, self._readonly_item(param_label))
            self._table.setItem(row, 1, self._readonly_item(_fmt(local_values.get(local_key))))
            self._table.setItem(row, 2, self._readonly_item(_fmt(param_errors.get(local_key), "4g")))

    @staticmethod
    def _readonly_item(text: str) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        return item

    def _on_copy_to_clipboard(self):
        lines = ["Parameter\tValue\tError"]
        for row in range(self._table.rowCount()):
            lines.append("\t".join(
                self._table.item(row, col).text() for col in range(3)
            ))
        QApplication.clipboard().setText("\n".join(lines))


def _local_param_values(spec) -> list[tuple[str, float]]:
    """(local_key, value) pairs in the same local-key vocabulary as
    describe_local_params()/FitResult.param_results."""
    items = [(f"nr_{name}", fp.value) for name, fp in spec.nonresonant.items()]
    for i, peak in enumerate(spec.peaks):
        items += [(f"p{i}_{name}", fp.value) for name, fp in peak.params.items()]
    return items
