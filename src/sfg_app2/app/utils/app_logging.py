from __future__ import annotations
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from platformdirs import user_log_dir

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
