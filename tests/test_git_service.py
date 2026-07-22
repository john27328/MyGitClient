from __future__ import annotations

import subprocess
from pathlib import Path

from pytestqt.qtbot import QtBot

from mygitclient.git.models import (
    AmendPreview,
    BranchesSnapshot,
    BranchInfo,
    CommitDiffSnapshot,
    CommitFilesSnapshot,
    CommitPage,
    DiffSnapshot,
    FileStatus,
    RefComparisonDiffSnapshot,
    RefComparisonSnapshot,
    StashesSnapshot,
    TagsSnapshot,
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


def test_history_excludes_stash_commits(qtbot: QtBot, tmp_path: Path) -> None:
    _git(tmp_path, "init", "--initial-branch=main")
    tracked = tmp_path / "tracked.txt"
    tracked.write_text("before\n", encoding="utf-8")
    _git(tmp_path, "add", "tracked.txt")
    identity = (
        "-c",
        "user.name=MyGitClient Test",
        "-c",
        "user.email=test@example.invalid",
    )
    _git(tmp_path, *identity, "commit", "-m", "initial")
    tracked.write_text("after\n", encoding="utf-8")
    _git(tmp_path, "stash", "push", "-m", "hidden stash")
    service = GitService()
    pages: list[object] = []
    service.history_ready.connect(pages.append)

    with qtbot.waitSignal(service.history_ready, timeout=5000):
        service.request_history(tmp_path)

    page = pages[-1]
    assert isinstance(page, CommitPage)
    assert [commit.subject for commit in page.commits] == ["initial"]


def test_history_can_be_limited_to_one_branch(qtbot: QtBot, tmp_path: Path) -> None:
    _git(tmp_path, "init", "--initial-branch=main")
    tracked = tmp_path / "tracked.txt"
    identity = (
        "-c",
        "user.name=MyGitClient Test",
        "-c",
        "user.email=test@example.invalid",
    )
    tracked.write_text("main\n", encoding="utf-8")
    _git(tmp_path, "add", "tracked.txt")
    _git(tmp_path, *identity, "commit", "-m", "main commit")
    _git(tmp_path, "switch", "-c", "feature")
    tracked.write_text("feature\n", encoding="utf-8")
    _git(tmp_path, "add", "tracked.txt")
    _git(tmp_path, *identity, "commit", "-m", "feature commit")
    service = GitService()
    pages: list[object] = []
    service.history_ready.connect(pages.append)

    with qtbot.waitSignal(service.history_ready, timeout=5000):
        service.request_history(tmp_path, refs=("refs/heads/main",))

    page = pages[-1]
    assert isinstance(page, CommitPage)
    assert [commit.subject for commit in page.commits] == ["main commit"]

    with qtbot.waitSignal(service.history_ready, timeout=5000):
        service.request_history(
            tmp_path, refs=("refs/heads/main", "refs/heads/feature")
        )

    comparison_page = pages[-1]
    assert isinstance(comparison_page, CommitPage)
    assert {commit.subject for commit in comparison_page.commits} == {
        "feature commit",
        "main commit",
    }


def test_refs_can_be_compared_by_file_and_diff(qtbot: QtBot, tmp_path: Path) -> None:
    _git(tmp_path, "init", "--initial-branch=main")
    tracked = tmp_path / "tracked.txt"
    tracked.write_text("base\n", encoding="utf-8")
    _git(tmp_path, "add", "tracked.txt")
    identity = (
        "-c",
        "user.name=MyGitClient Test",
        "-c",
        "user.email=test@example.invalid",
    )
    _git(tmp_path, *identity, "commit", "-m", "base")
    _git(tmp_path, "switch", "-c", "feature")
    tracked.write_text("feature\n", encoding="utf-8")
    _git(tmp_path, *identity, "commit", "-am", "feature")
    service = GitService()
    comparisons: list[object] = []
    diffs: list[object] = []
    service.comparison_ready.connect(comparisons.append)
    service.comparison_diff_ready.connect(diffs.append)

    with qtbot.waitSignal(service.comparison_ready, timeout=5000):
        service.request_ref_comparison(tmp_path, "main", "feature")

    comparison = comparisons[-1]
    assert isinstance(comparison, RefComparisonSnapshot)
    assert [(change.status, change.path) for change in comparison.files] == [
        ("M", "tracked.txt")
    ]

    with qtbot.waitSignal(service.comparison_diff_ready, timeout=5000):
        service.request_ref_comparison_diff(tmp_path, "main", "feature", "tracked.txt")

    diff = diffs[-1]
    assert isinstance(diff, RefComparisonDiffSnapshot)
    assert "-base" in diff.diff.text
    assert "+feature" in diff.diff.text


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


def test_diff_can_ignore_whitespace_changes(qtbot: QtBot, tmp_path: Path) -> None:
    _git(tmp_path, "init", "--initial-branch=main")
    tracked = tmp_path / "tracked.txt"
    tracked.write_text("hello world\n", encoding="utf-8")
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
    tracked.write_text("hello     world\n", encoding="utf-8")
    service = GitService()
    results: list[object] = []
    service.diff_ready.connect(results.append)

    with qtbot.waitSignal(service.diff_ready, timeout=5000):
        service.request_diff(
            tmp_path,
            FileStatus("tracked.txt", ".", "M"),
            staged=False,
            ignore_whitespace=True,
        )

    result = results[0]
    assert isinstance(result, DiffSnapshot)
    assert not any(line.kind in {"addition", "deletion"} for line in result.diff.lines)


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


def test_amend_preview_includes_message_body_and_full_diff(
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
        "Initial subject",
        "-m",
        "Initial description",
    )
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True
    ).strip()
    service = GitService()
    results: list[object] = []
    service.amend_preview_ready.connect(results.append)

    with qtbot.waitSignal(service.amend_preview_ready, timeout=5000):
        service.request_amend_preview(tmp_path, commit)

    preview = results[0]
    assert isinstance(preview, AmendPreview)
    assert preview.commit_oid == commit
    assert preview.subject == "Initial subject"
    assert preview.description == "Initial description"
    assert "diff --git a/tracked.txt b/tracked.txt" in preview.diff.text
    assert "+content" in preview.diff.text


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

    with qtbot.waitSignal(service.mutation_ready, timeout=5000):
        service.request_rename_branch(tmp_path, feature, "renamed-feature")
    renamed = BranchInfo("refs/heads/renamed-feature", "renamed-feature", "2" * 40, False)
    with qtbot.waitSignal(service.mutation_ready, timeout=5000):
        service.request_delete_branch(tmp_path, renamed)
    branches = subprocess.check_output(
        ["git", "branch", "--format=%(refname:short)"], cwd=tmp_path, text=True
    ).splitlines()
    assert "renamed-feature" not in branches


