"""The Fitting tab's job chips bar.

    [① 3 spectra ▾] [② 4 peaks + NR ▾] [③ Global · centers shared ▾] [④ 2800–3000 · None ▾]  [▶ Fit 3 globally] [?]

Each chip shows its step's live summary and opens a popover holding that
step's controls. A chip whose step still needs something shows ⚠, and
the first such chip is outlined with a "Start here" hint, so the order
is discoverable without a wizard; a familiar user just clicks Fit. A
short coach-mark tour walks the chips once (and on demand via "?").
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, Qt, Signal
from PySide6.QtGui import QGuiApplication, QPalette
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QToolButton, QVBoxLayout,
    QWidget,
)

_CIRCLED = "①②③④⑤⑥⑦⑧⑨"

_CHIP_STYLE = """
QToolButton#jobChip {
    border: 1px solid palette(mid);
    border-radius: 12px;
    padding: 3px 10px;
    background: palette(button);
}
QToolButton#jobChip:hover { border-color: palette(highlight); }
QToolButton#jobChip[attention="true"] { border: 2px solid #d9822b; }
QToolButton#jobChip[tour="true"] { border: 2px solid palette(highlight); }
"""


class Popover(QFrame):
    """A frameless popup panel anchored under a chip. Closes on an
    outside click or Esc (Qt.Popup semantics); `closed` lets the bar
    refresh summaries afterwards."""

    closed = Signal()

    def __init__(self, title: str, content: QWidget, parent=None):
        super().__init__(parent, Qt.WindowType.Popup)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setObjectName("jobPopover")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 10)
        heading = QLabel(f"<b>{title}</b>")
        layout.addWidget(heading)
        layout.addWidget(content)
        self.content = content

    def show_below(self, anchor: QWidget):
        self.adjustSize()
        pos = anchor.mapToGlobal(QPoint(0, anchor.height() + 2))
        screen = QGuiApplication.screenAt(pos) or QGuiApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            pos.setX(max(area.left(), min(pos.x(), area.right() - self.width())))
            pos.setY(max(area.top(), min(pos.y(), area.bottom() - self.height())))
        self.move(pos)
        self.show()

    def hideEvent(self, event):
        super().hideEvent(event)
        self.closed.emit()


class JobChip(QToolButton):
    def __init__(self, number: int, title: str, parent=None):
        super().__init__(parent)
        self.setObjectName("jobChip")
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.number = number
        self.title = title
        self.summary = ""
        self.needs_attention = False
        self.setProperty("attention", False)
        self.setProperty("tour", False)

    def set_state(self, summary: str, needs_attention: bool):
        self.summary = summary
        self.needs_attention = needs_attention
        warn = "  ⚠" if needs_attention else ""
        self.setText(f"{_CIRCLED[self.number - 1]} {self.title}: {summary}{warn}  ▾")
        self.setToolTip(f"Step {self.number} — {self.title}. Click to change.")

    def set_highlight(self, prop: str, on: bool):
        self.setProperty(prop, on)
        self.style().unpolish(self)
        self.style().polish(self)


class TourBubble(QFrame):
    """One coach mark: a small panel under a target widget with the
    step's explanation and Next / Skip."""

    next_clicked = Signal()
    skip_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.ToolTip)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet("TourBubble { background: palette(base); border: 2px solid palette(highlight); }")
        layout = QVBoxLayout(self)
        self._counter = QLabel()
        self._counter.setForegroundRole(QPalette.ColorRole.PlaceholderText)
        self._text = QLabel()
        self._text.setWordWrap(True)
        self._text.setMinimumWidth(280)
        self._text.setMaximumWidth(360)
        buttons = QHBoxLayout()
        self._skip = QPushButton("Skip tour")
        self._next = QPushButton("Next")
        self._skip.clicked.connect(self.skip_clicked)
        self._next.clicked.connect(self.next_clicked)
        buttons.addWidget(self._skip)
        buttons.addStretch()
        buttons.addWidget(self._next)
        layout.addWidget(self._counter)
        layout.addWidget(self._text)
        layout.addLayout(buttons)

    def show_step(self, anchor: QWidget, text: str, index: int, total: int):
        self._counter.setText(f"{index + 1} / {total}")
        self._text.setText(text)
        self._next.setText("Done" if index == total - 1 else "Next")
        self.adjustSize()
        pos = anchor.mapToGlobal(QPoint(0, anchor.height() + 6))
        screen = QGuiApplication.screenAt(pos) or QGuiApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            pos.setX(max(area.left(), min(pos.x(), area.right() - self.width())))
        self.move(pos)
        self.show()
        self.raise_()


