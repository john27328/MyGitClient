from __future__ import annotations

import subprocess
from pathlib import Path

from pytestqt.qtbot import QtBot

from mygitclient.git.models import (
    AmendPreview,
    BranchesSnapshot,
    BranchInfo,
    BranchPointSnapshot,
    CherryPickPreviewSnapshot,
    CommitDiffSnapshot,
    CommitFilesSnapshot,
    CommitPage,
    CommitSummary,
    ConflictVersionsSnapshot,
    DiffSnapshot,
    FileStatus,
    MergePreviewSnapshot,
    RebasePreviewSnapshot,
    RebaseTodoItem,
    RefComparisonDiffSnapshot,
    RefComparisonSnapshot,
    RepositoryOperationSnapshot,
    RevertPreviewSnapshot,
    StashesSnapshot,
    TagsSnapshot,
)
from mygitclient.git.runner import GitRunner
from mygitclient.git.service import GitService, detect_repository_operation


def _git(repository: Path, *arguments: str) -> None:
    subprocess.run(
        ["git", *arguments], cwd=repository, check=True, capture_output=True
    )


def _configure_identity(repository: Path) -> None:
    _git(repository, "config", "user.name", "MyGitClient Test")
    _git(repository, "config", "user.email", "test@example.invalid")


def _summary(repository: Path, revision: str) -> CommitSummary:
    fields = subprocess.check_output(
        [
            "git",
            "show",
            "-s",
            "--format=%H%x00%P%x00%an%x00%ae%x00%aI%x00%s",
            revision,
        ],
        cwd=repository,
    ).decode("utf-8").rstrip("\n").split("\0")
    return CommitSummary(
        oid=fields[0],
        parent_oids=tuple(fields[1].split()),
        author_name=fields[2],
        author_email=fields[3],
        authored_at=fields[4],
        subject=fields[5],
    )


def test_completed_runner_is_released(qtbot: QtBot, tmp_path: Path) -> None:
    _git(tmp_path, "init", "--initial-branch=main")
    service = GitService()

    with qtbot.waitSignal(service.status_ready, timeout=5000):
        service.request_status(tmp_path)

    qtbot.waitUntil(lambda: not service.findChildren(GitRunner), timeout=5000)


def test_rebase_operation_progress_is_detected(tmp_path: Path) -> None:
    rebase = tmp_path / "rebase-merge"
    rebase.mkdir()
    (rebase / "msgnum").write_text("2\n", encoding="ascii")
    (rebase / "end").write_text("4\n", encoding="ascii")
    (rebase / "message").write_text("current subject\n\nbody\n", encoding="utf-8")
    (rebase / "git-rebase-todo").write_text(
        "pick abc next subject\nfixup def final subject\n", encoding="utf-8"
    )

    operation = detect_repository_operation(tmp_path)

    assert operation is not None
    assert operation.kind == "rebase"
    assert operation.current_step == 2
    assert operation.total_steps == 4
    assert operation.current_subject == "current subject"
    assert operation.remaining == ("next subject", "final subject")


def test_merge_preview_lists_incoming_commits_and_files(
    qtbot: QtBot, tmp_path: Path
) -> None:
    _git(tmp_path, "init", "--initial-branch=main")
    _configure_identity(tmp_path)
    base = tmp_path / "base.txt"
    base.write_text("base\n", encoding="utf-8")
    _git(tmp_path, "add", "base.txt")
    _git(tmp_path, "commit", "-m", "base")
    _git(tmp_path, "switch", "-c", "feature")
    incoming = tmp_path / "incoming.txt"
    incoming.write_text("incoming\n", encoding="utf-8")
    _git(tmp_path, "add", "incoming.txt")
    _git(tmp_path, "commit", "-m", "incoming change")
    feature_oid = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True
    ).strip()
    _git(tmp_path, "switch", "main")
    target = BranchInfo("refs/heads/feature", "feature", feature_oid, False)
    service = GitService()
    previews: list[object] = []
    service.merge_preview_ready.connect(previews.append)

    with qtbot.waitSignal(service.merge_preview_ready, timeout=5000):
        service.request_merge_preview(tmp_path, target)

    preview = previews[-1]
    assert isinstance(preview, MergePreviewSnapshot)
    assert [commit.subject for commit in preview.commits] == ["incoming change"]
    assert preview.files == ("incoming.txt",)

    with qtbot.waitSignal(service.mutation_ready, timeout=5000):
        service.request_merge(tmp_path, target, autostash=False)
    assert incoming.exists()


