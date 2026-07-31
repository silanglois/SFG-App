from __future__ import annotations
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QCheckBox, QComboBox,
    QStackedWidget, QListWidget, QListWidgetItem, QLabel, QDialogButtonBox,
)

from sfg_app2.app.utils.color_coding_settings import ColorCodingSettings

_MODES = ["single", "multiple", "role"]
_SCOPES = ["file_list", "match_table", "both"]


class ColorCodingSettingsDialog(QDialog):
    """Preferences dialog for the Load/Match tab's filename color-coding."""

    def __init__(self, settings: ColorCodingSettings, available_fields: list[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Filename color-coding")
        self._settings = settings

        layout = QVBoxLayout(self)

        self._enable_check = QCheckBox("Color-code filenames by metadata")
        self._enable_check.setChecked(settings.enabled)
        layout.addWidget(self._enable_check)

        form = QFormLayout()
        layout.addLayout(form)

        self._mode_combo = QComboBox()
        self._mode_combo.addItems(["Single field", "Multiple fields", "Role (signal/background)"])
        form.addRow("Group by:", self._mode_combo)

        self._single_field_combo = QComboBox()
        self._single_field_combo.addItems(available_fields)

        self._multi_list = QListWidget()
        for field in available_fields:
            item = QListWidgetItem(field)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if field in settings.fields else Qt.CheckState.Unchecked
            )
            self._multi_list.addItem(item)

        self._role_label = QLabel("Groups every file as Signal or Background.")

        self._stack = QStackedWidget()
        self._stack.addWidget(self._single_field_combo)
        self._stack.addWidget(self._multi_list)
        self._stack.addWidget(self._role_label)
        form.addRow(self._stack)

        self._scope_combo = QComboBox()
        self._scope_combo.addItems(["File list", "Matched-sets table", "Both"])
        form.addRow("Apply to:", self._scope_combo)

        # restore current mode/fields/scope
        mode_idx = _MODES.index(settings.mode) if settings.mode in _MODES else 0
        self._mode_combo.setCurrentIndex(mode_idx)
        self._stack.setCurrentIndex(mode_idx)
        if settings.mode == "single" and settings.fields and settings.fields[0] in available_fields:
            self._single_field_combo.setCurrentText(settings.fields[0])
        scope_idx = _SCOPES.index(settings.scope) if settings.scope in _SCOPES else 0
        self._scope_combo.setCurrentIndex(scope_idx)

        self._enable_check.toggled.connect(self._update_enabled_state)
        self._mode_combo.currentIndexChanged.connect(self._stack.setCurrentIndex)
        self._update_enabled_state(settings.enabled)

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self._on_ok)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def _update_enabled_state(self, checked: bool):
        self._mode_combo.setEnabled(checked)
        self._stack.setEnabled(checked)
        self._scope_combo.setEnabled(checked)

    def _on_ok(self):
        self._settings.enabled = self._enable_check.isChecked()
        self._settings.mode = _MODES[self._mode_combo.currentIndex()]

        if self._settings.mode == "single":
            self._settings.fields = (
                [self._single_field_combo.currentText()] if self._single_field_combo.count() else []
            )
        elif self._settings.mode == "multiple":
            self._settings.fields = [
                self._multi_list.item(i).text()
                for i in range(self._multi_list.count())
                if self._multi_list.item(i).checkState() == Qt.CheckState.Checked
            ]
        else:
            self._settings.fields = []

        self._settings.scope = _SCOPES[self._scope_combo.currentIndex()]
        self._settings.save()
        self.accept()
