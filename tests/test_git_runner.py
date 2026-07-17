from __future__ import annotations

import subprocess
from pathlib import Path

from pytestqt.qtbot import QtBot

from mygitclient.git.models import GitCommand, GitResult
from mygitclient.git.parsers import parse_status_porcelain_v2
from mygitclient.git.runner import GitRunner


def _git(repository: Path, *arguments: str) -> None:
    subprocess.run(
        ["git", *arguments],
        cwd=repository,
        check=True,
        capture_output=True,
    )


def test_runner_reads_status_from_real_repository(qtbot: QtBot, tmp_path: Path) -> None:
    _git(tmp_path, "init", "--initial-branch=main")
    tracked = tmp_path / "tracked.txt"
    tracked.write_text("initial\n", encoding="utf-8")
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
    tracked.write_text("changed\n", encoding="utf-8")
    (tmp_path / "new file.txt").write_text("new\n", encoding="utf-8")

    runner = GitRunner()
    command = GitCommand(
        ("status", "--porcelain=v2", "--branch", "-z"),
        tmp_path,
        "test status",
    )
    results: list[object] = []

    def capture_result(result: object) -> None:
        results.append(result)

    runner.completed.connect(capture_result)
    with qtbot.waitSignal(runner.completed, timeout=5000) as blocker:
        runner.run(command)

    assert blocker.signal_triggered
    result = results[0]
    assert isinstance(result, GitResult)
    assert result.succeeded
    status = parse_status_porcelain_v2(result.stdout)
    assert status.branch.head == "main"
    assert {(file.path, file.worktree_status) for file in status.files} == {
        ("tracked.txt", "M"),
        ("new file.txt", "?"),
    }


def test_runner_reports_user_cancellation(qtbot: QtBot, tmp_path: Path) -> None:
    _git(tmp_path, "init", "--initial-branch=main")
    runner = GitRunner()
    results: list[object] = []
    runner.completed.connect(results.append)

    runner.run(GitCommand(("cat-file", "--batch"), tmp_path, "wait for objects"))
    qtbot.waitUntil(lambda: runner.is_running, timeout=5000)
    with qtbot.waitSignal(runner.completed, timeout=5000):
        runner.cancel()

    assert len(results) == 1
    result = results[0]
    assert isinstance(result, GitResult)
    assert result.cancelled
