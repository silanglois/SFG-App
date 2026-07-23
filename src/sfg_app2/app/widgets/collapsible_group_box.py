from __future__ import annotations
from PySide6.QtWidgets import QGroupBox, QWidget, QSizePolicy
from PySide6.QtCore import Qt


def make_collapsible(groupbox: QGroupBox) -> None:
    """Wire a checkable QGroupBox to collapse/expand on toggle.
    Call once after setupUi.
    """
    _apply(groupbox, not groupbox.isChecked())
    groupbox.toggled.connect(lambda checked: _apply(groupbox, not checked))


def _apply(groupbox: QGroupBox, collapsed: bool) -> None:
    for child in groupbox.findChildren(
        QWidget,
        options=Qt.FindChildOption.FindDirectChildrenOnly,
    ):
        child.setVisible(not collapsed)

    if collapsed:
        groupbox.setMaximumHeight(groupbox.sizeHint().height())
        groupbox.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Fixed,
        )
    else:
        groupbox.setMaximumHeight(16777215)
        groupbox.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Preferred,
        )