from __future__ import annotations

import os
import platform
import sys
import time
from pathlib import Path

import pytest
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices

from mygitclient import pytest_temp_storage


def _managed_configuration(root: Path, name: str) -> Path:
    configuration = root / name
    configuration.mkdir()
    (configuration / pytest_temp_storage.MANAGED_MARKER).touch()
    return configuration


def test_configuration_name_identifies_platform_and_python() -> None:
    name = pytest_temp_storage.configuration_name()

    assert platform.system().lower() in name
    assert sys.implementation.name in name
    assert f"{sys.version_info.major}.{sys.version_info.minor}" in name


def test_unmocked_desktop_open_is_rejected() -> None:
    with pytest.raises(AssertionError, match="attempted to open an external URL"):
        QDesktopServices.openUrl(QUrl("https://example.invalid"))


def test_cleanup_removes_stale_runs_but_preserves_active_and_unmanaged(tmp_path: Path) -> None:
    configuration = _managed_configuration(tmp_path, "windows-x86_64-cpython-3.14")
    stale = configuration / "run-1-stale"
    stale.mkdir()
    (stale / pytest_temp_storage.LOCK_FILE).write_bytes(b"1")
    (stale / "result.txt").write_text("stale", encoding="utf-8")

    active = configuration / "run-2-active"
    active.mkdir()
    active_lock = pytest_temp_storage.acquire_run_lock(
        active / pytest_temp_storage.LOCK_FILE
    )

    unmanaged = tmp_path / "manual-basetemp"
    unmanaged.mkdir()
    (unmanaged / "keep.txt").write_text("keep", encoding="utf-8")

    try:
        failed = pytest_temp_storage.cleanup_stale_runs(
            tmp_path, keep=configuration / "run-current"
        )
    finally:
        pytest_temp_storage.unlock(active_lock)
        active_lock.close()

    assert failed == []
    assert not stale.exists()
    assert active.exists()
    assert unmanaged.exists()


def test_cleanup_waits_before_removing_an_unlocked_incomplete_run(tmp_path: Path) -> None:
    configuration = _managed_configuration(tmp_path, "linux-x86_64-cpython-3.14")
    recent = configuration / "run-3-starting"
    recent.mkdir()

    failed = pytest_temp_storage.cleanup_stale_runs(tmp_path, keep=tmp_path / "other")

    assert failed == []
    assert recent.exists()
    old_time = time.time() - pytest_temp_storage.UNLOCKED_RUN_GRACE_SECONDS - 1
    recent.touch()
    recent.chmod(recent.stat().st_mode)
    os.utime(recent, (old_time, old_time))

    failed = pytest_temp_storage.cleanup_stale_runs(tmp_path, keep=tmp_path / "other")

    assert failed == []
    assert not recent.exists()
