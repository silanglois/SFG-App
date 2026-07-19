# src/sfg_app2/app/widgets/spectrum_plot_widget.py
from __future__ import annotations
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
from PySide6.QtWidgets import QWidget, QVBoxLayout


class SpectrumPlotWidget(QWidget):
    """Reusable matplotlib canvas for embedding in any Qt widget or dialog."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.figure = Figure(tight_layout=True)
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.toolbar = NavigationToolbar2QT(self.canvas, self)
        self.ax = self.figure.add_subplot(111)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.toolbar)
        layout.addWidget(self.canvas)

    def clear(self):
        self.ax.clear()
        self.canvas.draw()

    def plot(self, x, y, label: str = None, **kwargs):
        self.ax.plot(x, y, label=label, **kwargs)
        if label:
            self.ax.legend()
        self.canvas.draw()

    def set_labels(self, xlabel: str = "", ylabel: str = "", title: str = ""):
        self.ax.set_xlabel(xlabel)
        self.ax.set_ylabel(ylabel)
        self.ax.set_title(title)
        self.canvas.draw()