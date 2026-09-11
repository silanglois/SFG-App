# src/sfg_app2/app/dialogs/processing_params_dialog.py
from __future__ import annotations
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget,
    QTableWidgetItem, QPushButton, QLabel, QDialogButtonBox,
    QHeaderView, QCheckBox,
)
from PySide6.QtCore import Qt

from sfg_app2.app.dialogs._multi_entry_table import merge_entries_into_wide_rows


def _fmt(value) -> str:
    return "N/A" if value is None else str(value)


def _despike_rows(despike: dict) -> list[tuple[str, str]]:
    rows = []
    for key, label in [
        ("signal", "Signal"), ("background", "Background"),
        ("reference", "Reference"), ("reference_background", "Reference background"),
    ]:
        c = despike.get(key) or {}
        rows.append((f"Despike — {label} window", _fmt(c.get("window"))))
        rows.append((f"Despike — {label} threshold", _fmt(c.get("threshold"))))
    return rows


def _source_rows(provenance: dict) -> list[tuple[str, str]]:
    return [
        ("Signal file",               _fmt(provenance.get("signal"))),
        ("Background file",           _fmt(provenance.get("background"))),
        ("Reference file",            _fmt(provenance.get("reference"))),
        ("Reference background file", _fmt(provenance.get("reference_background"))),
    ]


def _homodyne_rows(provenance: dict) -> list[tuple[str, str]]:
    rows = _source_rows(provenance)
    rows += _despike_rows(provenance.get("despike", {}))

    bg = provenance.get("background_subtraction", {})
    rows += [
        ("Background subtraction", "applied" if bg.get("applied") else "not applied"),
        ("Background subtraction — signal offset", _fmt(bg.get("signal_offset"))),
        ("Background subtraction — ref offset",    _fmt(bg.get("ref_offset"))),
    ]

    norm = provenance.get("normalization", {})
    rows.append(("Normalization", "applied" if norm.get("applied") else "not applied"))

    up = provenance.get("upconversion", {})
    rows += [
        ("Upconversion", "applied" if up.get("applied") else "not applied"),
        ("Upconversion — wavelength (nm)", _fmt(up.get("wavelength_nm"))),
    ]
    return rows


def _heterodyne_rows(provenance: dict) -> list[tuple[str, str]]:
    rows = _source_rows(provenance)
    rows += _despike_rows(provenance.get("despike", {}))

    bg = provenance.get("background_subtraction", {})
    rows += [
        ("BG subtraction — offset",          _fmt(bg.get("bg_offset"))),
        ("BG subtraction — edge left (pts)", _fmt(bg.get("edge_left"))),
        ("BG subtraction — edge right (pts)", _fmt(bg.get("edge_right"))),
        ("BG smoothing — window",            _fmt(bg.get("bg_smoothing_window"))),
        ("BG smoothing — order",             _fmt(bg.get("bg_smoothing_order"))),
        ("Signal smoothing — window",        _fmt(bg.get("sig_smoothing_window"))),
        ("Signal smoothing — order",         _fmt(bg.get("sig_smoothing_order"))),
    ]

    fft = provenance.get("fft_filter", {})
    rows += [
        ("FFT — window type",           _fmt(fft.get("window_type"))),
        ("FFT — start (pts)",           _fmt(fft.get("fft_start"))),
        ("FFT — end (pts)",             _fmt(fft.get("fft_end"))),
        ("FFT — HG left (pts)",         _fmt(fft.get("hg_left"))),
        ("FFT — HG right (pts)",        _fmt(fft.get("hg_right"))),
        ("FFT — mask start (pts)",      _fmt(fft.get("mask_start"))),
        ("FFT — mask end (pts)",        _fmt(fft.get("mask_end"))),
        ("FFT — mask transition (pts)", _fmt(fft.get("mask_transition"))),
        ("FFT — mask factor",           _fmt(fft.get("mask_factor"))),
    ]

    norm = provenance.get("normalization", {})
    rows += [
        ("Normalization — sample exposure (s)",    _fmt(norm.get("sample_exposure_s"))),
        ("Normalization — reference exposure (s)", _fmt(norm.get("reference_exposure_s"))),
        ("Normalization — phase correction (deg)", _fmt(norm.get("phase_correction_deg"))),
    ]

    up = provenance.get("upconversion", {})
    rows.append(("Upconversion — wavelength (nm)", _fmt(up.get("wavelength_nm"))))
    rows.append(("Frames processed", _fmt(provenance.get("n_frames"))))
    return rows


