from __future__ import annotations
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QRadioButton, QButtonGroup,
    QListWidget, QListWidgetItem, QPushButton, QAbstractItemView,
    QDialogButtonBox,
)


class LegendFieldsDialog(QDialog):
    """Lets the user pick what a Spectra Library legend label is built
    from: the filename, no legend at all, or an ordered combination of
    metadata fields (e.g. "Polarization - Date"). Filename/None are
    exclusive of everything else (each is its own radio choice);
    combined fields are checked+reordered in a drag-and-drop list,
    mirroring MetadataPatternsDialog's field-ordering pattern.
    """

    def __init__(self, current_fields: list[str], available_fields: list[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Legend fields")
        self._result_fields: list[str] = list(current_fields)

        layout = QVBoxLayout(self)

        self._filename_radio = QRadioButton("Filename")
        self._none_radio = QRadioButton("None (no legend)")
        self._custom_radio = QRadioButton("Combine metadata fields:")
        self._mode_group = QButtonGroup(self)
        for radio in (self._filename_radio, self._none_radio, self._custom_radio):
            self._mode_group.addButton(radio)
            layout.addWidget(radio)

        self._fields_list = QListWidget()
        self._fields_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self._fields_list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self._fields_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        layout.addWidget(self._fields_list)

        move_row = QHBoxLayout()
        self._up_button = QPushButton("Move Up")
        self._down_button = QPushButton("Move Down")
        move_row.addWidget(self._up_button)
        move_row.addWidget(self._down_button)
        move_row.addStretch()
        layout.addLayout(move_row)

        hint = QLabel('Checked fields are combined in this order, joined with " - ".')
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self._populate_fields_list(current_fields, available_fields)

        if current_fields == ["Filename"]:
            self._filename_radio.setChecked(True)
        elif current_fields == ["None"]:
            self._none_radio.setChecked(True)
        elif current_fields:
            self._custom_radio.setChecked(True)
        else:
            self._filename_radio.setChecked(True)

        self._mode_group.buttonToggled.connect(self._update_enabled_state)
        self._update_enabled_state()

        self._up_button.clicked.connect(lambda: self._move_current(-1))
        self._down_button.clicked.connect(lambda: self._move_current(1))

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self._on_ok)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def _populate_fields_list(self, current_fields: list[str], available_fields: list[str]):
        # Checked fields first, in their current combined order, so
        # reopening the dialog shows exactly what's currently applied.
        ordered = [f for f in current_fields if f in available_fields]
        ordered += [f for f in available_fields if f not in ordered]
        self._fields_list.clear()
        for field in ordered:
            item = QListWidgetItem(field)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if field in current_fields else Qt.CheckState.Unchecked
            )
            self._fields_list.addItem(item)

    def _update_enabled_state(self, *_args):
        enabled = self._custom_radio.isChecked()
        self._fields_list.setEnabled(enabled)
        self._up_button.setEnabled(enabled)
        self._down_button.setEnabled(enabled)

    def _move_current(self, delta: int):
        lw = self._fields_list
        row = lw.currentRow()
        new_row = row + delta
        if row < 0 or not (0 <= new_row < lw.count()):
            return
        item = lw.takeItem(row)
        lw.insertItem(new_row, item)
        lw.setCurrentItem(item)

    def _on_ok(self):
        if self._filename_radio.isChecked():
            self._result_fields = ["Filename"]
        elif self._none_radio.isChecked():
            self._result_fields = ["None"]
        else:
            checked = [
                self._fields_list.item(i).text()
                for i in range(self._fields_list.count())
                if self._fields_list.item(i).checkState() == Qt.CheckState.Checked
            ]
            self._result_fields = checked or ["Filename"]
        self.accept()

    def result_fields(self) -> list[str]:
        return self._result_fields