def test_merge_conflict_is_detected_and_can_be_aborted(
    qtbot: QtBot, tmp_path: Path
) -> None:
    _git(tmp_path, "init", "--initial-branch=main")
    _configure_identity(tmp_path)
    identity = (
        "-c",
        "user.name=MyGitClient Test",
        "-c",
        "user.email=test@example.invalid",
    )
    tracked = tmp_path / "tracked.txt"
    tracked.write_text("base\n", encoding="utf-8")
    _git(tmp_path, "add", "tracked.txt")
    _git(tmp_path, *identity, "commit", "-m", "base")
    _git(tmp_path, "switch", "-c", "feature")
    tracked.write_text("feature\n", encoding="utf-8")
    _git(tmp_path, "add", "tracked.txt")
    _git(tmp_path, *identity, "commit", "-m", "feature")
    _git(tmp_path, "switch", "main")
    tracked.write_text("main\n", encoding="utf-8")
    _git(tmp_path, "add", "tracked.txt")
    _git(tmp_path, *identity, "commit", "-m", "main")
    merge = subprocess.run(
        ["git", "merge", "feature"],
        cwd=tmp_path,
        check=False,
        capture_output=True,
    )
    assert merge.returncode != 0
    qtbot.waitUntil(
        lambda: (operation := detect_repository_operation(tmp_path / ".git"))
        is not None
        and operation.kind == "merge",
        timeout=5000,
    )
    service = GitService()
    snapshots: list[object] = []
    service.repository_operation_ready.connect(snapshots.append)

    with qtbot.waitSignal(service.repository_operation_ready, timeout=5000):
        service.request_repository_operation(tmp_path)

    snapshot = snapshots[-1]
    assert isinstance(snapshot, RepositoryOperationSnapshot)
    assert snapshot.operation is not None
    assert snapshot.operation.kind == "merge"

    conflict = FileStatus("tracked.txt", "U", "U", unmerged=True)
    versions: list[object] = []
    service.conflict_versions_ready.connect(versions.append)
    with qtbot.waitSignal(service.conflict_versions_ready, timeout=5000):
        service.request_conflict_versions(tmp_path, conflict)
    snapshot = versions[-1]
    assert isinstance(snapshot, ConflictVersionsSnapshot)
    assert snapshot.base == b"base\n"
    assert snapshot.current == b"main\n"
    assert snapshot.incoming == b"feature\n"
    assert dict(snapshot.attributes) == {
        "binary": "unspecified",
        "diff": "unspecified",
        "merge": "unspecified",
    }
    with qtbot.waitSignal(service.mutation_ready, timeout=5000):
        service.request_conflict_side(tmp_path, conflict, side="ours")
    assert tracked.read_text(encoding="utf-8") == "main\n"
    unresolved = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=U"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    assert unresolved.stdout == b""
    with qtbot.waitSignal(service.mutation_ready, timeout=5000):
        service.request_resolve_conflict(tmp_path, conflict, "resolved\n")
    assert tracked.read_text(encoding="utf-8") == "resolved\n"
    staged = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    assert staged.stdout.strip() == "tracked.txt"

    with qtbot.waitSignal(service.mutation_ready, timeout=5000):
        service.request_repository_operation_action(
            tmp_path, kind="merge", action="abort"
        )

    assert not (tmp_path / ".git" / "MERGE_HEAD").exists()
    assert tracked.read_text(encoding="utf-8") == "main\n"


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


def test_branch_point_is_loaded_with_merge_base(qtbot: QtBot, tmp_path: Path) -> None:
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
    fork_oid = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True
    ).strip()
    _git(tmp_path, "switch", "-c", "feature")
    tracked.write_text("feature\n", encoding="utf-8")
    _git(tmp_path, "add", "tracked.txt")
    _git(tmp_path, *identity, "commit", "-m", "feature")

    service = GitService()
    snapshots: list[object] = []
    service.branch_point_ready.connect(snapshots.append)
    with qtbot.waitSignal(service.branch_point_ready, timeout=5000):
        service.request_branch_point(
            tmp_path, "refs/heads/feature", "refs/heads/main"
        )

    assert len(snapshots) == 1
    snapshot = snapshots[0]
    assert isinstance(snapshot, BranchPointSnapshot)
    assert snapshot.commit_oid == fork_oid
    assert snapshot.base_ref == "refs/heads/main"


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


