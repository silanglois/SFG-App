from __future__ import annotations
import logging
from pathlib import Path

from PySide6.QtCore import Signal, Qt, QStringListModel
from PySide6.QtWidgets import QWidget, QFileDialog, QMessageBox

from sfg_app2.app.ui.ui_load_match_tab import Ui_loadmatchTab
from sfg_app2.processing.utils import load_datafiles
from sfg_app2.processing.matcher import DataFileMatcher, MatchingConfig

logger = logging.getLogger(__name__)


class LoadMatchTab(QWidget):
    # emitted when user clicks "Start Processing" with complete matched sets
    matching_complete = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.ui = Ui_loadmatchTab()
        self.ui.setupUi(self)

        self._files: list = []          # loaded DataFile objects
        self._matched: list = []        # MatchedSet list after auto-match
        self._file_list_model = QStringListModel()
        self.ui.loadedfilesListView.setModel(self._file_list_model)

        self._connect_signals()

    # ── Signal wiring ─────────────────────────────────────────────────────────

    def _connect_signals(self):
        self.ui.pushButton.clicked.connect(self._on_update)
        self.ui.reviewmetadataButton.clicked.connect(self._on_review_metadata)
        self.ui.automatchButton.clicked.connect(self._on_auto_match)
        self.ui.startprocessingButton.clicked.connect(self._on_start_processing)

        # disable buttons that require files/matching first
        self.ui.reviewmetadataButton.setEnabled(False)
        self.ui.automatchButton.setEnabled(False)
        self.ui.startprocessingButton.setEnabled(False)

    # ── File loading ──────────────────────────────────────────────────────────

    def load_from_folder(self, folder: str | Path):
        """Called by MainWindow when the user picks a folder via the menu."""
        try:
            self._files = load_datafiles(
                folder,
                patterns=[
                    ["sample", "polarization", "center_wavelength",
                     "acquisition_time", "timestamp", "date"],
                    ["sample", "concentration", "potential", "polarization",
                     "center_wavelength", "acquisition_time", "timestamp", "date"],
                ],
            )
            self._refresh_file_list()
            self.ui.reviewmetadataButton.setEnabled(True)
            self.ui.automatchButton.setEnabled(True)
            logger.info("Loaded %d files from %s.", len(self._files), folder)
        except Exception as e:
            QMessageBox.critical(self, "Load Error", str(e))
            logger.error("Failed to load files: %s", e)

    def _refresh_file_list(self):
        names = [f.path.name for f in self._files]
        self._file_list_model.setStringList(names)

    # ── Button handlers ───────────────────────────────────────────────────────

    def _on_update(self):
        """Reload files from the same folder — refreshes if files changed on disk."""
        if not self._files:
            QMessageBox.information(self, "No folder loaded", "Load a folder first via File → Load files from folder.")
            return
        folder = self._files[0].path.parent
        self.load_from_folder(folder)

    def _on_review_metadata(self):
        # placeholder — will open a dialog showing metadata per file
        QMessageBox.information(
            self, "Review Metadata",
            "\n".join(
                f"{f.path.name}: {f.metadata}"
                for f in self._files
            )
        )

    def _on_auto_match(self):
        if not self._files:
            return
        try:
            matcher = DataFileMatcher(
                self._files,
                reference_names=["Au", "gold", "quartz"],
                background_config=MatchingConfig(
                    required_keys=["polarization", "date"],
                    optional_keys=["center_wavelength", "acquisition_time"],
                ),
                reference_config=MatchingConfig(
                    required_keys=["polarization"],
                    optional_keys=["center_wavelength"],
                ),
            )
            self._matched = matcher.match()
            self._refresh_matched_table()
            self.ui.startprocessingButton.setEnabled(True)
            logger.info("Auto-match complete: %d sets.", len(self._matched))
        except Exception as e:
            QMessageBox.critical(self, "Match Error", str(e))
            logger.error("Auto-match failed: %s", e)

    def _on_start_processing(self):
        incomplete = [m for m in self._matched if not m.is_complete()]
        if incomplete:
            reply = QMessageBox.question(
                self,
                "Incomplete Matches",
                f"{len(incomplete)} matched set(s) are incomplete and will be skipped.\n"
                "Continue anyway?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply == QMessageBox.No:
                return
        self.matching_complete.emit(self._matched)

    # ── Matched files table ───────────────────────────────────────────────────

    def _refresh_matched_table(self):
        """Populate matchedfilesTableView with matched set summaries."""
        from PySide6.QtGui import QStandardItemModel, QStandardItem

        model = QStandardItemModel()
        model.setHorizontalHeaderLabels(
            ["Signal", "Background", "Reference", "Ref Background", "Complete"]
        )

        def name(f):
            return f.path.name if f else "—"

        for m in self._matched:
            row = [
                QStandardItem(name(m.signal)),
                QStandardItem(name(m.background)),
                QStandardItem(name(m.reference)),
                QStandardItem(name(m.reference_background)),
                QStandardItem("✓" if m.is_complete() else "✗"),
            ]
            for item in row:
                item.setEditable(False)
            model.appendRow(row)

        self.ui.matchedfilesTableView.setModel(model)
        self.ui.matchedfilesTableView.resizeColumnsToContents()