def test_tags_can_be_loaded_created_and_deleted(qtbot: QtBot, tmp_path: Path) -> None:
    _git(tmp_path, "init", "--initial-branch=main")
    _git(tmp_path, "config", "user.name", "MyGitClient Test")
    _git(tmp_path, "config", "user.email", "test@example.invalid")
    _git(
        tmp_path,
        "-c",
        "user.name=MyGitClient Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "--allow-empty",
        "-m",
        "initial",
    )
    _git(tmp_path, "tag", "lightweight")
    _git(
        tmp_path,
        "-c",
        "user.name=MyGitClient Test",
        "-c",
        "user.email=test@example.invalid",
        "tag",
        "-a",
        "annotated",
        "-m",
        "Release notes",
    )
    service = GitService()
    results: list[object] = []
    service.tags_ready.connect(results.append)

    with qtbot.waitSignal(service.tags_ready, timeout=5000):
        service.request_tags(tmp_path)
    snapshot = results[-1]
    assert isinstance(snapshot, TagsSnapshot)
    assert {tag.name: tag.annotated for tag in snapshot.tags} == {
        "annotated": True,
        "lightweight": False,
    }

    with qtbot.waitSignal(service.mutation_ready, timeout=5000):
        service.request_create_tag(tmp_path, "new-tag", "HEAD", "New release")
    with qtbot.waitSignal(service.mutation_ready, timeout=5000):
        service.request_delete_tag(tmp_path, "new-tag")
    tags = subprocess.check_output(
        ["git", "tag", "--list"], cwd=tmp_path, text=True
    ).splitlines()
    assert "new-tag" not in tags


