from __future__ import annotations
import json
import logging
import re
import warnings

import matplotlib as mpl
import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from aquarel import Theme, list_themes
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QTabWidget, QWidget,
    QLabel, QLineEdit, QPlainTextEdit, QComboBox, QCheckBox, QPushButton,
    QDoubleSpinBox, QSpinBox, QColorDialog, QDialogButtonBox, QMessageBox,
    QScrollArea,
)

from sfg_app2.app.utils.plotting_settings import (
    MATPLOTLIB_DEFAULT, custom_styles_dir, is_custom_style, _apply_theme_object,
)

logger = logging.getLogger(__name__)

_FONT_SIZE_OPTIONS = list(Theme._font_size_options)
_FONT_WEIGHT_OPTIONS = list(Theme._font_weight_options)
_FONT_FAMILY_OPTIONS = list(Theme._font_family_options)
_FONT_STYLE_OPTIONS = list(Theme._font_style_options)
_FONT_VARIANT_OPTIONS = list(Theme._font_variant_options)
_LINE_STYLE_OPTIONS = list(Theme._line_style_options)
_DIRECTION_OPTIONS = list(Theme._direction_options)
_TICK_OPTIONS = list(Theme._tick_options)
_AXIS_OPTIONS = list(Theme._axis_options)
_HALIGN_OPTIONS = list(Theme._horizontal_alignment_options)
_VALIGN_OPTIONS = list(Theme._vertical_alignment_options)
_LOCATION_OPTIONS = list(Theme._location_options)
_LEGEND_LOCATION_OPTIONS = list(Theme._legend_location_options)

_DEFAULT_PALETTE = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b"]


def _slugify(text: str) -> str:
    text = text.strip().lower().replace(" ", "_")
    return re.sub(r"[^a-z0-9_-]", "", text)


def _group(theme: Theme, key: str) -> dict:
    return theme.params.get(key, {})


def _parse_font_list(text: str) -> list[str] | None:
    names = [s.strip() for s in text.split(",") if s.strip()]
    return names or None


def _join_font_list(value) -> str:
    if not value:
        return ""
    return ", ".join(value) if isinstance(value, list) else str(value)


# ── Small reusable field widgets ────────────────────────────────────────────

class _ColorField:
    """A color-swatch button, optionally paired with a 'Transparent'
    checkbox for the two fields aquarel/the app treat 'none' specially
    for (figure/plot background)."""

    def __init__(self, initial, allow_transparent: bool = False):
        self.value = initial if isinstance(initial, str) and initial != "none" else "#ffffff"
        self.transparent = allow_transparent and initial == "none"
        self.button = QPushButton()
        self.button.setFixedWidth(50)
        self.button.clicked.connect(self._pick)
        self.transparent_check = None
        if allow_transparent:
            self.transparent_check = QCheckBox("Transparent")
            self.transparent_check.setChecked(self.transparent)
            self.transparent_check.toggled.connect(self._on_transparent_toggled)
        self.on_change = None
        self._refresh()

    def widget(self) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.button)
        if self.transparent_check is not None:
            layout.addWidget(self.transparent_check)
        layout.addStretch()
        return row

    def _refresh(self):
        if self.transparent:
            self.button.setStyleSheet("")
            self.button.setText("(none)")
            self.button.setEnabled(False)
        else:
            self.button.setStyleSheet(f"background-color: {self.value}; border: 1px solid #888;")
            self.button.setText("")
            self.button.setEnabled(True)

    def _pick(self):
        chosen = QColorDialog.getColor(QColor(self.value), self.button, "Pick color")
        if chosen.isValid():
            self.value = chosen.name()
            self._refresh()
            if self.on_change:
                self.on_change()

    def _on_transparent_toggled(self, checked: bool):
        self.transparent = checked
        self._refresh()
        if self.on_change:
            self.on_change()

    def current(self) -> str:
        return "none" if self.transparent else self.value


