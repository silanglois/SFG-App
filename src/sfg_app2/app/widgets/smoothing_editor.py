from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
    QSpinBox, QWidget,
)

from sfg_app2.processing.smoothing import SmoothingSpec, smoothing_methods

# (key in the provenance/notebook dicts, row label)
BACKGROUNDS = (("sample", "Sample BG"), ("reference", "Reference BG"))


class _SmoothingRow(QWidget):
    """One background's method combo + that method's parameter spinboxes.

    Every method's spinboxes are built once and only the current method's
    are shown, so switching methods back and forth keeps the values the
    user typed (rather than resetting them to the defaults).
    """

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.combo = QComboBox()
        for method in smoothing_methods():
            self.combo.addItem(method.display_name, userData=method.key)
        layout.addWidget(self.combo)

        self._param_widgets: dict[str, list[tuple[str, QWidget, QWidget]]] = {}
        for method in smoothing_methods():
            widgets = []
            for p in method.params:
                label = QLabel(p.label)
                if p.is_int:
                    spin = QSpinBox()
                    spin.setRange(int(p.minimum), int(p.maximum))
                    spin.setValue(int(p.default))
                    if p.name == "window":
                        spin.setSingleStep(2)
                else:
                    spin = QDoubleSpinBox()
                    spin.setDecimals(p.decimals)
                    spin.setRange(p.minimum, p.maximum)
                    spin.setValue(float(p.default))
                    spin.setSingleStep(0.5)
                spin.setToolTip(p.tooltip)
                label.setToolTip(p.tooltip)
                spin.valueChanged.connect(self.changed)
                layout.addWidget(label)
                layout.addWidget(spin)
                widgets.append((p.name, label, spin))
            self._param_widgets[method.key] = widgets
        layout.addStretch()

        self.combo.currentIndexChanged.connect(self._update_visibility)
        self.combo.currentIndexChanged.connect(self.changed)
        self._update_visibility()

    def _update_visibility(self):
        current = self.combo.currentData()
        for key, widgets in self._param_widgets.items():
            for _name, label, spin in widgets:
                label.setVisible(key == current)
                spin.setVisible(key == current)

    def spec(self) -> SmoothingSpec:
        key = self.combo.currentData()
        return SmoothingSpec(key, {name: spin.value() for name, _l, spin in self._param_widgets[key]})

    def set_spec(self, spec: SmoothingSpec | dict | None):
        spec = SmoothingSpec.from_dict(spec)
        self.blockSignals(True)
        try:
            for name, _label, spin in self._param_widgets[spec.method]:
                spin.setValue(spec.params[name])
            self.combo.setCurrentIndex(max(0, self.combo.findData(spec.method)))
        finally:
            self.blockSignals(False)
        self._update_visibility()


class BackgroundSmoothingEditor(QGroupBox):
    """Smoothing method + parameters for the sample and reference
    backgrounds (processing/smoothing.py's registry decides the rows)."""

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__("Background smoothing", parent)
        self.setToolTip(
            "Smooth the frame-averaged background before it is subtracted. "
            "Windows and widths are in data points."
        )
        grid = QGridLayout(self)
        self.rows: dict[str, _SmoothingRow] = {}
        for r, (key, label) in enumerate(BACKGROUNDS):
            row = _SmoothingRow()
            row.changed.connect(self.changed)
            grid.addWidget(QLabel(label), r, 0)
            grid.addWidget(row, r, 1)
            self.rows[key] = row

    def spec(self, key: str) -> SmoothingSpec:
        return self.rows[key].spec()

    def to_dict(self) -> dict:
        return {key: row.spec().to_dict() for key, row in self.rows.items()}

    def set_from_dict(self, data: dict | None):
        data = data or {}
        for key, row in self.rows.items():
            row.set_spec(data.get(key))
        self.changed.emit()
