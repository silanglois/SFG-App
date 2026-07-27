from __future__ import annotations
import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QTableWidget, QTableWidgetItem, QComboBox, QDialogButtonBox,
    QInputDialog, QAbstractItemView, QHeaderView, QMessageBox, QGroupBox, QWidget,
)

from sfg_app2.app.utils.matching_settings import (
    MatchingSettings, type_rules_conflicts,
)
from sfg_app2.app.dialogs.metadata_patterns_dialog import KNOWN_FIELDS
from sfg_app2.app.widgets.collapsible_group_box import make_collapsible

logger = logging.getLogger(__name__)

STATE_OPTIONS = ["Ignore", "Optional", "Required", "Closest"]
TYPE_OPTIONS = ["Heterodyne", "Homodyne"]
SCOPE_OPTIONS = ["Signal", "Background", "Both"]
DEFAULT_RULE_FIELD = "sample"
FILENAME_SENTINEL = "Filename"

ROLE_MODE_OPTIONS = [
    "End of filename (suffix)", "Beginning of filename (prefix)", "Metadata field",
]
ROLE_MODE_TO_INTERNAL = {
    "End of filename (suffix)": "suffix",
    "Beginning of filename (prefix)": "prefix",
    "Metadata field": "field",
}
ROLE_MODE_FROM_INTERNAL = {v: k for k, v in ROLE_MODE_TO_INTERNAL.items()}
ROLE_MODE_LIST_LABEL = {
    "suffix": "Filename tokens that indicate background (matched at the end, "
              "e.g. \"bg\"):",
    "prefix": "Filename tokens that indicate background (matched at the "
              "beginning, e.g. \"bg\"):",
    "field": "Metadata field values that indicate background (e.g. \"dark\"):",
}


