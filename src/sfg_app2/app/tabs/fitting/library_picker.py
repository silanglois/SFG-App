"""Pick Spectra Library entries to add to the fit job."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from sfg_app2.processing.kinds import kind_label

_HIDDEN_KEYS = {"label", "exported", "source_filename"}


class LibraryPickerDialog(QDialog):
    """Checkbox table of the Spectra Library: label, kind and every
    metadata field, with a text filter. Entries already in the job are
    shown checked and disabled."""

    def __init__(self, entries: list, already_in_job: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add spectra from the Spectra Library")
        self._entries = list(entries)
        in_job = {id(e) for e in already_in_job}

        keys = []
        for e in self._entries:
            for k, v in (getattr(e.spectrum, "metadata", None) or {}).items():
                if k not in _HIDDEN_KEYS and v not in (None, "") and k not in keys:
                    keys.append(k)
        self._keys = keys

        layout = QVBoxLayout(self)
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Filter:"))
        self._filter = QLineEdit()
        self._filter.setPlaceholderText("Type to filter by name or metadata (e.g. ssp, 25C)…")
        self._filter.textChanged.connect(self._apply_filter)
        filter_row.addWidget(self._filter)
        layout.addLayout(filter_row)

        self.table = QTableWidget(len(self._entries), 2 + len(keys))
        self.table.setHorizontalHeaderLabels(["Spectrum", "Kind"] + keys)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        for row, e in enumerate(self._entries):
            name = QTableWidgetItem(e.label)
            name.setFlags(name.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            if id(e) in in_job:
                name.setCheckState(Qt.CheckState.Checked)
                name.setFlags(name.flags() & ~Qt.ItemFlag.ItemIsEnabled)
                name.setToolTip("Already in the fit job")
            else:
                name.setCheckState(Qt.CheckState.Unchecked)
            self.table.setItem(row, 0, name)
            self.table.setItem(row, 1, QTableWidgetItem(kind_label(e.kind)))
            meta = getattr(e.spectrum, "metadata", None) or {}
            for col, k in enumerate(keys, start=2):
                v = meta.get(k)
                self.table.setItem(row, col, QTableWidgetItem("" if v is None else str(v)))
        self.table.itemDoubleClicked.connect(self._toggle_row)
        layout.addWidget(self.table)

        select_row = QHBoxLayout()
        all_btn = QPushButton("Check shown")
        all_btn.clicked.connect(lambda: self._set_shown(True))
        none_btn = QPushButton("Uncheck shown")
        none_btn.clicked.connect(lambda: self._set_shown(False))
        select_row.addWidget(all_btn)
        select_row.addWidget(none_btn)
        select_row.addStretch()
        layout.addLayout(select_row)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Add checked")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.resize(640, 420)

    def _row_enabled(self, row: int) -> bool:
        return bool(self.table.item(row, 0).flags() & Qt.ItemFlag.ItemIsEnabled)

    def _toggle_row(self, item: QTableWidgetItem):
        name = self.table.item(item.row(), 0)
        if self._row_enabled(item.row()):
            checked = name.checkState() == Qt.CheckState.Checked
            name.setCheckState(Qt.CheckState.Unchecked if checked else Qt.CheckState.Checked)

    def _apply_filter(self, text: str):
        needle = text.strip().lower()
        for row in range(self.table.rowCount()):
            cells = [self.table.item(row, c).text().lower() for c in range(self.table.columnCount())]
            self.table.setRowHidden(row, bool(needle) and not any(needle in c for c in cells))

    def _set_shown(self, checked: bool):
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for row in range(self.table.rowCount()):
            if not self.table.isRowHidden(row) and self._row_enabled(row):
                self.table.item(row, 0).setCheckState(state)

    def set_checked(self, labels: list[str]):
        """Programmatic check (tests)."""
        for row in range(self.table.rowCount()):
            if self.table.item(row, 0).text() in labels and self._row_enabled(row):
                self.table.item(row, 0).setCheckState(Qt.CheckState.Checked)

    def selected_entries(self) -> list:
        return [e for row, e in enumerate(self._entries)
                if self._row_enabled(row)
                and self.table.item(row, 0).checkState() == Qt.CheckState.Checked]
