from __future__ import annotations
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QComboBox, QLineEdit, QPushButton, QCheckBox, QColorDialog, QDialogButtonBox,
    QLabel, QWidget,
)

from sfg_app2.app.tabs.processed_results import TraceStyle, _LINESTYLE_CHOICES

_LINESTYLE_NAMES = [name for name, _ in _LINESTYLE_CHOICES]
_LINESTYLE_BY_NAME = dict(_LINESTYLE_CHOICES)
_LINESTYLE_BY_VALUE = {value: name for name, value in _LINESTYLE_CHOICES}
_AXES = ["Primary", "Secondary"]

_COL_LABEL, _COL_COLOR, _COL_LINESTYLE, _COL_AXIS, _COL_VISIBLE = range(1, 6)


class TraceStyleDialog(QDialog):
    """Per-component trace styling for a single SpectrumEntry — one row per
    plotted component (just one for homodyne, up to four for heterodyne).
    """

    def __init__(self, entry_label: str, components: list[tuple[str, str]],
                 styles: dict[str, TraceStyle], parent=None):
        """`components` is a list of (style_key, display_name) pairs.
        `styles` is the entry's live styles dict — edited in place only on OK."""
        super().__init__(parent)
        self.setWindowTitle(f"Trace properties — {entry_label}")
        self._styles = styles
        self._components = components
        self._colors: dict[str, str] = {}   # style_key -> current color hex (or "" for auto)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Leave label blank / color unset to use automatic values."))

        self._table = QTableWidget(len(components), 6, self)
        self._table.setHorizontalHeaderLabels(
            ["Component", "Label", "Color", "Line style", "Axis", "Visible"]
        )
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setStretchLastSection(False)
        layout.addWidget(self._table)

        for row, (key, display_name) in enumerate(components):
            style = styles.get(key, TraceStyle())

            name_item = QTableWidgetItem(display_name)
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._table.setItem(row, 0, name_item)

            label_edit = QLineEdit(style.label or "")
            self._table.setCellWidget(row, _COL_LABEL, label_edit)

            self._colors[key] = style.color or ""
            color_btn = QPushButton()
            color_btn.setFixedWidth(60)
            self._style_color_button(color_btn, style.color)
            color_btn.clicked.connect(lambda _checked, k=key, b=color_btn: self._on_pick_color(k, b))
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

    def _style_color_button(self, button: QPushButton, color: str | None):
        if color:
            button.setStyleSheet(f"background-color: {color};")
            button.setText("")
        else:
            button.setStyleSheet("")
            button.setText("Auto")

    def _on_pick_color(self, key: str, button: QPushButton):
        current = self._colors.get(key) or "#ffffff"
        chosen = QColorDialog.getColor(QColor(current), self, "Trace color")
        if chosen.isValid():
            self._colors[key] = chosen.name()
            self._style_color_button(button, chosen.name())

    def _on_reset_all(self):
        for row, (key, _display_name) in enumerate(self._components):
            self._table.cellWidget(row, _COL_LABEL).setText("")
            self._colors[key] = ""
            self._style_color_button(self._table.cellWidget(row, _COL_COLOR), None)
            self._table.cellWidget(row, _COL_LINESTYLE).setCurrentText("Solid")
            self._table.cellWidget(row, _COL_AXIS).setCurrentText("Primary")
            self._table.cellWidget(row, _COL_VISIBLE).findChild(QCheckBox).setChecked(True)

    def _on_ok(self):
        for row, (key, _display_name) in enumerate(self._components):
            label = self._table.cellWidget(row, _COL_LABEL).text().strip()
            linestyle_name = self._table.cellWidget(row, _COL_LINESTYLE).currentText()
            axis_name = self._table.cellWidget(row, _COL_AXIS).currentText()
            visible = self._table.cellWidget(row, _COL_VISIBLE).findChild(QCheckBox).isChecked()
            self._styles[key] = TraceStyle(
                color=self._colors.get(key) or None,
                linestyle=_LINESTYLE_BY_NAME.get(linestyle_name, "-"),
                axis="secondary" if axis_name == "Secondary" else "primary",
                label=label or None,
                visible=visible,
            )
        self.accept()
