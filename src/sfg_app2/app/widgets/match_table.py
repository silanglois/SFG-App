from __future__ import annotations
import logging
from PySide6.QtWidgets import QTableView, QAbstractItemView, QHeaderView, QMenu
from PySide6.QtCore import (
    Qt, QAbstractTableModel, QModelIndex,
    QMimeData, QByteArray, Signal
)
from PySide6.QtGui import QColor, QBrush

logger = logging.getLogger(__name__)

COLUMNS = ["Sample", "Sample BG", "Reference", "Ref BG"]
MIME_FILE = "application/sfg-app-file"
MIME_SOURCE = "application/sfg-app-source-cell"


class MatchTableModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        # each row: list of 4 (path, display_name) tuples or None
        self._rows: list[list[tuple[str, str] | None]] = []

    def rowCount(self, parent=QModelIndex()):
        return len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        return len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole:
            if orientation == Qt.Orientation.Horizontal:
                return COLUMNS[section]
            return str(section + 1)
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        cell = self._rows[index.row()][index.column()]
        if role == Qt.ItemDataRole.DisplayRole:
            return cell[1] if cell else "—"
        if role == Qt.ItemDataRole.UserRole:
            return cell[0] if cell else None
        if role == Qt.ItemDataRole.ForegroundRole:
            return QBrush(QColor(180, 180, 180)) if cell is None else None
        if role == Qt.ItemDataRole.ToolTipRole:
            return cell[0] if cell else "Drop a file here"
        return None

    def flags(self, index):
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        flags |= Qt.ItemFlag.ItemIsDropEnabled
        if index.isValid() and self._rows[index.row()][index.column()]:
            flags |= Qt.ItemFlag.ItemIsDragEnabled
        return flags

    def mimeTypes(self):
        return [MIME_FILE, MIME_SOURCE]

    def mimeData(self, indexes):
        if not indexes:
            return None
        index = indexes[0]
        path = self.data(index, Qt.ItemDataRole.UserRole)
        if not path:
            return None
        mime = QMimeData()
        mime.setData(MIME_FILE, QByteArray(path.encode()))
        mime.setData(MIME_SOURCE, QByteArray(f"{index.row()},{index.column()}".encode()))
        return mime

    def canDropMimeData(self, data, action, row, column, parent):
        return data.hasFormat(MIME_FILE)

    def dropMimeData(self, data, action, row, column, parent):
        return False   # handled entirely in MatchTableView.dropEvent

    # ── Data manipulation ─────────────────────────────────────────────────────

    def set_cell(self, row: int, col: int, path: str, display_name: str):
        self._rows[row][col] = (path, display_name)
        index = self.createIndex(row, col)
        self.dataChanged.emit(index, index, [Qt.ItemDataRole.DisplayRole])

    def clear_cell(self, row: int, col: int):
        self._rows[row][col] = None
        index = self.createIndex(row, col)
        self.dataChanged.emit(index, index, [Qt.ItemDataRole.DisplayRole])

    def add_row(self) -> int:
        row = len(self._rows)
        self.beginInsertRows(QModelIndex(), row, row)
        self._rows.append([None, None, None, None])
        self.endInsertRows()
        return row

    def remove_row(self, row: int):
        self.beginRemoveRows(QModelIndex(), row, row)
        self._rows.pop(row)
        self.endRemoveRows()

    def all_paths_used(self) -> set[str]:
        paths = set()
        for row in self._rows:
            for cell in row:
                if cell:
                    paths.add(cell[0])
        return paths

    def to_matched_sets(self, file_registry: dict) -> list:
        from sfg_app2.processing.matcher import MatchedSet
        results = []
        for row in self._rows:
            def get(col, r=row):
                cell = r[col]
                return file_registry.get(cell[0]) if cell else None
            results.append(MatchedSet(
                signal=get(0),
                background=get(1),
                reference=get(2),
                reference_background=get(3),
            ))
        return [m for m in results if m.signal is not None]


class MatchTableView(QTableView):
    table_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._table_model = MatchTableModel()
        self.setModel(self._table_model)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(MIME_FILE):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat(MIME_FILE):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        mime = event.mimeData()
        if not mime.hasFormat(MIME_FILE):
            event.ignore()
            return

        path = mime.data(MIME_FILE).data().decode()
        display_name = path.replace("\\", "/").split("/")[-1]

        pos = event.position().toPoint()
        target_index = self.indexAt(pos)
        col = self.columnAt(pos.x())
        if col < 0:
            col = 0

        # create new row if dropped below existing rows
        if target_index.isValid():
            target_row = target_index.row()
        else:
            target_row = self._table_model.add_row()

        # clear source cell on internal table drag
        if mime.hasFormat(MIME_SOURCE):
            src_row, src_col = map(int, mime.data(MIME_SOURCE).data().decode().split(","))
            self._table_model.clear_cell(src_row, src_col)

        self._table_model.set_cell(target_row, col, path, display_name)
        event.acceptProposedAction()
        self.table_changed.emit()

    def _on_context_menu(self, pos):
        index = self.indexAt(pos)
        if not index.isValid():
            return
        menu = QMenu(self)
        clear_action = menu.addAction("Clear cell")
        remove_action = menu.addAction("Remove row")
        action = menu.exec(self.viewport().mapToGlobal(pos))
        if action == clear_action:
            self._table_model.clear_cell(index.row(), index.column())
            self.table_changed.emit()
        elif action == remove_action:
            self._table_model.remove_row(index.row())
            self.table_changed.emit()