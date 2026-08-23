from __future__ import annotations
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMainWindow, QDockWidget, QWidget, QVBoxLayout


class DockablePlotPanel:
    """Mixin: composes a plot widget + a set of named QDockWidgets inside
    a nested QMainWindow.

    QDockWidget requires a QMainWindow to dock into, and docking against
    the app's single real MainWindow would snap panels to the whole app
    window's edges instead of staying scoped to this panel — so a small
    QMainWindow is nested here purely as a local dock area, the same
    reasoning already used by ProcessedResultsTab's "Visualization
    parameters" dock (see app/tabs/processed_results.py:_setup_plot).

    Subclasses call _init_dock_area() once, optionally with a fixed
    central widget, then _add_dock() for each parameter section. By
    default all of a panel's docks are tabified together — closest to
    the old "one section shown at a time" feel, while every tab stays
    fully draggable/floatable/closable. Passing tabify=False to
    _add_dock() opts a dock out of that shared tab group entirely (its
    own area, untouched by whatever the tabified group is doing) — for
    a panel whose plot should stay visible by default alongside its
    (tabbed) control docks, rather than being just another tab in the
    same group. _set_dock_visibility() drives step-based auto-focus.
    """

    def _init_dock_area(self, central_widget: QWidget | None = None) -> QMainWindow:
        self._dock_main_window = QMainWindow()
        # Off by default in Qt -- without it, each of the four perimeter
        # areas can only ever hold one dock (or one tabbed stack) as a
        # single unsplittable unit, so a dock can only ever move between
        # the four outer edges, never split against another dock's edge
        # to build a genuine 2D grid.
        self._dock_main_window.setDockNestingEnabled(True)
        if central_widget is not None:
            self._dock_main_window.setCentralWidget(central_widget)
        self._docks: dict[str, QDockWidget] = {}
        self._dock_tab_anchor: QDockWidget | None = None
        return self._dock_main_window

    def _add_dock(self, key: str, title: str, content: QWidget,
                   expand_horizontally: bool = False, fill: bool = False,
                   area: Qt.DockWidgetArea = Qt.DockWidgetArea.RightDockWidgetArea,
                   tabify: bool = True) -> QDockWidget:
        # wrap content in its own sizeHint-only box, top-left in a wrapper
        # with a trailing stretch — relying on content.layout().setAlignment()
        # alone left rows visibly stretched apart (QGridLayout distributing
        # the dock's leftover space into row/column gaps rather than
        # collapsing to its sizeHint), so the leftover space is instead
        # soaked up here, once, outside of content's own layout entirely.
        # expand_horizontally opts out of the AlignLeft half of that clamp
        # for sections whose content should still use the full dock width
        # (e.g. exclude_frames' per-component checkbox strips). fill opts
        # out of the whole clamp+stretch: for content that should fill the
        # dock in both directions (a table, a plot widget), sizeHint-only
        # top-left clamping is actively wrong.
        content.setVisible(True)   # a widget detached from a QTabWidget's
                                    # non-current page stays hidden otherwise
        wrapper = QWidget()
        outer = QVBoxLayout(wrapper)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(content)
        if not fill:
            align = Qt.AlignmentFlag.AlignTop
            if not expand_horizontally:
                align |= Qt.AlignmentFlag.AlignLeft
            outer.setAlignment(content, align)
            outer.addStretch()

        dock = QDockWidget(title, self._dock_main_window)
        dock.setObjectName(f"dock_{key}")   # required for save/restoreState
        dock.setWidget(wrapper)
        dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        if tabify and self._dock_tab_anchor is not None:
            self._dock_main_window.tabifyDockWidget(self._dock_tab_anchor, dock)
        else:
            self._dock_main_window.addDockWidget(area, dock)
            if tabify:
                self._dock_tab_anchor = dock
        self._docks[key] = dock
        return dock

    def _set_dock_visibility(self, visible_keys: set[str], focus_key: str | None = None):
        for key, dock in self._docks.items():
            dock.setVisible(key in visible_keys)
        if focus_key is not None and focus_key in self._docks:
            self._docks[focus_key].raise_()

    def view_menu_actions(self) -> list:
        return [dock.toggleViewAction() for dock in self._docks.values()]

    def save_dock_state(self) -> bytes:
        return bytes(self._dock_main_window.saveState())

    def restore_dock_state(self, data: bytes | None):
        if data:
            self._dock_main_window.restoreState(data)
