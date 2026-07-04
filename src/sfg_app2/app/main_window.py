from PySide6.QtWidgets import (
    QMainWindow, QTabWidget, QWidget,
    QVBoxLayout, QLabel
)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SFG App")
        self.setMinimumSize(1000, 700)

        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

        # placeholder tabs — replace one at a time
        self._add_placeholder("Load & Match")
        self._add_placeholder("Processing Parameters")
        self._add_placeholder("Process & Review")
        self._add_placeholder("Fitting")
        self._add_placeholder("Export")

        # disable tabs that aren't ready yet
        for i in range(1, self.tabs.count()):
            self.tabs.setTabEnabled(i, False)

    def _add_placeholder(self, name: str):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.addWidget(QLabel(f"{name} — coming soon"))
        self.tabs.addTab(widget, name)

    def unlock_tab(self, index: int):
        """Call this when a step is complete to enable the next tab."""
        self.tabs.setTabEnabled(index, True)
        self.tabs.setCurrentIndex(index)