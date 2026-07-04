from __future__ import annotations
import logging
from PySide6.QtWidgets import QFileDialog, QMainWindow, QVBoxLayout
from sfg_app2.app.ui.ui_main_window import Ui_MainWindow

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)

        # shared state — populated as the user progresses through tabs
        self.matched_sets: list = []
        self.processed_results: dict = {}

        self._init_tabs()
        self._connect_menu()
        self._lock_tabs_from(1)   # only Load/Match tab enabled at start

    # ── Tab setup ─────────────────────────────────────────────────────────────

    def _init_tabs(self):
        """Replace placeholder widgets with real tab content."""
        # Tab 1: Load/Match
        # Import here to avoid circular imports at module level
        from sfg_app2.app.tabs.load_match import LoadMatchTab
        self.load_match_tab = LoadMatchTab()
        self._replace_tab(0, self.load_match_tab, "Load / Match")
        self.load_match_tab.matching_complete.connect(self._on_matching_complete)

        # future tabs — add here as you build them
        # from sfg_app2.app.tabs.parameters import ParametersTab
        # self.parameters_tab = ParametersTab()
        # self._replace_tab(1, self.parameters_tab, "Processing Parameters")

    def _replace_tab(self, index: int, widget, label: str):
        """Swap a whole tab (used when the tab has no placeholder child)."""
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
        logger.info("Matching complete: %d matched sets.", len(matched_sets))
        self.statusBar().showMessage(f"Matched {len(matched_sets)} file sets.")
        self.unlock_tab(1)

    # ── Menu connections ──────────────────────────────────────────────────────

    def _connect_menu(self):
        self.ui.actionLoad_file_s.triggered.connect(self._on_load_files)
        self.ui.actionLoad_files_from_folder.triggered.connect(self._on_load_folder)
        self.ui.actionIgnore_selected_files.triggered.connect(self._on_ignore_files)
        self.ui.actionUse_metadata_patterns.toggled.connect(self._on_toggle_metadata_patterns)
        self.ui.actionSet_metadata_patterns.triggered.connect(self._on_set_metadata_patterns)
        self.ui.actionAbout.triggered.connect(self._on_about)
        self.ui.actionDocs_tutorials.triggered.connect(self._on_docs)

    # ── Menu handlers (stubs — fill in as you build each feature) ────────────

    def _on_load_files(self):
        self.statusBar().showMessage("Load file(s) — not yet implemented")

    def _on_load_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select data folder")
        if folder:
            self.load_match_tab.load_from_folder(folder)
            self.statusBar().showMessage(f"Loaded from {folder}")

    def _on_ignore_files(self):
        self.statusBar().showMessage("Ignore selected — not yet implemented")

    def _on_toggle_metadata_patterns(self, checked: bool):
        self.statusBar().showMessage(
            f"Metadata patterns {'enabled' if checked else 'disabled'}"
        )

    def _on_set_metadata_patterns(self):
        self.statusBar().showMessage("Set metadata patterns — not yet implemented")

    def _on_about(self):
        self.statusBar().showMessage("SFG-App — about dialog not yet implemented")

    def _on_docs(self):
        self.statusBar().showMessage("Docs & tutorials — not yet implemented")


















# from PySide6.QtWidgets import (
#     QMainWindow, QTabWidget, QWidget,
#     QVBoxLayout, QLabel
# )


# class MainWindow(QMainWindow):
#     def __init__(self):
#         super().__init__()
#         self.setWindowTitle("SFG App")
#         self.setMinimumSize(1000, 700)

#         self.tabs = QTabWidget()
#         self.setCentralWidget(self.tabs)

#         # placeholder tabs — replace one at a time
#         self._add_placeholder("Load & Match")
#         self._add_placeholder("Processing Parameters")
#         self._add_placeholder("Process & Review")
#         self._add_placeholder("Fitting")
#         self._add_placeholder("Export")

#         # disable tabs that aren't ready yet
#         for i in range(1, self.tabs.count()):
#             self.tabs.setTabEnabled(i, False)

#     def _add_placeholder(self, name: str):
#         widget = QWidget()
#         layout = QVBoxLayout(widget)
#         layout.addWidget(QLabel(f"{name} — coming soon"))
#         self.tabs.addTab(widget, name)

#     def unlock_tab(self, index: int):
#         """Call this when a step is complete to enable the next tab."""
#         self.tabs.setTabEnabled(index, True)
#         self.tabs.setCurrentIndex(index)