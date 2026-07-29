from __future__ import annotations
import uuid


def new_folder(name: str, children: list[dict] | None = None) -> dict:
    return {
        "type": "folder",
        "id": str(uuid.uuid4()),
        "name": name,
        "children": children if children is not None else [],
    }


def new_leaf(name: str, data: dict, active: bool = False) -> dict:
    return {
        "type": "leaf",
        "id": str(uuid.uuid4()),
        "name": name,
        "active": active,
        "data": data,
    }


def iter_leaves(nodes: list[dict]):
    """Depth-first generator over every leaf node in the tree."""
    for node in nodes:
        if node["type"] == "leaf":
            yield node
        else:
            yield from iter_leaves(node.get("children", []))


def find_node(nodes: list[dict], node_id: str) -> dict | None:
    for node in nodes:
        if node["id"] == node_id:
            return node
        if node["type"] == "folder":
            found = find_node(node.get("children", []), node_id)
            if found is not None:
                return found
    return None


def find_parent_list(nodes: list[dict], node_id: str) -> list[dict] | None:
    """Returns the list (either `nodes` itself or some folder's `children`)
    that directly contains node_id, or None if not found anywhere."""
    for node in nodes:
        if node["id"] == node_id:
            return nodes
        if node["type"] == "folder":
            found = find_parent_list(node.get("children", []), node_id)
            if found is not None:
                return found
    return None


def remove_node(nodes: list[dict], node_id: str) -> dict | None:
    parent_list = find_parent_list(nodes, node_id)
    if parent_list is None:
        return None
    for i, node in enumerate(parent_list):
        if node["id"] == node_id:
            return parent_list.pop(i)
    return None


def move_node(root: list[dict], node_id: str, new_parent_id: str | None):
    """Move node (and its subtree) to be a child of new_parent_id's folder,
    or to the root list if new_parent_id is None. No-op if node_id isn't
    found, or if new_parent_id doesn't resolve to a folder (falls back to
    root placement in that case)."""
    node = remove_node(root, node_id)
    if node is None:
        return
    if new_parent_id is None:
        root.append(node)
        return
    parent = find_node(root, new_parent_id)
    if parent is not None and parent["type"] == "folder":
        parent["children"].append(node)
    else:
        root.append(node)
