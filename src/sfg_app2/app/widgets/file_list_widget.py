from __future__ import annotations
from PySide6.QtWidgets import (
    QListWidget, QListWidgetItem, QAbstractItemView, QMenu, QApplication
)
from PySide6.QtCore import Qt, QMimeData, QByteArray, Signal
from PySide6.QtGui import QDrag, QFont, QBrush, QPalette

from sfg_app2.app.utils import color_coding

MIME_FILE = "application/sfg-app-file"
_METADATA_ROLE = Qt.ItemDataRole.UserRole + 1


class FileListWidget(QListWidget):
    remove_requested = Signal(list)    # list of path strings
    metadata_requested = Signal(list)
    plot_requested = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._used_paths: set[str] = set()
        self._color_settings = None   # ColorCodingSettings, set via set_color_coding_settings()
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)

    def set_color_coding_settings(self, settings):
        self._color_settings = settings

    # ── Context menu ──────────────────────────────────────────────────────────

    def _on_context_menu(self, pos):
        selected = self._selected_paths()
        if not selected:
            return
        n = len(selected)
        label = f"{n} file{'s' if n > 1 else ''}"

        menu = QMenu(self)
        plot_action = menu.addAction(f"Plot {label}")
        metadata_action = menu.addAction(f"Review/Edit metadata — {label}")
        menu.addSeparator()
        remove_action = menu.addAction(f"Remove {label}")

        action = menu.exec(self.viewport().mapToGlobal(pos))
        if action == plot_action:
            self.plot_requested.emit(selected)
        elif action == metadata_action:
            self.metadata_requested.emit(selected)
        elif action == remove_action:
            self.remove_requested.emit(selected)

    def _selected_paths(self) -> list[str]:
        return [
            item.data(Qt.ItemDataRole.UserRole)
            for item in self.selectedItems()
        ]

    # ── File management (unchanged from before) ───────────────────────────────

    def add_file(self, path: str, display_name: str, metadata: dict | None = None):
        item = QListWidgetItem(display_name)
        item.setData(Qt.ItemDataRole.UserRole, path)
        item.setData(_METADATA_ROLE, metadata or {})
        self.addItem(item)
        self._apply_style(item, path in self._used_paths, metadata or {}, self._color_settings)

    def set_files(self, files: list):
        self.clear()
        self._used_paths.clear()
        for f in files:
            self.add_file(str(f.path), f.path.name, getattr(f, "metadata", None))

    def refresh_colors(self):
        """Re-apply item styling (e.g. after color-coding settings change)
        without rebuilding the list."""
        for i in range(self.count()):
            item = self.item(i)
            path = item.data(Qt.ItemDataRole.UserRole)
            metadata = item.data(_METADATA_ROLE) or {}
            self._apply_style(item, path in self._used_paths, metadata, self._color_settings)

    def mark_used(self, path: str):
        self._used_paths.add(path)
        self._update_item_style(path)

    def mark_unused(self, path: str):
        self._used_paths.discard(path)
        self._update_item_style(path)

    def sync_used(self, used_paths: set[str]):
        for i in range(self.count()):
            item = self.item(i)
            path = item.data(Qt.ItemDataRole.UserRole)
            new_used = path in used_paths
            old_used = path in self._used_paths
            if old_used != new_used:
                if new_used:
                    self._used_paths.add(path)
                else:
                    self._used_paths.discard(path)
                metadata = item.data(_METADATA_ROLE) or {}
                self._apply_style(item, new_used, metadata, self._color_settings)

    def _update_item_style(self, path: str):
        for i in range(self.count()):
            item = self.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == path:
                metadata = item.data(_METADATA_ROLE) or {}
                self._apply_style(item, path in self._used_paths, metadata, self._color_settings)

    @staticmethod
    def _apply_style(item: QListWidgetItem, used: bool, metadata: dict, settings) -> None:
        key = None
        if settings is not None and settings.enabled and settings.scope in ("file_list", "both"):
            key = color_coding.group_key(metadata, settings)

        if key is not None:
            bg = color_coding.color_for_key(key)
            if used:
                bg = bg.lighter(130)
            item.setBackground(bg)
            item.setForeground(color_coding.contrasting_text_color(bg))
            item.setToolTip(f"Group: {key}")
        else:
            item.setBackground(QBrush())
            if used:
                list_widget = item.listWidget()
                palette = list_widget.palette() if list_widget is not None else QApplication.palette()
                item.setForeground(palette.color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text))
            else:
                item.setForeground(QBrush())   # clear override -> Qt uses the palette's normal text color
            item.setToolTip("")

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