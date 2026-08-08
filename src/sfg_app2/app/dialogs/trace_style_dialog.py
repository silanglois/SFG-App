from __future__ import annotations
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QComboBox, QLineEdit, QPushButton, QCheckBox, QColorDialog, QDialogButtonBox,
    QLabel, QWidget, QMenu,
)

from sfg_app2.app.tabs.processed_results import TraceStyle, _LINESTYLE_CHOICES

_LINESTYLE_NAMES = [name for name, _ in _LINESTYLE_CHOICES]
_LINESTYLE_BY_NAME = dict(_LINESTYLE_CHOICES)
_LINESTYLE_BY_VALUE = {value: name for name, value in _LINESTYLE_CHOICES}
_AXES = ["Primary", "Secondary"]

_COL_ENTRY, _COL_COMPONENT, _COL_LABEL, _COL_COLOR, _COL_LINESTYLE, _COL_AXIS, _COL_VISIBLE = range(7)
_EDITABLE_COLS = {_COL_LABEL, _COL_COLOR, _COL_LINESTYLE, _COL_AXIS, _COL_VISIBLE}


class TraceStyleDialog(QDialog):
    """Per-component trace styling for one or more selected SpectrumEntry
    objects — one row per (entry, component) pair (one component row for a
    homodyne entry, up to four for a heterodyne entry), all editable
    together regardless of how many files are selected.
    """

    def __init__(self, rows: list[tuple[object, str, str]], parent=None):
        """`rows` is a list of (entry, style_key, display_name) triples —
        entry is a SpectrumEntry (duck-typed: needs .label and .styles)."""
        super().__init__(parent)
        self._rows = rows
        n_entries = len({id(entry) for entry, _key, _name in rows})
        title = rows[0][0].label if n_entries == 1 else f"{n_entries} files"
        self.setWindowTitle(f"Trace properties — {title}")
        self.resize(640, 320)
        self._colors: dict[int, str] = {}   # row -> current color hex (or "" for auto)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "Leave label blank / color unset to use automatic values. "
            "Right-click a cell to reset just that field, or a whole row."
        ))

        self._table = QTableWidget(len(rows), 7, self)
        self._table.setHorizontalHeaderLabels(
            ["File", "Component", "Label", "Color", "Line style", "Axis", "Visible"]
        )
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setStretchLastSection(False)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._on_table_context_menu)
        layout.addWidget(self._table)

        for row, (entry, key, display_name) in enumerate(rows):
            style = entry.styles.get(key, TraceStyle())
            self._init_row(row, entry.label, display_name, style)

        self._table.resizeColumnsToContents()

        reset_row = QHBoxLayout()
        reset_btn = QPushButton("Reset all to auto")
        reset_btn.clicked.connect(self._on_reset_all)
        reset_row.addWidget(reset_btn)
        reset_row.addStretch()
        layout.addLayout(reset_row)

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self._on_ok)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    # ── Row construction ─────────────────────────────────────────────────────

    def _init_row(self, row: int, entry_label: str, display_name: str, style: TraceStyle):
        entry_item = QTableWidgetItem(entry_label)
        entry_item.setFlags(entry_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self._table.setItem(row, _COL_ENTRY, entry_item)

        name_item = QTableWidgetItem(display_name)
        name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self._table.setItem(row, _COL_COMPONENT, name_item)

        label_edit = QLineEdit(style.label or "")
        self._table.setCellWidget(row, _COL_LABEL, label_edit)

        self._colors[row] = style.color or ""
        color_btn = QPushButton()
        color_btn.setFixedWidth(60)
        self._style_color_button(color_btn, style.color)
        color_btn.clicked.connect(lambda _checked, r=row, b=color_btn: self._on_pick_color(r, b))
        self._table.setCellWidget(row, _COL_COLOR, color_btn)

        style_combo = QComboBox()
        style_combo.addItems(_LINESTYLE_NAMES)
        style_combo.setCurrentText(_LINESTYLE_BY_VALUE.get(style.linestyle, "Solid"))
        self._table.setCellWidget(row, _COL_LINESTYLE, style_combo)

        axis_combo = QComboBox()
        axis_combo.addItems(_AXES)
        axis_combo.setCurrentText("Secondary" if style.axis == "secondary" else "Primary")
        self._table.setCellWidget(row, _COL_AXIS, axis_combo)

        visible_check = QCheckBox()
        visible_check.setChecked(style.visible)
        cell = QHBoxLayout()
        cell.setContentsMargins(0, 0, 0, 0)
        cell.setAlignment(Qt.AlignmentFlag.AlignCenter)
        holder = QWidget()
        cell.addWidget(visible_check)
        holder.setLayout(cell)
        self._table.setCellWidget(row, _COL_VISIBLE, holder)

    def _style_color_button(self, button: QPushButton, color: str | None):
        if color:
            button.setStyleSheet(f"background-color: {color};")
            button.setText("")
        else:
            button.setStyleSheet("")
            button.setText("Auto")

    def _visible_checkbox(self, row: int) -> QCheckBox:
        return self._table.cellWidget(row, _COL_VISIBLE).findChild(QCheckBox)

    # ── Color picking ─────────────────────────────────────────────────────────

    def _on_pick_color(self, row: int, button: QPushButton):
        current = self._colors.get(row) or "#ffffff"
        chosen = QColorDialog.getColor(QColor(current), self, "Trace color")
        if chosen.isValid():
            self._colors[row] = chosen.name()
            self._style_color_button(button, chosen.name())

    # ── Reset (bulk / per-row / per-field) ─────────────────────────────────────

    def _reset_field(self, row: int, col: int):
        if col == _COL_LABEL:
            self._table.cellWidget(row, _COL_LABEL).setText("")
        elif col == _COL_COLOR:
            self._colors[row] = ""
            self._style_color_button(self._table.cellWidget(row, _COL_COLOR), None)
        elif col == _COL_LINESTYLE:
            self._table.cellWidget(row, _COL_LINESTYLE).setCurrentText("Solid")
        elif col == _COL_AXIS:
            self._table.cellWidget(row, _COL_AXIS).setCurrentText("Primary")
        elif col == _COL_VISIBLE:
            self._visible_checkbox(row).setChecked(True)

    def _reset_row(self, row: int):
        for col in _EDITABLE_COLS:
            self._reset_field(row, col)

    def _on_reset_all(self):
        for row in range(self._table.rowCount()):
            self._reset_row(row)

    def _on_table_context_menu(self, pos):
        index = self._table.indexAt(pos)
        if not index.isValid():
            return
        row, col = index.row(), index.column()

        menu = QMenu(self)
        field_action = None
        if col in _EDITABLE_COLS:
            field_action = menu.addAction("Reset field")
        row_action = menu.addAction("Reset row")

        action = menu.exec(self._table.viewport().mapToGlobal(pos))
        if field_action is not None and action == field_action:
            self._reset_field(row, col)
        elif action == row_action:
            self._reset_row(row)

    # ── Commit ───────────────────────────────────────────────────────────────

    def _on_ok(self):
        for row, (entry, key, _display_name) in enumerate(self._rows):
            label = self._table.cellWidget(row, _COL_LABEL).text().strip()
            linestyle_name = self._table.cellWidget(row, _COL_LINESTYLE).currentText()
            axis_name = self._table.cellWidget(row, _COL_AXIS).currentText()
            visible = self._visible_checkbox(row).isChecked()
            entry.styles[key] = TraceStyle(
                color=self._colors.get(row) or None,
                linestyle=_LINESTYLE_BY_NAME.get(linestyle_name, "-"),
                axis="secondary" if axis_name == "Secondary" else "primary",
                label=label or None,
                visible=visible,
            )
        self.accept()
