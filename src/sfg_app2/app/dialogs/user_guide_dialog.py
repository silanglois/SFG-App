from __future__ import annotations

import logging
import sys
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QListWidget, QPushButton, QTextBrowser, QVBoxLayout,
)

logger = logging.getLogger(__name__)

_GUIDE_DIR = Path(__file__).parents[1] / "ressources" / "user_guide"


def user_guide_site_index() -> Path | None:
    """Absolute path to the built MkDocs user-guide site's ``index.html``.

    Returns ``None`` when the site hasn't been built. Frozen (PyInstaller
    ``--onedir``): bundled at ``<_MEIPASS>/user_guide_site/`` by
    ``packaging/sfg-app.spec``. From source: ``<repo_root>/site/``, which only
    exists after ``uv run mkdocs build``. Callers fall back to
    :class:`UserGuideDialog` (the plain-text viewer) when this is ``None``.
    """
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        candidate = base / "user_guide_site" / "index.html"
    else:
        # user_guide_dialog.py -> dialogs / app / sfg_app2 / src / <repo root>
        candidate = Path(__file__).resolve().parents[4] / "site" / "index.html"
    return candidate if candidate.is_file() else None


def _windows_default_browser_command() -> str | None:
    """The ``shell\\open\\command`` string for the user's default browser.

    Resolved from the ``https`` URL-association UserChoice, so it's the real
    default *browser* regardless of what ``.html`` files are associated with
    (often an editor on a dev machine). Returns ``None`` if it can't be found.
    """
    try:
        import winreg
    except ImportError:  # not Windows
        return None
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\Shell\Associations"
            r"\UrlAssociations\https\UserChoice",
        ) as key:
            progid = winreg.QueryValueEx(key, "ProgId")[0]
        with winreg.OpenKey(
            winreg.HKEY_CLASSES_ROOT, rf"{progid}\shell\open\command"
        ) as key:
            command = winreg.QueryValueEx(key, None)[0]
    except OSError:
        return None
    return command or None


def open_user_guide_site(index: Path) -> bool:
    """Open the built guide's ``index.html`` in the user's web browser.

    ``QDesktopServices.openUrl`` on a ``file://`` URL delegates to whatever
    app owns ``.html`` -- an editor, for many developers -- so on Windows we
    launch the default browser explicitly and only fall back to the generic
    handler if that can't be resolved. Returns ``True`` if something was
    launched.
    """
    url = QUrl.fromLocalFile(str(index))
    command = _windows_default_browser_command()
    if command is not None:
        import subprocess

        url_str = url.toString()
        if "%1" in command:
            command = command.replace("%1", url_str)
        else:
            command = f'{command} "{url_str}"'
        try:
            subprocess.Popen(command)
            return True
        except OSError as e:
            logger.warning(
                "Couldn't launch the default browser (%s); falling back to "
                "the system .html handler.", e,
            )
    return QDesktopServices.openUrl(url)


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
    """Non-modal, browsable in-app user guide.

    Plain-text fallback for when the bundled MkDocs site
    (:func:`user_guide_site_index`) isn't available. Renders the same section
    Markdown with ``QTextBrowser``, so LaTeX math and admonition blocks show
    as raw source rather than typeset.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("SFG-App User Guide")
        self.resize(900, 650)

        outer = QVBoxLayout(self)
        body = QHBoxLayout()
        outer.addLayout(body, stretch=1)

        self._nav = QListWidget()
        self._nav.setFixedWidth(220)
        for _, title in _SECTIONS:
            self._nav.addItem(title)
        body.addWidget(self._nav)

        self._browser = QTextBrowser()
        self._browser.setOpenExternalLinks(True)
        self._browser.setSearchPaths([str(_GUIDE_DIR)])
        body.addWidget(self._browser, stretch=1)

        footer = QHBoxLayout()
        footer.addStretch(1)
        open_folder = QPushButton("Open guide folder")
        open_folder.setToolTip(
            "Open the folder containing the raw guide files and images."
        )
        open_folder.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(_GUIDE_DIR)))
        )
        footer.addWidget(open_folder)
        outer.addLayout(footer)

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
