from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from sys import stderr

from platformdirs import user_log_path


def log_file_path() -> Path:
    directory = user_log_path("MyGitClient", appauthor=False, ensure_exists=False)
    directory.mkdir(parents=True, exist_ok=True)
    return directory / "mygitclient.log"


def configure_logging() -> None:
    try:
        handler: logging.Handler = RotatingFileHandler(
            log_file_path(), maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8"
        )
    except OSError:
        handler = logging.StreamHandler(stderr) if stderr is not None else logging.NullHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()
    root.addHandler(handler)
