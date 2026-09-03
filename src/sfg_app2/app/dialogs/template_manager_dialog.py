from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QAbstractItemView,
    QPushButton, QLabel, QMessageBox, QInputDialog, QFileDialog, QDialogButtonBox,
)

from sfg_app2.app.utils.fit_template_manager import FitTemplateManager


class TemplateManagerDialog(QDialog):
    """Rename/delete/export/import fit templates -- everything the
    Fitting tab's compact combo+Apply+Save row doesn't have room for.
    Every action (rename/delete/import) writes straight through to the
    FitTemplateManager (and thus disk) immediately, same as Save/Apply
    already do on the main tab -- there's no separate "commit" step,
    so Close is the only way out and it's always safe to click.
    """

    def __init__(self, manager: FitTemplateManager, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Manage fit templates")
        self.resize(420, 380)
        self._manager = manager

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "Select one or more templates. Rename/Delete act on a single "
            "selection; Export works on any number selected."
        ))

        self._list = QListWidget()
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        layout.addWidget(self._list, stretch=1)
        self._refresh_list()

        btn_row = QHBoxLayout()
        rename_btn = QPushButton("Rename...")
        rename_btn.clicked.connect(self._on_rename)
        btn_row.addWidget(rename_btn)
        delete_btn = QPushButton("Delete")
        delete_btn.clicked.connect(self._on_delete)
        btn_row.addWidget(delete_btn)
        export_btn = QPushButton("Export...")
        export_btn.clicked.connect(self._on_export)
        btn_row.addWidget(export_btn)
        import_btn = QPushButton("Import...")
        import_btn.clicked.connect(self._on_import)
        btn_row.addWidget(import_btn)
        layout.addLayout(btn_row)

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        button_box.rejected.connect(self.reject)
        button_box.accepted.connect(self.accept)
        layout.addWidget(button_box)

    def _refresh_list(self):
        self._list.clear()
        self._list.addItems(self._manager.names())

    def _selected_names(self) -> list[str]:
        return [item.text() for item in self._list.selectedItems()]

    def _on_rename(self):
        names = self._selected_names()
        if len(names) != 1:
            QMessageBox.information(self, "Select one template", "Select exactly one template to rename.")
            return
        old = names[0]
        new, ok = QInputDialog.getText(self, "Rename template", "New name:", text=old)
        new = new.strip()
        if not ok or not new or new == old:
            return
        if new in self._manager.names():
            QMessageBox.warning(self, "Name already in use", f'A template named "{new}" already exists.')
            return
        self._manager.rename(old, new)
        self._refresh_list()

    def _on_delete(self):
        names = self._selected_names()
        if not names:
            return
        listed = ", ".join(names)
        if QMessageBox.question(
            self, "Delete template(s)",
            f"Delete {len(names)} template(s)?\n\n{listed}",
        ) != QMessageBox.StandardButton.Yes:
            return
        for name in names:
            self._manager.delete(name)
        self._refresh_list()

    def _on_export(self):
        names = self._selected_names()
        if not names:
            QMessageBox.information(self, "Nothing selected", "Select one or more templates to export.")
            return
        path_str, _ = QFileDialog.getSaveFileName(
            self, "Export fit templates", "fit_templates.json", "JSON files (*.json)",
        )
        if not path_str:
            return
        if not self._manager.export_to_file(names, path_str):
            QMessageBox.warning(self, "Export failed", "Could not write the template file — see log for details.")
            return
        QMessageBox.information(self, "Export complete", f"{len(names)} template(s) exported to {path_str}")

    def _on_import(self):
        path_str, _ = QFileDialog.getOpenFileName(
            self, "Import fit templates", "", "JSON files (*.json)",
        )
        if not path_str:
            return
        imported = self._manager.import_from_file(path_str)
        if not imported:
            QMessageBox.warning(
                self, "Nothing imported",
                "No templates were found in that file — see log for details.",
            )
            return
        self._refresh_list()
        QMessageBox.information(
            self, "Import complete",
            f"Imported {len(imported)} template(s):\n\n" + "\n".join(imported),
        )
