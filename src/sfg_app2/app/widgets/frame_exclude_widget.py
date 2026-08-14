from __future__ import annotations

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import QWidget, QHBoxLayout, QCheckBox, QPushButton, QScrollArea


class FrameCheckStrip(QWidget):
    """A compact, wrapping row of per-frame checkboxes (checked = included).

    Used once per component (signal/background/reference/ref_background) to
    let the user exclude individual frames from averaging. Frame ids are
    supplied by the owning panel via set_frame_ids(); excluded frames can be
    read/set via excluded_frames()/set_excluded_frames().
    """

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._checkboxes: dict[int, QCheckBox] = {}

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(2)

        self._strip = QWidget()
        self._strip_layout = QHBoxLayout(self._strip)
        self._strip_layout.setContentsMargins(2, 0, 2, 0)
        self._strip_layout.setSpacing(6)
        self._strip_layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidget(self._strip)
        scroll.setWidgetResizable(True)
        scroll.setFixedHeight(30)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(scroll)

        all_btn = QPushButton("All")
        all_btn.setFixedWidth(36)
        all_btn.clicked.connect(lambda: self._set_all(True))
        none_btn = QPushButton("None")
        none_btn.setFixedWidth(42)
        none_btn.clicked.connect(lambda: self._set_all(False))
        outer.addWidget(all_btn)
        outer.addWidget(none_btn)

    # ── Public API ────────────────────────────────────────────────────────────

    def set_frame_ids(self, ids: list[int]) -> None:
        """Rebuild the checkbox row for a new set of frame ids. Frames not
        previously seen default to included (checked)."""
        previous = self.excluded_frames()

        while self._strip_layout.count() > 1:
            item = self._strip_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._checkboxes.clear()

        for fid in ids:
            cb = QCheckBox(str(fid))
            cb.setChecked(fid not in previous)
            cb.toggled.connect(lambda _checked: self.changed.emit())
            self._checkboxes[fid] = cb
            self._strip_layout.insertWidget(self._strip_layout.count() - 1, cb)

    def excluded_frames(self) -> set[int]:
        return {fid for fid, cb in self._checkboxes.items() if not cb.isChecked()}

    def set_excluded_frames(self, excluded: set[int]) -> None:
        for fid, cb in self._checkboxes.items():
            cb.blockSignals(True)
            cb.setChecked(fid not in excluded)
            cb.blockSignals(False)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _set_all(self, checked: bool) -> None:
        for cb in self._checkboxes.values():
            cb.blockSignals(True)
            cb.setChecked(checked)
            cb.blockSignals(False)
        self.changed.emit()