class _PaletteEditor(QWidget):
    """A row of color swatches (the trace color-cycle palette) with
    add/remove — right-click a swatch to remove it."""

    changed = Signal()

    def __init__(self, colors: list[str], parent=None):
        super().__init__(parent)
        self._colors = list(colors) if colors else list(_DEFAULT_PALETTE)
        self._row = QHBoxLayout(self)
        self._row.setContentsMargins(0, 0, 0, 0)
        self._rebuild()

    def _rebuild(self):
        while self._row.count():
            item = self._row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for i, color in enumerate(self._colors):
            btn = QPushButton()
            btn.setFixedSize(28, 28)
            btn.setToolTip("Click to change, right-click to remove")
            btn.setStyleSheet(f"background-color: {color}; border: 1px solid #888;")
            btn.clicked.connect(lambda _checked=False, idx=i: self._pick(idx))
            btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            btn.customContextMenuRequested.connect(lambda _pos, idx=i: self._remove(idx))
            self._row.addWidget(btn)
        add_btn = QPushButton("+")
        add_btn.setFixedSize(28, 28)
        add_btn.clicked.connect(self._add)
        self._row.addWidget(add_btn)
        self._row.addStretch()

    def _pick(self, idx: int):
        chosen = QColorDialog.getColor(QColor(self._colors[idx]), self, "Palette color")
        if chosen.isValid():
            self._colors[idx] = chosen.name()
            self._rebuild()
            self.changed.emit()

    def _remove(self, idx: int):
        if len(self._colors) > 1:
            self._colors.pop(idx)
            self._rebuild()
            self.changed.emit()

    def _add(self):
        chosen = QColorDialog.getColor(QColor("#1f77b4"), self, "New palette color")
        if chosen.isValid():
            self._colors.append(chosen.name())
            self._rebuild()
            self.changed.emit()

    def colors(self) -> list[str]:
        return list(self._colors)


def _make_size_combo(value) -> QComboBox:
    combo = QComboBox()
    combo.setEditable(True)
    combo.addItems(_FONT_SIZE_OPTIONS)
    combo.setCurrentText(str(value) if value is not None else "medium")
    return combo


def _read_size_combo(combo: QComboBox):
    text = combo.currentText().strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return text if text in _FONT_SIZE_OPTIONS else None


def _make_weight_combo(value) -> QComboBox:
    combo = QComboBox()
    combo.setEditable(True)
    combo.addItems(_FONT_WEIGHT_OPTIONS)
    combo.setCurrentText(str(value) if value is not None else "normal")
    return combo


def _read_weight_combo(combo: QComboBox):
    text = combo.currentText().strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return text if text in _FONT_WEIGHT_OPTIONS else None


def _make_enum_combo(options: list[str], value) -> QComboBox:
    combo = QComboBox()
    combo.addItems(options)
    if value in options:
        combo.setCurrentText(value)
    return combo


