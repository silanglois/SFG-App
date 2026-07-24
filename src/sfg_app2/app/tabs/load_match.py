from __future__ import annotations
import logging
from pathlib import Path

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import QWidget, QFileDialog, QMessageBox

from sfg_app2.app.ui.ui_load_match_tab import Ui_loadmatchTab
from sfg_app2.app.widgets.file_list_widget import FileListWidget
from sfg_app2.app.widgets.match_table import MatchTableView
from sfg_app2.processing.utils import load_datafiles
from sfg_app2.processing.data_file import UnrecognizedFormatError

logger = logging.getLogger(__name__)


class LoadMatchTab(QWidget):
    matching_complete = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.ui = Ui_loadmatchTab()
        self.ui.setupUi(self)

        self._files: list = []
        self._file_registry: dict = {}      # path str → DataFile
        self._loaded_folder: Path | None = None
        self._individual_file_paths: list[Path] = []

        self._replace_list_and_table()
        self._connect_signals()
        self._set_buttons_enabled(files_loaded=False, matched=False)

    # ── Widget replacement ────────────────────────────────────────────────────

    def _replace_list_and_table(self):
        """Replace QListView and QTableView from .ui with custom widgets."""
        splitter = self.ui.splitter

        # replace QListView (index 0) with FileListWidget
        old_list = splitter.widget(0)
        old_list.hide()
        self.file_list_widget = FileListWidget()
        splitter.insertWidget(0, self.file_list_widget)

        # replace QTableView (index 2, since we inserted at 0) with MatchTableView
        old_table = splitter.widget(2)
        old_table.hide()
        self.match_table = MatchTableView()
        splitter.insertWidget(2, self.match_table)

    # ── Signal wiring ─────────────────────────────────────────────────────────

    def _connect_signals(self):
        self.ui.pushButton.clicked.connect(self._on_update)
        self.ui.reviewmetadataButton.clicked.connect(self._on_review_metadata)
        self.ui.automatchButton.clicked.connect(self._on_auto_match)
        self.ui.startprocessingButton.clicked.connect(self._on_start_processing)
        self.match_table.table_changed.connect(self._on_table_changed)
        self.file_list_widget.remove_requested.connect(self._on_remove_files)
        self.file_list_widget.metadata_requested.connect(self._on_review_metadata)
        self.file_list_widget.plot_requested.connect(self._on_plot_files)

    def _set_buttons_enabled(self, files_loaded: bool, matched: bool):
        self.ui.reviewmetadataButton.setEnabled(files_loaded)
        self.ui.automatchButton.setEnabled(files_loaded)
        self.ui.startprocessingButton.setEnabled(matched)

    # ── File loading ──────────────────────────────────────────────────────────

    def load_from_folder(self, folder: str | Path):
        try:
            new_files = load_datafiles(folder, patterns=self._get_active_patterns())
            self._loaded_folder = Path(folder)
            added, skipped = self._merge_files(new_files)
            self._refresh_file_list()
            self._report_merge_result(added, skipped)
            self._set_buttons_enabled(files_loaded=bool(self._files), matched=False)
        except Exception as e:
            QMessageBox.critical(self, "Load Error", str(e))
            logger.error("Failed to load files: %s", e)

    def load_individual_files(self, paths: list[str]):
        from sfg_app2.processing.data_file import DataFile
        from sfg_app2.processing.utils import _strip_role_suffix, DEFAULT_ROLE_SUFFIXES

        newly_loaded = []
        for path_str in paths:
            path = Path(path_str)
            try:
                patterns = self._get_active_patterns()
                clean_stem, role = _strip_role_suffix(path.stem, DEFAULT_ROLE_SUFFIXES)
                n_parts = len(clean_stem.split("_"))
                pattern_map = {len(p): p for p in patterns} if patterns else {}
                fields = pattern_map.get(n_parts) if pattern_map else None
                extra_metadata = {"role": role} if role else {}
                newly_loaded.append(DataFile(path, filename_fields=fields, metadata=extra_metadata))
            except UnrecognizedFormatError as e:
                logger.warning("Skipping %s: %s", path.name, e)
            except Exception as e:
                logger.warning("Could not load %s: %s — skipping.", path.name, e)

        added, skipped = self._merge_files(newly_loaded)
        self._individual_file_paths.extend(f.path for f in added)
        self._refresh_file_list()
        self._report_merge_result(added, skipped)
        self._set_buttons_enabled(files_loaded=bool(self._files), matched=False)

    def _merge_files(self, new_files: list) -> tuple[list, list]:
        existing = {f.path.resolve() for f in self._files}
        ignored = self._get_ignored_paths()
        added, skipped = [], []
        for f in new_files:
            resolved = f.path.resolve()
            if resolved in existing or resolved in ignored:
                skipped.append(f.path)
            else:
                self._files.append(f)
                self._file_registry[str(f.path)] = f
                existing.add(resolved)
                added.append(f)
        return added, skipped

    def _get_ignored_paths(self) -> set[Path]:
        """Pull ignored paths from MainWindow if available."""
        try:
            main = self.window()
            if hasattr(main, "ignored_paths"):
                return main.ignored_paths
        except Exception:
            pass
        return set()

    def remove_ignored_files(self, ignored_paths: set[Path]) -> int:
        """Remove any loaded files whose resolved path is in ignored_paths.
        Called by MainWindow when the ignore list changes.
        Returns count of files removed.
        """
        to_remove = {
            str(f.path) for f in self._files
            if f.path.resolve() in ignored_paths
        }
        if not to_remove:
            return 0

        # warn if any are in the match table
        table_paths = self.match_table._table_model.all_paths_used()
        in_table = to_remove & table_paths
        if in_table:
            names = "\n".join(Path(p).name for p in in_table)
            reply = QMessageBox.question(
                self,
                "Ignored files in match table",
                f"The following ignored file(s) are assigned in the match table "
                f"and will be removed:\n\n{names}\n\nContinue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.No:
                return 0

        # remove from table
        for path in in_table:
            model = self.match_table._table_model
            for row in range(model.rowCount()):
                for col in range(model.columnCount()):
                    if model.data(
                        model.createIndex(row, col),
                        Qt.ItemDataRole.UserRole
                    ) == path:
                        model.clear_cell(row, col)

        # remove from file tracking
        self._files = [f for f in self._files if str(f.path) not in to_remove]
        for p in to_remove:
            self._file_registry.pop(p, None)
        self._individual_file_paths = [
            p for p in self._individual_file_paths
            if str(p) not in to_remove
        ]

        self._refresh_file_list()
        self._on_table_changed()
        return len(to_remove)

    def _refresh_file_list(self):
        self.file_list_widget.set_files(self._files)
        # re-sync used markers against current table state
        self._on_table_changed()

    def _on_table_changed(self):
        """Sync used markers whenever table changes."""
        used = self.match_table._table_model.all_paths_used()
        self.file_list_widget.sync_used(used)
        # enable start processing if at least one row has a signal
        has_rows = self.match_table._table_model.rowCount() > 0
        self._set_buttons_enabled(files_loaded=bool(self._files), matched=has_rows)

    def _get_active_patterns(self) -> list[list[str]] | None:
        """Returns active patterns if the toggle is on, None otherwise.
        None signals load_datafiles to skip pattern parsing entirely.
        """
        try:
            main = self.window()
            if hasattr(main, "use_metadata_patterns") and not main.use_metadata_patterns:
                return None
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

    def reparse_loaded_files(self):
        """Re-parse filename metadata for all loaded files using current
        toggle state and active patterns. Manual metadata always wins.
        """
        from sfg_app2.processing.utils import _strip_role_suffix, DEFAULT_ROLE_SUFFIXES

        patterns = self._get_active_patterns()
        pattern_map = {len(p): p for p in patterns} if patterns else {}

        for f in self._files:
            clean_stem, _ = _strip_role_suffix(f.path.stem, DEFAULT_ROLE_SUFFIXES)
            n_parts = len(clean_stem.split("_"))
            fields = pattern_map.get(n_parts) if pattern_map else None
            f.reparse_filename_metadata(fields)

        logger.info(
            "Re-parsed metadata for %d files (patterns %s).",
            len(self._files),
            "enabled" if patterns else "disabled",
        )
        self._refresh_file_list()

    # ── Button handlers ───────────────────────────────────────────────────────

    def _on_update(self):
        if not self._files and self._loaded_folder is None:
            QMessageBox.information(self, "Nothing loaded",
                                    "Load a folder or files first.")
            return
        self._files = []
        self._file_registry = {}

        if self._loaded_folder:
            try:
                folder_files = load_datafiles(
                    self._loaded_folder,
                    patterns=self._get_active_patterns()
                )
                # filter ignored before merging
                ignored = self._get_ignored_paths()
                folder_files = [f for f in folder_files
                                if f.path.resolve() not in ignored]
                self._merge_files(folder_files)
            except Exception as e:
                QMessageBox.critical(self, "Update Error", str(e))

        if self._individual_file_paths:
            ignored = self._get_ignored_paths()
            still_valid = [
                p for p in self._individual_file_paths
                if p.exists() and p.resolve() not in ignored
            ]
            self._individual_file_paths = still_valid
            if still_valid:
                self.load_individual_files([str(p) for p in still_valid])

        self._refresh_file_list()

    def _on_review_metadata(self):
        QMessageBox.information(
            self, "Review Metadata",
            "\n".join(f"{f.path.name}: {f.metadata}" for f in self._files)
        )

    def _on_auto_match(self):
        if not self._files:
            return
        try:
            from sfg_app2.processing.matcher import DataFileMatcher, MatchingConfig
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
            matched = matcher.match()
            self._populate_table_from_matched(matched)
            self._set_buttons_enabled(files_loaded=True, matched=True)
        except Exception as e:
            QMessageBox.critical(self, "Match Error", str(e))
            logger.error("Auto-match failed: %s", e)

    def _populate_table_from_matched(self, matched: list):
        model = self.match_table._table_model
        while model.rowCount() > 0:
            model.remove_row(0)

        def add(row, col, f):
            if f is not None:
                model.set_cell(row, col, str(f.path), f.path.name)

        for m in matched:
            row = model.add_row()
            add(row, 0, m.signal)
            add(row, 1, m.background)
            add(row, 2, m.reference)
            add(row, 3, m.reference_background)
            model.set_type(row, m.spectrum_type.capitalize())

        self._on_table_changed()

    def _on_start_processing(self):
        matched = self.match_table._table_model.to_matched_sets(self._file_registry)
        incomplete = [m for m in matched if not m.is_complete()]
        if incomplete:
            reply = QMessageBox.question(
                self, "Incomplete Matches",
                f"{len(incomplete)} set(s) are incomplete and will be skipped. Continue?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply == QMessageBox.No:
                return
        self.matching_complete.emit(matched)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _get_active_patterns(self) -> list[list[str]]:
        try:
            main = self.window()
            if hasattr(main, "pattern_manager"):
                return main.pattern_manager.active_patterns
        except Exception:
            pass
        return [
            ["sample", "polarization", "center_wavelength", "acquisition_time", "timestamp", "date"],
            ["sample", "concentration", "potential", "polarization",
             "center_wavelength", "acquisition_time", "timestamp", "date"],
        ]

    def _report_merge_result(self, added: list, skipped: list):
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

    # ── Context Menu Handlers ─────────────────────────────────────────

    def _on_remove_files(self, paths: list[str]):
        # check which are in the match table
        table_paths = self.match_table._table_model.all_paths_used()
        in_table = [p for p in paths if p in table_paths]

        if in_table:
            names = "\n".join(Path(p).name for p in in_table)
            reply = QMessageBox.question(
                self,
                "Files in Match Table",
                f"The following file(s) are assigned in the match table "
                f"and will be removed from both:\n\n{names}\n\nContinue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.No:
                return

        # remove from table first
        for path in in_table:
            model = self.match_table._table_model
            for row in range(model.rowCount()):
                for col in range(model.columnCount()):
                    if model.data(model.createIndex(row, col),
                                Qt.ItemDataRole.UserRole) == path:
                        model.clear_cell(row, col)

        # remove from file list and registry
        path_set = set(paths)
        self._files = [f for f in self._files if str(f.path) not in path_set]
        for p in path_set:
            self._file_registry.pop(p, None)
        self._individual_file_paths = [
            p for p in self._individual_file_paths if str(p) not in path_set
        ]

        self._refresh_file_list()
        self._on_table_changed()
        logger.info("Removed %d file(s).", len(paths))

    def _on_review_metadata(self, paths: list[str]):
        from sfg_app2.app.dialogs.metadata_edit_dialog import MetadataEditDialog
        files = [self._file_registry[p] for p in paths if p in self._file_registry]
        if not files:
            return
        dialog = MetadataEditDialog(files, parent=self)
        dialog.exec()

    def _on_plot_files(self, paths: list[str]):
        from sfg_app2.app.dialogs.plot_dialog import PlotDialog
        files = [self._file_registry[p] for p in paths if p in self._file_registry]
        if not files:
            return
        dialog = PlotDialog(files, parent=self)
        dialog.exec()