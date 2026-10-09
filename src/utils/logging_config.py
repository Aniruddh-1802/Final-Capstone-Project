"""Logging setup: console plus a rotating file with timestamp, level, module and message."""
from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

from utils.request_context import RequestIdFilter

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(module)s | %(request_id)s | %(message)s"
_MAX_BYTES = 5 * 1024 * 1024
_BACKUP_COUNT = 5


def setup_logging(name: str, log_dir: str | os.PathLike[str] | None = None,
                  level: int = logging.INFO) -> logging.Logger:
    """Return a logger writing to the console and to ``<log_dir>/<name>.log``.

    ``log_dir`` defaults to the LOG_DIR environment variable, then ``logs``.
    Calling it twice for the same name does not add duplicate handlers.
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)
    if logger.handlers:
        return logger

    formatter = logging.Formatter(LOG_FORMAT)
    request_filter = RequestIdFilter()
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    console.addFilter(request_filter)
    logger.addHandler(console)

    directory = Path(log_dir or os.environ.get("LOG_DIR") or "logs")
    try:
        directory.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            directory / f"{name}.log", maxBytes=_MAX_BYTES,
            backupCount=_BACKUP_COUNT, encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler.addFilter(request_filter)
        logger.addHandler(file_handler)
    except OSError as exc:  # keep console logging even if the folder is unwritable
        logger.warning("File logging disabled (%s)", exc)

    logger.propagate = False
    return logger