def test_force_delete_branch_with_unmerged_commit(qtbot: QtBot, tmp_path: Path) -> None:
    _git(tmp_path, "init", "--initial-branch=main")
    identity = (
        "-c",
        "user.name=MyGitClient Test",
        "-c",
        "user.email=test@example.invalid",
    )
    _git(tmp_path, *identity, "commit", "--allow-empty", "-m", "initial")
    _git(tmp_path, "switch", "-c", "feature")
    _git(tmp_path, *identity, "commit", "--allow-empty", "-m", "feature")
    _git(tmp_path, "switch", "main")
    service = GitService()
    branch = BranchInfo("refs/heads/feature", "feature", "2" * 40, False, ahead=1)

    with qtbot.waitSignal(service.mutation_ready, timeout=5000):
        service.request_delete_branch(tmp_path, branch, force=True)

    branches = subprocess.check_output(
        ["git", "branch", "--format=%(refname:short)"], cwd=tmp_path, text=True
    ).splitlines()
    assert "feature" not in branches


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


def test_selected_files_can_be_staged_and_unstaged(
    qtbot: QtBot, tmp_path: Path
) -> None:
    _git(tmp_path, "init", "--initial-branch=main")
    files = tuple(
        FileStatus(path, ".", "M") for path in ("folder/first.txt", "folder/second.txt")
    )
    (tmp_path / "folder").mkdir()
    for file in files:
        (tmp_path / file.path).write_text("before\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
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
    for file in files:
        (tmp_path / file.path).write_text("after\n", encoding="utf-8")
    service = GitService()

    with qtbot.waitSignal(service.mutation_ready, timeout=5000):
        service.request_stage_files(tmp_path, files, staged=True, has_head=True)
    assert subprocess.check_output(
        ["git", "diff", "--cached", "--name-only"], cwd=tmp_path, text=True
    ).splitlines() == ["folder/first.txt", "folder/second.txt"]

    with qtbot.waitSignal(service.mutation_ready, timeout=5000):
        service.request_stage_files(tmp_path, files, staged=False, has_head=True)
    assert subprocess.check_output(
        ["git", "diff", "--cached", "--name-only"], cwd=tmp_path, text=True
    ).strip() == ""


def test_stashes_can_be_listed_applied_and_dropped(qtbot: QtBot, tmp_path: Path) -> None:
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
    _git(tmp_path, "stash", "push", "-m", "saved work")
    service = GitService()
    snapshots: list[object] = []
    service.stashes_ready.connect(snapshots.append)

    with qtbot.waitSignal(service.stashes_ready, timeout=5000):
        service.request_stashes(tmp_path)

    snapshot = snapshots[-1]
    assert isinstance(snapshot, StashesSnapshot)
    assert len(snapshot.stashes) == 1
    stash = snapshot.stashes[0]
    assert stash.ref == "stash@{0}"
    assert "saved work" in stash.subject

    with qtbot.waitSignal(service.mutation_ready, timeout=5000):
        service.request_stash_action(tmp_path, stash, action="apply")
    assert tracked.read_text(encoding="utf-8") == "after\n"
    _git(tmp_path, "restore", "tracked.txt")

    with qtbot.waitSignal(service.mutation_ready, timeout=5000):
        service.request_stash_action(tmp_path, stash, action="drop")
    assert subprocess.check_output(
        ["git", "stash", "list"], cwd=tmp_path, text=True
    ).strip() == ""


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


def test_fetch_and_push_with_upstream(qtbot: QtBot, tmp_path: Path) -> None:
    remote = tmp_path / "remote.git"
    repository = tmp_path / "repository"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    repository.mkdir()
    _git(repository, "init", "--initial-branch=main")
    _git(repository, "remote", "add", "origin", str(remote))
    identity = (
        "-c",
        "user.name=MyGitClient Test",
        "-c",
        "user.email=test@example.invalid",
    )
    _git(repository, *identity, "commit", "--allow-empty", "-m", "initial")
    service = GitService()

    with qtbot.waitSignal(service.mutation_ready, timeout=5000):
        service.request_push(repository, branch="main", set_upstream=True)

    assert subprocess.check_output(
        ["git", "rev-parse", "--abbrev-ref", "main@{upstream}"],
        cwd=repository,
        text=True,
    ).strip() == "origin/main"
    local_oid = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repository, text=True
    ).strip()
    remote_oid = subprocess.check_output(
        ["git", "rev-parse", "refs/heads/main"], cwd=remote, text=True
    ).strip()
    assert remote_oid == local_oid

    with qtbot.waitSignal(service.mutation_ready, timeout=5000):
        service.request_fetch(repository)