def test_diff_can_load_expanded_context(qtbot: QtBot, tmp_path: Path) -> None:
    _git(tmp_path, "init", "--initial-branch=main")
    tracked = tmp_path / "tracked.txt"
    lines = [f"line {number}\n" for number in range(60)]
    tracked.write_text("".join(lines), encoding="utf-8")
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
    lines[30] = "changed line\n"
    tracked.write_text("".join(lines), encoding="utf-8")
    service = GitService()
    results: list[object] = []
    service.diff_ready.connect(results.append)

    with qtbot.waitSignal(service.diff_ready, timeout=5000):
        service.request_diff(
            tmp_path,
            FileStatus("tracked.txt", ".", "M"),
            staged=False,
            context_lines=20,
        )

    result = results[0]
    assert isinstance(result, DiffSnapshot)
    rendered = "\n".join(line.text for line in result.diff.lines)
    assert "line 10" in rendered
    assert "line 50" in rendered


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


def test_remote_branch_can_be_deleted(qtbot: QtBot, tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    remote = tmp_path / "remote.git"
    repository.mkdir()
    _git(repository, "init", "--initial-branch=main")
    _git(remote.parent, "init", "--bare", str(remote))
    _git(repository, "remote", "add", "origin", str(remote))
    identity = (
        "-c",
        "user.name=MyGitClient Test",
        "-c",
        "user.email=test@example.invalid",
    )
    _git(repository, *identity, "commit", "--allow-empty", "-m", "initial")
    _git(repository, "branch", "feature")
    _git(repository, "push", "origin", "main", "feature")
    service = GitService()
    branch = BranchInfo(
        "refs/remotes/origin/feature", "origin/feature", "2" * 40, True
    )

    with qtbot.waitSignal(service.mutation_ready, timeout=5000):
        service.request_delete_remote_branch(repository, branch)

    result = subprocess.run(
        ["git", "--git-dir", str(remote), "show-ref", "--verify", "refs/heads/feature"],
        check=False,
        capture_output=True,
    )
    assert result.returncode != 0


def test_branch_can_be_created_from_selected_ref(qtbot: QtBot, tmp_path: Path) -> None:
    _git(tmp_path, "init", "--initial-branch=main")
    identity = (
        "-c",
        "user.name=MyGitClient Test",
        "-c",
        "user.email=test@example.invalid",
    )
    _git(tmp_path, *identity, "commit", "--allow-empty", "-m", "initial")
    _git(tmp_path, "switch", "-c", "source")
    _git(tmp_path, *identity, "commit", "--allow-empty", "-m", "source")
    _git(tmp_path, "switch", "main")
    source_oid = subprocess.check_output(
        ["git", "rev-parse", "source"], cwd=tmp_path, text=True
    ).strip()
    service = GitService()
    source = BranchInfo("refs/heads/source", "source", source_oid, False)

    with qtbot.waitSignal(service.mutation_ready, timeout=5000):
        service.request_create_branch_from(tmp_path, "new-from-source", source)

    assert (
        subprocess.check_output(["git", "branch", "--show-current"], cwd=tmp_path, text=True)
        .strip()
        == "new-from-source"
    )
    assert (
        subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True)
        .strip()
        == source_oid
    )


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


