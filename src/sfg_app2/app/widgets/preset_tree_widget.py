from __future__ import annotations
import copy
import uuid
from typing import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTreeWidget, QTreeWidgetItem,
    QPushButton, QAbstractItemView, QMessageBox,
)

from sfg_app2.app.utils.preset_tree import (
    new_folder, new_leaf, find_node, find_parent_list, remove_node,
)


class _DropTreeWidget(QTreeWidget):
    """QTreeWidget that notifies its owner after any internal drag-drop,
    so the backing dict-tree can be rebuilt from the new item hierarchy."""

    def __init__(self, on_drop: Callable[[], None], parent=None):
        super().__init__(parent)
        self._on_drop = on_drop

    def dropEvent(self, event):
        super().dropEvent(event)
        self._on_drop()


class PresetTreeWidget(QWidget):
    """Reusable tree-of-named-presets widget: folders for organization,
    leaves holding an arbitrary payload dict (`node["data"]`), with an
    "active" flag rendered as a bold "★ " prefix. Used by both the
    metadata-patterns dialog and the auto-matching profiles dialog.

    The tree operates on a backing `list[dict]` (see `preset_tree.py`)
    passed via `set_tree()` — it mutates that list in place, so callers
    should pass a working copy and persist it on their own OK/Cancel.
    """

    leafSelected = Signal(object)   # str leaf_id, or None (folder/nothing selected)
    treeChanged = Signal()          # any structural edit: add/remove/move/rename

    def __init__(
        self,
        leaf_data_factory: Callable[[], dict],
        new_leaf_name: str = "New Item",
        parent=None,
    ):
        super().__init__(parent)
        self._nodes: list[dict] = []
        self._leaf_data_factory = leaf_data_factory
        self._new_leaf_name = new_leaf_name

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.tree = _DropTreeWidget(self._on_internal_drop)
        self.tree.setHeaderHidden(True)
        self.tree.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.tree.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.currentItemChanged.connect(self._on_current_changed)
        self.tree.itemChanged.connect(self._on_item_edited)
        layout.addWidget(self.tree)

        btn_row = QHBoxLayout()
        self._add_btn = QPushButton("+")
        self._add_btn.setToolTip("Add item")
        self._add_btn.clicked.connect(self.add_leaf)
        self._remove_btn = QPushButton("-")
        self._remove_btn.setToolTip("Remove selected item/folder")
        self._remove_btn.clicked.connect(self.remove_selected)
        self._duplicate_btn = QPushButton("⧉")
        self._duplicate_btn.setToolTip("Duplicate selected item")
        self._duplicate_btn.clicked.connect(self.duplicate_selected)
        self._new_folder_btn = QPushButton("New Folder")
        self._new_folder_btn.clicked.connect(self.add_folder)
        for w in (self._add_btn, self._remove_btn, self._duplicate_btn, self._new_folder_btn):
            btn_row.addWidget(w)
        layout.addLayout(btn_row)

    # ── Public API ────────────────────────────────────────────────────────────

    def set_tree(self, nodes: list[dict]):
        self._nodes = nodes
        self._rebuild(preserve_selection=False)

    @property
    def nodes(self) -> list[dict]:
        return self._nodes

    def current_node(self) -> dict | None:
        """Always re-resolved by id against the live backing tree — items
        only ever store a node's id (see module note on QTreeWidgetItem
        data-copy semantics), never the node dict itself."""
        item = self.tree.currentItem()
        if item is None:
            return None
        node_id = item.data(0, Qt.ItemDataRole.UserRole)
        return find_node(self._nodes, node_id) if node_id else None

    def current_leaf_id(self) -> str | None:
        node = self.current_node()
        return node["id"] if node and node["type"] == "leaf" else None

    def refresh_labels(self):
        """Re-render text/bold for all items without losing selection —
        call after externally mutating a node (e.g. toggling `active`)."""
        self._rebuild(preserve_selection=True)

    def select_leaf(self, leaf_id: str):
        self._select_node(leaf_id)

    def add_leaf(self) -> dict:
        children = self._target_parent_children()
        node = new_leaf(self._new_leaf_name, self._leaf_data_factory())
        children.append(node)
        self._rebuild(preserve_selection=False)
        self._select_node(node["id"])
        self.treeChanged.emit()
        return node

    def add_folder(self) -> dict:
        children = self._target_parent_children()
        node = new_folder("New Folder")
        children.append(node)
        self._rebuild(preserve_selection=False)
        self._select_node(node["id"])
        self.treeChanged.emit()
        return node

    def duplicate_selected(self) -> dict | None:
        node = self.current_node()
        if node is None or node["type"] != "leaf":
            return None
        dup = copy.deepcopy(node)
        dup["id"] = str(uuid.uuid4())
        dup["name"] = f"{node['name']} (copy)"
        dup["active"] = False
        parent_list = find_parent_list(self._nodes, node["id"])
        if parent_list is None:
            parent_list = self._nodes
        parent_list.append(dup)
        self._rebuild(preserve_selection=False)
        self._select_node(dup["id"])
        self.treeChanged.emit()
        return dup

    def remove_selected(self, confirm: bool = True) -> bool:
        node = self.current_node()
        if node is None:
            return False
        if confirm:
            kind = "folder (and everything inside it)" if node["type"] == "folder" else "item"
            reply = QMessageBox.question(
                self, "Remove", f'Remove {kind} "{node["name"]}"?',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.No:
                return False
        remove_node(self._nodes, node["id"])
        self._rebuild(preserve_selection=False)
        self.treeChanged.emit()
        return True

    # ── Internal: rendering ──────────────────────────────────────────────────

    @staticmethod
    def _label_for(node: dict) -> str:
        if node["type"] == "leaf" and node.get("active"):
            return f"★ {node['name']}"
        return node["name"]

    def _rebuild(self, preserve_selection: bool):
        selected_id = None
        if preserve_selection:
            node = self.current_node()
            selected_id = node["id"] if node else None

        self.tree.blockSignals(True)
        self.tree.clear()
        self._populate(self._nodes, None)
        self.tree.expandAll()
        self.tree.blockSignals(False)

        if selected_id:
            self._select_node(selected_id)

    def _populate(self, nodes: list[dict], parent_item: QTreeWidgetItem | None):
        for node in nodes:
            item = QTreeWidgetItem([self._label_for(node)])
            item.setData(0, Qt.ItemDataRole.UserRole, node["id"])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
            if node["type"] == "folder":
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsDropEnabled)
                font = item.font(0)
                font.setBold(True)
                item.setFont(0, font)
            elif node.get("active"):
                font = item.font(0)
                font.setBold(True)
                item.setFont(0, font)

            if parent_item is None:
                self.tree.addTopLevelItem(item)
            else:
                parent_item.addChild(item)

            if node["type"] == "folder":
                self._populate(node.get("children", []), item)

    def _find_item(self, node_id: str, parent_item: QTreeWidgetItem | None = None):
        count = self.tree.topLevelItemCount() if parent_item is None else parent_item.childCount()
        get_child = self.tree.topLevelItem if parent_item is None else parent_item.child
        for i in range(count):
            item = get_child(i)
            item_id = item.data(0, Qt.ItemDataRole.UserRole)
            if item_id == node_id:
                return item
            found = self._find_item(node_id, item)
            if found is not None:
                return found
        return None

    def _select_node(self, node_id: str):
        item = self._find_item(node_id)
        if item is not None:
            self.tree.setCurrentItem(item)

    def _target_parent_children(self) -> list[dict]:
        """Where a newly added sibling should go: inside the selected
        folder, alongside the selected leaf (same parent), or at root."""
        node = self.current_node()
        if node is None:
            return self._nodes
        if node["type"] == "folder":
            return node["children"]
        parent_item = self.tree.currentItem().parent()
        if parent_item is None:
            return self._nodes
        parent_id = parent_item.data(0, Qt.ItemDataRole.UserRole)
        parent_node = find_node(self._nodes, parent_id)
        return parent_node["children"] if parent_node else self._nodes

    # ── Internal: signal handlers ────────────────────────────────────────────

    def _on_current_changed(self, current, _previous):
        node_id = current.data(0, Qt.ItemDataRole.UserRole) if current else None
        node = find_node(self._nodes, node_id) if node_id else None
        leaf_id = node_id if node and node["type"] == "leaf" else None
        self.leafSelected.emit(leaf_id)

    def _on_item_edited(self, item: QTreeWidgetItem, _column: int):
        node_id = item.data(0, Qt.ItemDataRole.UserRole)
        node = find_node(self._nodes, node_id) if node_id else None
        if node is None:
            return
        text = item.text(0)
        clean_name = text[2:] if text.startswith("★ ") else text
        node["name"] = clean_name
        self.tree.blockSignals(True)
        item.setText(0, self._label_for(node))
        self.tree.blockSignals(False)
        self.treeChanged.emit()

    def _on_internal_drop(self):
        self._nodes[:] = self._extract_nodes_from_widget()
        self.treeChanged.emit()

    def _extract_nodes_from_widget(self, parent_item: QTreeWidgetItem | None = None) -> list[dict]:
        count = self.tree.topLevelItemCount() if parent_item is None else parent_item.childCount()
        get_child = self.tree.topLevelItem if parent_item is None else parent_item.child
        result = []
        for i in range(count):
            item = get_child(i)
            node_id = item.data(0, Qt.ItemDataRole.UserRole)
            node = find_node(self._nodes, node_id)
            if node is None:
                continue
            if node["type"] == "folder":
                node = dict(node)
                node["children"] = self._extract_nodes_from_widget(item)
            result.append(node)
        return result
