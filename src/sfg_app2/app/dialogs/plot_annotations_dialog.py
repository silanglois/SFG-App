from __future__ import annotations
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QTableWidget, QTableWidgetItem,
    QComboBox, QLineEdit, QDoubleSpinBox, QPushButton, QColorDialog, QDialogButtonBox,
    QStackedWidget, QWidget,
)

from sfg_app2.app.tabs.processed_results import PlotAnnotation, _LINESTYLE_CHOICES

_LINESTYLE_NAMES = [name for name, _ in _LINESTYLE_CHOICES]
_LINESTYLE_BY_NAME = dict(_LINESTYLE_CHOICES)
_LINESTYLE_BY_VALUE = {value: name for name, value in _LINESTYLE_CHOICES}

_KIND_LABELS = [
    ("vline", "Vertical line"),
    ("hline", "Horizontal line"),
    ("region", "Shaded region (x range)"),
    ("text", "Text"),
]
_KIND_BY_LABEL = {label: kind for kind, label in _KIND_LABELS}
_LABEL_BY_KIND = {kind: label for kind, label in _KIND_LABELS}


def _summary(ann: PlotAnnotation) -> str:
    if ann.kind == "vline":
        return f"x = {ann.x}"
    if ann.kind == "hline":
        return f"y = {ann.y}"
    if ann.kind == "region":
        return f"x = {ann.x0} .. {ann.x1}"
    if ann.kind == "text":
        return f"({ann.x}, {ann.y}): \"{ann.text}\""
    return ""


class _AnnotationEditor(QDialog):
    """Add/edit a single PlotAnnotation."""

    def __init__(self, annotation: PlotAnnotation | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Annotation" if annotation is None else "Edit annotation")
        self._color = (annotation.color if annotation else "#000000")

        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)

        self._kind_combo = QComboBox()
        self._kind_combo.addItems([label for _kind, label in _KIND_LABELS])
        form.addRow("Type:", self._kind_combo)

        def make_spin():
            spin = QDoubleSpinBox()
            spin.setRange(-1e6, 1e6)
            spin.setDecimals(3)
            return spin

        self._x_spin = make_spin()
        self._y_spin = make_spin()
        self._x0_spin = make_spin()
        self._x1_spin = make_spin()
        self._text_edit = QLineEdit()
        self._text_x_spin = make_spin()
        self._text_y_spin = make_spin()

        vline_page = QWidget()
        f = QFormLayout(vline_page)
        f.addRow("x:", self._x_spin)

        hline_page = QWidget()
        f = QFormLayout(hline_page)
        f.addRow("y:", self._y_spin)

        region_page = QWidget()
        f = QFormLayout(region_page)
        f.addRow("x start:", self._x0_spin)
        f.addRow("x end:", self._x1_spin)

        text_page = QWidget()
        f = QFormLayout(text_page)
        f.addRow("x:", self._text_x_spin)
        f.addRow("y:", self._text_y_spin)
        f.addRow("Text:", self._text_edit)

        self._stack = QStackedWidget()
        self._stack.addWidget(vline_page)
        self._stack.addWidget(hline_page)
        self._stack.addWidget(region_page)
        self._stack.addWidget(text_page)
        layout.addWidget(self._stack)
        self._kind_combo.currentIndexChanged.connect(self._stack.setCurrentIndex)

        style_row = QHBoxLayout()
        self._color_btn = QPushButton()
        self._color_btn.setFixedWidth(60)
        self._update_color_button()
        self._color_btn.clicked.connect(self._on_pick_color)
        style_row.addWidget(self._color_btn)

        self._linestyle_combo = QComboBox()
        self._linestyle_combo.addItems(_LINESTYLE_NAMES)
        style_row.addWidget(self._linestyle_combo)
        style_row.addStretch()
        form.addRow("Style:", style_row)

        if annotation is not None:
            idx = [kind for kind, _label in _KIND_LABELS].index(annotation.kind)
            self._kind_combo.setCurrentIndex(idx)
            self._stack.setCurrentIndex(idx)
            self._x_spin.setValue(annotation.x or 0.0)
            self._y_spin.setValue(annotation.y or 0.0)
            self._x0_spin.setValue(annotation.x0 or 0.0)
            self._x1_spin.setValue(annotation.x1 or 0.0)
            self._text_x_spin.setValue(annotation.x or 0.0)
            self._text_y_spin.setValue(annotation.y or 0.0)
            self._text_edit.setText(annotation.text)
            self._linestyle_combo.setCurrentText(_LINESTYLE_BY_VALUE.get(annotation.linestyle, "Dashed"))

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def _update_color_button(self):
        self._color_btn.setStyleSheet(f"background-color: {self._color};")

    def _on_pick_color(self):
        chosen = QColorDialog.getColor(QColor(self._color), self, "Annotation color")
        if chosen.isValid():
            self._color = chosen.name()
            self._update_color_button()

    def result_annotation(self) -> PlotAnnotation:
        kind = _KIND_BY_LABEL[self._kind_combo.currentText()]
        linestyle = _LINESTYLE_BY_NAME.get(self._linestyle_combo.currentText(), "--")
        if kind == "vline":
            return PlotAnnotation(kind=kind, x=self._x_spin.value(), color=self._color, linestyle=linestyle)
        if kind == "hline":
            return PlotAnnotation(kind=kind, y=self._y_spin.value(), color=self._color, linestyle=linestyle)
        if kind == "region":
            return PlotAnnotation(kind=kind, x0=self._x0_spin.value(), x1=self._x1_spin.value(),
                                   color=self._color, linestyle=linestyle)
        return PlotAnnotation(kind=kind, x=self._text_x_spin.value(), y=self._text_y_spin.value(),
                               text=self._text_edit.text(), color=self._color, linestyle=linestyle)