class ProcessingParamsDialog(QDialog):
    """Read-only step-through viewer of the processing parameters used to
    produce each selected Results-tab entry — one entry at a time, prev/next
    navigation (mirrors MetadataEditDialog's structure, minus editing)."""

    def __init__(self, entries: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Processing Parameters")
        self.resize(520, 450)

        self._entries = entries
        self._current = 0

        layout = QVBoxLayout(self)

        self._label = QLabel()
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._label)

        self._combine_check = QCheckBox("Combine all selected into one table")
        self._combine_check.setEnabled(len(self._entries) > 1)
        self._combine_check.toggled.connect(self._on_mode_changed)
        layout.addWidget(self._combine_check)

        self._table = QTableWidget(0, 2)
        self._table.setHorizontalHeaderLabels(["Field", "Value"])
        self._table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self._table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self._table)

        nav_layout = QHBoxLayout()
        self._prev_button = QPushButton("← Previous")
        self._next_button = QPushButton("Next →")
        self._counter_label = QLabel()
        self._counter_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._prev_button.clicked.connect(self._on_prev)
        self._next_button.clicked.connect(self._on_next)
        nav_layout.addWidget(self._prev_button)
        nav_layout.addWidget(self._counter_label)
        nav_layout.addWidget(self._next_button)
        layout.addLayout(nav_layout)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.accept)
        layout.addWidget(buttons)

        self._load_current()

    def _on_prev(self):
        self._current = max(0, self._current - 1)
        self._load_current()

    def _on_next(self):
        self._current = min(len(self._entries) - 1, self._current + 1)
        self._load_current()

    @staticmethod
    def _rows_for_entry(entry) -> list[tuple[str, str]]:
        provenance = getattr(entry.spectrum, "provenance", None) or {}
        if entry.kind == "heterodyne":
            return _heterodyne_rows(provenance)
        return _homodyne_rows(provenance)

    def _on_mode_changed(self, combined: bool):
        self._prev_button.setVisible(not combined)
        self._counter_label.setVisible(not combined)
        self._next_button.setVisible(not combined)
        if combined:
            self._load_combined()
        else:
            self._load_current()

    def _fill_table(self, headers: list[str], rows: list[tuple]):
        self._table.setColumnCount(len(headers))
        self._table.setHorizontalHeaderLabels(headers)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        # Per-spectrum mode (exactly one value column) stretches it to fill
        # the dialog, as before; combined mode (several spectra columns)
        # has no single natural column to stretch, so size each to its
        # contents and let the table scroll horizontally instead.
        last_mode = (
            QHeaderView.ResizeMode.Stretch if len(headers) == 2
            else QHeaderView.ResizeMode.ResizeToContents
        )
        for col in range(1, len(headers)):
            header.setSectionResizeMode(col, last_mode)

        self._table.setRowCount(0)
        for row in rows:
            table_row = self._table.rowCount()
            self._table.insertRow(table_row)
            for col, text in enumerate(row):
                item = QTableWidgetItem(text)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self._table.setItem(table_row, col, item)

    def _load_current(self):
        entry = self._entries[self._current]
        self._label.setText(f"{entry.label}  ({entry.kind})")
        self._counter_label.setText(f"{self._current + 1} / {len(self._entries)}")
        self._prev_button.setEnabled(self._current > 0)
        self._next_button.setEnabled(self._current < len(self._entries) - 1)
        self._fill_table(["Field", "Value"], self._rows_for_entry(entry))

    def _load_combined(self):
        n = len(self._entries)
        self._label.setText(f"{n} spectrum/spectra (combined)" if n != 1 else self._entries[0].label)
        headers = ["Field"] + [entry.label for entry in self._entries]
        merged = merge_entries_into_wide_rows(
            [self._rows_for_entry(entry) for entry in self._entries]
        )
        self._fill_table(headers, merged)
