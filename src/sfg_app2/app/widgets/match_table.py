from __future__ import annotations
import logging
from PySide6.QtWidgets import QComboBox, QTableView, QAbstractItemView, QHeaderView, QMenu
from PySide6.QtCore import (
    Qt, QAbstractTableModel, QModelIndex,
    QMimeData, QByteArray, Signal
)
from PySide6.QtGui import QColor, QBrush

logger = logging.getLogger(__name__)

COLUMNS = ["Signal", "Sample BG", "Reference", "Ref BG", "Type"]
SPECTRUM_TYPES = ["Homodyne", "Heterodyne"]
MIME_FILE = "application/sfg-app-file"
MIME_SOURCE = "application/sfg-app-source-cell"


class MatchTableModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[list[tuple[str, str] | None]] = []
        self._types: list[str] = []
        self._metadata_lookup = None   # Callable[[str], dict | None]
        self._color_settings = None    # ColorCodingSettings

    def set_metadata_lookup(self, fn) -> None:
        self._metadata_lookup = fn

    def set_color_coding_settings(self, settings) -> None:
        self._color_settings = settings

    def refresh_colors(self) -> None:
        """Force re-render of every cell's color (e.g. after color-coding
        settings change), without touching the underlying data."""
        if not self._rows:
            return
        top_left = self.createIndex(0, 0)
        bottom_right = self.createIndex(len(self._rows) - 1, len(COLUMNS) - 1)
        self.dataChanged.emit(
            top_left, bottom_right,
            [Qt.ItemDataRole.BackgroundRole, Qt.ItemDataRole.ForegroundRole],
        )

    def _group_color(self, cell):
        if cell is None or self._color_settings is None or self._metadata_lookup is None:
            return None
        settings = self._color_settings
        if not (settings.enabled and settings.scope in ("match_table", "both")):
            return None
        from sfg_app2.app.utils import color_coding
        metadata = self._metadata_lookup(cell[0]) or {}
        key = color_coding.group_key(metadata, settings)
        return color_coding.color_for_key(key) if key is not None else None

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
        col = index.column()

        if col == 4:
            if role == Qt.ItemDataRole.DisplayRole:
                return self._types[index.row()]
            if role == Qt.ItemDataRole.UserRole:
                return self._types[index.row()].lower()
            return None

        cell = self._rows[index.row()][col]
        if role == Qt.ItemDataRole.DisplayRole:
            return cell[1] if cell else "—"
        if role == Qt.ItemDataRole.UserRole:
            return cell[0] if cell else None
        if role == Qt.ItemDataRole.BackgroundRole:
            color = self._group_color(cell)
            return QBrush(color) if color is not None else None
        if role == Qt.ItemDataRole.ForegroundRole:
            if cell is None:
                return QBrush(QColor(180, 180, 180))
            color = self._group_color(cell)
            if color is not None:
                from sfg_app2.app.utils import color_coding
                return QBrush(color_coding.contrasting_text_color(color))
            return None
        if role == Qt.ItemDataRole.ToolTipRole:
            return cell[0] if cell else "Drop a file here"
        return None

    def flags(self, index):
        if not index.isValid():
            return Qt.ItemFlag.ItemIsEnabled
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if index.column() == 4:
            flags |= Qt.ItemFlag.ItemIsEditable
            return flags
        flags |= Qt.ItemFlag.ItemIsDropEnabled
        if self._rows[index.row()][index.column()]:
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
        return data.hasFormat(MIME_FILE) and column != 4

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
        self._types.append("Homodyne")
        self.endInsertRows()
        return row

    def remove_row(self, row: int):
        self.beginRemoveRows(QModelIndex(), row, row)
        self._rows.pop(row)
        self._types.pop(row)
        self.endRemoveRows()

    def set_type(self, row: int, spectrum_type: str):
        self._types[row] = spectrum_type
        index = self.createIndex(row, 4)
        self.dataChanged.emit(index, index, [Qt.ItemDataRole.DisplayRole])

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
        for i, row in enumerate(self._rows):
            def get(col, r=row):
                cell = r[col]
                return file_registry.get(cell[0]) if cell else None
            results.append(MatchedSet(
                signal               = get(0),
                background           = get(1),
                reference            = get(2),
                reference_background = get(3),
                spectrum_type        = self._types[i].lower(),
            ))
        return [m for m in results if m.signal is not None]

from PySide6.QtWidgets import QStyledItemDelegate

class TypeColumnDelegate(QStyledItemDelegate):
    """Renders a combo box in the Type column."""

    def createEditor(self, parent, option, index):
        if index.column() != 4:
            return None
        combo = QComboBox(parent)
        combo.addItems(SPECTRUM_TYPES)
        combo.setFrame(False)
        return combo

    def setEditorData(self, editor, index):
        value = index.data(Qt.ItemDataRole.DisplayRole) or "Homodyne"
        idx = SPECTRUM_TYPES.index(value) if value in SPECTRUM_TYPES else 0
        editor.setCurrentIndex(idx)

    def setModelData(self, editor, model, index):
        model.set_type(index.row(), editor.currentText())

    def updateEditorGeometry(self, editor, option, index):
        editor.setGeometry(option.rect)

class MatchTableView(QTableView):
    table_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._table_model = MatchTableModel()
        self.setModel(self._table_model)
        self.setItemDelegateForColumn(4, TypeColumnDelegate(self))
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)

    def set_metadata_lookup(self, fn) -> None:
        self._table_model.set_metadata_lookup(fn)

    def set_color_coding_settings(self, settings) -> None:
        self._table_model.set_color_coding_settings(settings)

    def refresh_colors(self) -> None:
        self._table_model.refresh_colors()

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