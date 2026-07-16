from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from platformdirs import user_log_path


def log_file_path() -> Path:
    return user_log_path("MyGitClient", ensure_exists=True) / "mygitclient.log"


def configure_logging() -> None:
    handler = RotatingFileHandler(
        log_file_path(), maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()
    root.addHandler(handler)