def test_cherry_pick_range_preview_and_autostash(
    qtbot: QtBot, tmp_path: Path
) -> None:
    _git(tmp_path, "init", "--initial-branch=main")
    _configure_identity(tmp_path)
    identity = (
        "-c",
        "user.name=MyGitClient Test",
        "-c",
        "user.email=test@example.invalid",
    )
    local = tmp_path / "local.txt"
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    local.write_text("base\n", encoding="utf-8")
    _git(tmp_path, "add", "local.txt")
    _git(tmp_path, *identity, "commit", "-m", "initial")
    _git(tmp_path, "switch", "-c", "feature")
    first.write_text("first\n", encoding="utf-8")
    _git(tmp_path, "add", "first.txt")
    _git(tmp_path, *identity, "commit", "-m", "first")
    first_commit = _summary(tmp_path, "HEAD")
    second.write_text("second\n", encoding="utf-8")
    _git(tmp_path, "add", "second.txt")
    _git(tmp_path, *identity, "commit", "-m", "second")
    second_commit = _summary(tmp_path, "HEAD")
    _git(tmp_path, "switch", "main")
    local.write_text("local change\n", encoding="utf-8")

    service = GitService()
    previews: list[object] = []
    service.cherry_pick_preview_ready.connect(previews.append)
    commits = (first_commit, second_commit)

    with qtbot.waitSignal(service.cherry_pick_preview_ready, timeout=5000):
        service.request_cherry_pick_preview(tmp_path, commits)

    preview = previews[-1]
    assert isinstance(preview, CherryPickPreviewSnapshot)
    assert preview.commits == commits
    assert preview.files == ("first.txt", "second.txt")

    with qtbot.waitSignal(service.mutation_ready, timeout=5000):
        service.request_cherry_pick(tmp_path, commits, autostash=True)

    qtbot.waitUntil(
        lambda: first.exists()
        and second.exists()
        and local.read_text(encoding="utf-8") == "local change\n",
        timeout=5000,
    )
    assert first.read_text(encoding="utf-8") == "first\n"
    assert second.read_text(encoding="utf-8") == "second\n"
    assert local.read_text(encoding="utf-8") == "local change\n"
    subjects = subprocess.check_output(
        ["git", "log", "-2", "--format=%s"], cwd=tmp_path, text=True
    ).splitlines()
    assert subjects == ["second", "first"]
    assert subprocess.check_output(
        ["git", "stash", "list"], cwd=tmp_path, text=True
    ).strip() == ""


def test_cherry_pick_conflict_exposes_recovery_and_can_be_aborted(
    qtbot: QtBot, tmp_path: Path
) -> None:
    _git(tmp_path, "init", "--initial-branch=main")
    identity = (
        "-c",
        "user.name=MyGitClient Test",
        "-c",
        "user.email=test@example.invalid",
    )
    tracked = tmp_path / "tracked.txt"
    tracked.write_text("base\n", encoding="utf-8")
    _git(tmp_path, "add", "tracked.txt")
    _git(tmp_path, *identity, "commit", "-m", "initial")
    _git(tmp_path, "switch", "-c", "feature")
    tracked.write_text("feature\n", encoding="utf-8")
    _git(tmp_path, "add", "tracked.txt")
    _git(tmp_path, *identity, "commit", "-m", "feature")
    feature_commit = _summary(tmp_path, "HEAD")
    _git(tmp_path, "switch", "main")
    tracked.write_text("main\n", encoding="utf-8")
    _git(tmp_path, "add", "tracked.txt")
    _git(tmp_path, *identity, "commit", "-m", "main")
    service = GitService()
    errors: list[str] = []
    service.operation_failed.connect(errors.append)

    with qtbot.waitSignal(service.operation_failed, timeout=5000):
        service.request_cherry_pick(
            tmp_path, (feature_commit,), autostash=False
        )

    assert errors
    assert (tmp_path / ".git" / "CHERRY_PICK_HEAD").exists()
    operation = detect_repository_operation(tmp_path / ".git")
    assert operation is not None
    assert operation.kind == "cherry-pick"

    with qtbot.waitSignal(service.mutation_ready, timeout=5000):
        service.request_repository_operation_action(
            tmp_path, kind="cherry-pick", action="abort"
        )

    assert not (tmp_path / ".git" / "CHERRY_PICK_HEAD").exists()
    assert tracked.read_text(encoding="utf-8") == "main\n"


def test_revert_range_preview_and_reverse_commits(
    qtbot: QtBot, tmp_path: Path
) -> None:
    _git(tmp_path, "init", "--initial-branch=main")
    _configure_identity(tmp_path)
    identity = (
        "-c",
        "user.name=MyGitClient Test",
        "-c",
        "user.email=test@example.invalid",
    )
    base = tmp_path / "base.txt"
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    base.write_text("base\n", encoding="utf-8")
    _git(tmp_path, "add", "base.txt")
    _git(tmp_path, *identity, "commit", "-m", "initial")
    first.write_text("first\n", encoding="utf-8")
    _git(tmp_path, "add", "first.txt")
    _git(tmp_path, *identity, "commit", "-m", "first")
    first_commit = _summary(tmp_path, "HEAD")
    second.write_text("second\n", encoding="utf-8")
    _git(tmp_path, "add", "second.txt")
    _git(tmp_path, *identity, "commit", "-m", "second")
    second_commit = _summary(tmp_path, "HEAD")
    commits = (second_commit, first_commit)
    service = GitService()
    previews: list[object] = []
    service.revert_preview_ready.connect(previews.append)

    with qtbot.waitSignal(service.revert_preview_ready, timeout=5000):
        service.request_revert_preview(tmp_path, commits)

    preview = previews[-1]
    assert isinstance(preview, RevertPreviewSnapshot)
    assert preview.commits == commits
    assert preview.files == ("first.txt", "second.txt")
    assert "+first" in preview.diff.text
    assert "+second" in preview.diff.text

    with qtbot.waitSignal(service.mutation_ready, timeout=5000):
        service.request_revert(tmp_path, commits)

    qtbot.waitUntil(
        lambda: not first.exists() and not second.exists(),
        timeout=5000,
    )
    assert not first.exists()
    assert not second.exists()
    subjects = subprocess.check_output(
        ["git", "log", "-2", "--format=%s"], cwd=tmp_path, text=True
    ).splitlines()
    assert subjects == ['Revert "first"', 'Revert "second"']


