"""The results spreadsheet: one row per fitted spectrum, every parameter
as a column, plus a trend view (a parameter across the spectra) and an
overlay view. Select a row (click or ↑/↓) to show that fit in the
workspace; right-click a column header to plot its trend, or a row to
refit it."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QHBoxLayout, QHeaderView, QLabel, QMenu, QPushButton,
    QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from sfg_app2.app.widgets.spectrum_plot_widget import SpectrumPlotWidget

OK, WARN, FAIL = "ok", "warn", "fail"
_STATUS_TEXT = {OK: "✓", WARN: "⚠", FAIL: "✗"}
# mid tones: readable on both light and dark table backgrounds
_STATUS_COLOR = {OK: "#43a047", WARN: "#f57c00", FAIL: "#e53935"}
_ORIGIN_ROLE = Qt.ItemDataRole.UserRole + 1
_SORT_ROLE = Qt.ItemDataRole.UserRole + 2
_FIXED_COLUMNS = ["", "Spectrum", "χ²ᵣ", "R²"]


@dataclass
class ResultRow:
    label: str
    status: str                         # OK / WARN / FAIL
    status_tip: str = ""
    redchi: float | None = None
    r_squared: float | None = None
    values: dict = field(default_factory=dict)   # column key -> (value, stderr|None)
    metadata: dict = field(default_factory=dict)


@dataclass
class ResultColumn:
    key: str
    label: str
    shared: bool = False


class _SortItem(QTableWidgetItem):
    """Sorts by the number in _SORT_ROLE when both cells have one."""

    def __lt__(self, other):
        a, b = self.data(_SORT_ROLE), other.data(_SORT_ROLE)
        if a is not None and b is not None:
            return a < b
        return super().__lt__(other)


def _fmt(value: float | None, err: float | None = None) -> str:
    if value is None or not np.isfinite(value):
        return ""
    text = f"{value:.5g}"
    if err is not None and np.isfinite(err):
        text += f" ± {err:.2g}"
    return text


class ResultsView(QWidget):
    row_selected = Signal(int)             # origin row index, -1 for none
    refit_requested = Signal(list)         # origin row indices
    use_as_start_requested = Signal(int)
    remove_requested = Signal(list)
    export_requested = Signal()
    send_requested = Signal(list)          # origin row indices ([] = all)
    overlay_requested = Signal()           # the tab redraws the overlay plot

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[ResultRow] = []
        self._columns: list[ResultColumn] = []
        # False for a global fit: its rows can't be refit one by one.
        self.refit_allowed = True

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.header_label = QLabel(
            "No multi-spectrum fit yet — add 2 or more spectra in ①, choose how to fit them in ③, "
            "and press Fit."
        )
        self.header_label.setWordWrap(True)
        layout.addWidget(self.header_label)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        # ── table ──
        table_page = QWidget()
        tl = QVBoxLayout(table_page)
        tl.setContentsMargins(0, 0, 0, 0)
        self.table = QTableWidget(0, len(_FIXED_COLUMNS))
        self.table.setHorizontalHeaderLabels(_FIXED_COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.horizontalHeader().customContextMenuRequested.connect(self._on_header_menu)
        self.table.horizontalHeader().setToolTip("Right-click a parameter column to plot its trend or hide it")
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_row_menu)
        self.table.currentCellChanged.connect(lambda row, _c, _pr, _pc: self._emit_selected(row))
        tl.addWidget(self.table)

        bar = QHBoxLayout()
        self.refit_btn = QPushButton("Refit selected")
        self.refit_btn.setToolTip("Fit the selected spectra again from the starting model")
        self.refit_btn.clicked.connect(lambda: self.refit_requested.emit(self.selected_rows()))
        self.send_btn = QPushButton("Send to Spectra Library")
        self.send_btn.setToolTip("Add the selected fits (all, if none selected) to the Spectra Library")
        self.send_btn.clicked.connect(lambda: self.send_requested.emit(self.selected_rows()))
        self.export_btn = QPushButton("Export summary…")
        self.export_btn.setToolTip("One summary CSV plus one fit CSV per spectrum")
        self.export_btn.clicked.connect(self.export_requested)
        for b in (self.refit_btn, self.send_btn, self.export_btn):
            bar.addWidget(b)
        bar.addStretch()
        tl.addLayout(bar)
        self.tabs.addTab(table_page, "Table")

        # ── trend ──
        trend_page = QWidget()
        trl = QVBoxLayout(trend_page)
        trl.setContentsMargins(0, 0, 0, 0)
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Parameter:"))
        self.trend_param_combo = QComboBox()
        self.trend_param_combo.currentIndexChanged.connect(lambda _i: self.draw_trend())
        controls.addWidget(self.trend_param_combo, stretch=1)
        controls.addWidget(QLabel("against:"))
        self.trend_x_combo = QComboBox()
        self.trend_x_combo.currentIndexChanged.connect(lambda _i: self.draw_trend())
        controls.addWidget(self.trend_x_combo)
        trl.addLayout(controls)
        self.trend_plot = SpectrumPlotWidget()
        trl.addWidget(self.trend_plot)
        self.tabs.addTab(trend_page, "Trend")

        # ── overlay ──
        self.overlay_plot = SpectrumPlotWidget()
        self.tabs.addTab(self.overlay_plot, "Overlay")
        self.tabs.currentChanged.connect(self._on_tab_changed)

        self._update_buttons()

    # ── data ─────────────────────────────────────────────────────────────

    def set_results(self, rows: list[ResultRow], columns: list[ResultColumn],
                    header: str = "", header_tip: str = ""):
        previous = self.selected_rows()
        self._rows = list(rows)
        self._columns = list(columns)
        if header:
            self.header_label.setText(header)
        self.header_label.setToolTip(header_tip)

        table = self.table
        table.setSortingEnabled(False)
        table.blockSignals(True)
        table.clear()
        table.setColumnCount(len(_FIXED_COLUMNS) + len(columns))
        labels = _FIXED_COLUMNS + [f"{c.label} ⇄" if c.shared else c.label for c in columns]
        table.setHorizontalHeaderLabels(labels)
        for i, c in enumerate(columns):
            if c.shared:
                table.horizontalHeaderItem(len(_FIXED_COLUMNS) + i).setToolTip(
                    "Shared: one common value fit jointly across every spectrum")
        table.horizontalHeaderItem(2).setToolTip(
            "Reduced χ² of this spectrum's own fit (in a global fit: this spectrum's share, "
            "not the combined value in the line above)")
        table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            status = _SortItem(_STATUS_TEXT[row.status])
            status.setForeground(QBrush(QColor(_STATUS_COLOR[row.status])))
            status.setToolTip(row.status_tip)
            status.setData(_ORIGIN_ROLE, r)
            status.setData(_SORT_ROLE, {FAIL: 0, WARN: 1, OK: 2}[row.status])
            status.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            table.setItem(r, 0, status)
            name = _SortItem(row.label)
            name.setData(_ORIGIN_ROLE, r)
            table.setItem(r, 1, name)
            for col, value in ((2, row.redchi), (3, row.r_squared)):
                item = _SortItem(_fmt(value))
                item.setData(_ORIGIN_ROLE, r)
                if value is not None and np.isfinite(value):
                    item.setData(_SORT_ROLE, float(value))
                table.setItem(r, col, item)
            for i, c in enumerate(columns):
                value, err = row.values.get(c.key, (None, None))
                item = _SortItem(_fmt(value, err))
                item.setData(_ORIGIN_ROLE, r)
                if value is not None and np.isfinite(value):
                    item.setData(_SORT_ROLE, float(value))
                table.setItem(r, len(_FIXED_COLUMNS) + i, item)
        table.resizeColumnsToContents()
        table.blockSignals(False)
        table.setSortingEnabled(True)

        self._rebuild_trend_combos()
        for origin in previous:
            self.select_row(origin)
        self._update_buttons()
        self.draw_trend()
        self.overlay_requested.emit()

    def rows(self) -> list[ResultRow]:
        return list(self._rows)

    def _origin_of(self, table_row: int) -> int:
        item = self.table.item(table_row, 0)
        return -1 if item is None else int(item.data(_ORIGIN_ROLE))

    def selected_rows(self) -> list[int]:
        rows = {self._origin_of(i.row()) for i in self.table.selectionModel().selectedRows()}
        return sorted(r for r in rows if r >= 0)

    def select_row(self, origin: int):
        for table_row in range(self.table.rowCount()):
            if self._origin_of(table_row) == origin:
                self.table.setCurrentCell(table_row, 1)
                return

    def clear_selection(self):
        self.table.blockSignals(True)
        self.table.clearSelection()
        self.table.setCurrentCell(-1, -1)
        self.table.blockSignals(False)

    def _emit_selected(self, table_row: int):
        self._update_buttons()
        self.row_selected.emit(self._origin_of(table_row) if table_row >= 0 else -1)

    def _update_buttons(self):
        has_rows = bool(self._rows)
        self.refit_btn.setEnabled(has_rows and self.refit_allowed and bool(self.selected_rows()))
        self.refit_btn.setToolTip(
            "Fit the selected spectra again from the starting model" if self.refit_allowed
            else "Rows of a global fit can't be refit on their own — run the global fit again.")
        self.send_btn.setEnabled(has_rows)
        self.export_btn.setEnabled(has_rows)

    # ── menus ────────────────────────────────────────────────────────────

    def _on_header_menu(self, pos):
        col = self.table.horizontalHeader().logicalIndexAt(pos)
        menu = QMenu(self)
        trend = None
        if col >= len(_FIXED_COLUMNS) or col == 2:
            trend = menu.addAction("Plot trend")
        hide = menu.addAction("Hide column") if col >= len(_FIXED_COLUMNS) else None
        show_all = menu.addAction("Show all columns")
        chosen = menu.exec(self.table.horizontalHeader().mapToGlobal(pos))
        if chosen is None:
            return
        if chosen is trend:
            self.show_trend_for_column(col)
        elif chosen is hide:
            self.table.setColumnHidden(col, True)
        elif chosen is show_all:
            for c in range(self.table.columnCount()):
                self.table.setColumnHidden(c, False)

    def show_trend_for_column(self, col: int):
        key = "__redchi__" if col == 2 else self._columns[col - len(_FIXED_COLUMNS)].key
        idx = self.trend_param_combo.findData(key)
        if idx >= 0:
            self.trend_param_combo.setCurrentIndex(idx)
        self.tabs.setCurrentIndex(1)

    def _on_row_menu(self, pos):
        if self.table.itemAt(pos) is None:
            return
        rows = self.selected_rows()
        if not rows:
            return
        menu = QMenu(self)
        refit = menu.addAction("Refit selected" if len(rows) > 1 else "Refit this spectrum")
        refit.setEnabled(self.refit_allowed)
        use = menu.addAction("Use as starting model") if len(rows) == 1 else None
        send = menu.addAction("Send to Spectra Library")
        menu.addSeparator()
        remove = menu.addAction("Remove from job")
        chosen = menu.exec(self.table.viewport().mapToGlobal(pos))
        if chosen is refit:
            self.refit_requested.emit(rows)
        elif chosen is use and use is not None:
            self.use_as_start_requested.emit(rows[0])
        elif chosen is send:
            self.send_requested.emit(rows)
        elif chosen is remove:
            self.remove_requested.emit(rows)

    # ── trend ────────────────────────────────────────────────────────────

    def _rebuild_trend_combos(self):
        prev_param = self.trend_param_combo.currentData()
        prev_x = self.trend_x_combo.currentData()
        for combo in (self.trend_param_combo, self.trend_x_combo):
            combo.blockSignals(True)
            combo.clear()
        for c in self._columns:
            self.trend_param_combo.addItem(c.label, userData=c.key)
        self.trend_param_combo.addItem("χ²ᵣ", userData="__redchi__")
        self.trend_x_combo.addItem("Order in job", userData=None)
        keys = []
        for row in self._rows:
            for k, v in row.metadata.items():
                if k not in keys and v not in (None, ""):
                    keys.append(k)
        for k in keys:
            self.trend_x_combo.addItem(k, userData=k)
        for combo, prev in ((self.trend_param_combo, prev_param), (self.trend_x_combo, prev_x)):
            idx = combo.findData(prev)
            combo.setCurrentIndex(idx if idx >= 0 else 0)
            combo.blockSignals(False)

    def draw_trend(self):
        plot = self.trend_plot
        plot.full_clear()
        ax = plot.ax
        key = self.trend_param_combo.currentData()
        if key is None or not self._rows:
            plot.canvas.draw_idle()
            return
        values, errors = [], []
        for row in self._rows:
            if key == "__redchi__":
                v, e = row.redchi, None
            else:
                v, e = row.values.get(key, (None, None))
            values.append(np.nan if v is None else v)
            errors.append(0.0 if e is None or not np.isfinite(e) else e)
        x_key = self.trend_x_combo.currentData()
        labels = [row.label for row in self._rows]
        x_numeric = None
        if x_key is not None:
            try:
                x_numeric = [float(row.metadata.get(x_key)) for row in self._rows]
            except (TypeError, ValueError):
                x_numeric = None
        if x_numeric is not None:
            order = np.argsort(x_numeric)
            ax.errorbar(np.asarray(x_numeric)[order], np.asarray(values)[order],
                        yerr=np.asarray(errors)[order], fmt="o-", capsize=3)
            ax.set_xlabel(x_key)
        else:
            x = np.arange(len(labels))
            ax.errorbar(x, values, yerr=errors, fmt="o-", capsize=3)
            ax.set_xticks(x)
            tick_labels = labels if x_key is None else [str(r.metadata.get(x_key, "")) for r in self._rows]
            ax.set_xticklabels(tick_labels, rotation=45, ha="right")
            ax.set_xlabel("Spectrum" if x_key is None else x_key)
        ax.set_ylabel(self.trend_param_combo.currentText())
        plot.sync_x_range()   # keep a user-set x range across redraws
        plot.canvas.draw_idle()

    def _on_tab_changed(self, index: int):
        if index == 2:
            self.overlay_requested.emit()