class PlotAnnotationsDialog(QDialog):
    """Manage the list of free-form annotations (lines/regions/text) drawn
    on top of the Results tab plot."""

    def __init__(self, annotations: list[PlotAnnotation], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Plot annotations")
        self.resize(480, 320)
        self._annotations = list(annotations)   # edit a copy, commit on OK

        layout = QVBoxLayout(self)

        self._table = QTableWidget(0, 2, self)
        self._table.setHorizontalHeaderLabels(["Type", "Details"])
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self._table)
        self._reload_table()

        btn_row = QHBoxLayout()
        add_btn = QPushButton("Add...")
        add_btn.clicked.connect(self._on_add)
        edit_btn = QPushButton("Edit...")
        edit_btn.clicked.connect(self._on_edit)
        remove_btn = QPushButton("Remove")
        remove_btn.clicked.connect(self._on_remove)
        btn_row.addWidget(add_btn)
        btn_row.addWidget(edit_btn)
        btn_row.addWidget(remove_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def _reload_table(self):
        self._table.setRowCount(len(self._annotations))
        for row, ann in enumerate(self._annotations):
            self._table.setItem(row, 0, QTableWidgetItem(_LABEL_BY_KIND.get(ann.kind, ann.kind)))
            self._table.setItem(row, 1, QTableWidgetItem(_summary(ann)))
        self._table.resizeColumnsToContents()

    def _on_add(self):
        editor = _AnnotationEditor(parent=self)
        if editor.exec() == QDialog.DialogCode.Accepted:
            self._annotations.append(editor.result_annotation())
            self._reload_table()

    def _on_edit(self):
        row = self._table.currentRow()
        if row < 0:
            return
        editor = _AnnotationEditor(self._annotations[row], parent=self)
        if editor.exec() == QDialog.DialogCode.Accepted:
            self._annotations[row] = editor.result_annotation()
            self._reload_table()

    def _on_remove(self):
        row = self._table.currentRow()
        if row < 0:
            return
        del self._annotations[row]
        self._reload_table()

    def result_annotations(self) -> list[PlotAnnotation]:
        return self._annotations
