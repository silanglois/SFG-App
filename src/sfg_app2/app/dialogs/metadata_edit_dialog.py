# src/sfg_app2/app/dialogs/metadata_edit_dialog.py
from __future__ import annotations
import logging
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget,
    QTableWidgetItem, QPushButton, QLabel, QDialogButtonBox,
    QHeaderView, QLineEdit, QMessageBox
)
from PySide6.QtCore import Qt

logger = logging.getLogger(__name__)


class MetadataEditDialog(QDialog):
    """Step-through metadata editor — one file at a time, prev/next navigation."""

    def __init__(self, files: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Review / Edit Metadata")
        self.resize(500, 400)

        self._files = files
        self._current = 0
        self._edits: dict[int, dict] = {}    # index → modified metadata

        layout = QVBoxLayout(self)

        # file label
        self._file_label = QLabel()
        self._file_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._file_label)

        # metadata table
        self._table = QTableWidget(0, 2)
        self._table.setHorizontalHeaderLabels(["Field", "Value"])
        self._table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self._table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self._table.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self._table)

        # prev / next navigation
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

        # metadata editing
        add_field_layout = QHBoxLayout()
        self._new_key_edit = QLineEdit()
        self._new_key_edit.setPlaceholderText("Field name...")
        self._new_val_edit = QLineEdit()
        self._new_val_edit.setPlaceholderText("Value...")
        self._add_field_button = QPushButton("+ Add field")
        self._add_field_button.clicked.connect(self._on_add_field)
        add_field_layout.addWidget(self._new_key_edit)
        add_field_layout.addWidget(self._new_val_edit)
        add_field_layout.addWidget(self._add_field_button)
        layout.insertLayout(2, add_field_layout)

        self._new_key_edit.returnPressed.connect(self._on_add_field)
        self._new_val_edit.returnPressed.connect(self._on_add_field)

        # ok / cancel
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_ok)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._load_current()

    # ── Navigation ────────────────────────────────────────────────────────────

    def _on_add_field(self):
        key = self._new_key_edit.text().strip()
        val = self._new_val_edit.text().strip()

        if not key:
            self._new_key_edit.setFocus()
            return

        # check for duplicate key — offer to overwrite existing
        for row in range(self._table.rowCount()):
            existing_key = self._table.item(row, 0).text()
            if existing_key.lower() == key.lower():
                reply = QMessageBox.question(
                    self,
                    "Field already exists",
                    f"Field \"{existing_key}\" already exists. Overwrite its value?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if reply == QMessageBox.StandardButton.Yes:
                    self._table.item(row, 1).setText(val)
                    self._new_key_edit.clear()
                    self._new_val_edit.clear()
                    self._on_item_changed()
                return

        # new key — append a row
        self._table.blockSignals(True)
        row = self._table.rowCount()
        self._table.insertRow(row)
        key_item = QTableWidgetItem(key)
        key_item.setFlags(key_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self._table.setItem(row, 0, key_item)
        self._table.setItem(row, 1, QTableWidgetItem(val))
        self._table.blockSignals(False)

        self._new_key_edit.clear()
        self._new_val_edit.clear()
        self._on_item_changed()
        self._table.scrollToBottom()

    def _on_prev(self):
        self._save_current()
        self._current = max(0, self._current - 1)
        self._load_current()

    def _on_next(self):
        self._save_current()
        self._current = min(len(self._files) - 1, self._current + 1)
        self._load_current()

    def _load_current(self):
        f = self._files[self._current]
        if hasattr(f, "path"):
            display = f.path.name
        elif hasattr(f, "_display_name"):
            display = f._display_name
        else:
            display = str(f)
        self._file_label.setText(display)
        self._counter_label.setText(
            f"{self._current + 1} / {len(self._files)}"
        )
        self._prev_button.setEnabled(self._current > 0)
        self._next_button.setEnabled(self._current < len(self._files) - 1)

        # use saved edits if available, otherwise original metadata
        metadata = self._edits.get(self._current, f.metadata).copy()

        self._table.blockSignals(True)
        self._table.setRowCount(0)
        for key, value in metadata.items():
            row = self._table.rowCount()
            self._table.insertRow(row)
            key_item = QTableWidgetItem(str(key))
            key_item.setFlags(key_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._table.setItem(row, 0, key_item)
            self._table.setItem(row, 1, QTableWidgetItem(str(value) if value is not None else ""))
        self._table.blockSignals(False)

    def _save_current(self):
        """Persist current table edits for the current file index."""
        metadata = {}
        for row in range(self._table.rowCount()):
            key = self._table.item(row, 0).text()
            val_item = self._table.item(row, 1)
            metadata[key] = val_item.text() if val_item else ""
        self._edits[self._current] = metadata

    def _on_item_changed(self):
        # mark this file as having unsaved edits (visual feedback)
        self._file_label.setText(f"{self._files[self._current].path.name}  ✎")

    # ── OK — apply edits back to DataFile objects ─────────────────────────────

    def _on_ok(self):
        self._save_current()
        for idx, edited_metadata in self._edits.items():
            f = self._files[idx]
            if hasattr(f, "_parsed_metadata") and hasattr(f, "set_manual_metadata"):
                # DataFile — preserve parsed vs manual distinction
                for key, value in edited_metadata.items():
                    original_val = f._parsed_metadata.get(key)
                    if value != str(original_val) if original_val is not None else True:
                        f.set_manual_metadata(key, value)
            else:
                # ProcessedSpectrum or anything else — plain dict update
                f.metadata.update(edited_metadata)
                logger.info("Metadata updated for %s.", getattr(f, "label", str(idx)))
        self.accept()