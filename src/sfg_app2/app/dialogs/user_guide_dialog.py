from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QListWidget, QTextBrowser,
)

logger = logging.getLogger(__name__)

_GUIDE_DIR = Path(__file__).parents[1] / "ressources" / "user_guide"

_SECTIONS = [
    ("00_overview.md", "Getting Started"),
    ("01_load_match.md", "Load & Match"),
    ("02_process_review_homodyne.md", "Process & Review — Homodyne"),
    ("03_process_review_heterodyne.md", "Process & Review — Heterodyne"),
    ("04_results.md", "Spectra Library"),
    ("05_fitting.md", "Fitting"),
    ("06_settings_preferences.md", "Settings & Preferences"),
    ("07_reference_tips.md", "Reference & Tips"),
]


class UserGuideDialog(QDialog):
    """Non-modal, browsable in-app user guide."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("SFG-App User Guide")
        self.resize(900, 650)

        layout = QHBoxLayout(self)

        self._nav = QListWidget()
        self._nav.setFixedWidth(220)
        for _, title in _SECTIONS:
            self._nav.addItem(title)
        layout.addWidget(self._nav)

        self._browser = QTextBrowser()
        self._browser.setOpenExternalLinks(True)
        self._browser.setSearchPaths([str(_GUIDE_DIR)])
        layout.addWidget(self._browser, stretch=1)

        self._nav.currentRowChanged.connect(self._show_section)
        self._nav.setCurrentRow(0)

    def _show_section(self, index: int):
        if index < 0:
            return
        filename, title = _SECTIONS[index]
        try:
            text = (_GUIDE_DIR / filename).read_text(encoding="utf-8")
        except OSError as e:
            logger.error("Failed to load user guide section %r: %s", filename, e)
            self._browser.setPlainText(f'Couldn\'t load this section ("{title}").\n\n{e}')
            return
        self._browser.setMarkdown(text)
