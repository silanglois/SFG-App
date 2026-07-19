from __future__ import annotations
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QAbstractItemView
from PySide6.QtCore import Qt, QMimeData, QByteArray
from PySide6.QtGui import QDrag, QColor, QFont

MIME_FILE = "application/sfg-app-file"


class FileListWidget(QListWidget):
    """Drag-enabled file list with visual used/unused marking."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._used_paths: set[str] = set()

    def add_file(self, path: str, display_name: str):
        item = QListWidgetItem(display_name)
        item.setData(Qt.ItemDataRole.UserRole, path)
        self.addItem(item)

    def set_files(self, files: list):
        """Repopulate from a list of DataFile objects."""
        self.clear()
        self._used_paths.clear()
        for f in files:
            self.add_file(str(f.path), f.path.name)

    def mark_used(self, path: str):
        self._used_paths.add(path)
        self._update_item_style(path)

    def mark_unused(self, path: str):
        self._used_paths.discard(path)
        self._update_item_style(path)

    def sync_used(self, used_paths: set[str]):
        """Sync all used markers at once — call after any table change."""
        for i in range(self.count()):
            item = self.item(i)
            path = item.data(Qt.ItemDataRole.UserRole)
            old_used = path in self._used_paths
            new_used = path in used_paths
            if old_used != new_used:
                if new_used:
                    self._used_paths.add(path)
                else:
                    self._used_paths.discard(path)
                self._apply_style(item, new_used)

    def _update_item_style(self, path: str):
        for i in range(self.count()):
            item = self.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == path:
                self._apply_style(item, path in self._used_paths)

    @staticmethod
    def _apply_style(item: QListWidgetItem, used: bool):
        item.setForeground(QColor(150, 150, 150) if used else QColor(0, 0, 0))
        font = item.font()
        font.setItalic(used)
        item.setFont(font)

    def startDrag(self, supported_actions):
        item = self.currentItem()
        if item is None:
            return
        path = item.data(Qt.ItemDataRole.UserRole)
        mime = QMimeData()
        mime.setData(MIME_FILE, QByteArray(path.encode()))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.CopyAction)