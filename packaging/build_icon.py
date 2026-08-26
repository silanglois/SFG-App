"""Regenerates packaging/icon.ico from the app's source icon.svg.

Only needs re-running if icon.svg changes. Requires the "dev"
dependency group (pillow): uv run --group dev python packaging/build_icon.py
"""
from __future__ import annotations

import sys
from io import BytesIO
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication

_REPO_ROOT = Path(__file__).parent.parent
_ICON_SVG = _REPO_ROOT / "src" / "sfg_app2" / "app" / "ressources" / "icon.svg"
_ICON_ICO = Path(__file__).parent / "icon.ico"
_BASE_SIZE = 256   # rendered once at high resolution; Pillow downsamples
_ICO_SIZES = [(16, 16), (32, 32), (48, 48), (256, 256)]


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    renderer = QSvgRenderer(str(_ICON_SVG))

    pixmap = QPixmap(_BASE_SIZE, _BASE_SIZE)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()

    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    pixmap.save(buffer, "PNG")

    image = Image.open(BytesIO(bytes(data)))
    image.save(_ICON_ICO, format="ICO", sizes=_ICO_SIZES)
    print(f"Wrote {_ICON_ICO}")


if __name__ == "__main__":
    main()
