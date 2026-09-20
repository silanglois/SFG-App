from __future__ import annotations
import logging
from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton,
    QSpinBox, QVBoxLayout,
)

from sfg_app2.processing.readers import (
    CANONICAL_COLUMNS, ReadOptions, UnrecognizedFormatError, peek_columns,
    read_spectrum,
)

logger = logging.getLogger(__name__)

# (label, value). None means "work it out", which is the default and
# handles ordinary CSVs plus the other separators instruments emit.
_SEPARATORS = [
    ("Detect automatically", None),
    ("Comma  ,", ","),
    ("Semicolon  ;", ";"),
    ("Tab", "\t"),
    ("Pipe  |", "|"),
    ("Space", " "),
]

_DECIMALS = [("Point  1.23", "."), ("Comma  1,23", ",")]

_ENCODINGS = ["utf-8", "latin-1", "cp1252", "utf-16"]

_AUTO = "(detect)"


class FileFormatDialog(QDialog):
    """Import options for raw files, plus the column mapping.

    Opened either from the menu, or automatically when a file can't be
    read — in which case `sample_path` is that file and the preview
    shows exactly why, so the mapping can be fixed against the file
    that actually failed.
    """

    def __init__(self, options: ReadOptions, sample_path: Path | None = None,
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle("File import options")
        self.setMinimumWidth(520)
        self._sample_path = Path(sample_path) if sample_path else None

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "How raw data files should be read. The defaults handle ordinary "
            "CSV exports — change these only if a file won't load."
        ))

        layout.addWidget(self._build_format_group(options))
        layout.addWidget(self._build_columns_group(options))
        layout.addWidget(self._build_preview_group())

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._refresh_sources()
        self._update_preview()

    # ── Construction ──────────────────────────────────────────────────────

    def _build_format_group(self, options: ReadOptions) -> QGroupBox:
        group = QGroupBox("Format")
        form = QFormLayout(group)

        self._separator = QComboBox()
        for label, value in _SEPARATORS:
            self._separator.addItem(label, value)
        self._separator.setCurrentIndex(
            max(self._separator.findData(options.delimiter), 0))

        self._decimal = QComboBox()
        for label, value in _DECIMALS:
            self._decimal.addItem(label, value)
        self._decimal.setCurrentIndex(max(self._decimal.findData(options.decimal), 0))

        self._encoding = QComboBox()
        self._encoding.setEditable(True)
        self._encoding.addItems(_ENCODINGS)
        self._encoding.setCurrentText(options.encoding)

        self._skiprows = QSpinBox()
        self._skiprows.setRange(0, 1000)
        self._skiprows.setValue(options.skiprows)
        self._skiprows.setToolTip(
            "Instrument exports often start with a block of settings "
            "before the column headers.")

        form.addRow("Separator:", self._separator)
        form.addRow("Decimal mark:", self._decimal)
        form.addRow("Encoding:", self._encoding)
        form.addRow("Lines to skip:", self._skiprows)

        for widget in (self._separator, self._decimal, self._encoding):
            widget.currentTextChanged.connect(self._on_format_changed)
        self._skiprows.valueChanged.connect(self._on_format_changed)
        return group

    def _build_columns_group(self, options: ReadOptions) -> QGroupBox:
        group = QGroupBox("Columns")
        form = QFormLayout(group)
        form.addRow(QLabel(
            "Leave as “(detect)” when the file already labels its columns "
            "Frame / Wavelength / Intensity."))

        self._column_combos: dict[str, QComboBox] = {}
        for canonical in CANONICAL_COLUMNS:
            combo = QComboBox()
            combo.setEditable(True)
            combo.currentTextChanged.connect(self._update_preview)
            self._column_combos[canonical] = combo
            form.addRow(f"{canonical}:", combo)
        self._initial_columns = dict(options.columns)

        self._frame_columns = QLineEdit(", ".join(options.frame_columns))
        self._frame_columns.setPlaceholderText("all other columns")
        self._frame_columns.setToolTip(
            "Only for files that put each frame in its own column. Frame "
            "numbers are read from the headers (\"1\", \"Frame 1\", \"S1\"), "
            "so this is only needed when such a file also carries a column "
            "that isn't a frame — a dark reference, say."
        )
        self._frame_columns.textChanged.connect(self._update_preview)
        form.addRow("Frame columns:", self._frame_columns)
        return group

    def _build_preview_group(self) -> QGroupBox:
        group = QGroupBox("Preview")
        box = QVBoxLayout(group)

        row = QHBoxLayout()
        self._sample_label = QLabel()
        choose = QPushButton("Choose a file…")
        choose.clicked.connect(self._on_choose_sample)
        row.addWidget(self._sample_label, 1)
        row.addWidget(choose)
        box.addLayout(row)

        self._preview = QPlainTextEdit()
        self._preview.setReadOnly(True)
        self._preview.setMaximumHeight(140)
        box.addWidget(self._preview)
        return group

    # ── State ─────────────────────────────────────────────────────────────

    def options(self) -> ReadOptions:
        columns = {}
        for canonical, combo in self._column_combos.items():
            source = combo.currentText().strip()
            if source and source != _AUTO:
                columns[canonical] = source
        return ReadOptions(
            delimiter=self._separator.currentData(),
            decimal=self._decimal.currentData(),
            encoding=self._encoding.currentText().strip() or "utf-8",
            skiprows=self._skiprows.value(),
            columns=columns,
            frame_columns=[c.strip() for c in self._frame_columns.text().split(",")
                           if c.strip()],
        )

    def _on_format_changed(self):
        self._refresh_sources()
        self._update_preview()

    def _refresh_sources(self):
        """Offer the sample file's real headers as mapping choices.

        They depend on the separator and skipped lines, so this reruns
        whenever those change -- otherwise the dropdowns would offer
        columns from a parse the user has already moved on from.
        """
        found = peek_columns(self._sample_path, self.options()) if self._sample_path else []
        for canonical, combo in self._column_combos.items():
            current = combo.currentText().strip() or self._initial_columns.get(canonical, "")
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(_AUTO)
            combo.addItems(found)
            combo.setCurrentText(current if current else _AUTO)
            combo.blockSignals(False)

    def _on_choose_sample(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose a file to test", "", "Data files (*.csv *.txt *.dat *.asc *.tsv);;All files (*)")
        if path:
            self._sample_path = Path(path)
            self._refresh_sources()
            self._update_preview()

    def _update_preview(self):
        if self._sample_path is None:
            self._sample_label.setText("No file chosen.")
            self._preview.setPlainText("")
            return

        self._sample_label.setText(self._sample_path.name)
        try:
            df = read_spectrum(self._sample_path, self.options())
        except UnrecognizedFormatError as e:
            found = peek_columns(self._sample_path, self.options())
            hint = (f"\n\nColumns found: {', '.join(found)}"
                    if found else "\n\nNo columns could be read at all — try a "
                                  "different separator or skip more lines.")
            self._preview.setPlainText(f"Can't read this file.\n\n{e}{hint}")
            return

        frames = df["Frame"].nunique()
        self._preview.setPlainText(
            f"Read {len(df)} rows, {frames} frame(s).\n\n"
            + df.head(5).to_string(index=False)
        )