class AutoMatchingSettingsDialog(QDialog):
    """Lets the user configure how "Auto-match Files" identifies references,
    detects background files (by filename suffix/prefix or a metadata
    field), matches backgrounds/references to signals, and forces homodyne
    vs. heterodyne processing based on a metadata field or filename
    substring.
    """

    def __init__(self, settings: MatchingSettings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Auto-Matching Parameters")
        self.resize(480, 750)
        self._settings = settings

        self._build_ui()
        self._populate_reference_names()
        self._populate_role_box()
        self._populate_type_rules()
        self._populate_fields_table()

        for box in (self._ref_box, self._role_box, self._rules_box, self._fields_box):
            box.setCheckable(True)
            box.setChecked(True)
            make_collapsible(box)

        # make_collapsible() forces every direct child visible whenever the
        # box is expanded, which would override the role field row's own
        # mode-dependent visibility — reassert it now and on every future
        # expand/collapse toggle.
        self._role_box.toggled.connect(lambda _checked: self._update_role_box_visibility())
        self._update_role_box_visibility()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        layout = QVBoxLayout(self)

        layout.addWidget(self._build_reference_names_box())
        layout.addWidget(self._build_role_box())
        layout.addWidget(self._build_type_rules_box())
        layout.addWidget(self._build_fields_box())

        self._button_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        self._button_box.accepted.connect(self._on_ok)
        self._button_box.rejected.connect(self.reject)
        layout.addWidget(self._button_box)

    def _build_reference_names_box(self) -> QGroupBox:
        self._ref_box = QGroupBox("Reference sample names")
        box_layout = QVBoxLayout(self._ref_box)
        ref_label = QLabel(
            "Sample names that identify a file as a reference "
            "(matched case-insensitively):"
        )
        ref_label.setWordWrap(True)
        box_layout.addWidget(ref_label)
        ref_row = QHBoxLayout()
        self._ref_list = QListWidget()
        ref_row.addWidget(self._ref_list)
        ref_buttons = QVBoxLayout()
        add_ref_btn = QPushButton("Add")
        remove_ref_btn = QPushButton("Remove")
        add_ref_btn.clicked.connect(self._on_add_reference_name)
        remove_ref_btn.clicked.connect(self._on_remove_reference_name)
        ref_buttons.addWidget(add_ref_btn)
        ref_buttons.addWidget(remove_ref_btn)
        ref_buttons.addStretch()
        ref_row.addLayout(ref_buttons)
        box_layout.addLayout(ref_row)
        return self._ref_box

    def _build_role_box(self) -> QGroupBox:
        self._role_box = QGroupBox("Background role detection")
        box_layout = QVBoxLayout(self._role_box)

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Detect background files by:"))
        self._role_mode_combo = QComboBox()
        self._role_mode_combo.addItems(ROLE_MODE_OPTIONS)
        self._role_mode_combo.currentTextChanged.connect(self._on_role_mode_changed)
        mode_row.addWidget(self._role_mode_combo)
        mode_row.addStretch()
        box_layout.addLayout(mode_row)

        self._role_values_label = QLabel()
        self._role_values_label.setWordWrap(True)
        box_layout.addWidget(self._role_values_label)

        field_row = QHBoxLayout()
        field_row.addWidget(QLabel("Metadata field:"))
        self._role_field_combo = self._make_field_combo(DEFAULT_RULE_FIELD, include_filename=False)
        field_row.addWidget(self._role_field_combo)
        field_row.addStretch()
        self._role_field_row_widget = QWidget()
        self._role_field_row_widget.setLayout(field_row)
        box_layout.addWidget(self._role_field_row_widget)

        values_row = QHBoxLayout()
        self._role_values_list = QListWidget()
        values_row.addWidget(self._role_values_list)
        values_buttons = QVBoxLayout()
        add_value_btn = QPushButton("Add")
        remove_value_btn = QPushButton("Remove")
        add_value_btn.clicked.connect(self._on_add_role_value)
        remove_value_btn.clicked.connect(self._on_remove_role_value)
        values_buttons.addWidget(add_value_btn)
        values_buttons.addWidget(remove_value_btn)
        values_buttons.addStretch()
        values_row.addLayout(values_buttons)
        box_layout.addLayout(values_row)

        return self._role_box

    def _build_type_rules_box(self) -> QGroupBox:
        self._rules_box = QGroupBox("Force homodyne / heterodyne processing")
        box_layout = QVBoxLayout(self._rules_box)
        rules_label = QLabel(
            "Force a spectrum type when a chosen filename-parsed field matches "
            "a value, or when a substring appears anywhere in the filename "
            "(choose \"Filename\" as the field) — checked against the signal's "
            "and/or background's field/filename (case-insensitively). First "
            "matching rule wins; sets matching no rule default to homodyne:"
        )
        rules_label.setWordWrap(True)
        box_layout.addWidget(rules_label)
        self._rules_table = QTableWidget(0, 4)
        self._rules_table.setHorizontalHeaderLabels(
            ["Field", "Value", "Force type", "Applies to"]
        )
        self._rules_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self._rules_table.verticalHeader().setVisible(False)
        self._rules_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        box_layout.addWidget(self._rules_table)

        rules_btn_row = QHBoxLayout()
        add_rule_btn = QPushButton("Add rule")
        remove_rule_btn = QPushButton("Remove selected rule")
        add_rule_btn.clicked.connect(self._on_add_type_rule)
        remove_rule_btn.clicked.connect(self._on_remove_type_rule)
        rules_btn_row.addWidget(add_rule_btn)
        rules_btn_row.addWidget(remove_rule_btn)
        rules_btn_row.addStretch()
        box_layout.addLayout(rules_btn_row)
        return self._rules_box

    def _build_fields_box(self) -> QGroupBox:
        self._fields_box = QGroupBox("Metadata matching rules")
        box_layout = QVBoxLayout(self._fields_box)
        fields_label = QLabel(
            "Metadata fields used to match a signal to its background/reference — "
            "Required must match exactly. Optional prefers a match but is skipped "
            "if no candidate matches. Closest picks the nearest numeric/date value, "
            "in priority order (top row highest priority):"
        )
        fields_label.setWordWrap(True)
        box_layout.addWidget(fields_label)
        self._fields_table = QTableWidget(0, 3)
        self._fields_table.setHorizontalHeaderLabels(["Field", "Background", "Reference"])
        self._fields_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self._fields_table.verticalHeader().setVisible(False)
        self._fields_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        box_layout.addWidget(self._fields_table)

        add_field_row = QHBoxLayout()
        add_field_btn = QPushButton("Add field...")
        add_field_btn.clicked.connect(self._on_add_field)
        remove_field_btn = QPushButton("Remove selected field")
        remove_field_btn.clicked.connect(self._on_remove_field)
        add_field_row.addWidget(add_field_btn)
        add_field_row.addWidget(remove_field_btn)
        add_field_row.addStretch()
        box_layout.addLayout(add_field_row)
        return self._fields_box

    # ── Reference names ──────────────────────────────────────────────────────

    def _populate_reference_names(self):
        self._ref_list.clear()
        for name in self._settings.reference_names:
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
            self._ref_list.addItem(item)

    def _on_add_reference_name(self):
        item = QListWidgetItem("new_sample")
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
        self._ref_list.addItem(item)
        self._ref_list.setCurrentItem(item)
        self._ref_list.editItem(item)

    def _on_remove_reference_name(self):
        row = self._ref_list.currentRow()
        if row >= 0:
            self._ref_list.takeItem(row)

    # ── Background role detection ────────────────────────────────────────────

    def _populate_role_box(self):
        s = self._settings
        self._role_mode_combo.setCurrentText(
            ROLE_MODE_FROM_INTERNAL.get(s.background_role_mode, ROLE_MODE_OPTIONS[0])
        )
        self._role_field_combo.setCurrentText(s.background_role_field or DEFAULT_RULE_FIELD)
        self._role_values_list.clear()
        for value in s.background_role_values:
            item = QListWidgetItem(value)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
            self._role_values_list.addItem(item)
        self._update_role_box_visibility()

    def _on_role_mode_changed(self, _text: str):
        self._update_role_box_visibility()

    def _update_role_box_visibility(self):
        mode = ROLE_MODE_TO_INTERNAL.get(self._role_mode_combo.currentText(), "suffix")
        self._role_values_label.setText(ROLE_MODE_LIST_LABEL[mode])
        self._role_field_row_widget.setVisible(mode == "field")

    def _on_add_role_value(self):
        item = QListWidgetItem("new_value")
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
        self._role_values_list.addItem(item)
        self._role_values_list.setCurrentItem(item)
        self._role_values_list.editItem(item)

    def _on_remove_role_value(self):
        row = self._role_values_list.currentRow()
        if row >= 0:
            self._role_values_list.takeItem(row)

    # ── Type-forcing rules ────────────────────────────────────────────────────

    def _populate_type_rules(self):
        self._rules_table.setRowCount(0)
        for rule in self._settings.type_rules:
            field_text = (
                FILENAME_SENTINEL if rule.get("mode", "field") == "filename"
                else (rule.get("field") or DEFAULT_RULE_FIELD)
            )
            self._add_type_rule_row(
                field_text,
                rule.get("key", ""),
                rule.get("type", "heterodyne").capitalize(),
                rule.get("scope", "both").capitalize(),
            )

    def _make_field_combo(self, field_text: str, include_filename: bool = True) -> QComboBox:
        combo = QComboBox()
        combo.setEditable(True)
        if include_filename:
            combo.addItem(FILENAME_SENTINEL)
        combo.addItems(KNOWN_FIELDS)
        combo.setCurrentText(field_text or DEFAULT_RULE_FIELD)
        return combo

    def _add_type_rule_row(self, field_text: str, key: str, type_text: str, scope_text: str):
        row = self._rules_table.rowCount()
        self._rules_table.insertRow(row)

        self._rules_table.setCellWidget(row, 0, self._make_field_combo(field_text))
        self._rules_table.setItem(row, 1, QTableWidgetItem(key))

        type_combo = QComboBox()
        type_combo.addItems(TYPE_OPTIONS)
        if type_text in TYPE_OPTIONS:
            type_combo.setCurrentText(type_text)
        self._rules_table.setCellWidget(row, 2, type_combo)

        scope_combo = QComboBox()
        scope_combo.addItems(SCOPE_OPTIONS)
        if scope_text in SCOPE_OPTIONS:
            scope_combo.setCurrentText(scope_text)
        self._rules_table.setCellWidget(row, 3, scope_combo)

    def _on_add_type_rule(self):
        self._add_type_rule_row(DEFAULT_RULE_FIELD, "new_value", "Heterodyne", "Signal")

    def _on_remove_type_rule(self):
        row = self._rules_table.currentRow()
        if row >= 0:
            self._rules_table.removeRow(row)

    def _collect_type_rules(self) -> list[dict]:
        rules = []
        for row in range(self._rules_table.rowCount()):
            key = self._rules_table.item(row, 1).text().strip()
            if not key:
                continue
            field = self._rules_table.cellWidget(row, 0).currentText().strip() or DEFAULT_RULE_FIELD
            type_text = self._rules_table.cellWidget(row, 2).currentText()
            scope_text = self._rules_table.cellWidget(row, 3).currentText()
            if field == FILENAME_SENTINEL:
                rules.append({
                    "mode": "filename",
                    "key": key,
                    "type": type_text.lower(),
                    "scope": scope_text.lower(),
                })
            else:
                rules.append({
                    "mode": "field",
                    "field": field,
                    "key": key,
                    "type": type_text.lower(),
                    "scope": scope_text.lower(),
                })
        return rules

    # ── Fields table ──────────────────────────────────────────────────────────

    def _state_for(self, field: str, required_keys: list[str],
                    optional_keys: list[str], closest_keys: list[str]) -> str:
        if field in required_keys:
            return "Required"
        if field in optional_keys:
            return "Optional"
        if field in closest_keys:
            return "Closest"
        return "Ignore"

    def _populate_fields_table(self):
        s = self._settings
        configured = (
            s.background_required_keys + s.background_optional_keys + s.background_closest_keys +
            s.reference_required_keys + s.reference_optional_keys + s.reference_closest_keys
        )
        fields = list(KNOWN_FIELDS)
        for f in configured:
            if f not in fields:
                fields.append(f)

        self._fields_table.setRowCount(0)
        for field in fields:
            self._add_field_row(
                field,
                self._state_for(field, s.background_required_keys,
                                 s.background_optional_keys, s.background_closest_keys),
                self._state_for(field, s.reference_required_keys,
                                 s.reference_optional_keys, s.reference_closest_keys),
            )

    def _add_field_row(self, field: str, bg_state: str, ref_state: str):
        row = self._fields_table.rowCount()
        self._fields_table.insertRow(row)
        self._fields_table.setItem(row, 0, QTableWidgetItem(field))

        bg_combo = QComboBox()
        bg_combo.addItems(STATE_OPTIONS)
        bg_combo.setCurrentText(bg_state)
        self._fields_table.setCellWidget(row, 1, bg_combo)

        ref_combo = QComboBox()
        ref_combo.addItems(STATE_OPTIONS)
        ref_combo.setCurrentText(ref_state)
        self._fields_table.setCellWidget(row, 2, ref_combo)

    def _on_add_field(self):
        name, ok = QInputDialog.getText(self, "Add Field", "Metadata field name:")
        name = name.strip()
        if not ok or not name:
            return
        existing = {
            self._fields_table.item(r, 0).text()
            for r in range(self._fields_table.rowCount())
        }
        if name in existing:
            return
        self._add_field_row(name, "Ignore", "Ignore")

    def _on_remove_field(self):
        row = self._fields_table.currentRow()
        if row >= 0:
            self._fields_table.removeRow(row)

    # ── OK ────────────────────────────────────────────────────────────────────

    def _on_ok(self):
        type_rules = self._collect_type_rules()
        conflicts = type_rules_conflicts(type_rules)
        if conflicts:
            def describe(rule):
                source = "filename" if rule.get("mode") == "filename" else rule.get("field")
                return f"{source}=\"{rule['key']}\""
            lines = [
                f"  • {describe(a)} as {a['type']} ({a['scope']}) vs. "
                f"{b['type']} ({b['scope']})"
                for a, b in conflicts
            ]
            QMessageBox.warning(
                self, "Conflicting Rules",
                "These rules force different types for the same field/value "
                "with overlapping scope — fix before saving:\n\n"
                + "\n".join(lines)
            )
            return

        role_mode = ROLE_MODE_TO_INTERNAL.get(self._role_mode_combo.currentText(), "suffix")
        role_field = self._role_field_combo.currentText().strip()
        if role_mode == "field" and not role_field:
            QMessageBox.warning(
                self, "Missing Field",
                "Choose a metadata field for background role detection, or "
                "switch to filename suffix/prefix detection."
            )
            return
        role_values = []
        seen_role_values = set()
        for i in range(self._role_values_list.count()):
            text = self._role_values_list.item(i).text().strip()
            if text and text.lower() not in seen_role_values:
                role_values.append(text)
                seen_role_values.add(text.lower())

        names = []
        seen = set()
        for i in range(self._ref_list.count()):
            text = self._ref_list.item(i).text().strip()
            if text and text.lower() not in seen:
                names.append(text)
                seen.add(text.lower())
        self._settings.reference_names = names
        self._settings.type_rules = type_rules
        self._settings.background_role_mode = role_mode
        self._settings.background_role_field = role_field
        self._settings.background_role_values = role_values

        bg_required, bg_optional, bg_closest = [], [], []
        ref_required, ref_optional, ref_closest = [], [], []
        for row in range(self._fields_table.rowCount()):
            field = self._fields_table.item(row, 0).text().strip()
            if not field:
                continue
            bg_state = self._fields_table.cellWidget(row, 1).currentText()
            ref_state = self._fields_table.cellWidget(row, 2).currentText()
            if bg_state == "Required":
                bg_required.append(field)
            elif bg_state == "Optional":
                bg_optional.append(field)
            elif bg_state == "Closest":
                bg_closest.append(field)
            if ref_state == "Required":
                ref_required.append(field)
            elif ref_state == "Optional":
                ref_optional.append(field)
            elif ref_state == "Closest":
                ref_closest.append(field)

        self._settings.background_required_keys = bg_required
        self._settings.background_optional_keys = bg_optional
        self._settings.background_closest_keys = bg_closest
        self._settings.reference_required_keys = ref_required
        self._settings.reference_optional_keys = ref_optional
        self._settings.reference_closest_keys = ref_closest
        self._settings.save()
        self.accept()
