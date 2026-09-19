from __future__ import annotations
import logging
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QLabel, QListWidget, QListWidgetItem,
    QVBoxLayout,
)

from sfg_app2.app.utils.settings_bundle import PARTS, available_parts

logger = logging.getLogger(__name__)


class SettingsBundleDialog(QDialog):
    """Pick which parts of the configuration to export or import.

    On import the list is what the bundle actually contains, and the
    warning is explicit: a part is replaced wholesale, not merged.
    """

    def __init__(self, mode: str, part_keys: list[str] | None = None, parent=None):
        super().__init__(parent)
        exporting = mode == "export"
        self.setWindowTitle("Export settings" if exporting else "Import settings")
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "Choose what to include. The bundle is a single file you can "
            "hand to someone else."
            if exporting else
            "Choose what to restore. Each part is replaced completely, "
            "not merged with what you have now."
        ))

        labels = {part.key: part.label for part in PARTS}
        keys = ([p.key for p in available_parts()] if exporting
                else list(part_keys or []))

        self._list = QListWidget()
        for key in keys:
            item = QListWidgetItem(labels.get(key, key))
            item.setData(Qt.ItemDataRole.UserRole, key)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            self._list.addItem(item)
        layout.addWidget(self._list)

        if not keys:
            layout.addWidget(QLabel(
                "Nothing to export yet — no settings have been saved."
                if exporting else "This bundle is empty."
            ))

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_keys(self) -> list[str]:
        return [
            self._list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self._list.count())
            if self._list.item(i).checkState() == Qt.CheckState.Checked
        ]
