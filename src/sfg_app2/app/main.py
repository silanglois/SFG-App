import sys
from pathlib import Path
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap, QPainter, QColor, QIcon
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication, QSplashScreen
from .main_window import MainWindow
from .utils.appearance_settings import AppearanceSettings

_ICON_PATH = Path(__file__).parent / "ressources" / "icon.svg"
_ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)


def _load_app_icon() -> QIcon:
    """Builds the icon from explicit raster sizes rather than relying on
    the SVG icon engine to service every size Windows' taskbar/Alt-Tab
    request on demand -- rendering them upfront is cheap and avoids any
    size the engine doesn't handle silently falling back to a blank icon."""
    renderer = QSvgRenderer(str(_ICON_PATH))
    icon = QIcon()
    for size in _ICON_SIZES:
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        icon.addPixmap(pixmap)
    return icon


def _set_windows_app_id():
    # Windows groups/identifies taskbar buttons by the process's
    # AppUserModelID, which defaults to being derived from python.exe
    # itself when unset -- so the taskbar can show python's icon/identity
    # even though the window's own icon (title bar, Alt-Tab) is correct.
    # This gives the running app its own identity instead.
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("SFGApp.SFGApp2")


def _make_splash_pixmap() -> QPixmap:
    pixmap = QPixmap(420, 260)
    pixmap.fill(QColor("#2b2b2b"))
    painter = QPainter(pixmap)
    painter.setPen(QColor("#f0f0f0"))
    font = painter.font()
    font.setPointSize(18)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "SFG-App")
    painter.end()
    return pixmap


def run():
    _set_windows_app_id()

    app = QApplication(sys.argv)
    app.setWindowIcon(_load_app_icon())

    # Applied before the splash screen is constructed so every window,
    # including the splash, renders with the chosen scheme from the start.
    AppearanceSettings().apply_current()

    # MainWindow is heavy to construct (4 tabs, each hosting a nested
    # QMainWindow full of dock widgets), all built synchronously before
    # the window is first shown -- a splash screen guarantees whatever
    # appears during that construction gap is intentional, rather than
    # a partially-laid-out frame of the real window.
    splash = QSplashScreen(_make_splash_pixmap())
    splash.showMessage(
        "Loading...", Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter,
        QColor("#f0f0f0"),
    )
    splash.show()

    # A processEvents() call issued before app.exec() has even started
    # isn't a reliable way to guarantee the OS actually composites the
    # splash's first frame before the next line blocks the whole loop
    # for as long as MainWindow() takes to construct. Deferring the
    # heavy work to fire via a zero-delay QTimer, once app.exec() is
    # already pumping events, guarantees Qt has processed the splash's
    # own show/expose events first.
    def _start():
        window = MainWindow()
        window.show()
        app.processEvents()   # let the new window's layout settle while
                               # the splash is still covering it
        splash.finish(window)   # closes the splash once `window` is shown
        app._main_window = window   # keep a reference alive past _start()

    QTimer.singleShot(0, _start)
    sys.exit(app.exec())
