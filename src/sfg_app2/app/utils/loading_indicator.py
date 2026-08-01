from __future__ import annotations
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QProgressDialog


def show_loading(parent, message: str = "Loading...") -> QProgressDialog:
    """Show an indeterminate, non-cancelable 'please wait' popup.
    Caller must call .close() on the returned dialog when the slow
    operation finishes."""
    dlg = QProgressDialog(message, None, 0, 0, parent)
    dlg.setWindowTitle("Please wait")
    dlg.setWindowModality(Qt.WindowModality.WindowModal)
    dlg.setMinimumDuration(0)
    dlg.setCancelButton(None)
    dlg.show()
    QApplication.processEvents()
    return dlg
