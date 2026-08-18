from __future__ import annotations
import copy
import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QTableWidget, QTableWidgetItem, QComboBox, QDialogButtonBox,
    QInputDialog, QAbstractItemView, QHeaderView, QMessageBox, QGroupBox, QWidget,
    QSplitter, QScrollArea, QToolBox,
)

from sfg_app2.app.utils.matching_settings import (
    MatchingSettings, MatchingProfileManager, type_rules_conflicts, TYPE_RULE_TYPES,
)
from sfg_app2.app.utils.preset_tree import find_node, iter_leaves
from sfg_app2.app.widgets.preset_tree_widget import PresetTreeWidget
from sfg_app2.app.dialogs.metadata_patterns_dialog import KNOWN_FIELDS

logger = logging.getLogger(__name__)

STATE_OPTIONS = ["Ignore", "Optional", "Required", "Closest", "Highest"]
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
    """Lets the user manage multiple named auto-matching profiles
    (organized in a tree, so they can be grouped into folders), each
    configuring how "Auto-match Files" identifies references, detects
    background files, matches backgrounds/references to signals, and
    forces homodyne vs. heterodyne processing. Exactly one profile is
    active at a time — that's the one LoadMatchTab's "Auto-match Files"
    button actually uses.
    """

    def __init__(self, manager: MatchingProfileManager, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Auto-Matching Parameters")
        self.resize(820, 750)
        self._manager = manager
        self._tree: list[dict] = copy.deepcopy(manager.tree)
        self._current_leaf_id: str | None = None

        self._build_ui()
        self._tree_widget.set_tree(self._tree)

        self._update_role_box_visibility()
        self._set_editor_enabled(False)

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        outer = QVBoxLayout(self)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        outer.addWidget(splitter)

        splitter.addWidget(self._build_tree_pane())

        self._toolbox = QToolBox()

        def add_page(box: QGroupBox):
            title = box.title()
            box.setTitle("")   # QToolBox already shows a page header — avoid double title
            self._toolbox.addItem(box, title)

        add_page(self._build_reference_names_box())
        add_page(self._build_role_box())
        add_page(self._build_type_rules_box())
        add_page(self._build_fields_box())

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._toolbox)
        splitter.addWidget(scroll)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        self._button_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        self._button_box.accepted.connect(self._on_ok)
        self._button_box.rejected.connect(self.reject)
        outer.addWidget(self._button_box)

    def _build_tree_pane(self) -> QWidget:
        pane = QWidget()
        layout = QVBoxLayout(pane)
        layout.addWidget(QLabel("Saved profiles:"))

        self._tree_widget = PresetTreeWidget(
            leaf_data_factory=lambda: MatchingSettings().to_dict(),
            new_leaf_name="New Profile",
        )
        self._tree_widget.leafSelected.connect(self._on_leaf_selected)
        layout.addWidget(self._tree_widget)

        self._set_active_btn = QPushButton("★ Set Active")
        self._set_active_btn.clicked.connect(self._on_set_active)
        layout.addWidget(self._set_active_btn)

        return pane

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

        priority_label = QLabel(
            "Preferred background role order, when more than one background "
            "matches the same signal (first = highest priority, "
            "comma-separated; blank = no preference). The spectrum type is "
            "guessed from the signal alone (via the rules in \"Force "
            "homodyne / heterodyne processing\") before a background is "
            "picked:"
        )
        priority_label.setWordWrap(True)
        box_layout.addWidget(priority_label)

        self._role_priority_table = QTableWidget(len(TYPE_RULE_TYPES), 2)
        self._role_priority_table.setHorizontalHeaderLabels(
            ["Spectrum type", "Preferred role order"]
        )
        self._role_priority_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self._role_priority_table.verticalHeader().setVisible(False)
        for row, spectrum_type in enumerate(TYPE_RULE_TYPES):
            type_item = QTableWidgetItem(spectrum_type.capitalize())
            type_item.setFlags(type_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._role_priority_table.setItem(row, 0, type_item)
            self._role_priority_table.setItem(row, 1, QTableWidgetItem(""))
        box_layout.addWidget(self._role_priority_table)

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
        move_rule_up_btn = QPushButton("↑ Move Up")
        move_rule_down_btn = QPushButton("↓ Move Down")
        add_rule_btn.clicked.connect(self._on_add_type_rule)
        remove_rule_btn.clicked.connect(self._on_remove_type_rule)
        move_rule_up_btn.clicked.connect(self._on_move_rule_up)
        move_rule_down_btn.clicked.connect(self._on_move_rule_down)
        rules_btn_row.addWidget(add_rule_btn)
        rules_btn_row.addWidget(remove_rule_btn)
        rules_btn_row.addWidget(move_rule_up_btn)
        rules_btn_row.addWidget(move_rule_down_btn)
        rules_btn_row.addStretch()
        box_layout.addLayout(rules_btn_row)
        return self._rules_box

    def _build_fields_box(self) -> QGroupBox:
        self._fields_box = QGroupBox("Metadata matching rules")
        box_layout = QVBoxLayout(self._fields_box)
        fields_label = QLabel(
            "Metadata fields used to match a signal to its background/reference — "
            "Required must match exactly. Optional prefers a match but is skipped "
            "if no candidate matches. Closest picks the nearest numeric/date value; "
            "Highest picks the largest numeric value (independent of the signal's "
            "own value) — both in priority order (top row highest priority; use "
            "↑/↓ to reorder — a higher Closest/Highest field fully decides "
            "the match before a lower one is ever consulted). This order is shared "
            "between the Background and Reference columns. Unit-suffixed values "
            "(e.g. \"30kHz\", \"3.4um\", \"0.1V\") compare on their numeric part, "
            "ignoring the unit:"
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
        move_up_btn = QPushButton("↑ Move Up")
        move_up_btn.clicked.connect(self._on_move_field_up)
        move_down_btn = QPushButton("↓ Move Down")
        move_down_btn.clicked.connect(self._on_move_field_down)
        add_field_row.addWidget(add_field_btn)
        add_field_row.addWidget(remove_field_btn)
        add_field_row.addWidget(move_up_btn)
        add_field_row.addWidget(move_down_btn)
        add_field_row.addStretch()
        box_layout.addLayout(add_field_row)
        return self._fields_box

    # ── Profile tree ──────────────────────────────────────────────────────────

    def _set_editor_enabled(self, enabled: bool):
        for box in (self._ref_box, self._role_box, self._rules_box, self._fields_box):
            box.setEnabled(enabled)

    def _on_leaf_selected(self, leaf_id: str | None):
        if self._current_leaf_id is not None:
            self._save_editor_to_leaf(self._current_leaf_id)

        self._current_leaf_id = leaf_id
        if leaf_id is None:
            self._set_editor_enabled(False)
            return

        leaf = find_node(self._tree, leaf_id)
        if leaf is None:
            self._set_editor_enabled(False)
            return

        self._set_editor_enabled(True)
        self._load_leaf_data(leaf["data"])

    def _save_editor_to_leaf(self, leaf_id: str):
        leaf = find_node(self._tree, leaf_id)
        if leaf is not None:
            leaf["data"] = self._collect_leaf_data()

    def _on_set_active(self):
        leaf_id = self._tree_widget.current_leaf_id()
        if leaf_id is None:
            QMessageBox.information(self, "Nothing selected", "Select a profile first.")
            return
        for leaf in iter_leaves(self._tree):
            leaf["active"] = (leaf["id"] == leaf_id)
        self._tree_widget.refresh_labels()

    def _load_leaf_data(self, data: dict):
        settings = MatchingSettings.from_dict(data)
        self._populate_reference_names(settings)
        self._populate_role_box(settings)
        self._populate_type_rules(settings)
        self._populate_fields_table(settings)

    def _collect_leaf_data(self) -> dict:
        role_mode = ROLE_MODE_TO_INTERNAL.get(self._role_mode_combo.currentText(), "suffix")
        role_field = self._role_field_combo.currentText().strip()
        role_values = []
        seen_role_values = set()
        for i in range(self._role_values_list.count()):
            text = self._role_values_list.item(i).text().strip()
            if text and text.lower() not in seen_role_values:
                role_values.append(text)
                seen_role_values.add(text.lower())

        role_priority = {}
        for row, spectrum_type in enumerate(TYPE_RULE_TYPES):
            text = self._role_priority_table.item(row, 1).text().strip()
            tokens = [t.strip() for t in text.split(",") if t.strip()]
            if tokens:
                role_priority[spectrum_type] = tokens

        names = []
        seen = set()
        for i in range(self._ref_list.count()):
            text = self._ref_list.item(i).text().strip()
            if text and text.lower() not in seen:
                names.append(text)
                seen.add(text.lower())

        bg_required, bg_optional, bg_closest, bg_highest = [], [], [], []
        ref_required, ref_optional, ref_closest, ref_highest = [], [], [], []
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
            elif bg_state == "Highest":
                bg_highest.append(field)
            if ref_state == "Required":
                ref_required.append(field)
            elif ref_state == "Optional":
                ref_optional.append(field)
            elif ref_state == "Closest":
                ref_closest.append(field)
            elif ref_state == "Highest":
                ref_highest.append(field)

        return {
            "reference_names": names,
            "type_rules": self._collect_type_rules(),
            "background_role_mode": role_mode,
            "background_role_field": role_field,
            "background_role_values": role_values,
            "background_role_priority": role_priority,
            "background_required_keys": bg_required,
            "background_optional_keys": bg_optional,
            "background_closest_keys": bg_closest,
            "background_highest_keys": bg_highest,
            "reference_required_keys": ref_required,
            "reference_optional_keys": ref_optional,
            "reference_closest_keys": ref_closest,
            "reference_highest_keys": ref_highest,
        }

    # ── Reference names ──────────────────────────────────────────────────────

    def _populate_reference_names(self, settings: MatchingSettings):
        self._ref_list.clear()
        for name in settings.reference_names:
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

    def _populate_role_box(self, settings: MatchingSettings):
        self._role_mode_combo.setCurrentText(
            ROLE_MODE_FROM_INTERNAL.get(settings.background_role_mode, ROLE_MODE_OPTIONS[0])
        )
        self._role_field_combo.setCurrentText(settings.background_role_field or DEFAULT_RULE_FIELD)
        self._role_values_list.clear()
        for value in settings.background_role_values:
            item = QListWidgetItem(value)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
            self._role_values_list.addItem(item)
        for row, spectrum_type in enumerate(TYPE_RULE_TYPES):
            order = settings.background_role_priority.get(spectrum_type, [])
            self._role_priority_table.item(row, 1).setText(", ".join(order))
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

    def _populate_type_rules(self, settings: MatchingSettings):
        self._rules_table.setRowCount(0)
        for rule in settings.type_rules:
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

    def _swap_rule_rows(self, row_a: int, row_b: int):
        field_a = self._rules_table.cellWidget(row_a, 0).currentText()
        field_b = self._rules_table.cellWidget(row_b, 0).currentText()
        key_a = self._rules_table.item(row_a, 1).text()
        key_b = self._rules_table.item(row_b, 1).text()
        type_a = self._rules_table.cellWidget(row_a, 2).currentText()
        type_b = self._rules_table.cellWidget(row_b, 2).currentText()
        scope_a = self._rules_table.cellWidget(row_a, 3).currentText()
        scope_b = self._rules_table.cellWidget(row_b, 3).currentText()
        self._rules_table.cellWidget(row_a, 0).setCurrentText(field_b)
        self._rules_table.cellWidget(row_b, 0).setCurrentText(field_a)
        self._rules_table.item(row_a, 1).setText(key_b)
        self._rules_table.item(row_b, 1).setText(key_a)
        self._rules_table.cellWidget(row_a, 2).setCurrentText(type_b)
        self._rules_table.cellWidget(row_b, 2).setCurrentText(type_a)
        self._rules_table.cellWidget(row_a, 3).setCurrentText(scope_b)
        self._rules_table.cellWidget(row_b, 3).setCurrentText(scope_a)

    def _on_move_rule_up(self):
        row = self._rules_table.currentRow()
        if row > 0:
            self._swap_rule_rows(row, row - 1)
            self._rules_table.setCurrentCell(row - 1, 0)

    def _on_move_rule_down(self):
        row = self._rules_table.currentRow()
        if 0 <= row < self._rules_table.rowCount() - 1:
            self._swap_rule_rows(row, row + 1)
            self._rules_table.setCurrentCell(row + 1, 0)

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
                    optional_keys: list[str], closest_keys: list[str],
                    highest_keys: list[str]) -> str:
        if field in required_keys:
            return "Required"
        if field in optional_keys:
            return "Optional"
        if field in closest_keys:
            return "Closest"
        if field in highest_keys:
            return "Highest"
        return "Ignore"

    def _populate_fields_table(self, settings: MatchingSettings):
        # Row order encodes tie-break priority (top row = highest priority)
        # for Closest/Highest, and actual cascade priority for Optional
        # (Matcher._find_closest applies optional_keys as a cascading,
        # order-sensitive filter, not an order-independent preference) — so
        # every per-role key list's saved order must round-trip, not just
        # Closest/Highest, or reopening-then-OK can silently rewrite a
        # profile's real matching priority to KNOWN_FIELDS order.
        # A list with only one entry carries no real order information, so
        # don't let it force its field ahead of a longer list's carefully
        # (re)ordered fields — process longer lists first (stable sort, so
        # ties keep the bg/ref required/optional/closest/highest order).
        key_lists = (
            settings.background_required_keys, settings.background_optional_keys,
            settings.background_closest_keys, settings.background_highest_keys,
            settings.reference_required_keys, settings.reference_optional_keys,
            settings.reference_closest_keys, settings.reference_highest_keys,
        )
        ordered: list[str] = []
        seen: set[str] = set()
        for key_list in sorted(key_lists, key=len, reverse=True):
            for f in key_list:
                if f not in seen:
                    ordered.append(f)
                    seen.add(f)

        fields = list(ordered)
        for f in KNOWN_FIELDS:
            if f not in seen:
                fields.append(f)
                seen.add(f)

        self._fields_table.setRowCount(0)
        for field in fields:
            self._add_field_row(
                field,
                self._state_for(field, settings.background_required_keys,
                                 settings.background_optional_keys, settings.background_closest_keys,
                                 settings.background_highest_keys),
                self._state_for(field, settings.reference_required_keys,
                                 settings.reference_optional_keys, settings.reference_closest_keys,
                                 settings.reference_highest_keys),
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

    def _swap_field_rows(self, row_a: int, row_b: int):
        field_a = self._fields_table.item(row_a, 0).text()
        field_b = self._fields_table.item(row_b, 0).text()
        bg_a = self._fields_table.cellWidget(row_a, 1).currentText()
        bg_b = self._fields_table.cellWidget(row_b, 1).currentText()
        ref_a = self._fields_table.cellWidget(row_a, 2).currentText()
        ref_b = self._fields_table.cellWidget(row_b, 2).currentText()
        self._fields_table.item(row_a, 0).setText(field_b)
        self._fields_table.item(row_b, 0).setText(field_a)
        self._fields_table.cellWidget(row_a, 1).setCurrentText(bg_b)
        self._fields_table.cellWidget(row_b, 1).setCurrentText(bg_a)
        self._fields_table.cellWidget(row_a, 2).setCurrentText(ref_b)
        self._fields_table.cellWidget(row_b, 2).setCurrentText(ref_a)

    def _on_move_field_up(self):
        row = self._fields_table.currentRow()
        if row > 0:
            self._swap_field_rows(row, row - 1)
            self._fields_table.setCurrentCell(row - 1, 0)

    def _on_move_field_down(self):
        row = self._fields_table.currentRow()
        if 0 <= row < self._fields_table.rowCount() - 1:
            self._swap_field_rows(row, row + 1)
            self._fields_table.setCurrentCell(row + 1, 0)

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
        if role_mode == "field" and not role_field and self._current_leaf_id is not None:
            QMessageBox.warning(
                self, "Missing Field",
                "Choose a metadata field for background role detection, or "
                "switch to filename suffix/prefix detection."
            )
            return

        if self._current_leaf_id is not None:
            self._save_editor_to_leaf(self._current_leaf_id)

        self._manager._tree = self._tree
        self._manager.save()
        self.accept()
