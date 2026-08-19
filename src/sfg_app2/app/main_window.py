# src/sfg_app2/app/main_window.py
from __future__ import annotations
import logging
from pathlib import Path

from PySide6.QtWidgets import QMainWindow, QVBoxLayout, QFileDialog, QMessageBox, QMenu
from sfg_app2.app.ui.ui_main_window import Ui_MainWindow
from sfg_app2.app.utils.pattern_manager import PatternManager
from sfg_app2.app.utils.plotting_settings import PlottingSettings
from sfg_app2.app.utils.matching_settings import MatchingProfileManager
from sfg_app2.app.utils.color_coding_settings import ColorCodingSettings
from sfg_app2.app.utils.dock_layout_settings import DockLayoutSettings

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)

        self.matched_sets: list = []
        self.processed_results: dict = {}
        self.pattern_manager = PatternManager()
        self.matching_profiles = MatchingProfileManager()
        self.matching_settings = self.matching_profiles.active_settings()
        self.plotting_settings = PlottingSettings()
        self.plotting_settings.apply_current()
        self.color_coding_settings = ColorCodingSettings()
        self.dock_layout_settings = DockLayoutSettings()
        self._ignored_paths: set[Path] = set()  # resolved absolute paths

        self._init_tabs()
        self.process_review_tab.restore_dock_layouts(self.dock_layout_settings)
        self.processed_results_tab.restore_dock_state(self.dock_layout_settings.get("results"))
        self._connect_menu()
        self._build_view_menu()
        self._build_window_menu()
        self._lock_tabs_from(1)
        self.ui.mainTabWidget.setTabEnabled(2, True)   # Results always accessible
        self.ui.mainTabWidget.setTabEnabled(3, True)   # Post Processing always accessible

    def closeEvent(self, event):
        self.process_review_tab.save_dock_layouts(self.dock_layout_settings)
        self.dock_layout_settings.set("results", self.processed_results_tab.save_dock_state())
        self.dock_layout_settings.save()
        self.load_match_tab.close_plot_windows()
        super().closeEvent(event)

    # ── Tab setup ─────────────────────────────────────────────────────────────

    def _init_tabs(self):
        from sfg_app2.app.tabs.load_match import LoadMatchTab
        from sfg_app2.app.tabs.process_review import ProcessReviewTab
        from sfg_app2.app.tabs.processed_results import ProcessedResultsTab

        self.load_match_tab = LoadMatchTab()
        self._replace_tab(0, self.load_match_tab, "Load / Match")
        self.load_match_tab.matching_complete.connect(self._on_matching_complete)

        self.process_review_tab = ProcessReviewTab()
        self._replace_tab(1, self.process_review_tab, "Process / Review")
        self.process_review_tab.processing_complete.connect(self._on_processing_complete)

        self.processed_results_tab = ProcessedResultsTab()
        self._replace_tab(2, self.processed_results_tab, "Results")

        # tab 3 (Post Processing) — placeholder for now
        from PySide6.QtWidgets import QWidget, QLabel
        placeholder = QWidget()
        QVBoxLayout(placeholder).addWidget(QLabel("Post Processing — coming soon"))
        self._replace_tab(3, placeholder, "Post Processing")

    def _replace_tab(self, index: int, widget, label: str):
        self.ui.mainTabWidget.removeTab(index)
        self.ui.mainTabWidget.insertTab(index, widget, label)

    # ── Tab progression ───────────────────────────────────────────────────────

    def _lock_tabs_from(self, index: int):
        for i in range(index, self.ui.mainTabWidget.count()):
            self.ui.mainTabWidget.setTabEnabled(i, False)

    def unlock_tab(self, index: int):
        self.ui.mainTabWidget.setTabEnabled(index, True)
        self.ui.mainTabWidget.setCurrentIndex(index)

    # ── Tab signal handlers ───────────────────────────────────────────────────

    def _on_matching_complete(self, matched_sets: list):
        self.matched_sets = matched_sets
        self.process_review_tab.set_matched_sets(matched_sets)
        self.statusBar().showMessage(f"Matched {len(matched_sets)} file sets.")
        self.unlock_tab(1)

    def _on_processing_complete(self, results: dict):
        self.processed_results = results
        self.processed_results_tab.add_results(results)
        self.statusBar().showMessage(f"{len(results)} set(s) processed.")
        self.ui.mainTabWidget.setTabEnabled(2, True)
        self.ui.mainTabWidget.setCurrentIndex(2)

    # ── Menu connections ──────────────────────────────────────────────────────

    def _connect_menu(self):
        self.ui.actionLoad_file_s.triggered.connect(self._on_load_files)
        self.ui.actionLoad_files_from_folder.triggered.connect(self._on_load_folder)
        self.ui.actionIgnore_selected_files.triggered.connect(self._on_ignore_files)
        self.ui.actionUse_metadata_patterns.toggled.connect(self._on_toggle_metadata_patterns)
        self.ui.actionSet_metadata_patterns.triggered.connect(self._on_set_metadata_patterns)
        self.ui.actionSet_auto_matching_parameters.triggered.connect(
            self._on_set_auto_matching_parameters
        )
        self.ui.actionSet_plotting_settings.triggered.connect(self._on_set_plotting_settings)
        self.ui.actionSet_color_coding.triggered.connect(self._on_set_color_coding)
        self.ui.actionLoad_from_multiple_folders.toggled.connect(self._on_toggle_multi_folder)
        self.ui.actionAbout.triggered.connect(self._on_about)
        self.ui.actionDocs_tutorials.triggered.connect(self._on_docs)
        self.ui.actionUse_metadata_patterns.setChecked(True)
        self.ui.actionLoad_from_multiple_folders.setChecked(False)

    def _build_view_menu(self):
        """Lists every dock's own toggleViewAction() (the standard Qt
        idiom — each QDockWidget already knows how to show/hide/check
        itself) across both Process/Review panels and the Results tab.
        Both HomodynePanel and HDSFGPanel exist for the app's lifetime
        (just hidden inside a QStackedWidget), so their actions work
        regardless of which one is currently active.

        Menus/submenus are kept as instance attributes — without a
        surviving Python reference, PySide6 can garbage-collect the
        underlying C++ QMenu even though it's nominally parented to the
        menu bar.
        """
        self._view_menu = QMenu("View", self.menuBar())
        self.menuBar().insertMenu(self.ui.menuHelp.menuAction(), self._view_menu)
        self._view_submenus = {}
        for panel_name, actions in self.process_review_tab.view_menu_actions().items():
            submenu = self._view_menu.addMenu(panel_name)
            for action in actions:
                submenu.addAction(action)
            self._view_submenus[panel_name] = submenu

        results_submenu = self._view_menu.addMenu("Results panels")
        for action in self.processed_results_tab.view_menu_actions():
            results_submenu.addAction(action)
        self._view_submenus["Results panels"] = results_submenu

    def _build_window_menu(self):
        """Lists currently-open Load/Match plot-preview windows (each its
        own independent, minimizable QWidget — see PlotWindow), rebuilt
        from scratch every time the menu is opened rather than kept in
        sync incrementally, since windows come and go at runtime."""
        self._window_menu = QMenu("Window", self.menuBar())
        self.menuBar().insertMenu(self.ui.menuHelp.menuAction(), self._window_menu)
        self._window_menu.aboutToShow.connect(self._rebuild_window_menu)

    def _rebuild_window_menu(self):
        self._window_menu.clear()
        windows = self.load_match_tab.plot_windows
        if not windows:
            action = self._window_menu.addAction("No plot windows open")
            action.setEnabled(False)
            return
        for window in windows:
            action = self._window_menu.addAction(window.windowTitle())
            action.triggered.connect(
                lambda checked=False, w=window: self._raise_window(w)
            )
        self._window_menu.addSeparator()
        close_all = self._window_menu.addAction("Close all plot windows")
        close_all.triggered.connect(self.load_match_tab.close_plot_windows)

    @staticmethod
    def _raise_window(window):
        window.showNormal()
        window.raise_()
        window.activateWindow()

    # ── Menu handlers ─────────────────────────────────────────────────────────

    def _on_load_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Select file(s)", "",
            "CSV files (*.csv);;All files (*.*)",
        )
        if paths:
            # filter out ignored paths before loading
            paths = [p for p in paths
                     if Path(p).resolve() not in self._ignored_paths]
            if paths:
                self.load_match_tab.load_individual_files(paths)
                self.statusBar().showMessage(f"Added {len(paths)} file(s).")

    def _on_load_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select data folder")
        if folder:
            self.load_match_tab.load_from_folder(folder)
            self.statusBar().showMessage(f"Loaded from {folder}")

    def _on_ignore_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Select files to ignore",
            "",
            "CSV files (*.csv);;All files (*.*)",
        )
        if not paths:
            return

        newly_ignored = set()
        for p in paths:
            resolved = Path(p).resolve()
            if resolved not in self._ignored_paths:
                self._ignored_paths.add(resolved)
                newly_ignored.add(resolved)

        if not newly_ignored:
            self.statusBar().showMessage("All selected files were already ignored.")
            return

        # remove any already-loaded files that are now ignored
        removed = self.load_match_tab.remove_ignored_files(self._ignored_paths)

        msg = f"{len(newly_ignored)} file(s) added to ignore list."
        if removed:
            msg += f" {removed} already-loaded file(s) removed."
        self.statusBar().showMessage(msg)
        logger.info(
            "Ignored paths updated: %d total, %d newly added.",
            len(self._ignored_paths), len(newly_ignored),
        )

    def _on_toggle_metadata_patterns(self, checked: bool):
        self.statusBar().showMessage(
            f"Metadata patterns {'enabled' if checked else 'disabled'}"
        )
        self.load_match_tab.reparse_loaded_files()

    def _on_toggle_multi_folder(self, checked: bool):
        self.statusBar().showMessage(
            f"Load files from multiple folders {'enabled' if checked else 'disabled'}"
        )

    def _on_set_metadata_patterns(self):
        from sfg_app2.app.dialogs.metadata_patterns_dialog import MetadataPatternsDialog
        dialog = MetadataPatternsDialog(self.pattern_manager, parent=self)
        dialog.exec()

    def _on_set_auto_matching_parameters(self):
        from sfg_app2.app.dialogs.auto_matching_settings_dialog import AutoMatchingSettingsDialog
        dialog = AutoMatchingSettingsDialog(self.matching_profiles, parent=self)
        if dialog.exec():
            self.matching_settings = self.matching_profiles.active_settings()
            self.statusBar().showMessage("Auto-matching parameters updated.")

    def _on_set_plotting_settings(self):
        from sfg_app2.app.dialogs.plotting_settings_dialog import PlottingSettingsDialog
        dialog = PlottingSettingsDialog(self.plotting_settings, parent=self)
        if dialog.exec():
            self.process_review_tab.redraw_for_style_change()
            self.processed_results_tab.redraw_for_style_change()
            self.statusBar().showMessage(
                f"Plotting style set to '{self.plotting_settings.style}'."
            )

    def _on_set_color_coding(self):
        from sfg_app2.app.dialogs.color_coding_settings_dialog import ColorCodingSettingsDialog
        from sfg_app2.app.utils import color_coding

        files = getattr(self.load_match_tab, "_files", [])
        if files:
            fields = color_coding.available_fields(f.metadata for f in files)
        else:
            fields = sorted({
                field
                for pattern in self.pattern_manager.active_patterns
                for field in pattern
            })

        dialog = ColorCodingSettingsDialog(self.color_coding_settings, fields, parent=self)
        if dialog.exec():
            self.load_match_tab.refresh_color_coding()
            self.statusBar().showMessage("Filename color-coding settings updated.")

    def _on_about(self):
        self.statusBar().showMessage("SFG-App")

    def _on_docs(self):
        self.statusBar().showMessage("Docs & tutorials — not yet implemented")

    # ── Ignored paths — public property for LoadMatchTab ─────────────────────

    @property
    def ignored_paths(self) -> set[Path]:
        return self._ignored_paths

    @property
    def use_metadata_patterns(self) -> bool:
        return self.ui.actionUse_metadata_patterns.isChecked()

    @property
    def multi_folder_mode(self) -> bool:
        return self.ui.actionLoad_from_multiple_folders.isChecked()