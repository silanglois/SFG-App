from __future__ import annotations
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QHBoxLayout, QComboBox,
    QSpinBox, QDoubleSpinBox, QCheckBox, QLineEdit, QDialogButtonBox,
)


class SavePlotDialog(QDialog):
    """Collects file format/DPI/size/title options before a plot is
    exported. Doesn't touch the figure itself — see result_options()."""

    _EXTS = ["png", "tiff", "svg"]

    def __init__(self, figure, ax, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Save plot")

        orig_w, orig_h = figure.get_size_inches()
        current_title = ax.get_title()

        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)

        self._format_combo = QComboBox()
        self._format_combo.addItems(["PNG", "TIFF", "SVG"])
        form.addRow("File format:", self._format_combo)

        self._dpi_spin = QSpinBox()
        self._dpi_spin.setRange(50, 2400)
        self._dpi_spin.setValue(300)
        form.addRow("DPI:", self._dpi_spin)

        self._width_check = QCheckBox("Force width (in)")
        self._width_spin = QDoubleSpinBox()
        self._width_spin.setRange(0.1, 100.0)
        self._width_spin.setValue(orig_w)
        self._width_spin.setEnabled(False)
        self._width_check.toggled.connect(self._width_spin.setEnabled)
        width_row = QHBoxLayout()
        width_row.addWidget(self._width_check)
        width_row.addWidget(self._width_spin)
        form.addRow(width_row)

        self._height_check = QCheckBox("Force height (in)")
        self._height_spin = QDoubleSpinBox()
        self._height_spin.setRange(0.1, 100.0)
        self._height_spin.setValue(orig_h)
        self._height_spin.setEnabled(False)
        self._height_check.toggled.connect(self._height_spin.setEnabled)
        height_row = QHBoxLayout()
        height_row.addWidget(self._height_check)
        height_row.addWidget(self._height_spin)
        form.addRow(height_row)

        self._title_check = QCheckBox("Include title:")
        self._title_check.setChecked(bool(current_title))
        self._title_edit = QLineEdit(current_title)
        self._title_edit.setEnabled(bool(current_title))
        self._title_check.toggled.connect(self._title_edit.setEnabled)
        title_row = QHBoxLayout()
        title_row.addWidget(self._title_check)
        title_row.addWidget(self._title_edit)
        form.addRow(title_row)

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def result_options(self) -> dict:
        return {
            "format": self._EXTS[self._format_combo.currentIndex()],
            "dpi": self._dpi_spin.value(),
            "width": self._width_spin.value() if self._width_check.isChecked() else None,
            "height": self._height_spin.value() if self._height_check.isChecked() else None,
            "title": self._title_edit.text() if self._title_check.isChecked() else "",
        }
