from __future__ import annotations

import subprocess
from pathlib import Path

from pytestqt.qtbot import QtBot

from mygitclient.git.models import DiffSnapshot, FileStatus
from mygitclient.git.runner import GitRunner
from mygitclient.git.service import GitService


def _git(repository: Path, *arguments: str) -> None:
    subprocess.run(
        ["git", *arguments], cwd=repository, check=True, capture_output=True
    )


def test_completed_runner_is_released(qtbot: QtBot, tmp_path: Path) -> None:
    _git(tmp_path, "init", "--initial-branch=main")
    service = GitService()

    with qtbot.waitSignal(service.status_ready, timeout=5000):
        service.request_status(tmp_path)

    qtbot.waitUntil(lambda: not service.findChildren(GitRunner), timeout=5000)


def test_diff_result_identifies_its_repository(qtbot: QtBot, tmp_path: Path) -> None:
    _git(tmp_path, "init", "--initial-branch=main")
    tracked = tmp_path / "tracked.txt"
    tracked.write_text("before\n", encoding="utf-8")
    _git(tmp_path, "add", "tracked.txt")
    _git(
        tmp_path,
        "-c",
        "user.name=MyGitClient Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-m",
        "initial",
    )
    tracked.write_text("after\n", encoding="utf-8")
    service = GitService()
    results: list[object] = []
    service.diff_ready.connect(results.append)

    with qtbot.waitSignal(service.diff_ready, timeout=5000):
        service.request_diff(tmp_path, FileStatus("tracked.txt", ".", "M"), staged=False)

    assert len(results) == 1
    result = results[0]
    assert isinstance(result, DiffSnapshot)
    assert result.repository == tmp_path
    assert result.diff.path == "tracked.txt"
