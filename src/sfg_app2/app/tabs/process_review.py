from __future__ import annotations
import logging
from pathlib import Path

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (
    QWidget, QListWidgetItem, QMessageBox, QMenu, QFileDialog,
    QButtonGroup, QAbstractItemView, QSizePolicy,
)

from sfg_app2.app.ui.ui_process_review_tab import Ui_Form
from sfg_app2.app.widgets.hd_sfg_panel import HDSFGPanel
from sfg_app2.app.widgets.homodyne_panel import HomodynePanel

logger = logging.getLogger(__name__)


class ProcessReviewTab(QWidget):
    processing_complete = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.ui = Ui_Form()
        self.ui.setupUi(self)

        self.ui.calibrationFrame.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )

        self._matched_sets: list = []

        self._setup_button_groups()
        self._setup_right_stack()
        self._connect_signals()

    # ── Setup ─────────────────────────────────────────────────────────────────

    def _setup_button_groups(self):
        self._view_group = QButtonGroup(self)
        self._view_group.addButton(self.ui.singleViewRadio)
        self._view_group.addButton(self.ui.compareViewRadio)

    def _setup_right_stack(self):
        from PySide6.QtWidgets import QStackedWidget

        idx = self.ui.splitter.indexOf(self.ui.rightPanelWidget)
        if idx < 0:
            logger.error("rightPanelWidget not found in splitter.")
            return

        # rightPanelWidget is now just an empty placeholder (its contents
        # moved into HomodynePanel) — detach it before inserting the stack
        # in its place, so it doesn't linger as an extra empty splitter pane.
        self.ui.rightPanelWidget.setParent(None)

        self._right_stack = QStackedWidget()

        self._homodyne_panel = HomodynePanel()
        self._homodyne_panel.processing_complete.connect(self.processing_complete)
        self._right_stack.addWidget(self._homodyne_panel)   # page 0: homodyne

        self._hd_sfg_panel = HDSFGPanel()
        self._hd_sfg_panel.processing_complete.connect(self.processing_complete)
        self._right_stack.addWidget(self._hd_sfg_panel)     # page 1: HD-SFG

        self.ui.splitter.insertWidget(idx, self._right_stack)

    def _connect_signals(self):
        self.ui.matchedSetsListWidget.itemSelectionChanged.connect(
            self._on_selection_changed
        )
        self.ui.singleViewRadio.toggled.connect(self._on_view_changed)
        self.ui.upconversionSpinBox.valueChanged.connect(self._on_upconversion_changed)
        self.ui.calibrateButton.clicked.connect(self._on_calibrate)
        self.ui.matchedSetsListWidget.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self.ui.matchedSetsListWidget.customContextMenuRequested.connect(
            self._on_list_context_menu
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def set_matched_sets(self, matched_sets: list):
        self._matched_sets = matched_sets
        self._homodyne_panel.set_matched_sets(matched_sets)
        self._hd_sfg_panel.reset()
        self._populate_list()

    def get_upconversion_wavelength(self) -> float:
        return self.ui.upconversionSpinBox.value()

    # ── List ──────────────────────────────────────────────────────────────────

    def _populate_list(self):
        self.ui.matchedSetsListWidget.clear()
        for i, m in enumerate(self._matched_sets):
            complete = m.is_complete()
            name = m.signal.path.name if m.signal else f"Set {i + 1}"
            item = QListWidgetItem(f"{'✓' if complete else '✗'} {name}")
            item.setForeground(
                Qt.GlobalColor.darkGreen if complete else Qt.GlobalColor.red
            )
            self.ui.matchedSetsListWidget.addItem(item)

    # ── Notebook export ───────────────────────────────────────────────────────

    def _on_list_context_menu(self, pos):
        item = self.ui.matchedSetsListWidget.itemAt(pos)
        if item is None:
            return
        row = self.ui.matchedSetsListWidget.row(item)
        if not (0 <= row < len(self._matched_sets)):
            return
        matched = self._matched_sets[row]

        menu = QMenu(self)
        export_action = menu.addAction("Export processing notebook...")
        export_action.setEnabled(matched.is_complete())
        if not matched.is_complete():
            export_action.setToolTip("This set is missing one of its four files.")

        action = menu.exec(
            self.ui.matchedSetsListWidget.viewport().mapToGlobal(pos)
        )
        if action == export_action:
            self._on_export_processing_notebook(matched, row)

    def _notebook_payload(self, matched, idx: int) -> dict:
        """Everything the processing notebook needs, as plain data.

        The raw files are read back off disk rather than re-serialized
        from the loaded DataFrames, so the notebook starts from exactly
        the same bytes the app did -- including whichever of the two CSV
        layouts the instrument wrote.
        """
        kind = "heterodyne" if matched.spectrum_type == "heterodyne" else "homodyne"
        roles, raw_files = {}, {}
        for role in ("signal", "background", "reference", "reference_background"):
            data_file = getattr(matched, role, None)
            if data_file is None:
                continue
            path = Path(data_file.path)
            roles[role] = path.name
            raw_files[path.name] = path.read_text(encoding="utf-8", errors="replace")

        label = Path(matched.signal.path).stem if matched.signal else "processed"
        if kind == "heterodyne":
            config = self._hd_sfg_panel.notebook_config(self.get_upconversion_wavelength())
        else:
            config = self._homodyne_panel.notebook_config(
                self.get_upconversion_wavelength(), idx=idx,
            )

        return {
            "kind": kind,
            "label": label,
            "roles": roles,
            "raw_files": raw_files,
            "config": {**config, "label": label},
        }

    def _on_export_processing_notebook(self, matched, idx: int):
        from sfg_app2.app.utils import notebook_export, notebook_processing
        from sfg_app2.app.utils.loading_indicator import show_loading

        label = Path(matched.signal.path).stem if matched.signal else "processed"
        path_str, _ = QFileDialog.getSaveFileName(
            self, "Export processing notebook", f"{label}_processing.ipynb",
            "Jupyter Notebook (*.ipynb)",
        )
        if not path_str:
            return
        path = Path(path_str)
        if path.suffix.lower() != ".ipynb":
            path = path.with_suffix(".ipynb")

        loading = show_loading(self, "Building notebook...")
        try:
            payload = self._notebook_payload(matched, idx)
            notebook_export.write_notebook(notebook_processing.build(payload), path)
        except notebook_export.ProcessingSourceUnavailable as e:
            logger.error("Notebook export unavailable: %s", e)
            QMessageBox.warning(
                self, "Couldn't export notebook",
                "The processing sources this notebook embeds aren't available "
                f"in this build.\n\n{e}",
            )
            return
        except Exception as e:
            logger.error("Notebook export failed: %s", e, exc_info=True)
            QMessageBox.warning(self, "Couldn't export notebook", str(e))
            return
        finally:
            loading.close()

        size_kb = path.stat().st_size / 1024
        QMessageBox.information(
            self, "Notebook exported",
            f"Wrote {path.name} ({size_kb:.0f} KB).\n\nThe four raw files and "
            f"the processing code are both embedded — it runs as-is on Google "
            f"Colab, with nothing to upload and nothing to install.",
        )

    def _on_selection_changed(self):
        row = self.ui.matchedSetsListWidget.currentRow()
        all_selected = [
            i.row() for i in self.ui.matchedSetsListWidget.selectedIndexes()
        ]

        if row < 0 or row >= len(self._matched_sets):
            self.ui.setStatusLabel.setText("")
        else:
            m = self._matched_sets[row]

            def name(f):
                return f.path.name if f else "—"

            self.ui.setStatusLabel.setText(
                f"Signal:  {name(m.signal)}\n"
                f"BG:      {name(m.background)}\n"
                f"Ref:     {name(m.reference)}\n"
                f"Ref BG:  {name(m.reference_background)}\n"
                f"Type:    {m.spectrum_type}"
            )

            if m.spectrum_type == "heterodyne":
                self._right_stack.setCurrentIndex(1)
                self._hd_sfg_panel.set_matched_set(m, row)
            else:
                self._right_stack.setCurrentIndex(0)

        homodyne_indices = [
            i for i in all_selected
            if 0 <= i < len(self._matched_sets)
            and self._matched_sets[i].spectrum_type != "heterodyne"
        ]
        self._homodyne_panel.set_selection(homodyne_indices)

    def _on_view_changed(self, single: bool):
        self.ui.matchedSetsListWidget.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection if single
            else QAbstractItemView.SelectionMode.ExtendedSelection
        )

    # ── Plotting style ────────────────────────────────────────────────────────

    def redraw_for_style_change(self):
        self._hd_sfg_panel.redraw_for_style_change()
        self._homodyne_panel.redraw_for_style_change()

    # ── Dock layout persistence ──────────────────────────────────────────────

    def save_dock_layouts(self, settings):
        settings.set("homodyne", self._homodyne_panel.save_dock_state())
        settings.set("hd_sfg", self._hd_sfg_panel.save_dock_state())

    def restore_dock_layouts(self, settings):
        self._homodyne_panel.restore_dock_state(settings.get("homodyne"))
        self._hd_sfg_panel.restore_dock_state(settings.get("hd_sfg"))

    def view_menu_actions(self) -> dict[str, list]:
        return {
            "Homodyne panels": self._homodyne_panel.view_menu_actions(),
            "HD-SFG panels": self._hd_sfg_panel.view_menu_actions(),
        }

    # ── Upconversion ──────────────────────────────────────────────────────────

    def _on_upconversion_changed(self):
        self._homodyne_panel.on_upconversion_changed()
        stale = self._hd_sfg_panel.on_upconversion_changed()
        wl = self.ui.upconversionSpinBox.value()
        msg = f"Upconversion wavelength set to {wl:.1f} nm."
        if stale:
            msg += f" {stale} other HD-SFG set(s) will need reprocessing to reflect it."
        self.window().statusBar().showMessage(msg)

    # ── Calibration ───────────────────────────────────────────────────────────

    def _on_calibrate(self):
        from sfg_app2.app.dialogs.calibration_dialog import CalibrationDialog

        if not self._matched_sets:
            QMessageBox.information(self, "No data", "Load and match files first.")
            return
        # No dependency check up front any more: a missing
        # 'refractiveindex' only rules out tabulated materials, and the
        # dialog's other two reference modes work without it.
        dialog = CalibrationDialog(
            matched_sets=self._matched_sets,
            initial_wavelength=self.ui.upconversionSpinBox.value(),
            settings=getattr(self.window(), "calibration_settings", None),
            parent=self,
        )
        if dialog.exec():
            self.ui.upconversionSpinBox.setValue(dialog.result_wavelength)
