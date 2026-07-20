from __future__ import annotations

import logging
from pathlib import Path

from pytest import MonkeyPatch

from mygitclient import logging_config


def test_log_file_path_creates_non_duplicated_application_directory(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[tuple[str, bool, bool]] = []

    def fake_user_log_path(
        appname: str, *, appauthor: bool, ensure_exists: bool
    ) -> Path:
        calls.append((appname, appauthor, ensure_exists))
        return tmp_path / "MyGitClient" / "Logs"

    monkeypatch.setattr(logging_config, "user_log_path", fake_user_log_path)

    result = logging_config.log_file_path()

    assert result == tmp_path / "MyGitClient" / "Logs" / "mygitclient.log"
    assert result.parent.is_dir()
    assert calls == [("MyGitClient", False, False)]


def test_logging_falls_back_to_stderr_when_log_file_cannot_be_created(
    monkeypatch: MonkeyPatch,
) -> None:
    original_handlers = logging.root.handlers[:]

    def fail_to_create_handler(*args: object, **kwargs: object) -> logging.Handler:
        raise OSError("log directory is unavailable")

    monkeypatch.setattr(logging_config, "RotatingFileHandler", fail_to_create_handler)
    try:
        logging_config.configure_logging()
        assert len(logging.root.handlers) == 1
        assert isinstance(logging.root.handlers[0], logging.StreamHandler)
    finally:
        logging.root.handlers = original_handlers
