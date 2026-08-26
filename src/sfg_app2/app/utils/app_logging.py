from __future__ import annotations
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from platformdirs import user_log_dir

logger = logging.getLogger(__name__)

LOG_DIR = Path(user_log_dir("SFG-App"))
LOG_FILE = LOG_DIR / "sfg-app.log"


def configure_logging() -> Path:
    """Attaches handlers to the root logger so the logger.warning/error
    calls used throughout the app actually land somewhere -- without
    this, Python's "handler of last resort" only prints WARNING+ to
    stderr, which is invisible in a normal (non-console) launch, and
    there is no persistent record at all."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    file_handler = RotatingFileHandler(
        LOG_FILE, maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
    ))

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.WARNING)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(file_handler)
    root.addHandler(console_handler)
    return LOG_FILE


def install_excepthook():
    """Replaces the default sys.excepthook so an exception that escapes
    a Qt slot unguarded is logged and shown to the user instead of
    printing an invisible traceback (no console in a packaged build)
    and otherwise silently misbehaving. PySide6 routes uncaught slot
    exceptions through sys.excepthook, so this is the correct place to
    intercept them; returning normally here (rather than calling the
    default hook) keeps the app running instead of tearing it down."""
    def _handle(exc_type, exc_value, exc_tb):
        logger.critical("Unhandled exception", exc_info=(exc_type, exc_value, exc_tb))
        from PySide6.QtWidgets import QApplication, QMessageBox
        if QApplication.instance() is not None:
            QMessageBox.critical(
                None, "Unexpected error",
                f"An unexpected error occurred:\n\n{exc_value}\n\n"
                f"Details have been written to the log file:\n{LOG_FILE}",
            )

    sys.excepthook = _handle