class JobBar(QWidget):
    """Chips + Fit button + run status. The owning tab fills each chip's
    popover content and calls `set_chip()` whenever a summary changes."""

    fit_clicked = Signal()
    continue_clicked = Signal()
    stop_clicked = Signal()
    tour_finished = Signal()
    popover_closed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(_CHIP_STYLE)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 2, 0, 2)
        self._chips: list[JobChip] = []
        self._popovers: list[Popover] = []

        self._chip_row = QHBoxLayout()
        self._chip_row.setSpacing(6)
        self._layout.addLayout(self._chip_row)
        # Sits immediately before whichever chip needs attention first.
        self._start_hint = QLabel("Start here →")
        self._start_hint.setStyleSheet("color: #d9822b; font-weight: bold;")
        self._start_hint.setVisible(False)
        self._chip_row.addWidget(self._start_hint)
        self._layout.addStretch()

        self._status_label = QLabel("")
        self._status_label.setVisible(False)
        self._layout.addWidget(self._status_label)
        self._continue_btn = QPushButton("Continue ▸")
        self._continue_btn.setToolTip("Accept this spectrum's fit and continue the sequence from it.")
        self._continue_btn.clicked.connect(self.continue_clicked)
        self._continue_btn.setVisible(False)
        self._layout.addWidget(self._continue_btn)
        self._stop_btn = QPushButton("Stop")
        self._stop_btn.setToolTip("End the sequence here, keeping the spectra fitted so far.")
        self._stop_btn.clicked.connect(self.stop_clicked)
        self._stop_btn.setVisible(False)
        self._layout.addWidget(self._stop_btn)

        self.fit_button = QPushButton("▶ Fit")
        self.fit_button.setDefault(True)
        self.fit_button.setStyleSheet("QPushButton { font-weight: bold; padding: 4px 14px; }")
        self.fit_button.clicked.connect(self.fit_clicked)
        self._layout.addWidget(self.fit_button)

        self.help_button = QToolButton()
        self.help_button.setText("?")
        self.help_button.setToolTip("Show the quick tour of the Fitting tab")
        self.help_button.clicked.connect(self.start_tour)
        self._layout.addWidget(self.help_button)

        self._tour_steps: list[tuple[QWidget, str]] = []
        self._tour_index = -1
        self._tour_bubble: TourBubble | None = None

    # ── chips ────────────────────────────────────────────────────────────

    def add_chip(self, title: str, popover_title: str, content: QWidget) -> JobChip:
        chip = JobChip(len(self._chips) + 1, title)
        popover = Popover(popover_title, content, self)
        popover.closed.connect(self.popover_closed)
        chip.clicked.connect(lambda _c=False, c=chip, p=popover: self._toggle_popover(c, p))
        self._chip_row.addWidget(chip)
        self._chips.append(chip)
        self._popovers.append(popover)
        return chip

    def chip(self, index: int) -> JobChip:
        return self._chips[index]

    def popover(self, index: int) -> Popover:
        return self._popovers[index]

    def _toggle_popover(self, chip: JobChip, popover: Popover):
        if popover.isVisible():
            popover.hide()
            return
        self.close_popovers()
        popover.show_below(chip)

    def open_popover(self, index: int):
        self.close_popovers()
        self._popovers[index].show_below(self._chips[index])

    def close_popovers(self):
        for p in self._popovers:
            if p.isVisible():
                p.hide()

    def set_chip(self, index: int, summary: str, needs_attention: bool = False):
        self._chips[index].set_state(summary, needs_attention)
        self._update_start_hint()

    def _update_start_hint(self):
        first = next((c for c in self._chips if c.needs_attention), None)
        for c in self._chips:
            c.set_highlight("attention", c is first)
        self._chip_row.removeWidget(self._start_hint)
        if first is None:
            self._start_hint.setVisible(False)
            self._chip_row.insertWidget(0, self._start_hint)
            return
        self._chip_row.insertWidget(self._chip_row.indexOf(first), self._start_hint)
        self._start_hint.setVisible(True)

    def start_hint_target(self) -> JobChip | None:
        """The chip the "Start here" hint points at (tests)."""
        return next((c for c in self._chips if c.needs_attention), None)

    # ── fit button / run status ─────────────────────────────────────────

    def set_fit_label(self, text: str, enabled: bool, why_disabled: str = ""):
        self.fit_button.setText(f"▶ {text}")
        self.fit_button.setEnabled(enabled)
        self.fit_button.setToolTip("" if enabled else why_disabled)

    def set_paused(self, text: str):
        self._status_label.setText(text)
        self._status_label.setVisible(True)
        self._continue_btn.setVisible(True)
        self._stop_btn.setVisible(True)
        self.fit_button.setEnabled(False)

    def set_running(self, text: str):
        """A non-blocking run (a sequence between review points): status
        plus Stop, Fit disabled."""
        self._status_label.setText(text)
        self._status_label.setVisible(True)
        self._continue_btn.setVisible(False)
        self._stop_btn.setVisible(True)
        self.fit_button.setEnabled(False)

    def set_idle(self):
        self._status_label.setVisible(False)
        self._continue_btn.setVisible(False)
        self._stop_btn.setVisible(False)

    # ── tour ─────────────────────────────────────────────────────────────

    def set_tour_steps(self, steps: list[tuple[QWidget, str]]):
        self._tour_steps = steps

    def start_tour(self):
        if not self._tour_steps:
            return
        self.close_popovers()
        if self._tour_bubble is None:
            self._tour_bubble = TourBubble(self)
            self._tour_bubble.next_clicked.connect(self._tour_next)
            self._tour_bubble.skip_clicked.connect(self._end_tour)
        self._tour_index = -1
        self._tour_next()

    def tour_active(self) -> bool:
        return self._tour_index >= 0

    def _set_tour_target(self, widget: QWidget | None, on: bool):
        if isinstance(widget, JobChip):
            widget.set_highlight("tour", on)

    def _tour_next(self):
        if 0 <= self._tour_index < len(self._tour_steps):
            self._set_tour_target(self._tour_steps[self._tour_index][0], False)
        self._tour_index += 1
        if self._tour_index >= len(self._tour_steps):
            self._end_tour()
            return
        target, text = self._tour_steps[self._tour_index]
        self._set_tour_target(target, True)
        self._tour_bubble.show_step(target, text, self._tour_index, len(self._tour_steps))

    def _end_tour(self):
        if 0 <= self._tour_index < len(self._tour_steps):
            self._set_tour_target(self._tour_steps[self._tour_index][0], False)
        self._tour_index = -1
        if self._tour_bubble is not None:
            self._tour_bubble.hide()
        self.tour_finished.emit()

    def hideEvent(self, event):
        # don't leave a coach mark floating over another tab
        if event.type() == QEvent.Type.Hide and self.tour_active():
            self._end_tour()
        super().hideEvent(event)
