from __future__ import annotations

from importlib import metadata
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QDialogButtonBox,
)

from sfg_app2.app.utils.icon_rendering import render_svg_pixmap

_ICON_PATH = Path(__file__).parents[1] / "ressources" / "icon.svg"
_ICON_DISPLAY_SIZE = 96
_FALLBACK_VERSION = "0.1.0"

_HOMEPAGE_URL = "https://github.com/silanglois/SFG-App"
_DESCRIPTION = (
    "A desktop application for processing and analyzing Sum-Frequency "
    "Generation (SFG) spectroscopy data — homodyne and heterodyne — "
    "built with PySide6."
)


def _app_version() -> str:
    try:
        return metadata.version("sfg-app2")
    except metadata.PackageNotFoundError:
        return _FALLBACK_VERSION


class AboutDialog(QDialog):
    """Shows app identity, version, and licensing info."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("About SFG-App")
        self.setFixedSize(360, 320)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.setSpacing(6)

        icon_label = QLabel()
        icon_label.setPixmap(render_svg_pixmap(_ICON_PATH, _ICON_DISPLAY_SIZE))
        icon_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(icon_label)

        name_label = QLabel("SFG-App")
        name_font = name_label.font()
        name_font.setPointSize(name_font.pointSize() + 6)
        name_font.setBold(True)
        name_label.setFont(name_font)
        name_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(name_label)

        version_label = QLabel(f"Version {_app_version()}")
        version_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(version_label)

        description_label = QLabel(_DESCRIPTION)
        description_label.setWordWrap(True)
        description_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(description_label)

        author_label = QLabel("Author: Simon Langlois")
        author_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(author_label)

        license_label = QLabel("License: GNU General Public License v3.0")
        license_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(license_label)

        link_label = QLabel(f'<a href="{_HOMEPAGE_URL}">{_HOMEPAGE_URL}</a>')
        link_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        link_label.setOpenExternalLinks(True)
        link_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        layout.addWidget(link_label)

        layout.addStretch()

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)
