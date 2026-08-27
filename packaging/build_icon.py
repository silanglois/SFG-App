"""Regenerates packaging/icon.ico from the app's source icon.svg.

Only needs re-running if icon.svg changes. Requires the "dev"
dependency group (pillow): uv run --group dev python packaging/build_icon.py

Must be run on the real Qt platform, not QT_QPA_PLATFORM=offscreen --
confirmed the offscreen platform plugin doesn't render text on this
machine, which would silently drop the icon's "SFG" lettering.
"""
from __future__ import annotations

import sys
from io import BytesIO
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QBuffer, QByteArray, QIODevice
from PySide6.QtWidgets import QApplication

from sfg_app2.app.utils.icon_rendering import render_svg_pixmap

_ICON_SVG = Path(__file__).parent.parent / "src" / "sfg_app2" / "app" / "ressources" / "icon.svg"
_ICON_ICO = Path(__file__).parent / "icon.ico"
_SIZES = (16, 32, 48, 256)


def _to_pil_image(pixmap) -> Image.Image:
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    pixmap.save(buffer, "PNG")
    return Image.open(BytesIO(bytes(data)))


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    if app.platformName() == "offscreen":
        print(
            "Warning: running under the offscreen Qt platform, which doesn't "
            "render text on this machine -- the icon's \"SFG\" lettering would "
            "come out blank. Re-run without QT_QPA_PLATFORM=offscreen.",
            file=sys.stderr,
        )

    # Render each size directly from the vector source (rather than
    # rasterizing once and downsampling) so every size is crisp --
    # Pillow's ICO writer embeds an exact-size match as-is with no
    # resampling, only falling back to a blurrier LANCZOS thumbnail
    # for sizes it wasn't given directly.
    images = [_to_pil_image(render_svg_pixmap(_ICON_SVG, size)) for size in _SIZES]
    images[-1].save(
        _ICON_ICO, format="ICO",
        sizes=[im.size for im in images],
        append_images=images[:-1],
    )
    print(f"Wrote {_ICON_ICO}")


if __name__ == "__main__":
    main()
