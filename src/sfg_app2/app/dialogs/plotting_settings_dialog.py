from __future__ import annotations
import logging
import warnings
from pathlib import Path

import matplotlib as mpl
import numpy as np
from aquarel import Theme
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QDoubleSpinBox,
    QDialogButtonBox, QMessageBox, QFileDialog, QTreeWidget, QTreeWidgetItem,
)

from sfg_app2.app.utils.plotting_settings import (
    PlottingSettings, MATPLOTLIB_DEFAULT, DEFAULT_STYLE,
    apply_rcparams, _load_theme, is_custom_style, delete_custom_style,
    list_bundled_styles, list_themes, list_custom_styles,
)
from sfg_app2.app.utils import recent_paths_settings
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

        self._refresh_style_tree(select=settings.style)
        self._update_preview()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Style:"))
        self._style_tree = QTreeWidget()
        self._style_tree.setHeaderHidden(True)
        self._style_tree.setMaximumHeight(160)
        layout.addWidget(self._style_tree)

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

        marker_row = QHBoxLayout()
        marker_row.addWidget(QLabel("Marker size (Spectra Library \"Show as markers\"):"))
        self._marker_size_spin = QDoubleSpinBox()
        self._marker_size_spin.setRange(0.5, 20.0)
        self._marker_size_spin.setSingleStep(0.5)
        self._marker_size_spin.setValue(self._settings.marker_size)
        marker_row.addWidget(self._marker_size_spin)
        marker_row.addStretch()
        layout.addLayout(marker_row)

        self._figure = Figure(figsize=(4, 3), tight_layout=True)
        self._canvas = FigureCanvasQTAgg(self._figure)
        layout.addWidget(self._canvas)

        self._preview_status = QLabel("")
        self._preview_status.setStyleSheet("color: #c0392b;")
        self._preview_status.setWordWrap(True)
        layout.addWidget(self._preview_status)

        self._button_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        layout.addWidget(self._button_box)

    def _connect_signals(self):
        self._style_tree.currentItemChanged.connect(self._on_selection_changed)
        self._new_button.clicked.connect(self._on_new_style)
        self._edit_button.clicked.connect(self._on_edit_style)
        self._delete_button.clicked.connect(self._on_delete_style)
        self._import_button.clicked.connect(self._on_import_style)
        self._export_button.clicked.connect(self._on_export_style)
        self._button_box.accepted.connect(self._on_ok)
        self._button_box.rejected.connect(self.reject)

    # ── Style list management ────────────────────────────────────────────────

    def _refresh_style_tree(self, select: str | None = None):
        select = select if select is not None else self._selected_style_or_none()
        self._style_tree.blockSignals(True)
        self._style_tree.clear()

        default_item = QTreeWidgetItem([_display_name(MATPLOTLIB_DEFAULT)])
        default_item.setData(0, Qt.ItemDataRole.UserRole, MATPLOTLIB_DEFAULT)
        self._style_tree.addTopLevelItem(default_item)

        selected_item = default_item
        groups = [
            ("Bundled", sorted(list_bundled_styles())),
            ("Aquarel Themes", sorted(list_themes())),
            ("Custom", list_custom_styles()),
        ]
        for group_name, names in groups:
            if not names:
                continue
            group_item = QTreeWidgetItem([group_name])
            # Group headers organize the tree only -- they aren't a
            # selectable style, so mouse/keyboard navigation can't land
            # on one as "the selected style".
            group_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self._style_tree.addTopLevelItem(group_item)
            for name in names:
                leaf = QTreeWidgetItem([_display_name(name)])
                leaf.setData(0, Qt.ItemDataRole.UserRole, name)
                group_item.addChild(leaf)
                if name == select:
                    selected_item = leaf
            group_item.setExpanded(True)

        self._style_tree.blockSignals(False)
        self._style_tree.setCurrentItem(selected_item)
        self._update_button_states()

    def _selected_style_or_none(self) -> str | None:
        item = self._style_tree.currentItem()
        return item.data(0, Qt.ItemDataRole.UserRole) if item is not None else None

    def _update_button_states(self):
        custom = is_custom_style(self._selected_style())
        self._edit_button.setEnabled(custom)
        self._delete_button.setEnabled(custom)

    def _on_selection_changed(self, current: QTreeWidgetItem | None, _previous):
        if current is None or current.data(0, Qt.ItemDataRole.UserRole) is None:
            return   # a group header, not an actual style -- ignore
        self._update_button_states()
        self._update_preview()

    # ── Create / edit / delete ───────────────────────────────────────────────

    def _on_new_style(self):
        base = _base_theme_for(self._selected_style())
        dialog = CustomStyleEditorDialog(base, parent=self)
        if dialog.exec():
            self._refresh_style_tree(select=dialog.saved_name)

    def _on_edit_style(self):
        name = self._selected_style()
        if not is_custom_style(name):
            return
        base = _load_theme(name)
        dialog = CustomStyleEditorDialog(base, existing_name=name, parent=self)
        if dialog.exec():
            self._refresh_style_tree(select=dialog.saved_name)

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
        self._refresh_style_tree(select=DEFAULT_STYLE)

    # ── Import / export ──────────────────────────────────────────────────────

    def _on_import_style(self):
        path, _filter = QFileDialog.getOpenFileName(
            self, "Import plot style", recent_paths_settings.get_last_dir("settings"),
            "Style files (*.json)"
        )
        if not path:
            return
        recent_paths_settings.remember_dir("settings", path)
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
            self._refresh_style_tree(select=dialog.saved_name)

    def _on_export_style(self):
        name = self._selected_style()
        if name == MATPLOTLIB_DEFAULT:
            QMessageBox.information(
                self, "Nothing to export",
                "The plain Matplotlib default isn't a style file that can be exported.",
            )
            return
        last_dir = recent_paths_settings.get_last_dir("settings")
        default_name = f"{name}.json"
        default_path = str(Path(last_dir) / default_name) if last_dir else default_name
        path, _filter = QFileDialog.getSaveFileName(
            self, "Export plot style", default_path, "Style files (*.json)"
        )
        if not path:
            return
        recent_paths_settings.remember_dir("settings", path)
        try:
            _load_theme(name).save(path)
        except Exception as e:
            QMessageBox.warning(
                self, "Couldn't export style",
                f"The style could not be written to '{path}':\n{e}",
            )

    # ── Preview ───────────────────────────────────────────────────────────────

    def _selected_style(self) -> str:
        item = self._style_tree.currentItem()
        return item.data(0, Qt.ItemDataRole.UserRole) if item is not None else MATPLOTLIB_DEFAULT

    def _update_preview(self):
        style = self._selected_style()
        rcparams_orig = dict(mpl.rcParams)
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", mpl.MatplotlibDeprecationWarning)
                apply_rcparams(style)
                self._draw_sample_plot()
            self._preview_status.setText("")
        except Exception as e:
            logger.warning("Failed to render style preview: %s", e, exc_info=True)
            self._preview_status.setText(f"Couldn't render preview with this style: {e}")
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
        ok = self._settings.set_style(self._selected_style())
        ok = self._settings.set_marker_size(self._marker_size_spin.value()) and ok
        if not ok:
            QMessageBox.warning(
                self, "Couldn't save settings",
                "The plotting settings could not be saved to disk. "
                "They will apply for this session but won't persist.",
            )
        self.accept()
