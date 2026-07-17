from __future__ import annotations

import subprocess
from pathlib import Path

from pytestqt.qtbot import QtBot

from mygitclient.git.models import (
    BranchesSnapshot,
    CommitDiffSnapshot,
    CommitFilesSnapshot,
    DiffSnapshot,
    FileStatus,
)
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


def test_commit_files_and_diff_are_loaded(qtbot: QtBot, tmp_path: Path) -> None:
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
    parent = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True
    ).strip()
    tracked.write_text("after\n", encoding="utf-8")
    _git(
        tmp_path,
        "-c",
        "user.name=MyGitClient Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-am",
        "update",
    )
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True
    ).strip()
    service = GitService()
    file_results: list[object] = []
    diff_results: list[object] = []
    service.commit_files_ready.connect(file_results.append)
    service.commit_diff_ready.connect(diff_results.append)

    with qtbot.waitSignal(service.commit_files_ready, timeout=5000):
        service.request_commit_files(tmp_path, commit)
    with qtbot.waitSignal(service.commit_diff_ready, timeout=5000):
        service.request_commit_diff(
            tmp_path, commit, "tracked.txt", parent_oid=parent
        )

    files = file_results[0]
    assert isinstance(files, CommitFilesSnapshot)
    assert [(file.status, file.path) for file in files.files] == [("M", "tracked.txt")]
    diff = diff_results[0]
    assert isinstance(diff, CommitDiffSnapshot)
    assert "-before" in diff.diff.text
    assert "+after" in diff.diff.text


def test_branches_can_be_loaded_checked_out_and_created(
    qtbot: QtBot, tmp_path: Path
) -> None:
    _git(tmp_path, "init", "--initial-branch=main")
    tracked = tmp_path / "tracked.txt"
    tracked.write_text("content\n", encoding="utf-8")
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
    _git(tmp_path, "branch", "feature")
    service = GitService()
    results: list[object] = []
    service.branches_ready.connect(results.append)

    with qtbot.waitSignal(service.branches_ready, timeout=5000):
        service.request_branches(tmp_path)
    snapshot = results[-1]
    assert isinstance(snapshot, BranchesSnapshot)
    feature = next(branch for branch in snapshot.branches if branch.name == "feature")

    with qtbot.waitSignal(service.mutation_ready, timeout=5000):
        service.request_checkout(tmp_path, feature)
    with qtbot.waitSignal(service.mutation_ready, timeout=5000):
        service.request_create_branch(tmp_path, "new-branch")
    with qtbot.waitSignal(service.branches_ready, timeout=5000):
        service.request_branches(tmp_path)

    refreshed = results[-1]
    assert isinstance(refreshed, BranchesSnapshot)
    current = next(branch for branch in refreshed.branches if branch.current)
    assert current.name == "new-branch"