def test_rebase_preview_and_autostash_replays_current_branch(
    qtbot: QtBot, tmp_path: Path
) -> None:
    _git(tmp_path, "init", "--initial-branch=main")
    _configure_identity(tmp_path)
    identity = (
        "-c",
        "user.name=MyGitClient Test",
        "-c",
        "user.email=test@example.invalid",
    )
    base = tmp_path / "base.txt"
    local = tmp_path / "local.txt"
    feature_file = tmp_path / "feature.txt"
    upstream_file = tmp_path / "upstream.txt"
    base.write_text("base\n", encoding="utf-8")
    local.write_text("base\n", encoding="utf-8")
    _git(tmp_path, "add", "base.txt", "local.txt")
    _git(tmp_path, *identity, "commit", "-m", "initial")
    base_oid = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True
    ).strip()
    _git(tmp_path, "switch", "-c", "feature")
    feature_file.write_text("feature\n", encoding="utf-8")
    _git(tmp_path, "add", "feature.txt")
    _git(tmp_path, *identity, "commit", "-m", "feature")
    _git(tmp_path, "switch", "main")
    upstream_file.write_text("upstream\n", encoding="utf-8")
    _git(tmp_path, "add", "upstream.txt")
    _git(tmp_path, *identity, "commit", "-m", "upstream")
    main_oid = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True
    ).strip()
    _git(tmp_path, "switch", "feature")
    local.write_text("local change\n", encoding="utf-8")
    target = BranchInfo("refs/heads/main", "main", main_oid, False)
    service = GitService()
    previews: list[object] = []
    service.rebase_preview_ready.connect(previews.append)

    with qtbot.waitSignal(service.rebase_preview_ready, timeout=5000):
        service.request_rebase_preview(tmp_path, target)

    preview = previews[-1]
    assert isinstance(preview, RebasePreviewSnapshot)
    assert preview.target == target
    assert preview.base_oid == base_oid
    assert [commit.subject for commit in preview.commits] == ["feature"]
    assert preview.files == ("feature.txt",)
    assert preview.head_oid == subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True
    ).strip()

    with qtbot.waitSignal(service.mutation_ready, timeout=5000):
        service.request_rebase(tmp_path, target, autostash=True)

    qtbot.waitUntil(
        lambda: local.read_text(encoding="utf-8") == "local change\n"
        and feature_file.exists()
        and upstream_file.exists(),
        timeout=5000,
    )
    assert local.read_text(encoding="utf-8") == "local change\n"
    assert feature_file.read_text(encoding="utf-8") == "feature\n"
    assert upstream_file.read_text(encoding="utf-8") == "upstream\n"
    assert subprocess.check_output(
        ["git", "merge-base", "HEAD", "main"], cwd=tmp_path, text=True
    ).strip() == main_oid
    assert subprocess.check_output(
        ["git", "stash", "list"], cwd=tmp_path, text=True
    ).strip() == ""


