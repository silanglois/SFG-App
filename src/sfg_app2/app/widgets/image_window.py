# src/sfg_app2/app/widgets/image_window.py
from __future__ import annotations
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton

from sfg_app2.app.widgets.image_plot_widget import ImagePlotWidget
from sfg_app2.processing.image_file import CCDImage


class ImageWindow(QWidget):
    """Independent, minimizable window showing one CCD image — same
    lifecycle shape as PlotWindow (spectra): a genuine top-level window,
    not a modal dialog, so several can stay open at once. The caller is
    responsible for keeping a reference to it (e.g. MainWindow._image_windows)
    since nothing else does once it's shown.
    """

    def __init__(self, image: CCDImage, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle(f"CCD Image — {image.path.name}")
        self.resize(800, 700)

        layout = QVBoxLayout(self)

        self.plot_widget = ImagePlotWidget()
        layout.addWidget(self.plot_widget)
        self.plot_widget.set_image(image)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        close_row = QHBoxLayout()
        close_row.addStretch()
        close_row.addWidget(close_btn)
        layout.addLayout(close_row)
