# src/sfg_app2/app/dialogs/metadata_patterns_dialog.py
from __future__ import annotations
import copy
import logging
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QListWidgetItem, QMessageBox
)

from sfg_app2.app.ui.ui_metadata_patterns_dialog import Ui_Dialog
from sfg_app2.app.utils.pattern_manager import PatternManager

logger = logging.getLogger(__name__)

KNOWN_FIELDS = [
    "sample",
    "polarization",
    "center_wavelength",
    "acquisition_time",
    "timestamp",
    "date",
    "concentration",
    "potential",
    "temperature",
]

class NoScrollComboBox(QComboBox):
    """QComboBox that ignores scroll wheel events and right-click context
    menus, passing both up to the parent QListWidget."""

    def wheelEvent(self, event):
        event.ignore()

    def contextMenuEvent(self, event):
        event.ignore()


class MetadataPatternsDialog(QDialog):
    def __init__(self, pattern_manager: PatternManager, parent=None):
        super().__init__(parent)
        self.ui = Ui_Dialog()
        self.ui.setupUi(self)
        self.setWindowTitle("Metadata Patterns")

        # work on a deep copy — only write back on OK
        self._manager = pattern_manager
        self._patterns: list[dict] = copy.deepcopy(pattern_manager.all_patterns)
        self._current_index: int | None = None   # index into self._patterns

        self._setup_fields_list()
        self._populate_saved_patterns()
        self._connect_signals()
        self._update_active_lengths_label()
        self._set_conflict_warning("")

        # nothing selected yet — disable editor
        self._set_editor_enabled(False)

    # ── Setup ─────────────────────────────────────────────────────────────────

    def _setup_fields_list(self):
        fw = self.ui.fieldsListWidget
        fw.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        fw.setDefaultDropAction(Qt.MoveAction)
        fw.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        fw.model().rowsMoved.connect(self._on_fields_reordered)
        fw.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        fw.customContextMenuRequested.connect(self._on_fields_context_menu)

    def _on_fields_context_menu(self, position):
        from PySide6.QtWidgets import QMenu
        fw = self.ui.fieldsListWidget
        item = fw.itemAt(position)
        if item is None:
            return   # right-clicked on empty space, no menu needed

        menu = QMenu(self)
        delete_action = menu.addAction("Delete")
        action = menu.exec(fw.viewport().mapToGlobal(position))

        if action == delete_action:
            row = fw.row(item)
            fw.takeItem(row)
            self._save_current_fields_to_pattern()
            self._update_preview()

    def _connect_signals(self):
        # saved patterns list
        self.ui.savedPatternsListWidget.currentRowChanged.connect(self._on_pattern_selected)
        self.ui.addPatternButton.clicked.connect(self._on_add_pattern)
        self.ui.removePatternButton.clicked.connect(self._on_remove_pattern)
        self.ui.duplicatePatternButton.clicked.connect(self._on_duplicate_pattern)
        self.ui.pushButton_2.clicked.connect(self._on_set_active)
        self.ui.deactivateButton.clicked.connect(self._on_deactivate)

        # editor
        self.ui.patternNamemLineEdit.textChanged.connect(self._on_name_changed)
        self.ui.addFieldButton.clicked.connect(self._on_add_field)
        self.ui.moveUpButton.clicked.connect(self._on_move_up)
        self.ui.moveDownButton.clicked.connect(self._on_move_down)

        # preview
        self.ui.previewFilenameLineEdit.textChanged.connect(self._update_preview)

        # dialog buttons
        self.ui.buttonBox.accepted.connect(self._on_ok)
        self.ui.buttonBox.rejected.connect(self.reject)

    # ── Saved patterns list ───────────────────────────────────────────────────

    def _populate_saved_patterns(self):
        self.ui.savedPatternsListWidget.blockSignals(True)
        self.ui.savedPatternsListWidget.clear()
        for pattern in self._patterns:
            self.ui.savedPatternsListWidget.addItem(
                self._make_pattern_list_item(pattern)
            )
        self.ui.savedPatternsListWidget.blockSignals(False)

    def _make_pattern_list_item(self, pattern: dict) -> QListWidgetItem:
        active = pattern.get("active", False)
        prefix = "★ " if active else "    "
        item = QListWidgetItem(f"{prefix}{pattern['name']}")
        font = item.font()
        font.setBold(active)
        item.setFont(font)
        return item

    def _refresh_saved_patterns_list(self):
        """Refresh display names/bold without resetting selection."""
        for i, pattern in enumerate(self._patterns):
            item = self.ui.savedPatternsListWidget.item(i)
            if item:
                active = pattern.get("active", False)
                item.setText(f"{'★ ' if active else '    '}{pattern['name']}")
                font = item.font()
                font.setBold(active)
                item.setFont(font)

    def _on_pattern_selected(self, row: int):
        if row < 0 or row >= len(self._patterns):
            self._current_index = None
            self._set_editor_enabled(False)
            return
        self._save_current_fields_to_pattern()   # persist edits before switching
        self._current_index = row
        self._load_pattern_into_editor(self._patterns[row])
        self._set_editor_enabled(True)

    def _on_add_pattern(self):
        new_pattern = {"name": "New Pattern", "fields": ["sample"], "active": False}
        self._patterns.append(new_pattern)
        self.ui.savedPatternsListWidget.addItem(self._make_pattern_list_item(new_pattern))
        self.ui.savedPatternsListWidget.setCurrentRow(len(self._patterns) - 1)

    def _on_remove_pattern(self):
        row = self.ui.savedPatternsListWidget.currentRow()
        if row < 0:
            return
        name = self._patterns[row]["name"]
        reply = QMessageBox.question(
            self, "Remove Pattern",
            f"Remove pattern \"{name}\"?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self._patterns.pop(row)
            self.ui.savedPatternsListWidget.takeItem(row)
            self._current_index = None
            self._set_editor_enabled(False)
            self._update_active_lengths_label()

    def _on_duplicate_pattern(self):
        row = self.ui.savedPatternsListWidget.currentRow()
        if row < 0:
            return
        duplicate = copy.deepcopy(self._patterns[row])
        duplicate["name"] = f"{duplicate['name']} (copy)"
        duplicate["active"] = False
        self._patterns.append(duplicate)
        self.ui.savedPatternsListWidget.addItem(self._make_pattern_list_item(duplicate))
        self.ui.savedPatternsListWidget.setCurrentRow(len(self._patterns) - 1)

    # ── Active / deactivate ───────────────────────────────────────────────────

    def _on_set_active(self):
        row = self.ui.savedPatternsListWidget.currentRow()
        if row < 0:
            return
        warning = self._set_active_local(row, True)
        if warning:
            self._set_conflict_warning(f"⚠ {warning}")
        else:
            self._set_conflict_warning("")
            self._refresh_saved_patterns_list()
            self._update_active_lengths_label()

    def _on_deactivate(self):
        row = self.ui.savedPatternsListWidget.currentRow()
        if row < 0:
            return
        self._patterns[row]["active"] = False
        self._set_conflict_warning("")
        self._refresh_saved_patterns_list()
        self._update_active_lengths_label()

    def _set_active_local(self, index: int, active: bool) -> str | None:
        """Returns a conflict warning string, or None if clean."""
        target_len = len(self._patterns[index]["fields"])
        for i, p in enumerate(self._patterns):
            if i != index and p.get("active") and len(p["fields"]) == target_len:
                # show inline warning with a resolve option
                reply = QMessageBox.question(
                    self,
                    "Length Conflict",
                    f"Pattern \"{p['name']}\" is already active with "
                    f"{target_len} fields.\nActivating this will deactivate it. Continue?",
                    QMessageBox.Yes | QMessageBox.No,
                )
                if reply == QMessageBox.Yes:
                    p["active"] = False
                    self._patterns[index]["active"] = True
                    self._refresh_saved_patterns_list()
                    self._update_active_lengths_label()
                    return None
                else:
                    return None   # user cancelled, do nothing
        self._patterns[index]["active"] = True
        self._refresh_saved_patterns_list()
        self._update_active_lengths_label()
        return None

    def _set_conflict_warning(self, text: str):
        self.ui.conflictWarningLabel.setText(text)
        self.ui.conflictWarningLabel.setVisible(bool(text))

    def _update_active_lengths_label(self):
        lengths = sorted(
            len(p["fields"]) for p in self._patterns if p.get("active")
        )
        text = ", ".join(str(l) for l in lengths) if lengths else "none"
        self.ui.activeLengthsLabel.setText(f"Active lengths: {text}")

    # ── Editor ────────────────────────────────────────────────────────────────

    def _set_editor_enabled(self, enabled: bool):
        for w in [
            self.ui.patternNamemLineEdit,
            self.ui.fieldsListWidget,
            self.ui.addFieldButton,
            self.ui.moveUpButton,
            self.ui.moveDownButton,
            self.ui.previewFilenameLineEdit,
            self.ui.parsedResultTextEdit,
        ]:
            w.setEnabled(enabled)

    def _load_pattern_into_editor(self, pattern: dict):
        self.ui.patternNamemLineEdit.blockSignals(True)
        self.ui.patternNamemLineEdit.setText(pattern["name"])
        self.ui.patternNamemLineEdit.blockSignals(False)
        self._rebuild_fields_list(pattern["fields"])
        self._update_preview()

    def _on_name_changed(self, text: str):
        if self._current_index is None:
            return
        self._patterns[self._current_index]["name"] = text
        item = self.ui.savedPatternsListWidget.item(self._current_index)
        if item:
            active = self._patterns[self._current_index].get("active", False)
            item.setText(f"{'★ ' if active else '    '}{text}")

    # ── Fields list ───────────────────────────────────────────────────────────

    def _rebuild_fields_list(self, fields: list[str]):
        """Clear and repopulate fieldsListWidget with comboboxes for each field."""
        fw = self.ui.fieldsListWidget
        fw.clear()
        for field in fields:
            self._append_field_row(field)

    def _append_field_row(self, field_name: str = "sample"):
        fw = self.ui.fieldsListWidget
        item = QListWidgetItem()
        item.setSizeHint(__import__('PySide6.QtCore', fromlist=['QSize']).QSize(0, 30))
        fw.addItem(item)
        combo = self._make_field_combo(field_name)
        fw.setItemWidget(item, combo)

    def _make_field_combo(self, current_field: str) -> QComboBox:
        combo = NoScrollComboBox()
        combo.setEditable(True)
        combo.addItems(KNOWN_FIELDS)
        combo.addItem("other...")
        # set to current field, or add it if it's a custom value
        if current_field in KNOWN_FIELDS:
            combo.setCurrentText(current_field)
        else:
            combo.setCurrentText(current_field)   # editable, so this works for custom values
        combo.currentTextChanged.connect(self._update_preview)
        return combo

    def _get_current_fields(self) -> list[str]:
        """Read current field values from all comboboxes in fieldsListWidget."""
        fw = self.ui.fieldsListWidget
        fields = []
        for i in range(fw.count()):
            widget = fw.itemWidget(fw.item(i))
            if isinstance(widget, QComboBox):
                val = widget.currentText()
                if val and val != "other...":
                    fields.append(val)
        return fields

    def _save_current_fields_to_pattern(self):
        if self._current_index is None:
            return
        self._patterns[self._current_index]["fields"] = self._get_current_fields()

    def _on_fields_reordered(self):
        """After drag-drop, item widgets don't move with items.
        Collect field values by item order, then rebuild."""
        fw = self.ui.fieldsListWidget
        # item text is stale after move — use widget values in new order
        fields = self._get_current_fields()
        self._rebuild_fields_list(fields)
        self._save_current_fields_to_pattern()
        self._update_preview()

    def _on_add_field(self):
        self._append_field_row("")
        self._save_current_fields_to_pattern()
        self._update_preview()

    def _on_move_up(self):
        fw = self.ui.fieldsListWidget
        row = fw.currentRow()
        if row <= 0:
            return
        fields = self._get_current_fields()
        fields.insert(row - 1, fields.pop(row))
        self._rebuild_fields_list(fields)
        fw.setCurrentRow(row - 1)
        self._save_current_fields_to_pattern()
        self._update_preview()

    def _on_move_down(self):
        fw = self.ui.fieldsListWidget
        row = fw.currentRow()
        if row < 0 or row >= fw.count() - 1:
            return
        fields = self._get_current_fields()
        fields.insert(row + 1, fields.pop(row))
        self._rebuild_fields_list(fields)
        fw.setCurrentRow(row + 1)
        self._save_current_fields_to_pattern()
        self._update_preview()

    # ── Live preview ──────────────────────────────────────────────────────────

    def _update_preview(self):
        from sfg_app2.processing.utils import _strip_role_suffix, DEFAULT_ROLE_SUFFIXES

        filename = self.ui.previewFilenameLineEdit.text().strip()
        fields = self._get_current_fields()

        if not filename or not fields:
            self.ui.parsedResultTextEdit.setPlainText("")
            return

        stem = Path(filename).stem
        clean_stem, role = _strip_role_suffix(stem, DEFAULT_ROLE_SUFFIXES)
        parts = clean_stem.split("_")

        lines = []
        for i, field in enumerate(fields):
            value = parts[i] if i < len(parts) else "⚠ missing"
            lines.append(f"{field:<25} → {value}")

        if len(parts) > len(fields):
            extra = parts[len(fields):]
            lines.append(f"{'(extra parts)':<25} → {', '.join(extra)}")

        if role:
            lines.append(f"{'role':<25} → {role} (stripped)")

        self.ui.parsedResultTextEdit.setPlainText("\n".join(lines))

    # ── OK / save ─────────────────────────────────────────────────────────────

    def _on_ok(self):
        self._save_current_fields_to_pattern()
        self._manager._patterns = self._patterns
        self._manager.save()
        self.accept()