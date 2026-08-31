from __future__ import annotations

import os
import platform
import re
import shutil
import stat
import sys
import tempfile
import time
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import IO

import pytest

_ROOT = Path.cwd() / ".test-tmp-session"
MANAGED_MARKER = ".managed-by-mygitclient-tests"
LOCK_FILE = ".run.lock"
UNLOCKED_RUN_GRACE_SECONDS = 60.0


@dataclass
class _RunState:
    path: Path
    lock: IO[bytes]
    environment: dict[str, str | None]
    previous_tempdir: str | None


_ACTIVE_RUNS: dict[int, _RunState] = {}


def configuration_name() -> str:
    raw = "-".join(
        (
            platform.system(),
            platform.machine(),
            sys.implementation.name,
            f"{sys.version_info.major}.{sys.version_info.minor}",
        )
    ).lower()
    return re.sub(r"[^a-z0-9._-]+", "-", raw).strip("-")


def _try_lock(handle: IO[bytes]) -> bool:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True

    import fcntl

    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def unlock(handle: IO[bytes]) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return

    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def acquire_run_lock(path: Path) -> IO[bytes]:
    handle = path.open("a+b")
    if path.stat().st_size == 0:
        handle.write(b"1")
        handle.flush()
    if not _try_lock(handle):
        handle.close()
        raise RuntimeError(f"Could not lock pytest run directory: {path.parent}")
    return handle


def _remove_tree(path: Path) -> bool:
    def make_writable_and_retry(function: object, failed_path: str, _: object) -> None:
        try:
            os.chmod(failed_path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
            if callable(function):
                function(failed_path)
        except OSError:
            return

    try:
        shutil.rmtree(path, onexc=make_writable_and_retry)
    except OSError:
        return False
    return not path.exists()


def _run_is_stale(path: Path, *, now: float) -> bool:
    lock_path = path / LOCK_FILE
    if not lock_path.exists():
        try:
            return now - path.stat().st_mtime >= UNLOCKED_RUN_GRACE_SECONDS
        except OSError:
            return False

    try:
        handle = lock_path.open("r+b")
    except OSError:
        return False
    try:
        if not _try_lock(handle):
            return False
        unlock(handle)
        return True
    finally:
        handle.close()


def cleanup_stale_runs(root: Path, *, keep: Path) -> list[Path]:
    failed: list[Path] = []
    now = time.time()
    try:
        configuration_dirs = tuple(root.iterdir())
    except OSError:
        return [root]

    for configuration_dir in configuration_dirs:
        if not configuration_dir.is_dir() or not (
            configuration_dir / MANAGED_MARKER
        ).is_file():
            continue
        try:
            candidates = tuple(configuration_dir.glob("run-*"))
        except OSError:
            failed.append(configuration_dir)
            continue
        for candidate in candidates:
            if candidate == keep or not candidate.is_dir():
                continue
            if _run_is_stale(candidate, now=now) and not _remove_tree(candidate):
                failed.append(candidate)
    return failed


def pytest_configure(config: pytest.Config) -> None:
    if not os.environ.get("QT_QPA_PLATFORM"):
        os.environ["QT_QPA_PLATFORM"] = "offscreen"

    if config.getoption("basetemp") is not None:
        return

    configuration_dir = _ROOT / configuration_name()
    configuration_dir.mkdir(parents=True, exist_ok=True)
    (configuration_dir / MANAGED_MARKER).touch(exist_ok=True)

    run_path = configuration_dir / f"run-{os.getpid()}-{time.time_ns()}"
    run_path.mkdir()
    lock = acquire_run_lock(run_path / LOCK_FILE)

    failed = cleanup_stale_runs(_ROOT, keep=run_path)
    if failed:
        paths = ", ".join(str(path) for path in failed[:3])
        warnings.warn(
            f"Could not remove {len(failed)} stale pytest directorie(s): {paths}",
            RuntimeWarning,
            stacklevel=1,
        )

    system_temp = run_path / "system"
    system_temp.mkdir()
    previous_environment = {name: os.environ.get(name) for name in ("TEMP", "TMP", "TMPDIR")}
    for name in previous_environment:
        os.environ[name] = str(system_temp)

    previous_tempdir = tempfile.tempdir
    tempfile.tempdir = str(system_temp)
    config.option.basetemp = str(run_path / "pytest")
    _ACTIVE_RUNS[id(config)] = _RunState(
        path=run_path,
        lock=lock,
        environment=previous_environment,
        previous_tempdir=previous_tempdir,
    )


@pytest.fixture(autouse=True)
def prevent_unmocked_desktop_open(monkeypatch: pytest.MonkeyPatch) -> None:
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices

    def reject_open(url: QUrl) -> bool:
        raise AssertionError(f"Test attempted to open an external URL or file: {url.toString()}")

    monkeypatch.setattr(QDesktopServices, "openUrl", reject_open)


def pytest_unconfigure(config: pytest.Config) -> None:
    state = _ACTIVE_RUNS.pop(id(config), None)
    if state is None:
        return

    tempfile.tempdir = state.previous_tempdir
    for name, value in state.environment.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value

    unlock(state.lock)
    state.lock.close()
    _remove_tree(state.path)
