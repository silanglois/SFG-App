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
        self._loaded_folder: Path | None = None  # set only by load_from_folder
        self._individual_file_paths: list[Path] = [] # set only by load_individual_files
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
        try:
            new_files = load_datafiles(
                folder,
                patterns=self._get_active_patterns(),
            )
            self._loaded_folder = Path(folder)
            added, skipped = self._merge_files(new_files)
            self._refresh_file_list()
            if skipped:
                logger.info(
                    "%d duplicate(s) skipped from folder load.", len(skipped)
                )
            if self._files:
                self.ui.reviewmetadataButton.setEnabled(True)
                self.ui.automatchButton.setEnabled(True)
            logger.info("Loaded %d new files from %s.", len(added), folder)
        except Exception as e:
            QMessageBox.critical(self, "Load Error", str(e))
            logger.error("Failed to load files: %s", e)

    def _refresh_file_list(self):
        names = [f.path.name for f in self._files]
        self._file_list_model.setStringList(names)

    def load_individual_files(self, paths: list[str]):
        """Load individual files and merge into existing file list,
        skipping duplicates by resolved absolute path."""
        from sfg_app2.processing.data_file import DataFile
        from sfg_app2.processing.utils import _strip_role_suffix, DEFAULT_ROLE_SUFFIXES

        newly_loaded = []
        for path_str in paths:
            path = Path(path_str)
            try:
                # use same pattern logic as load_datafiles
                # pull active patterns from pattern_manager if available
                patterns = self._get_active_patterns()
                clean_stem, role = _strip_role_suffix(path.stem, DEFAULT_ROLE_SUFFIXES)
                n_parts = len(clean_stem.split("_"))
                pattern_map = {len(p): p for p in patterns}
                fields = pattern_map.get(n_parts)
                extra_metadata = {"role": role} if role else {}
                newly_loaded.append(
                    DataFile(path, filename_fields=fields, metadata=extra_metadata)
                )
            except Exception as e:
                logger.warning("Could not load %s: %s — skipping.", path.name, e)

        added, skipped = self._merge_files(newly_loaded)
        self._individual_file_paths.extend(f.path for f in added)
        self._refresh_file_list()

        if skipped:
            logger.info(
                "%d file(s) skipped as duplicates: %s",
                len(skipped), [p.name for p in skipped]
            )
        if added:
            self.ui.reviewmetadataButton.setEnabled(True)
            self.ui.automatchButton.setEnabled(True)

        self._report_merge_result(added, skipped)

    def _merge_files(self, new_files: list) -> tuple[list, list]:
        """Merge new DataFile objects into self._files, skipping duplicates.
        Returns (added, skipped) lists.
        """
        existing_paths = {f.path.resolve() for f in self._files}
        added, skipped = [], []
        for f in new_files:
            if f.path.resolve() in existing_paths:
                skipped.append(f.path)
            else:
                self._files.append(f)
                existing_paths.add(f.path.resolve())
                added.append(f)
        return added, skipped

    def _get_active_patterns(self) -> list[list[str]]:
        """Pull active patterns from MainWindow's PatternManager if available,
        fall back to hardcoded defaults."""
        try:
            main = self.window()
            if hasattr(main, "pattern_manager"):
                return main.pattern_manager.active_patterns
        except Exception:
            pass
        return [
            ["sample", "polarization", "center_wavelength",
            "acquisition_time", "timestamp", "date"],
            ["sample", "concentration", "potential", "polarization",
            "center_wavelength", "acquisition_time", "timestamp", "date"],
        ]

    def _report_merge_result(self, added: list, skipped: list):
        """Show a brief status message — only pops a dialog if there were skips."""
        from PySide6.QtWidgets import QMessageBox
        if skipped and added:
            QMessageBox.information(
                self, "Files Loaded",
                f"{len(added)} file(s) added.\n"
                f"{len(skipped)} duplicate(s) skipped:\n"
                + "\n".join(p.name for p in skipped)
            )
        elif skipped and not added:
            QMessageBox.warning(
                self, "No New Files",
                f"All {len(skipped)} selected file(s) are already loaded."
            )
        # if no skips, statusBar message in main_window is enough — no popup needed

    # ── Button handlers ───────────────────────────────────────────────────────

    def _on_update(self):
        if not self._files and self._loaded_folder is None and not self._individual_file_paths:
            QMessageBox.information(
                self, "Nothing loaded",
                "Load a folder or individual files first."
            )
            return

        self._files = []   # clear, then reload from tracked sources

        if self._loaded_folder:
            try:
                folder_files = load_datafiles(
                    self._loaded_folder,
                    patterns=self._get_active_patterns(),
                )
                added, _ = self._merge_files(folder_files)
                logger.info("Update: reloaded %d files from folder.", len(added))
            except Exception as e:
                QMessageBox.critical(self, "Update Error", str(e))
                logger.error("Failed to reload folder: %s", e)

        if self._individual_file_paths:
            # re-load only the individually selected files, skip any that no longer exist
            still_exist = [p for p in self._individual_file_paths if p.exists()]
            missing = [p for p in self._individual_file_paths if not p.exists()]
            if missing:
                logger.warning(
                    "Update: %d individually loaded file(s) no longer exist: %s",
                    len(missing), [p.name for p in missing]
                )
            self._individual_file_paths = still_exist   # drop missing from tracking
            self.load_individual_files([str(p) for p in still_exist])

        self._refresh_file_list()
        logger.info("Update complete: %d files total.", len(self._files))

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