class CustomStyleEditorDialog(QDialog):
    """Full-coverage editor for an aquarel Theme, seeded from a base style
    (built-in or custom) that the user tweaks and saves as a new (or
    overwritten) custom style. Every field aquarel's Theme.set_* methods
    expose is represented here; a live preview redraws on every change
    without ever leaking into the app's actual active plotting style
    (same rcParams snapshot/restore pattern as PlottingSettingsDialog)."""

    def __init__(self, base_theme: Theme, *, existing_name: str | None = None, parent=None):
        super().__init__(parent)
        self._existing_name = existing_name
        self.saved_name: str | None = None
        self.setWindowTitle("Edit custom style" if existing_name else "New custom style")
        self.resize(900, 700)

        self._theme = Theme.from_dict(json.loads(json.dumps({
            "info": base_theme.info,
            "params": base_theme.params,
            "overrides": base_theme.overrides,
            "transforms": base_theme.transforms,
        })))

        self._build_ui()
        self._connect_signals()
        self._update_preview()

    # ── UI construction ──────────────────────────────────────────────────────

    def _build_ui(self):
        layout = QVBoxLayout(self)

        name_form = QFormLayout()
        self._name_edit = QLineEdit(self._existing_name or "")
        self._name_edit.setEnabled(self._existing_name is None)
        if self._existing_name is None:
            self._name_edit.setPlaceholderText("My custom style")
        name_form.addRow("Name:", self._name_edit)
        self._description_edit = QLineEdit(self._theme.info.get("description", "") or "")
        if self._description_edit.text() == "No description available.":
            self._description_edit.clear()
        name_form.addRow("Description:", self._description_edit)
        layout.addLayout(name_form)

        self._tabs = QTabWidget()
        self._tabs.addTab(self._scrollable(self._build_colors_tab()), "Colors")
        self._tabs.addTab(self._scrollable(self._build_fonts_tab()), "Fonts && Text")
        self._tabs.addTab(self._scrollable(self._build_axes_tab()), "Axes && Ticks")
        self._tabs.addTab(self._scrollable(self._build_grid_tab()), "Grid && Lines")
        self._tabs.addTab(self._scrollable(self._build_legend_tab()), "Legend")
        self._tabs.addTab(self._scrollable(self._build_transforms_tab()), "Transforms && Advanced")
        layout.addWidget(self._tabs, stretch=1)

        self._figure = Figure(figsize=(4, 2.2), tight_layout=True)
        self._canvas = FigureCanvasQTAgg(self._figure)
        self._canvas.setFixedHeight(220)
        layout.addWidget(self._canvas)

        self._button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        layout.addWidget(self._button_box)

    @staticmethod
    def _scrollable(inner: QWidget) -> QScrollArea:
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setWidget(inner)
        return area

    def _build_colors_tab(self) -> QWidget:
        colors = _group(self._theme, "colors")
        widget = QWidget()
        form = QFormLayout(widget)

        self._palette_editor = _PaletteEditor(colors.get("palette") or _DEFAULT_PALETTE)
        form.addRow("Trace palette:", self._palette_editor)

        self._color_figure_bg = _ColorField(colors.get("figure_background_color", "white"), allow_transparent=True)
        form.addRow("Figure background:", self._color_figure_bg.widget())
        self._color_axes_bg = _ColorField(colors.get("plot_background_color", "white"), allow_transparent=True)
        form.addRow("Plot background:", self._color_axes_bg.widget())
        self._color_text = _ColorField(colors.get("text_color", "black"))
        form.addRow("Text color:", self._color_text.widget())
        self._color_axes = _ColorField(colors.get("axes_color", "black"))
        form.addRow("Axes line color:", self._color_axes.widget())
        self._color_axes_label = _ColorField(colors.get("axes_label_color", "black"))
        form.addRow("Axis label color:", self._color_axes_label.widget())
        self._color_line = _ColorField(colors.get("line_color", "black"))
        form.addRow("Line color:", self._color_line.widget())
        self._color_grid = _ColorField(colors.get("grid_color", "black"))
        form.addRow("Grid color:", self._color_grid.widget())
        self._color_tick = _ColorField(colors.get("tick_color", "black"))
        form.addRow("Tick color:", self._color_tick.widget())
        self._color_tick_label = _ColorField(colors.get("tick_label_color", "black"))
        form.addRow("Tick label color:", self._color_tick_label.widget())
        self._color_legend_bg = _ColorField(colors.get("legend_background_color", "white"))
        form.addRow("Legend background:", self._color_legend_bg.widget())
        self._color_legend_border = _ColorField(colors.get("legend_border_color", "black"))
        form.addRow("Legend border:", self._color_legend_border.widget())

        self._color_fields = [
            self._color_figure_bg, self._color_axes_bg, self._color_text, self._color_axes,
            self._color_axes_label, self._color_line, self._color_grid, self._color_tick,
            self._color_tick_label, self._color_legend_bg, self._color_legend_border,
        ]
        return widget

    def _build_fonts_tab(self) -> QWidget:
        fonts = _group(self._theme, "fonts")
        title = _group(self._theme, "title")
        axis_labels = _group(self._theme, "axis_labels")
        tick_labels = _group(self._theme, "tick_labels")

        widget = QWidget()
        form = QFormLayout(widget)

        form.addRow(QLabel("<b>Font</b>"))
        self._font_family = _make_enum_combo(_FONT_FAMILY_OPTIONS, fonts.get("family", "sans-serif"))
        form.addRow("Family:", self._font_family)
        self._font_size = QDoubleSpinBox()
        self._font_size.setRange(4.0, 72.0)
        self._font_size.setValue(float(fonts.get("size", 10.0)))
        form.addRow("Base size (pt):", self._font_size)
        self._font_style = _make_enum_combo(_FONT_STYLE_OPTIONS, fonts.get("style", "normal"))
        form.addRow("Style:", self._font_style)
        self._font_variant = _make_enum_combo(_FONT_VARIANT_OPTIONS, fonts.get("variant", "normal"))
        form.addRow("Variant:", self._font_variant)
        self._font_weight = _make_weight_combo(fonts.get("weight", "normal"))
        form.addRow("Weight:", self._font_weight)
        self._font_serif = QLineEdit(_join_font_list(fonts.get("serif")))
        self._font_serif.setPlaceholderText("e.g. Times New Roman, Georgia")
        form.addRow("Serif font names:", self._font_serif)
        self._font_sans_serif = QLineEdit(_join_font_list(fonts.get("sans-serif")))
        self._font_sans_serif.setPlaceholderText("e.g. Arial, Helvetica")
        form.addRow("Sans-serif font names:", self._font_sans_serif)
        self._font_monospace = QLineEdit(_join_font_list(fonts.get("monospace")))
        form.addRow("Monospace font names:", self._font_monospace)
        self._font_cursive = QLineEdit(_join_font_list(fonts.get("cursive")))
        form.addRow("Cursive font names:", self._font_cursive)
        self._font_fantasy = QLineEdit(_join_font_list(fonts.get("fantasy")))
        form.addRow("Fantasy font names:", self._font_fantasy)

        form.addRow(QLabel("<b>Title</b>"))
        self._title_location = _make_enum_combo(_HALIGN_OPTIONS, title.get("location", "center"))
        form.addRow("Location:", self._title_location)
        self._title_size = _make_size_combo(title.get("size", "large"))
        form.addRow("Size:", self._title_size)
        self._title_weight = _make_weight_combo(title.get("weight", "normal"))
        form.addRow("Weight:", self._title_weight)
        self._title_pad = QDoubleSpinBox()
        self._title_pad.setRange(-50.0, 50.0)
        self._title_pad.setValue(float(title.get("pad", 6.0)))
        form.addRow("Padding (pt):", self._title_pad)

        form.addRow(QLabel("<b>Axis labels</b>"))
        self._axis_label_pad = QDoubleSpinBox()
        self._axis_label_pad.setRange(-50.0, 50.0)
        self._axis_label_pad.setValue(float(axis_labels.get("pad", 4.0)))
        form.addRow("Padding (pt):", self._axis_label_pad)
        self._axis_label_size = _make_size_combo(axis_labels.get("size", "medium"))
        form.addRow("Size:", self._axis_label_size)
        self._axis_label_weight = _make_weight_combo(axis_labels.get("weight", "normal"))
        form.addRow("Weight:", self._axis_label_weight)

        form.addRow(QLabel("<b>Tick labels</b>"))
        self._tick_label_location = _make_enum_combo(_LOCATION_OPTIONS, tick_labels.get("location", "center"))
        form.addRow("Location:", self._tick_label_location)
        self._tick_label_size = _make_size_combo(tick_labels.get("size", "medium"))
        form.addRow("Size:", self._tick_label_size)
        self._tick_label_left = QCheckBox("Left")
        self._tick_label_left.setChecked(bool(tick_labels.get("left", True)))
        self._tick_label_right = QCheckBox("Right")
        self._tick_label_right.setChecked(bool(tick_labels.get("right", False)))
        self._tick_label_bottom = QCheckBox("Bottom")
        self._tick_label_bottom.setChecked(bool(tick_labels.get("bottom", True)))
        self._tick_label_top = QCheckBox("Top")
        self._tick_label_top.setChecked(bool(tick_labels.get("top", False)))
        sides = QHBoxLayout()
        for cb in (self._tick_label_left, self._tick_label_right, self._tick_label_bottom, self._tick_label_top):
            sides.addWidget(cb)
        form.addRow("Draw at:", sides)

        return widget

    def _build_axes_tab(self) -> QWidget:
        axes = _group(self._theme, "axes")
        ticks = _group(self._theme, "ticks")

        widget = QWidget()
        form = QFormLayout(widget)

        form.addRow(QLabel("<b>Axes</b>"))
        self._axes_width = QDoubleSpinBox()
        self._axes_width.setRange(0.0, 10.0)
        self._axes_width.setSingleStep(0.1)
        self._axes_width.setValue(float(axes.get("width", 1.0)))
        form.addRow("Line width:", self._axes_width)
        self._axes_top = QCheckBox("Top")
        self._axes_top.setChecked(bool(axes.get("top", True)))
        self._axes_bottom = QCheckBox("Bottom")
        self._axes_bottom.setChecked(bool(axes.get("bottom", True)))
        self._axes_left = QCheckBox("Left")
        self._axes_left.setChecked(bool(axes.get("left", True)))
        self._axes_right = QCheckBox("Right")
        self._axes_right.setChecked(bool(axes.get("right", True)))
        spines = QHBoxLayout()
        for cb in (self._axes_top, self._axes_bottom, self._axes_left, self._axes_right):
            spines.addWidget(cb)
        form.addRow("Visible spines:", spines)
        self._axes_xmargin = QDoubleSpinBox()
        self._axes_xmargin.setRange(0.0, 1.0)
        self._axes_xmargin.setSingleStep(0.01)
        self._axes_xmargin.setDecimals(3)
        self._axes_xmargin.setValue(float(axes.get("xmargin", 0.05)))
        form.addRow("X margin:", self._axes_xmargin)
        self._axes_ymargin = QDoubleSpinBox()
        self._axes_ymargin.setRange(0.0, 1.0)
        self._axes_ymargin.setSingleStep(0.01)
        self._axes_ymargin.setDecimals(3)
        self._axes_ymargin.setValue(float(axes.get("ymargin", 0.05)))
        form.addRow("Y margin:", self._axes_ymargin)
        self._axes_zmargin = QDoubleSpinBox()
        self._axes_zmargin.setRange(0.0, 1.0)
        self._axes_zmargin.setSingleStep(0.01)
        self._axes_zmargin.setDecimals(3)
        self._axes_zmargin.setValue(float(axes.get("zmargin", 0.05)))
        form.addRow("Z margin:", self._axes_zmargin)

        form.addRow(QLabel("<b>Ticks</b>"))
        self._ticks_x_align = _make_enum_combo(_HALIGN_OPTIONS, ticks.get("x_align", "center"))
        form.addRow("X alignment:", self._ticks_x_align)
        self._ticks_y_align = _make_enum_combo(_VALIGN_OPTIONS, ticks.get("y_align", "center_baseline"))
        form.addRow("Y alignment:", self._ticks_y_align)
        self._ticks_direction = _make_enum_combo(_DIRECTION_OPTIONS, ticks.get("direction", "out"))
        form.addRow("Direction:", self._ticks_direction)
        self._ticks_draw_minor = QCheckBox("Draw minor ticks")
        self._ticks_draw_minor.setChecked(bool(ticks.get("draw_minor", False)))
        form.addRow(self._ticks_draw_minor)
        self._ticks_width_major = QDoubleSpinBox()
        self._ticks_width_major.setRange(0.0, 10.0)
        self._ticks_width_major.setSingleStep(0.1)
        self._ticks_width_major.setValue(float(ticks.get("width_major", 0.8)))
        form.addRow("Major width:", self._ticks_width_major)
        self._ticks_width_minor = QDoubleSpinBox()
        self._ticks_width_minor.setRange(0.0, 10.0)
        self._ticks_width_minor.setSingleStep(0.1)
        self._ticks_width_minor.setValue(float(ticks.get("width_minor", 0.6)))
        form.addRow("Minor width:", self._ticks_width_minor)
        self._ticks_size_major = QDoubleSpinBox()
        self._ticks_size_major.setRange(0.0, 20.0)
        self._ticks_size_major.setSingleStep(0.5)
        self._ticks_size_major.setValue(float(ticks.get("size_major", 3.5)))
        form.addRow("Major size:", self._ticks_size_major)
        self._ticks_size_minor = QDoubleSpinBox()
        self._ticks_size_minor.setRange(0.0, 20.0)
        self._ticks_size_minor.setSingleStep(0.5)
        self._ticks_size_minor.setValue(float(ticks.get("size_minor", 2.0)))
        form.addRow("Minor size:", self._ticks_size_minor)
        self._ticks_pad_major = QDoubleSpinBox()
        self._ticks_pad_major.setRange(0.0, 20.0)
        self._ticks_pad_major.setSingleStep(0.1)
        self._ticks_pad_major.setValue(float(ticks.get("pad_major", 3.5)))
        form.addRow("Major padding:", self._ticks_pad_major)
        self._ticks_pad_minor = QDoubleSpinBox()
        self._ticks_pad_minor.setRange(0.0, 20.0)
        self._ticks_pad_minor.setSingleStep(0.1)
        self._ticks_pad_minor.setValue(float(ticks.get("pad_minor", 3.4)))
        form.addRow("Minor padding:", self._ticks_pad_minor)

        return widget

    def _build_grid_tab(self) -> QWidget:
        grid = _group(self._theme, "grid")
        lines = _group(self._theme, "lines")

        widget = QWidget()
        form = QFormLayout(widget)

        form.addRow(QLabel("<b>Grid</b>"))
        self._grid_draw = QCheckBox("Draw grid")
        self._grid_draw.setChecked(bool(grid.get("draw", False)))
        form.addRow(self._grid_draw)
        self._grid_axis = _make_enum_combo(_AXIS_OPTIONS, grid.get("axis", "both"))
        form.addRow("Axis:", self._grid_axis)
        self._grid_ticks = _make_enum_combo(_TICK_OPTIONS, grid.get("ticks", "major"))
        form.addRow("Tick level:", self._grid_ticks)
        self._grid_alpha = QDoubleSpinBox()
        self._grid_alpha.setRange(0.0, 1.0)
        self._grid_alpha.setSingleStep(0.05)
        self._grid_alpha.setValue(float(grid.get("alpha", 1.0)))
        form.addRow("Alpha:", self._grid_alpha)
        self._grid_style = _make_enum_combo(_LINE_STYLE_OPTIONS, grid.get("style", "-"))
        form.addRow("Line style:", self._grid_style)
        self._grid_width = QDoubleSpinBox()
        self._grid_width.setRange(0.0, 10.0)
        self._grid_width.setSingleStep(0.1)
        self._grid_width.setValue(float(grid.get("width", 0.8)))
        form.addRow("Line width:", self._grid_width)

        form.addRow(QLabel("<b>Lines</b>"))
        self._lines_style = _make_enum_combo(_LINE_STYLE_OPTIONS, lines.get("style", "-"))
        form.addRow("Style:", self._lines_style)
        self._lines_width = QDoubleSpinBox()
        self._lines_width.setRange(0.0, 10.0)
        self._lines_width.setSingleStep(0.1)
        self._lines_width.setValue(float(lines.get("width", 1.5)))
        form.addRow("Width:", self._lines_width)

        return widget

    def _build_legend_tab(self) -> QWidget:
        legend = _group(self._theme, "legend")

        widget = QWidget()
        form = QFormLayout(widget)

        self._legend_location = _make_enum_combo(_LEGEND_LOCATION_OPTIONS, legend.get("location", "best"))
        form.addRow("Location:", self._legend_location)
        self._legend_round = QCheckBox("Rounded corners")
        self._legend_round.setChecked(bool(legend.get("round", True)))
        form.addRow(self._legend_round)
        self._legend_shadow = QCheckBox("Shadow")
        self._legend_shadow.setChecked(bool(legend.get("shadow", False)))
        form.addRow(self._legend_shadow)
        self._legend_title_size = _make_size_combo(legend.get("title_size", "medium"))
        form.addRow("Title size:", self._legend_title_size)
        self._legend_text_size = _make_size_combo(legend.get("text_size", "medium"))
        form.addRow("Text size:", self._legend_text_size)
        self._legend_alpha = QDoubleSpinBox()
        self._legend_alpha.setRange(0.0, 1.0)
        self._legend_alpha.setSingleStep(0.05)
        self._legend_alpha.setValue(float(legend.get("alpha", 0.8)))
        form.addRow("Alpha:", self._legend_alpha)
        self._legend_marker_scale = QDoubleSpinBox()
        self._legend_marker_scale.setRange(0.0, 5.0)
        self._legend_marker_scale.setSingleStep(0.1)
        self._legend_marker_scale.setValue(float(legend.get("marker_scale", 1.0)))
        form.addRow("Marker scale:", self._legend_marker_scale)
        self._legend_padding = QDoubleSpinBox()
        self._legend_padding.setRange(0.0, 5.0)
        self._legend_padding.setSingleStep(0.1)
        self._legend_padding.setValue(float(legend.get("padding", 0.4)))
        form.addRow("Padding:", self._legend_padding)
        self._legend_margin = QDoubleSpinBox()
        self._legend_margin.setRange(0.0, 5.0)
        self._legend_margin.setSingleStep(0.1)
        self._legend_margin.setValue(float(legend.get("margin", 0.5)))
        form.addRow("Margin (to axes):", self._legend_margin)
        self._legend_spacing = QDoubleSpinBox()
        self._legend_spacing.setRange(0.0, 5.0)
        self._legend_spacing.setSingleStep(0.1)
        self._legend_spacing.setValue(float(legend.get("spacing", 0.5)))
        form.addRow("Item spacing:", self._legend_spacing)

        return widget

    def _build_transforms_tab(self) -> QWidget:
        transforms = self._theme.transforms or {}

        widget = QWidget()
        form = QFormLayout(widget)

        form.addRow(QLabel("<b>Transforms</b>"))
        self._trim_check = QCheckBox("Trim axes to nearest major tick")
        self._trim_check.setChecked("trim" in transforms)
        self._trim_axis = _make_enum_combo(_AXIS_OPTIONS, transforms.get("trim", {}).get("axis", "both"))
        trim_row = QHBoxLayout()
        trim_row.addWidget(self._trim_check)
        trim_row.addWidget(self._trim_axis)
        form.addRow(trim_row)

        self._offset_check = QCheckBox("Offset axes")
        self._offset_check.setChecked("offset" in transforms)
        self._offset_spin = QSpinBox()
        self._offset_spin.setRange(0, 100)
        self._offset_spin.setValue(int(transforms.get("offset", {}).get("distance", 10)))
        offset_row = QHBoxLayout()
        offset_row.addWidget(self._offset_check)
        offset_row.addWidget(self._offset_spin)
        form.addRow(offset_row)

        self._rotate_x_check = QCheckBox("Rotate X labels")
        self._rotate_x_check.setChecked("rotate_xlabel" in transforms)
        self._rotate_x_spin = QSpinBox()
        self._rotate_x_spin.setRange(-180, 180)
        self._rotate_x_spin.setValue(int(transforms.get("rotate_xlabel", {}).get("degrees", 45)))
        rotate_x_row = QHBoxLayout()
        rotate_x_row.addWidget(self._rotate_x_check)
        rotate_x_row.addWidget(self._rotate_x_spin)
        form.addRow(rotate_x_row)

        self._rotate_y_check = QCheckBox("Rotate Y labels")
        self._rotate_y_check.setChecked("rotate_ylabel" in transforms)
        self._rotate_y_spin = QSpinBox()
        self._rotate_y_spin.setRange(-180, 180)
        self._rotate_y_spin.setValue(int(transforms.get("rotate_ylabel", {}).get("degrees", 45)))
        rotate_y_row = QHBoxLayout()
        rotate_y_row.addWidget(self._rotate_y_check)
        rotate_y_row.addWidget(self._rotate_y_spin)
        form.addRow(rotate_y_row)

        form.addRow(QLabel("<b>Advanced: raw rcParam overrides (JSON object)</b>"))
        self._overrides_edit = QPlainTextEdit(json.dumps(self._theme.overrides or {}, indent=2))
        self._overrides_edit.setFixedHeight(120)
        form.addRow(self._overrides_edit)
        self._overrides_status = QLabel("")
        self._overrides_status.setStyleSheet("color: #c0392b;")
        form.addRow(self._overrides_status)

        return widget

    # ── Signal wiring ─────────────────────────────────────────────────────────

    def _connect_signals(self):
        for field in self._color_fields:
            field.on_change = self._update_preview
        self._palette_editor.changed.connect(self._update_preview)

        for widget in self.findChildren(QComboBox):
            widget.currentTextChanged.connect(self._update_preview)
        for widget in self.findChildren(QCheckBox):
            widget.toggled.connect(self._update_preview)
        for widget in (*self.findChildren(QDoubleSpinBox), *self.findChildren(QSpinBox)):
            widget.valueChanged.connect(self._update_preview)
        self._overrides_edit.textChanged.connect(self._update_preview)

        self._button_box.accepted.connect(self._on_save)
        self._button_box.rejected.connect(self.reject)

    # ── Field collection / theme rebuild ────────────────────────────────────

    def _collect_colors(self) -> dict:
        return dict(
            palette=self._palette_editor.colors(),
            figure_background_color=self._color_figure_bg.current(),
            plot_background_color=self._color_axes_bg.current(),
            text_color=self._color_text.current(),
            axes_color=self._color_axes.current(),
            axes_label_color=self._color_axes_label.current(),
            line_color=self._color_line.current(),
            grid_color=self._color_grid.current(),
            tick_color=self._color_tick.current(),
            tick_label_color=self._color_tick_label.current(),
            legend_background_color=self._color_legend_bg.current(),
            legend_border_color=self._color_legend_border.current(),
        )

    def _collect_fonts(self) -> dict:
        return dict(
            family=self._font_family.currentText(),
            size=self._font_size.value(),
            style=self._font_style.currentText(),
            variant=self._font_variant.currentText(),
            weight=_read_weight_combo(self._font_weight),
            serif=_parse_font_list(self._font_serif.text()),
            sans_serif=_parse_font_list(self._font_sans_serif.text()),
            monospace=_parse_font_list(self._font_monospace.text()),
            cursive=_parse_font_list(self._font_cursive.text()),
            fantasy=_parse_font_list(self._font_fantasy.text()),
        )

    def _collect_title(self) -> dict:
        return dict(
            location=self._title_location.currentText(),
            size=_read_size_combo(self._title_size),
            weight=_read_weight_combo(self._title_weight),
            pad=self._title_pad.value(),
        )

    def _collect_axis_labels(self) -> dict:
        return dict(
            pad=self._axis_label_pad.value(),
            size=_read_size_combo(self._axis_label_size),
            weight=_read_weight_combo(self._axis_label_weight),
        )

    def _collect_tick_labels(self) -> dict:
        return dict(
            location=self._tick_label_location.currentText(),
            size=_read_size_combo(self._tick_label_size),
            left=self._tick_label_left.isChecked(),
            right=self._tick_label_right.isChecked(),
            bottom=self._tick_label_bottom.isChecked(),
            top=self._tick_label_top.isChecked(),
        )

    def _collect_axes(self) -> dict:
        return dict(
            width=self._axes_width.value(),
            top=self._axes_top.isChecked(),
            bottom=self._axes_bottom.isChecked(),
            left=self._axes_left.isChecked(),
            right=self._axes_right.isChecked(),
            xmargin=self._axes_xmargin.value(),
            ymargin=self._axes_ymargin.value(),
            zmargin=self._axes_zmargin.value(),
        )

    def _collect_ticks(self) -> dict:
        return dict(
            x_align=self._ticks_x_align.currentText(),
            y_align=self._ticks_y_align.currentText(),
            direction=self._ticks_direction.currentText(),
            draw_minor=self._ticks_draw_minor.isChecked(),
            width_major=self._ticks_width_major.value(),
            width_minor=self._ticks_width_minor.value(),
            size_major=self._ticks_size_major.value(),
            size_minor=self._ticks_size_minor.value(),
            pad_major=self._ticks_pad_major.value(),
            pad_minor=self._ticks_pad_minor.value(),
        )

    def _collect_grid(self) -> dict:
        return dict(
            draw=self._grid_draw.isChecked(),
            axis=self._grid_axis.currentText(),
            ticks=self._grid_ticks.currentText(),
            alpha=self._grid_alpha.value(),
            style=self._grid_style.currentText(),
            width=self._grid_width.value(),
        )

    def _collect_lines(self) -> dict:
        return dict(
            style=self._lines_style.currentText(),
            width=self._lines_width.value(),
        )

    def _collect_legend(self) -> dict:
        return dict(
            location=self._legend_location.currentText(),
            round=self._legend_round.isChecked(),
            shadow=self._legend_shadow.isChecked(),
            title_size=_read_size_combo(self._legend_title_size),
            text_size=_read_size_combo(self._legend_text_size),
            alpha=self._legend_alpha.value(),
            marker_scale=self._legend_marker_scale.value(),
            padding=self._legend_padding.value(),
            margin=self._legend_margin.value(),
            spacing=self._legend_spacing.value(),
        )

    def _collect_transforms(self) -> dict:
        return dict(
            trim=self._trim_axis.currentText() if self._trim_check.isChecked() else None,
            offset=self._offset_spin.value() if self._offset_check.isChecked() else None,
            rotate_xlabel=self._rotate_x_spin.value() if self._rotate_x_check.isChecked() else None,
            rotate_ylabel=self._rotate_y_spin.value() if self._rotate_y_check.isChecked() else None,
        )

    def _collect_overrides(self) -> dict:
        text = self._overrides_edit.toPlainText().strip()
        if not text:
            self._overrides_status.setText("")
            return {}
        try:
            data = json.loads(text)
            if not isinstance(data, dict):
                raise ValueError("must be a JSON object")
            self._overrides_status.setText("")
            return data
        except Exception as e:
            self._overrides_status.setText(f"Invalid JSON — ignoring overrides ({e})")
            return self._theme.overrides or {}

    def _rebuild_theme(self):
        self._theme.set_color(**self._collect_colors())
        self._theme.set_font(**self._collect_fonts())
        self._theme.set_title(**self._collect_title())
        self._theme.set_axis_labels(**self._collect_axis_labels())
        self._theme.set_tick_labels(**self._collect_tick_labels())
        self._theme.set_axes(**self._collect_axes())
        self._theme.set_ticks(**self._collect_ticks())
        self._theme.set_grid(**self._collect_grid())
        self._theme.set_lines(**self._collect_lines())
        self._theme.set_legend(**self._collect_legend())
        self._theme.set_transforms(**self._collect_transforms())
        self._theme.set_overrides(self._collect_overrides())

    # ── Preview ───────────────────────────────────────────────────────────────

    def _update_preview(self, *_args):
        self._rebuild_theme()
        rcparams_orig = dict(mpl.rcParams)
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", mpl.MatplotlibDeprecationWarning)
                _apply_theme_object(self._theme)
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

    # ── Save ──────────────────────────────────────────────────────────────────

    def _on_save(self):
        self._rebuild_theme()

        if self._existing_name:
            slug = self._existing_name
            raw_name = self._name_edit.text().strip() or slug
        else:
            raw_name = self._name_edit.text().strip()
            if not raw_name:
                QMessageBox.warning(self, "Name required", "Enter a name for the custom style.")
                return
            slug = _slugify(raw_name)
            if not slug:
                QMessageBox.warning(
                    self, "Invalid name",
                    "Enter a name using letters, numbers, spaces, or dashes.",
                )
                return
            if slug == MATPLOTLIB_DEFAULT or slug in set(list_themes()):
                QMessageBox.warning(
                    self, "Name reserved",
                    f"'{raw_name}' is a built-in style name and can't be used "
                    "for a custom style.",
                )
                return
            if is_custom_style(slug):
                reply = QMessageBox.question(
                    self, "Overwrite style?",
                    f"A custom style named '{raw_name}' already exists. Overwrite it?",
                )
                if reply != QMessageBox.StandardButton.Yes:
                    return

        description = self._description_edit.text().strip()
        self._theme.info["name"] = raw_name
        self._theme.info["description"] = description or "No description available."

        try:
            custom_styles_dir().mkdir(parents=True, exist_ok=True)
            self._theme.save(str(custom_styles_dir() / f"{slug}.json"))
        except Exception as e:
            logger.error("Failed to save custom style '%s': %s", slug, e)
            QMessageBox.warning(
                self, "Couldn't save style",
                f"The style could not be saved to disk: {e}",
            )
            return

        self.saved_name = slug
        self.accept()
