import sys
from pathlib import Path
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap, QPainter, QColor, QIcon
from PySide6.QtWidgets import QApplication, QSplashScreen
from .main_window import MainWindow

_ICON_PATH = Path(__file__).parent / "ressources" / "icon.svg"


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
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(str(_ICON_PATH)))

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