def test_interactive_rebase_reorders_and_rewords_commits(
    qtbot: QtBot, tmp_path: Path
) -> None:
    _git(tmp_path, "init", "--initial-branch=main")
    _configure_identity(tmp_path)
    tracked = tmp_path / "tracked.txt"
    tracked.write_text("base\n", encoding="utf-8")
    _git(tmp_path, "add", "tracked.txt")
    _git(tmp_path, "commit", "-m", "base")
    base_oid = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True
    ).strip()
    _git(tmp_path, "switch", "-c", "feature")
    first = tmp_path / "first.txt"
    first.write_text("first\n", encoding="utf-8")
    _git(tmp_path, "add", "first.txt")
    _git(tmp_path, "commit", "-m", "first")
    first_oid = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True
    ).strip()
    second = tmp_path / "second.txt"
    second.write_text("second\n", encoding="utf-8")
    _git(tmp_path, "add", "second.txt")
    _git(tmp_path, "commit", "-m", "second")
    second_oid = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True
    ).strip()
    target = BranchInfo("refs/heads/main", "main", base_oid, False)
    service = GitService()

    with qtbot.waitSignal(service.mutation_ready, timeout=10000):
        service.request_interactive_rebase(
            tmp_path,
            target,
            base_oid,
            (
                RebaseTodoItem("pick", second_oid, "second"),
                RebaseTodoItem("reword", first_oid, "renamed first"),
            ),
            autostash=False,
        )

    subjects = subprocess.check_output(
        ["git", "log", "-2", "--format=%s"], cwd=tmp_path, text=True
    ).splitlines()
    assert subjects == [
        "renamed first",
        "second",
    ]
    assert not (tmp_path / ".git" / "mygitclient-rebase-state").exists()


def test_rebase_conflict_can_be_staged_and_continued(
    qtbot: QtBot, tmp_path: Path
) -> None:
    _git(tmp_path, "init", "--initial-branch=main")
    _configure_identity(tmp_path)
    identity = (
        "-c",
        "user.name=MyGitClient Test",
        "-c",
        "user.email=test@example.invalid",
    )
    shared = tmp_path / "shared.txt"
    shared.write_text("base\n", encoding="utf-8")
    _git(tmp_path, "add", "shared.txt")
    _git(tmp_path, *identity, "commit", "-m", "base")
    _git(tmp_path, "switch", "-c", "feature")
    shared.write_text("feature\n", encoding="utf-8")
    _git(tmp_path, "add", "shared.txt")
    _git(tmp_path, *identity, "commit", "-m", "feature")
    _git(tmp_path, "switch", "main")
    shared.write_text("main\n", encoding="utf-8")
    _git(tmp_path, "add", "shared.txt")
    _git(tmp_path, *identity, "commit", "-m", "main")
    main_oid = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True
    ).strip()
    _git(tmp_path, "switch", "feature")
    service = GitService()
    target = BranchInfo("refs/heads/main", "main", main_oid, False)

    with qtbot.waitSignal(service.operation_failed, timeout=5000):
        service.request_rebase(tmp_path, target, autostash=False)

    operation = detect_repository_operation(tmp_path / ".git")
    assert operation is not None and operation.kind == "rebase"
    shared.write_text("resolved\n", encoding="utf-8")
    with qtbot.waitSignal(service.mutation_ready, timeout=5000):
        service.request_stage(
            tmp_path,
            FileStatus("shared.txt", "U", "U", unmerged=True),
            staged=True,
        )
    qtbot.waitUntil(
        lambda: subprocess.check_output(
            ["git", "diff", "--cached", "--name-only"],
            cwd=tmp_path,
            text=True,
        ).strip()
        == "shared.txt",
        timeout=5000,
    )
    with qtbot.waitSignal(service.mutation_ready, timeout=5000):
        service.request_repository_operation_action(
            tmp_path,
            kind="rebase",
            action="continue",
        )

    assert detect_repository_operation(tmp_path / ".git") is None
    assert shared.read_text(encoding="utf-8") == "resolved\n"
    assert subprocess.check_output(
        ["git", "merge-base", "HEAD", "main"], cwd=tmp_path, text=True
    ).strip() == main_oid


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


def test_discard_files_batches_tracked_and_untracked_changes(
    qtbot: QtBot, tmp_path: Path
) -> None:
    _git(tmp_path, "init", "--initial-branch=main")
    tracked = tmp_path / "tracked.txt"
    untracked = tmp_path / "untracked.txt"
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
    untracked.write_text("temporary\n", encoding="utf-8")
    service = GitService()
    mutations: list[str] = []
    errors: list[str] = []
    service.mutation_ready.connect(mutations.append)
    service.operation_failed.connect(errors.append)

    with qtbot.waitSignal(service.mutation_ready, timeout=5000):
        service.request_discard_files(
            tmp_path,
            (
                FileStatus("tracked.txt", ".", "M"),
                FileStatus("untracked.txt", "?", "?"),
            ),
        )

    assert mutations == ["discard"]
    assert not errors
    assert tracked.read_text(encoding="utf-8") == "before\n"
    assert not untracked.exists()


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
