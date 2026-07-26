# src/sfg_app2/app/main_window.py
from __future__ import annotations
import logging
from pathlib import Path

from PySide6.QtWidgets import QMainWindow, QVBoxLayout, QFileDialog, QMessageBox
from sfg_app2.app.ui.ui_main_window import Ui_MainWindow
from sfg_app2.app.utils.pattern_manager import PatternManager
from sfg_app2.app.utils.plotting_settings import PlottingSettings

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)

        self.matched_sets: list = []
        self.processed_results: dict = {}
        self.pattern_manager = PatternManager()
        self.plotting_settings = PlottingSettings()
        self.plotting_settings.apply_current()
        self._ignored_paths: set[Path] = set()  # resolved absolute paths

        self._init_tabs()
        self._connect_menu()
        self._lock_tabs_from(1)
        self.ui.mainTabWidget.setTabEnabled(2, True)   # Results always accessible
        self.ui.mainTabWidget.setTabEnabled(3, True)   # Post Processing always accessible

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
        self.ui.actionAbout.triggered.connect(self._on_about)
        self.ui.actionDocs_tutorials.triggered.connect(self._on_docs)
        self.ui.actionUse_metadata_patterns.setChecked(True)

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

    def _on_set_metadata_patterns(self):
        from sfg_app2.app.dialogs.metadata_patterns_dialog import MetadataPatternsDialog
        dialog = MetadataPatternsDialog(self.pattern_manager, parent=self)
        dialog.exec()

    def _on_set_auto_matching_parameters(self):
        self.statusBar().showMessage("Auto-matching parameters — not yet implemented")

    def _on_set_plotting_settings(self):
        from sfg_app2.app.dialogs.plotting_settings_dialog import PlottingSettingsDialog
        dialog = PlottingSettingsDialog(self.plotting_settings, parent=self)
        if dialog.exec():
            self.statusBar().showMessage(
                f"Plotting style set to '{self.plotting_settings.style}'. "
                "Restart the app for already-open plots to fully update."
            )

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