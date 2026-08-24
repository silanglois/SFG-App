from __future__ import annotations
import logging
import warnings

import matplotlib as mpl
import numpy as np
from aquarel import Theme
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QPushButton,
    QDialogButtonBox, QMessageBox, QFileDialog,
)

from sfg_app2.app.utils.plotting_settings import (
    PlottingSettings, MATPLOTLIB_DEFAULT, DEFAULT_STYLE, available_styles,
    apply_rcparams, _load_theme, is_custom_style, delete_custom_style,
)
from sfg_app2.app.dialogs.custom_style_editor_dialog import CustomStyleEditorDialog

logger = logging.getLogger(__name__)


def _display_name(style: str) -> str:
    if style == MATPLOTLIB_DEFAULT:
        return "Matplotlib default"
    return style.replace("_", " ").title()


def _base_theme_for(style: str) -> Theme:
    """A base Theme to seed the custom-style editor from -- the plain
    Matplotlib default has no theme file of its own, unlike every real
    aquarel style (built-in or custom)."""
    if style == MATPLOTLIB_DEFAULT:
        return Theme()
    return _load_theme(style)


class PlottingSettingsDialog(QDialog):
    """Lets the user preview and pick a matplotlib/aquarel plotting style."""

    def __init__(self, settings: PlottingSettings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Plotting Settings")
        self.resize(520, 480)
        self._settings = settings

        self._build_ui()
        self._connect_signals()

        self._refresh_style_combo(select=settings.style)
        self._update_preview()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        layout = QVBoxLayout(self)

        row = QHBoxLayout()
        row.addWidget(QLabel("Style:"))
        self._style_combo = QComboBox()
        row.addWidget(self._style_combo, stretch=1)
        layout.addLayout(row)

        manage_row = QHBoxLayout()
        self._new_button = QPushButton("New from selected style...")
        self._edit_button = QPushButton("Edit selected style...")
        self._delete_button = QPushButton("Delete selected style")
        self._import_button = QPushButton("Import style...")
        self._export_button = QPushButton("Export selected style...")
        for button in (
            self._new_button, self._edit_button, self._delete_button,
            self._import_button, self._export_button,
        ):
            manage_row.addWidget(button)
        layout.addLayout(manage_row)

        self._figure = Figure(figsize=(4, 3), tight_layout=True)
        self._canvas = FigureCanvasQTAgg(self._figure)
        layout.addWidget(self._canvas)

        self._button_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        layout.addWidget(self._button_box)

    def _connect_signals(self):
        self._style_combo.currentIndexChanged.connect(self._on_selection_changed)
        self._new_button.clicked.connect(self._on_new_style)
        self._edit_button.clicked.connect(self._on_edit_style)
        self._delete_button.clicked.connect(self._on_delete_style)
        self._import_button.clicked.connect(self._on_import_style)
        self._export_button.clicked.connect(self._on_export_style)
        self._button_box.accepted.connect(self._on_ok)
        self._button_box.rejected.connect(self.reject)

    # ── Style list management ────────────────────────────────────────────────

    def _refresh_style_combo(self, select: str | None = None):
        select = select if select is not None else self._selected_style_or_none()
        self._style_combo.blockSignals(True)
        self._style_combo.clear()
        styles = available_styles()
        built_in = [s for s in styles if not is_custom_style(s)]
        custom = [s for s in styles if is_custom_style(s)]
        for s in built_in:
            self._style_combo.addItem(_display_name(s), s)
        if custom:
            self._style_combo.insertSeparator(self._style_combo.count())
            for s in custom:
                self._style_combo.addItem(_display_name(s), s)
        self._style_combo.blockSignals(False)

        index = self._style_combo.findData(select)
        self._style_combo.setCurrentIndex(index if index >= 0 else 0)
        self._update_button_states()

    def _selected_style_or_none(self) -> str | None:
        return self._style_combo.currentData()

    def _update_button_states(self):
        custom = is_custom_style(self._selected_style())
        self._edit_button.setEnabled(custom)
        self._delete_button.setEnabled(custom)

    def _on_selection_changed(self):
        self._update_button_states()
        self._update_preview()

    # ── Create / edit / delete ───────────────────────────────────────────────

    def _on_new_style(self):
        base = _base_theme_for(self._selected_style())
        dialog = CustomStyleEditorDialog(base, parent=self)
        if dialog.exec():
            self._refresh_style_combo(select=dialog.saved_name)

    def _on_edit_style(self):
        name = self._selected_style()
        if not is_custom_style(name):
            return
        base = _load_theme(name)
        dialog = CustomStyleEditorDialog(base, existing_name=name, parent=self)
        if dialog.exec():
            self._refresh_style_combo(select=dialog.saved_name)

    def _on_delete_style(self):
        name = self._selected_style()
        if not is_custom_style(name):
            return
        reply = QMessageBox.question(
            self, "Delete style?",
            f"Delete the custom style '{_display_name(name)}'? This can't be undone.",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        if not delete_custom_style(name):
            QMessageBox.warning(
                self, "Couldn't delete style",
                "The custom style file could not be deleted from disk.",
            )
            return
        self._refresh_style_combo(select=DEFAULT_STYLE)

    # ── Import / export ──────────────────────────────────────────────────────

    def _on_import_style(self):
        path, _filter = QFileDialog.getOpenFileName(
            self, "Import plot style", "", "Style files (*.json)"
        )
        if not path:
            return
        try:
            theme = Theme.from_file(path)
        except Exception as e:
            QMessageBox.critical(
                self, "Couldn't import style",
                f"'{path}' isn't a valid plot style file:\n{e}",
            )
            return

        dialog = CustomStyleEditorDialog(theme, parent=self)
        dialog._name_edit.setText(theme.info.get("name", "") or "")
        if dialog.exec():
            self._refresh_style_combo(select=dialog.saved_name)

    def _on_export_style(self):
        name = self._selected_style()
        if name == MATPLOTLIB_DEFAULT:
            QMessageBox.information(
                self, "Nothing to export",
                "The plain Matplotlib default isn't a style file that can be exported.",
            )
            return
        default_path = f"{name}.json"
        path, _filter = QFileDialog.getSaveFileName(
            self, "Export plot style", default_path, "Style files (*.json)"
        )
        if not path:
            return
        try:
            _load_theme(name).save(path)
        except Exception as e:
            QMessageBox.warning(
                self, "Couldn't export style",
                f"The style could not be written to '{path}':\n{e}",
            )

    # ── Preview ───────────────────────────────────────────────────────────────

    def _selected_style(self) -> str:
        return self._style_combo.currentData()

    def _update_preview(self):
        style = self._selected_style()
        rcparams_orig = dict(mpl.rcParams)
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", mpl.MatplotlibDeprecationWarning)
                apply_rcparams(style)
                self._draw_sample_plot()
        finally:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", mpl.MatplotlibDeprecationWarning)
                mpl.rcParams.update(rcparams_orig)

    def _draw_sample_plot(self):
        self._figure.clf()
        ax = self._figure.add_subplot(111)
        x = np.linspace(0, 10, 200)
        for i, phase in enumerate((0, 1, 2)):
            ax.plot(x, np.sin(x + phase), label=f"trace {i + 1}")
        ax.set_xlabel("X-axis")
        ax.set_ylabel("Y-axis")
        ax.set_title("Preview")
        ax.legend()
        self._canvas.draw_idle()

    # ── OK ────────────────────────────────────────────────────────────────────

    def _on_ok(self):
        if not self._settings.set_style(self._selected_style()):
            QMessageBox.warning(
                self, "Couldn't save settings",
                "The plotting style could not be saved to disk. "
                "It will apply for this session but won't persist.",
            )
        self.accept()
