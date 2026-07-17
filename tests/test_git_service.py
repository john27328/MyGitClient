from __future__ import annotations

import subprocess
from pathlib import Path

from pytestqt.qtbot import QtBot

from mygitclient.git.models import (
    BranchesSnapshot,
    BranchInfo,
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


def test_selected_files_can_be_stashed(qtbot: QtBot, tmp_path: Path) -> None:
    _git(tmp_path, "init", "--initial-branch=main")
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_text("before first\n", encoding="utf-8")
    second.write_text("before second\n", encoding="utf-8")
    _git(tmp_path, "add", "first.txt", "second.txt")
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
    first.write_text("changed first\n", encoding="utf-8")
    second.write_text("changed second\n", encoding="utf-8")
    service = GitService()

    with qtbot.waitSignal(service.mutation_ready, timeout=5000):
        service.request_stash_files(
            tmp_path, (FileStatus("first.txt", ".", "M"),)
        )

    assert first.read_text(encoding="utf-8") == "before first\n"
    assert second.read_text(encoding="utf-8") == "changed second\n"
    assert subprocess.check_output(
        ["git", "stash", "list"], cwd=tmp_path, text=True
    ).startswith("stash@{0}")


def test_checkout_autostash_restores_local_changes(qtbot: QtBot, tmp_path: Path) -> None:
    _git(tmp_path, "init", "--initial-branch=main")
    local = tmp_path / "local.txt"
    branch_file = tmp_path / "branch.txt"
    local.write_text("base\n", encoding="utf-8")
    branch_file.write_text("base\n", encoding="utf-8")
    _git(tmp_path, "add", "local.txt", "branch.txt")
    identity = (
        "-c",
        "user.name=MyGitClient Test",
        "-c",
        "user.email=test@example.invalid",
    )
    _git(tmp_path, *identity, "commit", "-m", "initial")
    _git(tmp_path, "switch", "-c", "feature")
    branch_file.write_text("feature\n", encoding="utf-8")
    _git(tmp_path, *identity, "commit", "-am", "feature change")
    _git(tmp_path, "switch", "main")
    local.write_text("local change\n", encoding="utf-8")
    service = GitService()
    branch = BranchInfo("refs/heads/feature", "feature", "1" * 40, False)

    with qtbot.waitSignal(service.mutation_ready, timeout=5000):
        service.request_checkout(tmp_path, branch, autostash=True)

    assert subprocess.check_output(
        ["git", "branch", "--show-current"], cwd=tmp_path, text=True
    ).strip() == "feature"
    assert local.read_text(encoding="utf-8") == "local change\n"
    assert branch_file.read_text(encoding="utf-8") == "feature\n"
    assert subprocess.check_output(
        ["git", "stash", "list"], cwd=tmp_path, text=True
    ).strip() == ""


def test_checkout_autostash_stops_when_attributes_rewrite_worktree(
    qtbot: QtBot, tmp_path: Path
) -> None:
    _git(tmp_path, "init", "--initial-branch=main")
    tracked = tmp_path / "tracked.txt"
    tracked.write_bytes(b"before\r\n")
    _git(tmp_path, "-c", "core.autocrlf=false", "add", "tracked.txt")
    identity = (
        "-c",
        "user.name=MyGitClient Test",
        "-c",
        "user.email=test@example.invalid",
    )
    _git(tmp_path, *identity, "commit", "-m", "initial")
    _git(tmp_path, "switch", "-c", "feature")
    _git(tmp_path, "switch", "main")
    (tmp_path / ".gitattributes").write_text("*.txt text eol=lf\n", encoding="utf-8")
    _git(tmp_path, "add", ".gitattributes")
    _git(tmp_path, *identity, "commit", "-m", "normalize text files")
    tracked.write_bytes(b"local change\r\n")
    service = GitService()
    branch = BranchInfo("refs/heads/feature", "feature", "1" * 40, False)
    errors: list[str] = []
    service.operation_failed.connect(errors.append)

    with qtbot.waitSignal(service.operation_failed, timeout=5000):
        service.request_checkout(tmp_path, branch, autostash=True)

    assert "still contains changes after stashing" in errors[0]
    assert subprocess.check_output(
        ["git", "branch", "--show-current"], cwd=tmp_path, text=True
    ).strip() == "main"
    assert subprocess.check_output(
        ["git", "stash", "list"], cwd=tmp_path, text=True
    ).startswith("stash@{0}")


def test_discard_succeeds_with_gitattributes_warning(qtbot: QtBot, tmp_path: Path) -> None:
    _git(tmp_path, "init", "--initial-branch=main")
    tracked = tmp_path / "tracked.txt"
    tracked.write_text("before\n", encoding="utf-8")
    (tmp_path / ".gitattributes").write_text("* #invalid-attribute\n", encoding="utf-8")
    _git(tmp_path, "add", "tracked.txt", ".gitattributes")
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

    with qtbot.waitSignal(service.mutation_ready, timeout=5000):
        service.request_discard(tmp_path, FileStatus("tracked.txt", ".", "M"))

    assert tracked.read_text(encoding="utf-8") == "before\n"


def test_pull_rebase_autostash_restores_changes(qtbot: QtBot, tmp_path: Path) -> None:
    remote = tmp_path / "remote.git"
    seed = tmp_path / "seed"
    client = tmp_path / "client"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    subprocess.run(
        ["git", "clone", str(remote), str(seed)], check=True, capture_output=True
    )
    local = seed / "local.txt"
    remote_file = seed / "remote.txt"
    local.write_text("base\n", encoding="utf-8")
    remote_file.write_text("base\n", encoding="utf-8")
    _git(seed, "add", ".")
    identity = (
        "-c",
        "user.name=MyGitClient Test",
        "-c",
        "user.email=test@example.invalid",
    )
    _git(seed, *identity, "commit", "-m", "initial")
    _git(seed, "push", "-u", "origin", "master")
    subprocess.run(
        ["git", "clone", str(remote), str(client)], check=True, capture_output=True
    )
    remote_file.write_text("remote update\n", encoding="utf-8")
    _git(seed, *identity, "commit", "-am", "remote update")
    _git(seed, "push")
    (client / "local.txt").write_text("local change\n", encoding="utf-8")
    service = GitService()

    with qtbot.waitSignal(service.mutation_ready, timeout=10000):
        service.request_pull(client, rebase=True, autostash=True)

    assert (client / "local.txt").read_text(encoding="utf-8") == "local change\n"
    assert (client / "remote.txt").read_text(encoding="utf-8") == "remote update\n"
