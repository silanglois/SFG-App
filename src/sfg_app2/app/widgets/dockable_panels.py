from __future__ import annotations
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMainWindow, QDockWidget, QWidget


class DockablePlotPanel:
    """Mixin: composes a plot widget + a set of named QDockWidgets inside
    a nested QMainWindow.

    QDockWidget requires a QMainWindow to dock into, and docking against
    the app's single real MainWindow would snap panels to the whole app
    window's edges instead of staying scoped to this panel — so a small
    QMainWindow is nested here purely as a local dock area, the same
    reasoning already used by ProcessedResultsTab's "Visualization
    parameters" dock (see app/tabs/processed_results.py:_setup_plot).

    Subclasses call _init_dock_area() once with their plot widget, then
    _add_dock() for each parameter section. All of a panel's docks are
    tabified together by default — closest to the old "one section shown
    at a time" feel, while every tab stays fully draggable/floatable/
    closable. _set_dock_visibility() drives step-based auto-focus.
    """

    def _init_dock_area(self, plot_widget: QWidget) -> QMainWindow:
        self._dock_main_window = QMainWindow()
        self._dock_main_window.setCentralWidget(plot_widget)
        self._docks: dict[str, QDockWidget] = {}
        return self._dock_main_window

    def _add_dock(self, key: str, title: str, content: QWidget) -> QDockWidget:
        dock = QDockWidget(title, self._dock_main_window)
        dock.setObjectName(f"dock_{key}")   # required for save/restoreState
        dock.setWidget(content)
        dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        if self._docks:
            self._dock_main_window.tabifyDockWidget(next(iter(self._docks.values())), dock)
        else:
            self._dock_main_window.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
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
