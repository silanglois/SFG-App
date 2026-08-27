from __future__ import annotations
from pathlib import Path

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer


def render_svg_pixmap(svg_path: str | Path, size: int) -> QPixmap:
    """Rasterizes an SVG at exactly `size`x`size`.

    Passing an explicit target rect to QSvgRenderer.render() is
    required here -- without one, Qt renders at the SVG's own declared
    intrinsic width/height rather than scaling to fit the QPixmap, so
    an SVG whose width/height attributes don't match its viewBox (as
    icon.svg's don't -- ~800 vs. a 24-unit viewBox) gets silently
    clipped to whatever corner of that oversized render happens to
    land within `size`x`size`.
    """
    renderer = QSvgRenderer(str(svg_path))
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    return pixmap
