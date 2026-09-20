# src/sfg_app2/app/dialogs/metadata_patterns_dialog.py
from __future__ import annotations
import copy
import logging
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QFormLayout, QLabel, QLineEdit,
    QListWidgetItem, QMessageBox, QVBoxLayout,
)

from sfg_app2.app.ui.ui_metadata_patterns_dialog import Ui_Dialog
from sfg_app2.app.utils.pattern_manager import PatternManager, positional_length
from sfg_app2.app.utils.preset_tree import find_node, iter_leaves
from sfg_app2.app.widgets.preset_tree_widget import PresetTreeWidget
from sfg_app2.processing.data_file import FilenamePattern

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
        self._tree: list[dict] = copy.deepcopy(pattern_manager.tree)
        self._current_leaf_id: str | None = None

        self._setup_mode_controls()
        self._setup_fields_list()
        self._setup_saved_patterns_tree()
        self._connect_signals()
        self._update_active_lengths_label()
        self._set_conflict_warning("")

        # nothing selected yet — disable editor
        self._set_editor_enabled(False)

    def _setup_mode_controls(self):
        """Match-mode row, inserted above the fields list.

        Built in code rather than in the .ui file: the .ui and its
        generated ui_*.py are hand-maintained here, so editing both by
        hand just to add three rows invites them drifting apart.
        """
        self._mode_combo = QComboBox()
        self._mode_combo.addItem("Split on a separator", "positional")
        self._mode_combo.addItem("Regular expression", "regex")

        self._delimiter_edit = QLineEdit("_")
        self._delimiter_edit.setMaxLength(4)
        self._delimiter_edit.setFixedWidth(60)
        self._delimiter_edit.setToolTip("Character the filename is split on.")

        self._regex_edit = QLineEdit()
        self._regex_edit.setPlaceholderText(r"^(?P<sample>[^-]+)-(?P<polarization>\w+)$")
        self._regex_edit.setToolTip(
            "Named groups become the metadata fields. Use this when two "
            "layouts have the same number of parts -- splitting alone "
            "can't tell those apart."
        )

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        self._delimiter_label = QLabel("Separator:")
        self._regex_label = QLabel("Expression:")
        form.addRow("Match by:", self._mode_combo)
        form.addRow(self._delimiter_label, self._delimiter_edit)
        form.addRow(self._regex_label, self._regex_edit)
        # After the pattern-name row, before the fields list.
        self.ui.verticalLayout_3.insertLayout(2, form)

    def _setup_saved_patterns_tree(self):
        layout = QVBoxLayout(self.ui.savedPatternsPlaceholder)
        layout.setContentsMargins(0, 0, 0, 0)
        self._tree_widget = PresetTreeWidget(
            leaf_data_factory=lambda: {"fields": ["sample"], "delimiter": "_",
                                       "mode": "positional", "regex": ""},
            new_leaf_name="New Pattern",
        )
        self._tree_widget.leafSelected.connect(self._on_pattern_selected)
        layout.addWidget(self._tree_widget)
        self._tree_widget.set_tree(self._tree)

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
        # saved patterns tree
        self.ui.pushButton_2.clicked.connect(self._on_set_active)
        self.ui.deactivateButton.clicked.connect(self._on_deactivate)

        # editor
        self.ui.patternNamemLineEdit.textChanged.connect(self._on_name_changed)
        self._mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        self._delimiter_edit.textChanged.connect(self._on_editor_changed)
        self._regex_edit.textChanged.connect(self._on_editor_changed)
        self.ui.addFieldButton.clicked.connect(self._on_add_field)
        self.ui.moveUpButton.clicked.connect(self._on_move_up)
        self.ui.moveDownButton.clicked.connect(self._on_move_down)

        # preview
        self.ui.previewFilenameLineEdit.textChanged.connect(self._update_preview)

        # dialog buttons
        self.ui.buttonBox.accepted.connect(self._on_ok)
        self.ui.buttonBox.rejected.connect(self.reject)

    # ── Saved patterns tree ───────────────────────────────────────────────────

    def _all_patterns(self) -> list[dict]:
        return list(iter_leaves(self._tree))

    def _on_pattern_selected(self, leaf_id: str | None):
        if self._current_leaf_id is not None:
            self._save_current_fields_to_pattern()   # persist edits before switching
        self._current_leaf_id = leaf_id
        if leaf_id is None:
            self._set_editor_enabled(False)
            return
        leaf = find_node(self._tree, leaf_id)
        if leaf is None:
            self._set_editor_enabled(False)
            return
        self._load_pattern_into_editor(leaf)
        self._set_editor_enabled(True)

    # ── Active / deactivate ───────────────────────────────────────────────────

    def _on_set_active(self):
        leaf_id = self._tree_widget.current_leaf_id()
        if leaf_id is None:
            return
        warning = self._set_active_local(leaf_id, True)
        if warning:
            self._set_conflict_warning(f"⚠ {warning}")
        else:
            self._set_conflict_warning("")
            self._tree_widget.refresh_labels()
            self._update_active_lengths_label()

    def _on_deactivate(self):
        leaf_id = self._tree_widget.current_leaf_id()
        if leaf_id is None:
            return
        leaf = find_node(self._tree, leaf_id)
        if leaf is None:
            return
        leaf["active"] = False
        self._set_conflict_warning("")
        self._tree_widget.refresh_labels()
        self._update_active_lengths_label()

    def _set_active_local(self, leaf_id: str, active: bool) -> str | None:
        """Returns a conflict warning string, or None if clean."""
        target = find_node(self._tree, leaf_id)
        if target is None:
            return None
        target_len = positional_length(target)
        if target_len is None:
            # Regex patterns are picked by inspecting the filename, not by
            # token count, so they can't collide with anything.
            target["active"] = True
            self._tree_widget.refresh_labels()
            self._update_active_lengths_label()
            return None
        for p in self._all_patterns():
            if p["id"] != leaf_id and p.get("active") and positional_length(p) == target_len:
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
                    target["active"] = True
                    self._tree_widget.refresh_labels()
                    self._update_active_lengths_label()
                    return None
                else:
                    return None   # user cancelled, do nothing
        target["active"] = True
        self._tree_widget.refresh_labels()
        self._update_active_lengths_label()
        return None

    def _set_conflict_warning(self, text: str):
        self.ui.conflictWarningLabel.setText(text)
        self.ui.conflictWarningLabel.setVisible(bool(text))

    def _update_active_lengths_label(self):
        active = [p for p in self._all_patterns() if p.get("active")]
        lengths = sorted(n for n in (positional_length(p) for p in active)
                         if n is not None)
        text = ", ".join(str(l) for l in lengths) if lengths else "none"
        n_regex = sum(1 for p in active if positional_length(p) is None)
        if n_regex:
            text += f" (+{n_regex} by expression)"
        self.ui.activeLengthsLabel.setText(f"Active lengths: {text}")

    # ── Editor ────────────────────────────────────────────────────────────────

    def _set_editor_enabled(self, enabled: bool):
        for w in [
            self.ui.patternNamemLineEdit,
            self._mode_combo,
            self._delimiter_edit,
            self._regex_edit,
            self.ui.fieldsListWidget,
            self.ui.addFieldButton,
            self.ui.moveUpButton,
            self.ui.moveDownButton,
            self.ui.previewFilenameLineEdit,
            self.ui.parsedResultTextEdit,
        ]:
            w.setEnabled(enabled)
        if enabled:
            self._apply_mode_visibility()

    def _apply_mode_visibility(self):
        """In regex mode the fields come from the expression's named
        groups, so the hand-built field list has nothing to say."""
        is_regex = self._mode_combo.currentData() == "regex"
        for w in (self._regex_label, self._regex_edit):
            w.setVisible(is_regex)
        for w in (self._delimiter_label, self._delimiter_edit):
            w.setVisible(not is_regex)
        for w in (self.ui.fieldsListWidget, self.ui.addFieldButton,
                  self.ui.moveUpButton, self.ui.moveDownButton, self.ui.label_3):
            w.setVisible(not is_regex)

    def _on_mode_changed(self):
        self._apply_mode_visibility()
        self._on_editor_changed()

    def _on_editor_changed(self):
        self._save_current_fields_to_pattern()
        self._update_preview()
        self._update_active_lengths_label()

    def _editor_pattern(self) -> FilenamePattern:
        """The pattern as the editor currently describes it -- the single
        source of truth for both saving and the preview, so the preview
        can't drift from what loading will actually do."""
        return FilenamePattern(
            fields=self._get_current_fields(),
            delimiter=self._delimiter_edit.text() or "_",
            mode=self._mode_combo.currentData() or "positional",
            regex=self._regex_edit.text(),
        )

    def _load_pattern_into_editor(self, leaf: dict):
        pattern = FilenamePattern.coerce(leaf["data"] or {})
        self.ui.patternNamemLineEdit.blockSignals(True)
        self.ui.patternNamemLineEdit.setText(leaf["name"])
        self.ui.patternNamemLineEdit.blockSignals(False)

        for widget, value in ((self._delimiter_edit, pattern.delimiter),
                              (self._regex_edit, pattern.regex)):
            widget.blockSignals(True)
            widget.setText(value)
            widget.blockSignals(False)
        self._mode_combo.blockSignals(True)
        self._mode_combo.setCurrentIndex(max(self._mode_combo.findData(pattern.mode), 0))
        self._mode_combo.blockSignals(False)

        self._rebuild_fields_list(pattern.fields)
        self._apply_mode_visibility()
        self._update_preview()

    def _on_name_changed(self, text: str):
        if self._current_leaf_id is None:
            return
        leaf = find_node(self._tree, self._current_leaf_id)
        if leaf is None:
            return
        leaf["name"] = text
        self._tree_widget.refresh_labels()

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
        if self._current_leaf_id is None:
            return
        leaf = find_node(self._tree, self._current_leaf_id)
        if leaf is not None:
            leaf["data"] = self._editor_pattern().to_dict()

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

    def _role_kwargs(self) -> dict:
        try:
            main = self.window()
            if hasattr(main, "matching_settings"):
                return main.matching_settings.role_kwargs()
        except Exception:
            pass
        from sfg_app2.processing.utils import DEFAULT_ROLE_SUFFIXES
        return {"role_mode": "suffix", "role_values": DEFAULT_ROLE_SUFFIXES, "role_field": ""}

    def _update_preview(self):
        """Show what this pattern would actually produce.

        Runs the real FilenamePattern rather than re-implementing the
        split here, so the preview can't quietly disagree with what
        loading a file will do -- the whole point of having it.
        """
        from sfg_app2.processing.utils import resolve_role

        filename = self.ui.previewFilenameLineEdit.text().strip()
        if not filename:
            self.ui.parsedResultTextEdit.setPlainText("")
            return

        pattern = self._editor_pattern()
        role_kwargs = self._role_kwargs()
        clean_stem, matched, _ = resolve_role(
            Path(filename).stem, role_kwargs["role_mode"], role_kwargs["role_values"]
        )

        if pattern.mode == "regex" and not pattern.field_names():
            self.ui.parsedResultTextEdit.setPlainText(
                "⚠ No named groups yet — write them as (?P<name>...)."
                if pattern.regex else "")
            return

        applies = pattern.match(clean_stem) is not None
        lines = [f"{key:<25} → {value}"
                 for key, value in pattern.extract(clean_stem).items()]
        if not applies:
            lines.insert(0, "⚠ This pattern would NOT be picked for this file."
                            if pattern.mode == "regex" else
                            "⚠ Part count doesn't match — this pattern would "
                            "not be picked for this file.")
        if matched:
            lines.append(f"{'role':<25} → background (stripped)")

        self.ui.parsedResultTextEdit.setPlainText("\n".join(lines))

    # ── OK / save ─────────────────────────────────────────────────────────────

    def _on_ok(self):
        self._save_current_fields_to_pattern()
        self._manager._tree = self._tree
        if not self._manager.save():
            QMessageBox.warning(
                self, "Couldn't save settings",
                "Metadata patterns could not be saved to disk. "
                "Your changes will apply for this session but won't persist.",
            )
        self.accept()