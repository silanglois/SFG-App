# src/sfg_app2/app/dialogs/fit_parameters_dialog.py
from __future__ import annotations
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget,
    QTableWidgetItem, QPushButton, QLabel, QDialogButtonBox,
    QHeaderView, QApplication, QCheckBox,
)
from PySide6.QtCore import Qt

from sfg_app2.processing import provenance as provenance_mod
from sfg_app2.processing.fitting import (
    fit_model_spec_from_provenance_payload, describe_local_params,
)
from sfg_app2.app.dialogs._multi_entry_table import merge_entries_into_wide_rows


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

        self._combine_check = QCheckBox("Combine all selected into one table")
        self._combine_check.setEnabled(len(self._entries) > 1)
        self._combine_check.toggled.connect(self._on_mode_changed)
        layout.addWidget(self._combine_check)

        self._quality_label = QLabel()
        self._quality_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._quality_label.setWordWrap(True)
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

    @staticmethod
    def _payload_for(entry) -> dict | None:
        provenance = getattr(entry.spectrum, "provenance", None) or {}
        return provenance_mod.parse_fit_json(provenance)

    @staticmethod
    def _rows_for_entry(entry) -> list[tuple[str, str, str]] | None:
        """(param_label, value, error) rows for one entry, or None if it
        carries no fit data at all."""
        payload = FitParametersDialog._payload_for(entry)
        spec = fit_model_spec_from_provenance_payload(payload)
        if payload is None or spec is None:
            return None
        param_errors = payload.get("param_errors") or {}
        local_values = dict(_local_param_values(spec))
        return [
            (param_label, _fmt(local_values.get(local_key)), _fmt(param_errors.get(local_key), "4g"))
            for local_key, param_label in describe_local_params(spec)
        ]

    @staticmethod
    def _quality_line_for(entry) -> str:
        payload = FitParametersDialog._payload_for(entry)
        if payload is None or fit_model_spec_from_provenance_payload(payload) is None:
            return f"{entry.label}: no fit parameters found."
        return (
            f"{entry.label}: redchi = {_fmt(payload.get('redchi'))}   "
            f"R² = {_fmt(payload.get('r_squared'), '.4f')}   "
            f"AIC = {_fmt(payload.get('aic'))}   "
            f"BIC = {_fmt(payload.get('bic'))}   "
            f"weighting = {payload.get('weighting') or 'none'}"
        )

    def _on_mode_changed(self, combined: bool):
        self._prev_button.setVisible(not combined)
        self._counter_label.setVisible(not combined)
        self._next_button.setVisible(not combined)
        if combined:
            self._load_combined()
        else:
            self._load_current()

    def _fill_table(self, headers: list[str], rows: list[tuple]):
        self._table.setColumnCount(len(headers))
        self._table.setHorizontalHeaderLabels(headers)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in range(1, len(headers)):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)

        self._table.setRowCount(0)
        for row in rows:
            table_row = self._table.rowCount()
            self._table.insertRow(table_row)
            for col, text in enumerate(row):
                self._table.setItem(table_row, col, self._readonly_item(text))

    def _load_current(self):
        entry = self._entries[self._current]
        self._label.setText(f"{entry.label}  ({entry.kind})")
        self._counter_label.setText(f"{self._current + 1} / {len(self._entries)}")
        self._prev_button.setEnabled(self._current > 0)
        self._next_button.setEnabled(self._current < len(self._entries) - 1)

        rows = self._rows_for_entry(entry)
        self._quality_label.setText(self._quality_line_for(entry))
        self._copy_button.setEnabled(rows is not None)
        self._fill_table(["Parameter", "Value", "Error"], rows or [])

    def _load_combined(self):
        n = len(self._entries)
        self._label.setText(f"{n} spectrum/spectra (combined)" if n != 1 else self._entries[0].label)
        self._quality_label.setText("\n".join(self._quality_line_for(e) for e in self._entries))

        headers = ["Parameter"]
        per_entry_rows = []
        any_rows = False
        for entry in self._entries:
            rows = self._rows_for_entry(entry)
            headers += [f"{entry.label} Value", f"{entry.label} Error"]
            if rows is not None:
                any_rows = True
            per_entry_rows.append(rows or [])
        self._copy_button.setEnabled(any_rows)
        merged = merge_entries_into_wide_rows(per_entry_rows)
        self._fill_table(headers, merged)

    @staticmethod
    def _readonly_item(text: str) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        return item

    def _on_copy_to_clipboard(self):
        cols = self._table.columnCount()
        lines = ["\t".join(
            self._table.horizontalHeaderItem(col).text() for col in range(cols)
        )]
        for row in range(self._table.rowCount()):
            lines.append("\t".join(
                self._table.item(row, col).text() for col in range(cols)
            ))
        QApplication.clipboard().setText("\n".join(lines))


def _local_param_values(spec) -> list[tuple[str, float]]:
    """(local_key, value) pairs in the same local-key vocabulary as
    describe_local_params()/FitResult.param_results."""
    items = [(f"nr_{name}", fp.value) for name, fp in spec.nonresonant.items()]
    for i, peak in enumerate(spec.peaks):
        items += [(f"p{i}_{name}", fp.value) for name, fp in peak.params.items()]
    return items
