"""Logging setup: console + auto-rotating file handler."""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

from src.config import LogSettings

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s — %(message)s"
LOG_FILE = "conversational_ai.log"


def setup_logging(cfg: LogSettings) -> None:
    """Configure root logger with a console handler and a rotating file handler.

    Rotates at UTC midnight; files older than max_age_days are deleted automatically.
    Replaces any handlers installed by an earlier basicConfig call.
    """
    log_dir = Path(cfg.log_dir).expanduser()
    log_dir.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(LOG_FORMAT)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    file_handler = logging.handlers.TimedRotatingFileHandler(
        log_dir / LOG_FILE,
        when="midnight",
        backupCount=cfg.max_age_days,
        encoding="utf-8",
        utc=True,
    )
    file_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()
    root.addHandler(console_handler)
    root.addHandler(file_handler)
