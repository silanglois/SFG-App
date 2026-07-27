from __future__ import annotations
from PySide6.QtWidgets import QGroupBox, QWidget, QSizePolicy
from PySide6.QtCore import Qt


def make_collapsible(groupbox: QGroupBox) -> None:
    """Wire a checkable QGroupBox to collapse/expand on toggle.
    Call once after setupUi.
    """
    # remember the box's original vertical policy (e.g. Fixed) so expanding
    # it later restores that instead of always forcing Preferred, which
    # would let it compete for extra space in the outer layout.
    groupbox.setProperty("_orig_vpolicy", groupbox.sizePolicy().verticalPolicy())
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
        orig_vpolicy = groupbox.property("_orig_vpolicy")
        if orig_vpolicy is None:
            orig_vpolicy = QSizePolicy.Policy.Preferred
        groupbox.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            orig_vpolicy,
        )