# src/sfg_app2/app/dialogs/plot_dialog.py
from __future__ import annotations
import logging
from PySide6.QtWidgets import QDialog, QVBoxLayout, QDialogButtonBox

from sfg_app2.app.widgets.spectrum_plot_widget import SpectrumPlotWidget
from sfg_app2.app.utils.loading_indicator import show_loading

logger = logging.getLogger(__name__)


class PlotDialog(QDialog):
    """Overlay plot of multiple DataFile average spectra."""

    def __init__(self, files: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Spectra Preview")
        self.resize(800, 500)

        layout = QVBoxLayout(self)
        self.plot_widget = SpectrumPlotWidget()
        layout.addWidget(self.plot_widget)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        loading = show_loading(self, "Loading spectra...")
        try:
            self._plot_files(files)
        finally:
            loading.close()

    def _plot_files(self, files: list):
        self.plot_widget.clear()
        for f in files:
            try:
                avg = f.average_spectrum().frame(1)
                self.plot_widget.plot(
                    avg["Wavelength"].to_numpy(),
                    avg["Intensity"].to_numpy(),
                    label=f.path.name,
                )
            except Exception as e:
                logger.warning("Could not plot %s: %s", f.path.name, e)

        self.plot_widget.set_labels(
            xlabel="Wavelength",
            ylabel="Intensity",
            title=f"{len(files)} file(s) overlaid",
        )