from __future__ import annotations

from dataclasses import dataclass
from itertools import count
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from mygitclient.git.errors import format_git_error
from mygitclient.git.models import (
    AmendDiffSnapshot,
    AmendPreview,
    BranchInfo,
    BranchPointSnapshot,
    CherryPickPreviewSnapshot,
    CommitDiffSnapshot,
    CommitFilesSnapshot,
    CommitPage,
    CommitSummary,
    DiffSnapshot,
    FileStatus,
    GitCommand,
    GitResult,
    RebasePreviewSnapshot,
    RefComparisonDiffSnapshot,
    RefComparisonSnapshot,
    RepositoryOperation,
    RepositoryOperationSnapshot,
    RepositoryStatusSnapshot,
    RevertPreviewSnapshot,
    StashesSnapshot,
    StashInfo,
    TagsSnapshot,
    UnifiedDiff,
)
from mygitclient.git.operation_queue import GitOperationQueue
from mygitclient.git.parsers import (
    diff_paths,
    parse_amend_preview,
    parse_branches,
    parse_commit_files,
    parse_commit_log,
    parse_stashes,
    parse_status_porcelain_v2,
    parse_tags,
    parse_unified_diff,
)
from mygitclient.git.runner import GitRunner


@dataclass(slots=True)
class _CheckoutWorkflow:
    repository: Path
    branch: BranchInfo
    step: str
    stashed: bool = False
    pending_error: str | None = None


@dataclass(slots=True)
class _CherryPickWorkflow:
    repository: Path
    commits: tuple[CommitSummary, ...]
    step: str
    stashed: bool = False


@dataclass(slots=True)
class _RevertWorkflow:
    repository: Path
    commits: tuple[CommitSummary, ...]


@dataclass(slots=True)
class _RebasePreviewWorkflow:
    repository: Path
    target: BranchInfo
    request_id: int
    step: str = "base"
    base_oid: str = ""
    commits: tuple[CommitSummary, ...] = ()


class GitService(QObject):
    amend_diff_ready = Signal(object)
    amend_preview_ready = Signal(object)
    history_ready = Signal(object)
    branches_ready = Signal(object)
    branch_point_ready = Signal(object)
    cherry_pick_preview_ready = Signal(object)
    commit_files_ready = Signal(object)
    commit_diff_ready = Signal(object)
    comparison_ready = Signal(object)
    comparison_diff_ready = Signal(object)
    status_ready = Signal(object)
    repository_operation_ready = Signal(object)
    revert_preview_ready = Signal(object)
    rebase_preview_ready = Signal(object)
    diff_ready = Signal(object)
    mutation_ready = Signal(str)
    operation_cancelled = Signal()
    operation_failed = Signal(str)
    queue_changed = Signal(object)
    tags_ready = Signal(object)
    stashes_ready = Signal(object)

    _EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._runners: set[GitRunner] = set()
        self._request_ids = count(1)
        self._status_requests: dict[GitRunner, tuple[Path, int]] = {}
        self._latest_status_request: dict[Path, int] = {}
        self._operation_state_requests: dict[GitRunner, tuple[Path, int]] = {}
        self._latest_operation_state_request: dict[Path, int] = {}
        self._diff_requests: dict[GitRunner, tuple[Path, str, bool, bool, int]] = {}
        self._latest_diff_request: dict[tuple[Path, str, bool], int] = {}
        self._mutation_requests: dict[GitRunner, str] = {}
        self._history_requests: dict[GitRunner, tuple[Path, int, int, int]] = {}
        self._latest_history_request: dict[Path, int] = {}
        self._branch_requests: dict[GitRunner, tuple[Path, int]] = {}
        self._latest_branch_request: dict[Path, int] = {}
        self._branch_point_requests: dict[GitRunner, tuple[Path, str, str, int]] = {}
        self._latest_branch_point_request: dict[Path, int] = {}
        self._tag_requests: dict[GitRunner, tuple[Path, int]] = {}
        self._latest_tag_request: dict[Path, int] = {}
        self._stash_requests: dict[GitRunner, tuple[Path, int]] = {}
        self._latest_stash_request: dict[Path, int] = {}
        self._commit_files_requests: dict[GitRunner, tuple[Path, str, int]] = {}
        self._latest_commit_files_request: dict[Path, int] = {}
        self._commit_diff_requests: dict[GitRunner, tuple[Path, str, str, int]] = {}
        self._latest_commit_diff_request: dict[Path, int] = {}
        self._comparison_requests: dict[GitRunner, tuple[Path, str, str, int]] = {}
        self._latest_comparison_request: dict[Path, int] = {}
        self._comparison_diff_requests: dict[
            GitRunner, tuple[Path, str, str, str, int]
        ] = {}
        self._latest_comparison_diff_request: dict[Path, int] = {}
        self._amend_preview_requests: dict[GitRunner, tuple[Path, str, int]] = {}
        self._latest_amend_preview_request: dict[Path, int] = {}
        self._amend_diff_requests: dict[
            GitRunner, tuple[Path, str, str | None, int]
        ] = {}
        self._latest_amend_diff_request: dict[tuple[Path, str | None], int] = {}
        self._checkout_workflows: dict[GitRunner, _CheckoutWorkflow] = {}
        self._cherry_pick_preview_requests: dict[
            GitRunner, tuple[Path, tuple[CommitSummary, ...], int]
        ] = {}
        self._latest_cherry_pick_preview_request: dict[Path, int] = {}
        self._cherry_pick_workflows: dict[GitRunner, _CherryPickWorkflow] = {}
        self._pending_cherry_pick_autostash: set[Path] = set()
        self._revert_preview_requests: dict[
            GitRunner, tuple[Path, tuple[CommitSummary, ...], int]
        ] = {}
        self._latest_revert_preview_request: dict[Path, int] = {}
        self._revert_workflows: dict[GitRunner, _RevertWorkflow] = {}
        self._rebase_preview_workflows: dict[GitRunner, _RebasePreviewWorkflow] = {}
        self._latest_rebase_preview_request: dict[Path, int] = {}
        self._rebase_requests: dict[GitRunner, tuple[Path, BranchInfo]] = {}
        self._operation_action_requests: dict[GitRunner, tuple[Path, str, str]] = {}
        self._operation_queue = GitOperationQueue(self)
        self._operation_queue.changed.connect(self.queue_changed)

    def request_branches(self, repository: Path) -> GitRunner:
        runner = GitRunner(parent=self)
        self._runners.add(runner)
        request_id = next(self._request_ids)
        self._latest_branch_request[repository] = request_id
        self._branch_requests[runner] = (repository, request_id)
        runner.completed.connect(self._handle_branches)
        runner.failed_to_start.connect(self._handle_start_error)
        runner.run(
            GitCommand(
                (
                    "for-each-ref",
                    "--sort=refname",
                    "--format=%(refname)%00%(refname:short)%00%(objectname)%00"
                    "%(upstream:short)%00%(upstream:track)%00%(HEAD)%1e",
                    "refs/heads",
                    "refs/remotes",
                ),
                repository,
                "read branches",
            )
        )
        return runner

    def request_tags(self, repository: Path) -> GitRunner:
        runner = GitRunner(parent=self)
        self._runners.add(runner)
        request_id = next(self._request_ids)
        self._latest_tag_request[repository] = request_id
        self._tag_requests[runner] = (repository, request_id)
        runner.completed.connect(self._handle_tags)
        runner.failed_to_start.connect(self._handle_start_error)
        runner.run(
            GitCommand(
                (
                    "for-each-ref",
                    "--sort=-creatordate",
                    "--format=%(refname:short)%00%(objectname)%00%(objecttype)%00"
                    "%(*objectname)%00%(subject)%1e",
                    "refs/tags",
                ),
                repository,
                "read tags",
            )
        )
        return runner

    def request_branch_point(
        self, repository: Path, branch_ref: str, base_ref: str
    ) -> GitRunner:
        runner = GitRunner(parent=self)
        self._runners.add(runner)
        request_id = next(self._request_ids)
        self._latest_branch_point_request[repository] = request_id
        self._branch_point_requests[runner] = (
            repository,
            branch_ref,
            base_ref,
            request_id,
        )
        runner.completed.connect(self._handle_branch_point)
        runner.failed_to_start.connect(self._handle_start_error)
        runner.run(
            GitCommand(
                ("merge-base", branch_ref, base_ref),
                repository,
                "find branch point",
            )
        )
        return runner

    def request_stashes(self, repository: Path) -> GitRunner:
        runner = GitRunner(parent=self)
        self._runners.add(runner)
        request_id = next(self._request_ids)
        self._latest_stash_request[repository] = request_id
        self._stash_requests[runner] = (repository, request_id)
        runner.completed.connect(self._handle_stashes)
        runner.failed_to_start.connect(self._handle_start_error)
        runner.run(
            GitCommand(
                (
                    "stash",
                    "list",
                    "--format=%gd%x00%H%x00%gs%x1e",
                ),
                repository,
                "read stashes",
            )
        )
        return runner

    def request_stash_action(
        self, repository: Path, stash: StashInfo, *, action: str
    ) -> GitRunner:
        if action not in {"apply", "pop", "drop"}:
            raise ValueError(f"Unsupported stash action: {action}")
        runner = GitRunner(parent=self)
        self._runners.add(runner)
        self._mutation_requests[runner] = "stashes:changed"
        runner.completed.connect(self._handle_mutation)
        runner.failed_to_start.connect(self._handle_start_error)
        self._operation_queue.enqueue(
            runner,
            GitCommand(
                ("stash", action, stash.ref),
                repository,
                f"{action} stash",
            ),
        )
        return runner

    def request_create_tag(
        self, repository: Path, name: str, target: str, message: str = ""
    ) -> GitRunner:
        arguments = (
            ("tag", "-a", name, target, "-m", message)
            if message
            else ("tag", name, target)
        )
        return self._request_simple_mutation(
            repository, arguments, "tags:changed", "create tag"
        )

    def request_delete_tag(self, repository: Path, name: str) -> GitRunner:
        return self._request_simple_mutation(
            repository, ("tag", "-d", name), "tags:changed", "delete tag"
        )

    def request_push_tag(self, repository: Path, name: str) -> GitRunner:
        return self._request_simple_mutation(
            repository,
            ("push", "--progress", "origin", f"refs/tags/{name}"),
            "tags:changed",
            "push tag",
        )

    def _request_simple_mutation(
        self,
        repository: Path,
        arguments: tuple[str, ...],
        result: str,
        operation: str,
    ) -> GitRunner:
        runner = GitRunner(parent=self)
        self._runners.add(runner)
        self._mutation_requests[runner] = result
        runner.completed.connect(self._handle_mutation)
        runner.failed_to_start.connect(self._handle_start_error)
        self._operation_queue.enqueue(runner, GitCommand(arguments, repository, operation))
        return runner

    def request_checkout(
        self, repository: Path, branch: BranchInfo, *, autostash: bool = False
    ) -> GitRunner:
        if autostash:
            workflow = _CheckoutWorkflow(repository, branch, "stash")
            return self._run_checkout_workflow(
                workflow,
                (
                    "stash",
                    "push",
                    "-u",
                    "-m",
                    f"MyGitClient automatic stash before checkout {branch.name}",
                ),
                "stash changes before checkout",
            )
        arguments = (
            ("switch", "--track", branch.name)
            if branch.remote
            else ("switch", branch.name)
        )
        runner = GitRunner(parent=self)
        self._runners.add(runner)
        self._mutation_requests[runner] = f"branch:{branch.name}"
        runner.completed.connect(self._handle_mutation)
        runner.failed_to_start.connect(self._handle_start_error)
        self._operation_queue.enqueue(
            runner, GitCommand(arguments, repository, "checkout branch")
        )
        return runner

    def _run_checkout_workflow(
        self,
        workflow: _CheckoutWorkflow,
        arguments: tuple[str, ...],
        operation: str,
    ) -> GitRunner:
        runner = GitRunner(parent=self)
        self._runners.add(runner)
        self._checkout_workflows[runner] = workflow
        runner.completed.connect(self._handle_checkout_workflow)
        runner.failed_to_start.connect(self._handle_start_error)
        self._operation_queue.enqueue(
            runner,
            GitCommand(arguments, workflow.repository, operation),
            continuation=workflow.step != "stash",
        )
        return runner

    def request_create_branch(self, repository: Path, name: str) -> GitRunner:
        runner = GitRunner(parent=self)
        self._runners.add(runner)
        self._mutation_requests[runner] = f"branch:{name}"
        runner.completed.connect(self._handle_mutation)
        runner.failed_to_start.connect(self._handle_start_error)
        self._operation_queue.enqueue(
            runner, GitCommand(("switch", "-c", name), repository, "create branch")
        )
        return runner

    def request_rename_branch(
        self, repository: Path, branch: BranchInfo, new_name: str
    ) -> GitRunner:
        runner = GitRunner(parent=self)
        self._runners.add(runner)
        self._mutation_requests[runner] = "branches:renamed"
        runner.completed.connect(self._handle_mutation)
        runner.failed_to_start.connect(self._handle_start_error)
        self._operation_queue.enqueue(
            runner,
            GitCommand(("branch", "-m", branch.name, new_name), repository, "rename branch")
        )
        return runner

    def request_delete_branch(
        self, repository: Path, branch: BranchInfo, *, force: bool = False
    ) -> GitRunner:
        runner = GitRunner(parent=self)
        self._runners.add(runner)
        self._mutation_requests[runner] = "branches:deleted"
        runner.completed.connect(self._handle_mutation)
        runner.failed_to_start.connect(self._handle_start_error)
        flag = "-D" if force else "-d"
        self._operation_queue.enqueue(
            runner,
            GitCommand(("branch", flag, branch.name), repository, "delete branch"),
        )
        return runner

    def request_pull(
        self, repository: Path, *, rebase: bool, autostash: bool
    ) -> GitRunner:
        arguments = ["pull", "--progress", "--rebase" if rebase else "--no-rebase"]
        if autostash:
            arguments.append("--autostash")
        runner = GitRunner(parent=self)
        self._runners.add(runner)
        self._mutation_requests[runner] = "pull"
        runner.completed.connect(self._handle_mutation)
        runner.failed_to_start.connect(self._handle_start_error)
        self._operation_queue.enqueue(
            runner, GitCommand(tuple(arguments), repository, "pull changes")
        )
        return runner

    def request_fetch(self, repository: Path) -> GitRunner:
        runner = GitRunner(parent=self)
        self._runners.add(runner)
        self._mutation_requests[runner] = "fetch"
        runner.completed.connect(self._handle_mutation)
        runner.failed_to_start.connect(self._handle_start_error)
        self._operation_queue.enqueue(
            runner,
            GitCommand(("fetch", "--progress", "--prune"), repository, "fetch changes"),
        )
        return runner

    def request_push(
        self,
        repository: Path,
        *,
        branch: str,
        set_upstream: bool,
        force_with_lease: bool = False,
    ) -> GitRunner:
        arguments = ["push", "--progress"]
        if force_with_lease:
            arguments.append("--force-with-lease")
        if set_upstream:
            arguments.extend(("--set-upstream", "origin", branch))
        runner = GitRunner(parent=self)
        self._runners.add(runner)
        self._mutation_requests[runner] = "push"
        runner.completed.connect(self._handle_mutation)
        runner.failed_to_start.connect(self._handle_start_error)
        self._operation_queue.enqueue(
            runner, GitCommand(tuple(arguments), repository, "push changes")
        )
        return runner

    def request_commit_files(self, repository: Path, commit_oid: str) -> GitRunner:
        runner = GitRunner(parent=self)
        self._runners.add(runner)
        request_id = next(self._request_ids)
        self._latest_commit_files_request[repository] = request_id
        self._commit_files_requests[runner] = (repository, commit_oid, request_id)
        runner.completed.connect(self._handle_commit_files)
        runner.failed_to_start.connect(self._handle_start_error)
        runner.run(
            GitCommand(
                (
                    "diff-tree",
                    "--root",
                    "--no-commit-id",
                    "--name-status",
                    "--find-renames",
                    "-r",
                    "-z",
                    commit_oid,
                ),
                repository,
                "read commit files",
            )
        )
        return runner

    def request_cherry_pick_preview(
        self, repository: Path, commits: tuple[CommitSummary, ...]
    ) -> GitRunner:
        if not commits:
            raise ValueError("At least one commit is required")
        runner = GitRunner(parent=self)
        self._runners.add(runner)
        request_id = next(self._request_ids)
        self._latest_cherry_pick_preview_request[repository] = request_id
        self._cherry_pick_preview_requests[runner] = (
            repository,
            commits,
            request_id,
        )
        runner.completed.connect(self._handle_cherry_pick_preview)
        runner.failed_to_start.connect(self._handle_start_error)
        runner.run(
            GitCommand(
                (
                    "show",
                    "--format=",
                    "--name-only",
                    "--find-renames",
                    "-z",
                    *(commit.oid for commit in commits),
                ),
                repository,
                "preview cherry-pick",
            )
        )
        return runner

    def request_cherry_pick(
        self,
        repository: Path,
        commits: tuple[CommitSummary, ...],
        *,
        autostash: bool,
    ) -> GitRunner:
        if not commits:
            raise ValueError("At least one commit is required")
        if any(len(commit.parent_oids) > 1 for commit in commits):
            raise ValueError("Merge commits require an explicit mainline parent")
        workflow = _CherryPickWorkflow(
            repository,
            commits,
            "stash" if autostash else "cherry-pick",
        )
        if autostash:
            return self._run_cherry_pick_workflow(
                workflow,
                (
                    "stash",
                    "push",
                    "-u",
                    "-m",
                    "MyGitClient automatic stash before cherry-pick",
                ),
                "stash changes before cherry-pick",
            )
        return self._run_cherry_pick_workflow(
            workflow,
            ("cherry-pick", "--", *(commit.oid for commit in commits)),
            "cherry-pick commits",
        )

    def _run_cherry_pick_workflow(
        self,
        workflow: _CherryPickWorkflow,
        arguments: tuple[str, ...],
        operation: str,
    ) -> GitRunner:
        runner = GitRunner(parent=self)
        self._runners.add(runner)
        self._cherry_pick_workflows[runner] = workflow
        runner.completed.connect(self._handle_cherry_pick_workflow)
        runner.failed_to_start.connect(self._handle_start_error)
        self._operation_queue.enqueue(
            runner,
            GitCommand(arguments, workflow.repository, operation),
            continuation=workflow.step != "stash",
        )
        return runner

    def request_revert_preview(
        self, repository: Path, commits: tuple[CommitSummary, ...]
    ) -> GitRunner:
        if not commits:
            raise ValueError("At least one commit is required")
        if any(len(commit.parent_oids) > 1 for commit in commits):
            raise ValueError("Merge commits require an explicit mainline parent")
        runner = GitRunner(parent=self)
        self._runners.add(runner)
        request_id = next(self._request_ids)
        self._latest_revert_preview_request[repository] = request_id
        self._revert_preview_requests[runner] = (repository, commits, request_id)
        runner.completed.connect(self._handle_revert_preview)
        runner.failed_to_start.connect(self._handle_start_error)
        runner.run(
            GitCommand(
                (
                    "show",
                    "--format=",
                    "--no-color",
                    "--find-renames",
                    *(commit.oid for commit in commits),
                ),
                repository,
                "preview revert",
            )
        )
        return runner

    def request_revert(
        self, repository: Path, commits: tuple[CommitSummary, ...]
    ) -> GitRunner:
        if not commits:
            raise ValueError("At least one commit is required")
        if any(len(commit.parent_oids) > 1 for commit in commits):
            raise ValueError("Merge commits require an explicit mainline parent")
        runner = GitRunner(parent=self)
        self._runners.add(runner)
        self._revert_workflows[runner] = _RevertWorkflow(repository, commits)
        runner.completed.connect(self._handle_revert_workflow)
        runner.failed_to_start.connect(self._handle_start_error)
        self._operation_queue.enqueue(
            runner,
            GitCommand(
                ("revert", "--no-edit", "--", *(commit.oid for commit in commits)),
                repository,
                "revert commits",
            ),
        )
        return runner

    def request_rebase_preview(
        self, repository: Path, target: BranchInfo
    ) -> GitRunner:
        if target.current:
            raise ValueError("Cannot rebase a branch onto itself")
        request_id = next(self._request_ids)
        self._latest_rebase_preview_request[repository] = request_id
        workflow = _RebasePreviewWorkflow(repository, target, request_id)
        return self._run_rebase_preview(
            workflow,
            ("merge-base", "HEAD", target.full_name),
            "find rebase base",
        )

    def _run_rebase_preview(
        self,
        workflow: _RebasePreviewWorkflow,
        arguments: tuple[str, ...],
        operation: str,
    ) -> GitRunner:
        runner = GitRunner(parent=self)
        self._runners.add(runner)
        self._rebase_preview_workflows[runner] = workflow
        runner.completed.connect(self._handle_rebase_preview)
        runner.failed_to_start.connect(self._handle_start_error)
        runner.run(GitCommand(arguments, workflow.repository, operation))
        return runner

    def request_rebase(
        self, repository: Path, target: BranchInfo, *, autostash: bool
    ) -> GitRunner:
        if target.current:
            raise ValueError("Cannot rebase a branch onto itself")
        arguments = ["rebase"]
        if autostash:
            arguments.append("--autostash")
        arguments.append(target.full_name)
        runner = GitRunner(parent=self)
        self._runners.add(runner)
        self._rebase_requests[runner] = (repository, target)
        runner.completed.connect(self._handle_rebase)
        runner.failed_to_start.connect(self._handle_start_error)
        self._operation_queue.enqueue(
            runner,
            GitCommand(tuple(arguments), repository, f"rebase onto {target.name}"),
        )
        return runner

    def request_amend_preview(self, repository: Path, commit_oid: str) -> GitRunner:
        runner = GitRunner(parent=self)
        self._runners.add(runner)
        request_id = next(self._request_ids)
        self._latest_amend_preview_request[repository] = request_id
        self._amend_preview_requests[runner] = (repository, commit_oid, request_id)
        runner.completed.connect(self._handle_amend_preview)
        runner.failed_to_start.connect(self._handle_start_error)
        runner.run(
            GitCommand(
                (
                    "show",
                    "--format=%B%x00%P%x00",
                    "--root",
                    "--no-ext-diff",
                    "--no-color",
                    commit_oid,
                ),
                repository,
                "read amend preview",
            )
        )
        return runner

    def request_amend_diff(
        self,
        repository: Path,
        commit_oid: str,
        *,
        parent_oid: str | None,
        path: str | None = None,
    ) -> GitRunner:
        runner = GitRunner(parent=self)
        self._runners.add(runner)
        request_id = next(self._request_ids)
        key = (repository, path)
        self._latest_amend_diff_request[key] = request_id
        self._amend_diff_requests[runner] = (repository, commit_oid, path, request_id)
        runner.completed.connect(self._handle_amend_diff)
        runner.failed_to_start.connect(self._handle_start_error)
        arguments = [
            "diff",
            "--cached",
            "--no-ext-diff",
            "--no-color",
            parent_oid or self._EMPTY_TREE,
        ]
        if path is not None:
            arguments.extend(("--", path))
        runner.run(
            GitCommand(
                tuple(arguments),
                repository,
                "read amended commit diff",
            )
        )
        return runner

    def request_amend_file(
        self,
        repository: Path,
        commit_oid: str,
        parent_oid: str | None,
        path: str,
        *,
        included: bool,
    ) -> GitRunner:
        if included:
            arguments = ("add", "-A", "--", path)
            operation = "include file in amended commit"
        else:
            arguments = ("reset", "-q", parent_oid or self._EMPTY_TREE, "--", path)
            operation = "exclude file from amended commit"
        runner = GitRunner(parent=self)
        self._runners.add(runner)
        self._mutation_requests[runner] = path
        runner.completed.connect(self._handle_mutation)
        runner.failed_to_start.connect(self._handle_start_error)
        self._operation_queue.enqueue(runner, GitCommand(arguments, repository, operation))
        return runner

    def request_commit_diff(
        self,
        repository: Path,
        commit_oid: str,
        path: str,
        *,
        parent_oid: str | None,
        ignore_whitespace: bool = False,
    ) -> GitRunner:
        runner = GitRunner(parent=self)
        self._runners.add(runner)
        request_id = next(self._request_ids)
        self._latest_commit_diff_request[repository] = request_id
        self._commit_diff_requests[runner] = (repository, commit_oid, path, request_id)
        runner.completed.connect(self._handle_commit_diff)
        runner.failed_to_start.connect(self._handle_start_error)
        arguments = list(
            ("diff", "--no-ext-diff", "--no-color", parent_oid, commit_oid, "--", path)
            if parent_oid is not None
            else (
                "show",
                "--format=",
                "--root",
                "--no-ext-diff",
                "--no-color",
                commit_oid,
                "--",
                path,
            )
        )
        if ignore_whitespace:
            arguments.insert(1, "--ignore-all-space")
        runner.run(GitCommand(tuple(arguments), repository, "read commit diff"))
        return runner

    def request_history(
        self,
        repository: Path,
        *,
        offset: int = 0,
        limit: int = 100,
        refs: tuple[str, ...] = (),
    ) -> GitRunner:
        runner = GitRunner(parent=self)
        self._runners.add(runner)
        request_id = next(self._request_ids)
        self._latest_history_request[repository] = request_id
        self._history_requests[runner] = (repository, offset, limit, request_id)
        runner.completed.connect(self._handle_history)
        runner.failed_to_start.connect(self._handle_start_error)
        revisions = refs or ("--branches", "--remotes", "--tags")
        arguments = (
            "log",
            f"--skip={offset}",
            f"--max-count={limit + 1}",
            "--date=iso-strict",
            "--pretty=format:%x1e%H%x00%P%x00%an%x00%ae%x00%aI%x00%s",
            *revisions,
        )
        runner.run(GitCommand(arguments, repository, "read commit history"))
        return runner

    def request_ref_comparison(
        self, repository: Path, base_ref: str, compare_ref: str
    ) -> GitRunner:
        runner = GitRunner(parent=self)
        self._runners.add(runner)
        request_id = next(self._request_ids)
        self._latest_comparison_request[repository] = request_id
        self._comparison_requests[runner] = (
            repository,
            base_ref,
            compare_ref,
            request_id,
        )
        runner.completed.connect(self._handle_ref_comparison)
        runner.failed_to_start.connect(self._handle_start_error)
        runner.run(
            GitCommand(
                (
                    "diff",
                    "--name-status",
                    "-z",
                    "--find-renames",
                    f"{base_ref}...{compare_ref}",
                ),
                repository,
                "compare refs",
            )
        )
        return runner

    def request_ref_comparison_diff(
        self,
        repository: Path,
        base_ref: str,
        compare_ref: str,
        path: str,
        *,
        ignore_whitespace: bool = False,
    ) -> GitRunner:
        runner = GitRunner(parent=self)
        self._runners.add(runner)
        request_id = next(self._request_ids)
        self._latest_comparison_diff_request[repository] = request_id
        self._comparison_diff_requests[runner] = (
            repository,
            base_ref,
            compare_ref,
            path,
            request_id,
        )
        runner.completed.connect(self._handle_ref_comparison_diff)
        runner.failed_to_start.connect(self._handle_start_error)
        arguments = [
            "diff",
            "--no-ext-diff",
            "--no-color",
            f"{base_ref}...{compare_ref}",
            "--",
            path,
        ]
        if ignore_whitespace:
            arguments.insert(1, "--ignore-all-space")
        runner.run(
            GitCommand(
                tuple(arguments),
                repository,
                "read ref comparison diff",
            )
        )
        return runner

    def request_status(self, repository: Path) -> GitRunner:
        self.repository_operation_ready.emit(
            RepositoryOperationSnapshot(
                repository,
                detect_repository_operation(resolve_git_dir(repository)),
            )
        )
        runner = GitRunner(parent=self)
        self._runners.add(runner)
        request_id = next(self._request_ids)
        self._latest_status_request[repository] = request_id
        self._status_requests[runner] = (repository, request_id)
        runner.completed.connect(self._handle_status)
        runner.failed_to_start.connect(self._handle_start_error)
        runner.run(
            GitCommand(
                arguments=(
                    "status",
                    "--porcelain=v2",
                    "--branch",
                    "--untracked-files=all",
                    "-z",
                ),
                working_directory=repository,
                operation="read repository status",
            )
        )
        return runner

    def request_repository_operation(self, repository: Path) -> GitRunner:
        runner = GitRunner(parent=self)
        self._runners.add(runner)
        request_id = next(self._request_ids)
        self._latest_operation_state_request[repository] = request_id
        self._operation_state_requests[runner] = (repository, request_id)
        runner.completed.connect(self._handle_repository_operation)
        runner.failed_to_start.connect(self._handle_start_error)
        runner.run(
            GitCommand(
                ("rev-parse", "--absolute-git-dir"),
                repository,
                "read repository operation",
            )
        )
        return runner

    def request_repository_operation_action(
        self, repository: Path, *, kind: str, action: str
    ) -> GitRunner:
        supported: dict[str, frozenset[str]] = {
            "merge": frozenset({"continue", "abort"}),
            "rebase": frozenset({"continue", "skip", "abort"}),
            "cherry-pick": frozenset({"continue", "skip", "abort"}),
            "revert": frozenset({"continue", "skip", "abort"}),
        }
        if kind not in supported or action not in supported[kind]:
            raise ValueError(f"Unsupported {kind} action: {action}")
        arguments = (kind, f"--{action}")
        if action == "continue":
            arguments = ("-c", "core.editor=true", *arguments)
        runner = GitRunner(parent=self)
        self._runners.add(runner)
        self._operation_action_requests[runner] = (repository, kind, action)
        runner.completed.connect(self._handle_repository_operation_action)
        runner.failed_to_start.connect(self._handle_start_error)
        self._operation_queue.enqueue(
            runner,
            GitCommand(arguments, repository, f"{action} {kind}"),
        )
        return runner

    def request_diff(
        self,
        repository: Path,
        file: FileStatus,
        *,
        staged: bool,
        ignore_whitespace: bool = False,
    ) -> GitRunner:
        untracked = file.index_status == "?"
        if untracked:
            arguments = ["diff", "--no-index", "--no-color", "--", "/dev/null", file.path]
        else:
            arguments = ["diff", "--no-ext-diff", "--no-color"]
            if staged:
                arguments.append("--cached")
        if ignore_whitespace:
            arguments.insert(1, "--ignore-all-space")
        if not untracked:
            arguments.extend(("--", file.path))

        runner = GitRunner(parent=self)
        self._runners.add(runner)
        request_id = next(self._request_ids)
        key = (repository, file.path, staged)
        self._latest_diff_request[key] = request_id
        self._diff_requests[runner] = (
            repository,
            file.path,
            staged,
            untracked,
            request_id,
        )
        runner.completed.connect(self._handle_diff)
        runner.failed_to_start.connect(self._handle_start_error)
        runner.run(
            GitCommand(
                arguments=tuple(arguments),
                working_directory=repository,
                operation="read file diff",
            )
        )
        return runner

    def request_stage(self, repository: Path, file: FileStatus, *, staged: bool) -> GitRunner:
        if staged:
            arguments = ("add", "--", file.path)
            operation = "stage file"
        elif file.index_status == "A":
            arguments = ("rm", "--cached", "--", file.path)
            operation = "unstage new file"
        else:
            arguments = ("restore", "--staged", "--", file.path)
            operation = "unstage file"
        runner = GitRunner(parent=self)
        self._runners.add(runner)
        self._mutation_requests[runner] = file.path
        runner.completed.connect(self._handle_mutation)
        runner.failed_to_start.connect(self._handle_start_error)
        self._operation_queue.enqueue(runner, GitCommand(arguments, repository, operation))
        return runner

    def request_conflict_side(
        self, repository: Path, file: FileStatus, *, side: str
    ) -> GitRunner:
        if not file.unmerged:
            raise ValueError("Conflict sides are available only for unmerged files")
        if side not in {"ours", "theirs"}:
            raise ValueError(f"Unsupported conflict side: {side}")
        runner = GitRunner(parent=self)
        self._runners.add(runner)
        self._mutation_requests[runner] = file.path
        runner.completed.connect(self._handle_mutation)
        runner.failed_to_start.connect(self._handle_start_error)
        self._operation_queue.enqueue(
            runner,
            GitCommand(
                ("checkout", f"--{side}", "--", file.path),
                repository,
                f"use {side} conflict side",
            ),
        )
        return runner

    def request_stage_all(
        self, repository: Path, *, staged: bool, has_head: bool
    ) -> GitRunner:
        if staged:
            arguments = ("add", "-A", "--", ".")
            operation = "stage all files"
        elif has_head:
            arguments = ("reset", "-q", "HEAD", "--", ".")
            operation = "unstage all files"
        else:
            arguments = ("rm", "-r", "--cached", "--", ".")
            operation = "unstage all new files"
        runner = GitRunner(parent=self)
        self._runners.add(runner)
        self._mutation_requests[runner] = "."
        runner.completed.connect(self._handle_mutation)
        runner.failed_to_start.connect(self._handle_start_error)
        self._operation_queue.enqueue(runner, GitCommand(arguments, repository, operation))
        return runner

    def request_stage_files(
        self,
        repository: Path,
        files: tuple[FileStatus, ...],
        *,
        staged: bool,
        has_head: bool,
    ) -> GitRunner:
        paths = tuple(file.path for file in files)
        if staged:
            arguments = ("add", "--", *paths)
            operation = "stage selected files"
        elif has_head:
            arguments = ("restore", "--staged", "--", *paths)
            operation = "unstage selected files"
        else:
            arguments = ("rm", "-r", "--cached", "--", *paths)
            operation = "unstage selected new files"
        runner = GitRunner(parent=self)
        self._runners.add(runner)
        self._mutation_requests[runner] = paths[0] if len(paths) == 1 else "."
        runner.completed.connect(self._handle_mutation)
        runner.failed_to_start.connect(self._handle_start_error)
        self._operation_queue.enqueue(runner, GitCommand(arguments, repository, operation))
        return runner

    def request_commit(
        self, repository: Path, message: str, description: str, *, amend: bool
    ) -> GitRunner:
        arguments = ["commit"]
        if amend:
            arguments.append("--amend")
        arguments.extend(("-F", "-"))
        commit_text = message if not description else f"{message}\n\n{description}"
        runner = GitRunner(parent=self)
        self._runners.add(runner)
        self._mutation_requests[runner] = "commit"
        runner.completed.connect(self._handle_mutation)
        runner.failed_to_start.connect(self._handle_start_error)
        self._operation_queue.enqueue(
            runner,
            GitCommand(tuple(arguments), repository, "create commit"),
            f"{commit_text}\n".encode("utf-8", errors="surrogateescape"),
        )
        return runner

    def request_hunk(
        self, repository: Path, diff: UnifiedDiff, hunk_index: int, *, stage: bool
    ) -> GitRunner:
        arguments = ["apply", "--cached"]
        if not stage:
            arguments.append("--reverse")
        runner = GitRunner(parent=self)
        self._runners.add(runner)
        self._mutation_requests[runner] = diff.path
        runner.completed.connect(self._handle_mutation)
        runner.failed_to_start.connect(self._handle_start_error)
        self._operation_queue.enqueue(
            runner,
            GitCommand(tuple(arguments), repository, "update staged hunk"),
            diff.patch_for_hunk(hunk_index),
        )
        return runner

    def request_lines(
        self, repository: Path, diff: UnifiedDiff, selected_lines: set[int], *, stage: bool
    ) -> GitRunner:
        arguments = ["apply", "--cached"]
        if not stage:
            arguments.append("--reverse")
        runner = GitRunner(parent=self)
        self._runners.add(runner)
        self._mutation_requests[runner] = diff.path
        runner.completed.connect(self._handle_mutation)
        runner.failed_to_start.connect(self._handle_start_error)
        self._operation_queue.enqueue(
            runner,
            GitCommand(tuple(arguments), repository, "update selected diff lines"),
            diff.patch_for_lines(selected_lines),
        )
        return runner

    def request_discard(self, repository: Path, file: FileStatus) -> GitRunner:
        if file.index_status == "?":
            arguments = ("clean", "-f", "--", file.path)
        elif file.index_status == "A":
            arguments = ("rm", "-f", "--", file.path)
        elif file.is_staged:
            arguments = ("restore", "--source=HEAD", "--staged", "--worktree", "--", file.path)
        else:
            arguments = ("restore", "--worktree", "--", file.path)
        runner = GitRunner(parent=self)
        self._runners.add(runner)
        self._mutation_requests[runner] = file.path
        runner.completed.connect(self._handle_mutation)
        runner.failed_to_start.connect(self._handle_start_error)
        self._operation_queue.enqueue(
            runner, GitCommand(arguments, repository, "discard file changes")
        )
        return runner

    def request_stash_files(
        self, repository: Path, files: tuple[FileStatus, ...]
    ) -> GitRunner:
        runner = GitRunner(parent=self)
        self._runners.add(runner)
        self._mutation_requests[runner] = "stash"
        runner.completed.connect(self._handle_mutation)
        runner.failed_to_start.connect(self._handle_start_error)
        self._operation_queue.enqueue(
            runner,
            GitCommand(
                (
                    "stash",
                    "push",
                    "-u",
                    "-m",
                    "MyGitClient selected files",
                    "--",
                    *(file.path for file in files),
                ),
                repository,
                "stash selected files",
            )
        )
        return runner

    def ignore_path(self, repository: Path, path: str) -> None:
        if "\n" in path or "\r" in path:
            self.operation_failed.emit("Paths containing newlines cannot be added to .gitignore")
            return
        ignore_file = repository / ".gitignore"
        existing = (
            ignore_file.read_text(encoding="utf-8", errors="surrogateescape")
            if ignore_file.exists()
            else ""
        )
        lines = existing.splitlines()
        if path not in lines:
            prefix = "" if not existing or existing.endswith("\n") else "\n"
            ignore_file.write_text(
                f"{existing}{prefix}{path}\n",
                encoding="utf-8",
                errors="surrogateescape",
            )
        self.mutation_ready.emit(path)

    def cancel_operation(self, operation_id: int) -> None:
        self._operation_queue.cancel(operation_id)

    def shutdown(self) -> None:
        for runner in tuple(self._runners):
            runner.shutdown()
        self._runners.clear()

    def _release_runner(self, runner: GitRunner) -> None:
        self._runners.discard(runner)
        runner.deleteLater()

    @Slot(object)
    def _handle_status(self, result: object) -> None:
        runner = self.sender()
        if not isinstance(runner, GitRunner):
            self.operation_failed.emit("Git returned a result from an unknown operation")
            return
        request = self._status_requests.pop(runner, None)
        self._release_runner(runner)
        if not isinstance(result, GitResult):
            self.operation_failed.emit("Git returned an unexpected result")
            return
        if request is None:
            self.operation_failed.emit("Git returned status without a repository")
            return
        repository, request_id = request
        if self._latest_status_request.get(repository) != request_id:
            return
        self._latest_status_request.pop(repository, None)
        if result.cancelled:
            self.operation_cancelled.emit()
            return
        if not result.succeeded:
            self.operation_failed.emit(result.error_text or "Could not read repository status")
            return
        try:
            status = parse_status_porcelain_v2(result.stdout)
        except (ValueError, RuntimeError) as error:
            self.operation_failed.emit(str(error))
            return
        self.status_ready.emit(RepositoryStatusSnapshot(repository, status))

    @Slot(object)
    def _handle_repository_operation(self, result: object) -> None:
        runner = self.sender()
        if not isinstance(runner, GitRunner):
            self.operation_failed.emit(
                "Git returned an operation state from an unknown request"
            )
            return
        request = self._operation_state_requests.pop(runner, None)
        self._release_runner(runner)
        if request is None or not isinstance(result, GitResult):
            self.operation_failed.emit("Git returned an unexpected operation state")
            return
        repository, request_id = request
        if self._latest_operation_state_request.get(repository) != request_id:
            return
        self._latest_operation_state_request.pop(repository, None)
        if result.cancelled:
            return
        if not result.succeeded:
            self.operation_failed.emit(
                result.error_text or "Could not read repository operation"
            )
            return
        git_dir = Path(
            result.stdout.decode("utf-8", errors="surrogateescape").strip()
        )
        operation = detect_repository_operation(git_dir)
        self.repository_operation_ready.emit(
            RepositoryOperationSnapshot(repository, operation)
        )

    @Slot(object)
    def _handle_repository_operation_action(self, result: object) -> None:
        runner = self.sender()
        if not isinstance(runner, GitRunner):
            self.operation_failed.emit("Git returned an unknown operation action")
            return
        request = self._operation_action_requests.pop(runner, None)
        self._release_runner(runner)
        if request is None or not isinstance(result, GitResult):
            self.operation_failed.emit("Git returned an unexpected operation action")
            return
        repository, kind, action = request
        if result.cancelled:
            self.operation_cancelled.emit()
            return
        if not result.succeeded:
            self.operation_failed.emit(
                format_git_error(result.error_text, operation=f"{action} {kind}")
            )
            return
        operation = detect_repository_operation(resolve_git_dir(repository))
        if operation is None and repository in self._pending_cherry_pick_autostash:
            workflow = _CherryPickWorkflow(
                repository, (), "restore-stash", stashed=True
            )
            self._run_cherry_pick_workflow(
                workflow,
                ("stash", "pop", "--index"),
                "restore automatic stash",
            )
            return
        self.mutation_ready.emit("repository-operation:changed")

    @Slot(str)
    def _handle_start_error(self, message: str) -> None:
        runner = self.sender()
        if not isinstance(runner, GitRunner):
            return
        self._release_runner(runner)
        self._status_requests.pop(runner, None)
        self._operation_state_requests.pop(runner, None)
        self._diff_requests.pop(runner, None)
        self._mutation_requests.pop(runner, None)
        self._operation_action_requests.pop(runner, None)
        self._history_requests.pop(runner, None)
        self._branch_requests.pop(runner, None)
        self._tag_requests.pop(runner, None)
        checkout = self._checkout_workflows.pop(runner, None)
        self._commit_files_requests.pop(runner, None)
        self._commit_diff_requests.pop(runner, None)
        self._comparison_requests.pop(runner, None)
        self._comparison_diff_requests.pop(runner, None)
        self._cherry_pick_preview_requests.pop(runner, None)
        self._cherry_pick_workflows.pop(runner, None)
        self._revert_preview_requests.pop(runner, None)
        self._revert_workflows.pop(runner, None)
        self._rebase_preview_workflows.pop(runner, None)
        self._rebase_requests.pop(runner, None)
        if checkout is not None:
            self.operation_failed.emit(
                f"Could not {checkout.step} during checkout: {message}"
            )
            return
        self.operation_failed.emit(message)

    @Slot(object)
    def _handle_history(self, result: object) -> None:
        runner = self.sender()
        if not isinstance(runner, GitRunner):
            self.operation_failed.emit("Git returned history from an unknown operation")
            return
        request = self._history_requests.pop(runner, None)
        self._release_runner(runner)
        if request is None or not isinstance(result, GitResult):
            self.operation_failed.emit("Git returned an unexpected history result")
            return
        repository, offset, limit, request_id = request
        if self._latest_history_request.get(repository) != request_id:
            return
        self._latest_history_request.pop(repository, None)
        if result.cancelled:
            self.operation_cancelled.emit()
            return
        if not result.succeeded:
            self.operation_failed.emit(result.error_text or "Could not read commit history")
            return
        try:
            commits = parse_commit_log(result.stdout)
        except (ValueError, RuntimeError) as error:
            self.operation_failed.emit(str(error))
            return
        page = CommitPage(repository, commits[:limit], offset, len(commits) > limit)
        self.history_ready.emit(page)

    @Slot(object)
    def _handle_ref_comparison(self, result: object) -> None:
        runner = self.sender()
        if not isinstance(runner, GitRunner):
            self.operation_failed.emit("Git returned comparison from an unknown operation")
            return
        request = self._comparison_requests.pop(runner, None)
        self._release_runner(runner)
        if request is None or not isinstance(result, GitResult):
            self.operation_failed.emit("Git returned an unexpected comparison result")
            return
        repository, base_ref, compare_ref, request_id = request
        if self._latest_comparison_request.get(repository) != request_id:
            return
        self._latest_comparison_request.pop(repository, None)
        if result.cancelled:
            self.operation_cancelled.emit()
            return
        if not result.succeeded:
            self.operation_failed.emit(result.error_text or "Could not compare refs")
            return
        try:
            files = parse_commit_files(result.stdout)
        except (ValueError, RuntimeError) as error:
            self.operation_failed.emit(str(error))
            return
        self.comparison_ready.emit(
            RefComparisonSnapshot(repository, base_ref, compare_ref, files)
        )

    @Slot(object)
    def _handle_ref_comparison_diff(self, result: object) -> None:
        runner = self.sender()
        if not isinstance(runner, GitRunner):
            self.operation_failed.emit(
                "Git returned comparison diff from an unknown operation"
            )
            return
        request = self._comparison_diff_requests.pop(runner, None)
        self._release_runner(runner)
        if request is None or not isinstance(result, GitResult):
            self.operation_failed.emit("Git returned an unexpected comparison diff")
            return
        repository, base_ref, compare_ref, path, request_id = request
        if self._latest_comparison_diff_request.get(repository) != request_id:
            return
        self._latest_comparison_diff_request.pop(repository, None)
        if result.cancelled:
            self.operation_cancelled.emit()
            return
        if not result.succeeded:
            self.operation_failed.emit(result.error_text or "Could not read comparison diff")
            return
        diff = parse_unified_diff(result.stdout, path, staged=False)
        self.comparison_diff_ready.emit(
            RefComparisonDiffSnapshot(repository, base_ref, compare_ref, diff)
        )

    @Slot(object)
    def _handle_branches(self, result: object) -> None:
        runner = self.sender()
        if not isinstance(runner, GitRunner):
            self.operation_failed.emit("Git returned branches from an unknown operation")
            return
        request = self._branch_requests.pop(runner, None)
        self._release_runner(runner)
        if request is None or not isinstance(result, GitResult):
            self.operation_failed.emit("Git returned an unexpected branch result")
            return
        repository, request_id = request
        if self._latest_branch_request.get(repository) != request_id:
            return
        self._latest_branch_request.pop(repository, None)
        if result.cancelled:
            self.operation_cancelled.emit()
            return
        if not result.succeeded:
            self.operation_failed.emit(result.error_text or "Could not read branches")
            return
        try:
            snapshot = parse_branches(repository, result.stdout)
        except (ValueError, RuntimeError) as error:
            self.operation_failed.emit(str(error))
            return
        self.branches_ready.emit(snapshot)

    @Slot(object)
    def _handle_branch_point(self, result: object) -> None:
        runner = self.sender()
        if not isinstance(runner, GitRunner):
            self.operation_failed.emit("Git returned a branch point from an unknown operation")
            return
        request = self._branch_point_requests.pop(runner, None)
        self._release_runner(runner)
        if request is None or not isinstance(result, GitResult):
            self.operation_failed.emit("Git returned an unexpected branch point result")
            return
        repository, branch_ref, base_ref, request_id = request
        if self._latest_branch_point_request.get(repository) != request_id:
            return
        self._latest_branch_point_request.pop(repository, None)
        if result.cancelled:
            return
        if not result.succeeded:
            return
        commit_oid = result.stdout.decode("ascii", errors="replace").strip()
        if commit_oid:
            self.branch_point_ready.emit(
                BranchPointSnapshot(repository, branch_ref, base_ref, commit_oid)
            )

    @Slot(object)
    def _handle_tags(self, result: object) -> None:
        runner = self.sender()
        if not isinstance(runner, GitRunner):
            self.operation_failed.emit("Git returned tags from an unknown operation")
            return
        request = self._tag_requests.pop(runner, None)
        self._release_runner(runner)
        if request is None or not isinstance(result, GitResult):
            self.operation_failed.emit("Git returned an unexpected tag result")
            return
        repository, request_id = request
        if self._latest_tag_request.get(repository) != request_id:
            return
        self._latest_tag_request.pop(repository, None)
        if result.cancelled:
            self.operation_cancelled.emit()
            return
        if not result.succeeded:
            self.operation_failed.emit(result.error_text or "Could not read tags")
            return
        try:
            snapshot: TagsSnapshot = parse_tags(repository, result.stdout)
        except (ValueError, RuntimeError) as error:
            self.operation_failed.emit(str(error))
            return
        self.tags_ready.emit(snapshot)

    @Slot(object)
    def _handle_stashes(self, result: object) -> None:
        runner = self.sender()
        if not isinstance(runner, GitRunner):
            self.operation_failed.emit("Git returned stashes from an unknown operation")
            return
        request = self._stash_requests.pop(runner, None)
        self._release_runner(runner)
        if request is None or not isinstance(result, GitResult):
            self.operation_failed.emit("Git returned an unexpected stash result")
            return
        repository, request_id = request
        if self._latest_stash_request.get(repository) != request_id:
            return
        self._latest_stash_request.pop(repository, None)
        if result.cancelled:
            self.operation_cancelled.emit()
            return
        if not result.succeeded:
            self.operation_failed.emit(result.error_text or "Could not read stashes")
            return
        try:
            snapshot: StashesSnapshot = parse_stashes(repository, result.stdout)
        except (ValueError, RuntimeError) as error:
            self.operation_failed.emit(str(error))
            return
        self.stashes_ready.emit(snapshot)

    @Slot(object)
    def _handle_checkout_workflow(self, result: object) -> None:
        runner = self.sender()
        if not isinstance(runner, GitRunner):
            self.operation_failed.emit("Git returned an unknown checkout workflow result")
            return
        workflow = self._checkout_workflows.pop(runner, None)
        self._release_runner(runner)
        if workflow is None or not isinstance(result, GitResult):
            self.operation_failed.emit("Git returned an unexpected checkout workflow result")
            return
        if result.cancelled:
            if workflow.stashed:
                self.operation_failed.emit(
                    "Checkout was cancelled. The automatic stash was kept so no local "
                    "changes are lost."
                )
            else:
                self.operation_cancelled.emit()
            return
        if workflow.step == "stash":
            if not result.succeeded:
                self.operation_failed.emit(
                    format_git_error(
                        result.error_text, operation="stash local changes"
                    )
                )
                return
            workflow.stashed = b"No local changes to save" not in result.stdout
            workflow.step = "verify-stash"
            self._run_checkout_workflow(
                workflow,
                ("status", "--porcelain=v2", "-z"),
                "verify automatic stash",
            )
            return
        if workflow.step == "verify-stash":
            if not result.succeeded:
                self.operation_failed.emit(
                    format_git_error(
                        result.error_text, operation="verify automatic stash"
                    )
                )
                return
            if result.stdout:
                stash_note = (
                    " The automatic stash was kept so no local changes are lost."
                    if workflow.stashed
                    else ""
                )
                self.operation_failed.emit(
                    "Checkout was not started because the working tree still contains "
                    "changes after stashing. This can happen when .gitattributes or Git "
                    "line-ending settings rewrite a file. Fix the repository attributes, "
                    f"then refresh and try again.{stash_note}"
                )
                return
            workflow.step = "checkout"
            arguments = (
                ("switch", "--track", workflow.branch.name)
                if workflow.branch.remote
                else ("switch", workflow.branch.name)
            )
            self._run_checkout_workflow(workflow, arguments, "checkout branch")
            return
        if workflow.step == "checkout":
            if not result.succeeded:
                workflow.pending_error = format_git_error(
                    result.error_text, operation="checkout branch"
                )
            if workflow.stashed:
                workflow.step = "restore"
                self._run_checkout_workflow(
                    workflow, ("stash", "pop"), "restore automatic stash"
                )
                return
            if workflow.pending_error is not None:
                self.operation_failed.emit(workflow.pending_error)
            else:
                self.mutation_ready.emit(f"branch:{workflow.branch.name}")
            return
        if not result.succeeded:
            restore_error = format_git_error(
                result.error_text, operation="restore automatic stash"
            )
            prefix = (
                f"{workflow.pending_error}\n\n" if workflow.pending_error is not None else ""
            )
            self.operation_failed.emit(
                f"{prefix}The automatic stash was kept because it could not be restored:\n"
                f"{restore_error}"
            )
        elif workflow.pending_error is not None:
            self.operation_failed.emit(workflow.pending_error)
        else:
            self.mutation_ready.emit(f"branch:{workflow.branch.name}")

    @Slot(object)
    def _handle_cherry_pick_workflow(self, result: object) -> None:
        runner = self.sender()
        if not isinstance(runner, GitRunner):
            self.operation_failed.emit("Git returned an unknown cherry-pick result")
            return
        workflow = self._cherry_pick_workflows.pop(runner, None)
        self._release_runner(runner)
        if workflow is None or not isinstance(result, GitResult):
            self.operation_failed.emit("Git returned an unexpected cherry-pick result")
            return
        if result.cancelled:
            if workflow.stashed:
                self.operation_failed.emit(
                    "Cherry-pick was cancelled. The automatic stash was kept so no "
                    "local changes are lost."
                )
            else:
                self.operation_cancelled.emit()
            return
        if workflow.step == "stash":
            if not result.succeeded:
                self.operation_failed.emit(
                    format_git_error(
                        result.error_text, operation="stash local changes"
                    )
                )
                return
            workflow.stashed = b"No local changes to save" not in result.stdout
            workflow.step = "cherry-pick"
            self._run_cherry_pick_workflow(
                workflow,
                ("cherry-pick", "--", *(commit.oid for commit in workflow.commits)),
                "cherry-pick commits",
            )
            return
        if workflow.step == "cherry-pick":
            if not result.succeeded:
                if workflow.stashed:
                    self._pending_cherry_pick_autostash.add(workflow.repository)
                self.operation_failed.emit(
                    format_git_error(result.error_text, operation="cherry-pick commits")
                )
                self.mutation_ready.emit("repository-operation:changed")
                return
            if workflow.stashed:
                workflow.step = "restore-stash"
                self._run_cherry_pick_workflow(
                    workflow,
                    ("stash", "pop", "--index"),
                    "restore automatic stash",
                )
                return
            self.mutation_ready.emit("cherry-pick")
            return
        if not result.succeeded:
            self.operation_failed.emit(
                "Cherry-pick completed, but the automatic stash could not be restored. "
                "It was kept in the stash list.\n\n"
                + format_git_error(
                    result.error_text, operation="restore automatic stash"
                )
            )
        else:
            self._pending_cherry_pick_autostash.discard(workflow.repository)
        self.mutation_ready.emit("cherry-pick")

    @Slot(object)
    def _handle_cherry_pick_preview(self, result: object) -> None:
        runner = self.sender()
        if not isinstance(runner, GitRunner):
            self.operation_failed.emit("Git returned an unknown cherry-pick preview")
            return
        request = self._cherry_pick_preview_requests.pop(runner, None)
        self._release_runner(runner)
        if request is None or not isinstance(result, GitResult):
            self.operation_failed.emit("Git returned an unexpected cherry-pick preview")
            return
        repository, commits, request_id = request
        if self._latest_cherry_pick_preview_request.get(repository) != request_id:
            return
        self._latest_cherry_pick_preview_request.pop(repository, None)
        if result.cancelled:
            self.operation_cancelled.emit()
            return
        if not result.succeeded:
            self.operation_failed.emit(
                result.error_text or "Could not preview cherry-pick"
            )
            return
        files = tuple(
            sorted(
                {
                    part.decode("utf-8", errors="surrogateescape")
                    for part in result.stdout.split(b"\0")
                    if part
                }
            )
        )
        self.cherry_pick_preview_ready.emit(
            CherryPickPreviewSnapshot(repository, commits, files)
        )

    @Slot(object)
    def _handle_revert_workflow(self, result: object) -> None:
        runner = self.sender()
        if not isinstance(runner, GitRunner):
            self.operation_failed.emit("Git returned an unknown revert result")
            return
        workflow = self._revert_workflows.pop(runner, None)
        self._release_runner(runner)
        if workflow is None or not isinstance(result, GitResult):
            self.operation_failed.emit("Git returned an unexpected revert result")
            return
        if result.cancelled:
            self.operation_cancelled.emit()
            return
        if not result.succeeded:
            self.operation_failed.emit(
                format_git_error(result.error_text, operation="revert commits")
            )
            self.mutation_ready.emit("repository-operation:changed")
            return
        self.mutation_ready.emit("revert")

    @Slot(object)
    def _handle_revert_preview(self, result: object) -> None:
        runner = self.sender()
        if not isinstance(runner, GitRunner):
            self.operation_failed.emit("Git returned an unknown revert preview")
            return
        request = self._revert_preview_requests.pop(runner, None)
        self._release_runner(runner)
        if request is None or not isinstance(result, GitResult):
            self.operation_failed.emit("Git returned an unexpected revert preview")
            return
        repository, commits, request_id = request
        if self._latest_revert_preview_request.get(repository) != request_id:
            return
        self._latest_revert_preview_request.pop(repository, None)
        if result.cancelled:
            self.operation_cancelled.emit()
            return
        if not result.succeeded:
            self.operation_failed.emit(result.error_text or "Could not preview revert")
            return
        diff = parse_unified_diff(result.stdout, "", staged=True)
        self.revert_preview_ready.emit(
            RevertPreviewSnapshot(
                repository,
                commits,
                tuple(sorted(diff_paths(diff))),
                diff,
            )
        )

    @Slot(object)
    def _handle_rebase(self, result: object) -> None:
        runner = self.sender()
        if not isinstance(runner, GitRunner):
            self.operation_failed.emit("Git returned an unknown rebase result")
            return
        request = self._rebase_requests.pop(runner, None)
        self._release_runner(runner)
        if request is None or not isinstance(result, GitResult):
            self.operation_failed.emit("Git returned an unexpected rebase result")
            return
        if result.cancelled:
            self.operation_cancelled.emit()
            return
        if not result.succeeded:
            self.operation_failed.emit(
                format_git_error(result.error_text, operation="rebase branch")
            )
            self.mutation_ready.emit("repository-operation:changed")
            return
        self.mutation_ready.emit("rebase")

    @Slot(object)
    def _handle_rebase_preview(self, result: object) -> None:
        runner = self.sender()
        if not isinstance(runner, GitRunner):
            self.operation_failed.emit("Git returned an unknown rebase preview")
            return
        workflow = self._rebase_preview_workflows.pop(runner, None)
        self._release_runner(runner)
        if workflow is None or not isinstance(result, GitResult):
            self.operation_failed.emit("Git returned an unexpected rebase preview")
            return
        if (
            self._latest_rebase_preview_request.get(workflow.repository)
            != workflow.request_id
        ):
            return
        if result.cancelled:
            self._latest_rebase_preview_request.pop(workflow.repository, None)
            self.operation_cancelled.emit()
            return
        if not result.succeeded:
            self._latest_rebase_preview_request.pop(workflow.repository, None)
            self.operation_failed.emit(
                result.error_text or "Could not prepare rebase preview"
            )
            return
        if workflow.step == "base":
            workflow.base_oid = (
                result.stdout.decode("ascii", errors="replace").strip()
            )
            workflow.step = "commits"
            self._run_rebase_preview(
                workflow,
                (
                    "log",
                    "--reverse",
                    "--date=iso-strict",
                    "--pretty=format:%x1e%H%x00%P%x00%an%x00%ae%x00%aI%x00%s",
                    f"{workflow.target.full_name}..HEAD",
                ),
                "read commits to rebase",
            )
            return
        if workflow.step == "commits":
            try:
                workflow.commits = parse_commit_log(result.stdout)
            except (ValueError, RuntimeError) as error:
                self._latest_rebase_preview_request.pop(workflow.repository, None)
                self.operation_failed.emit(str(error))
                return
            workflow.step = "files"
            self._run_rebase_preview(
                workflow,
                (
                    "diff",
                    "--name-only",
                    "-z",
                    f"{workflow.target.full_name}...HEAD",
                ),
                "read files to rebase",
            )
            return
        self._latest_rebase_preview_request.pop(workflow.repository, None)
        files = tuple(
            sorted(
                part.decode("utf-8", errors="surrogateescape")
                for part in result.stdout.split(b"\0")
                if part
            )
        )
        self.rebase_preview_ready.emit(
            RebasePreviewSnapshot(
                workflow.repository,
                workflow.target,
                workflow.base_oid,
                workflow.commits,
                files,
            )
        )

    @Slot(object)
    def _handle_commit_files(self, result: object) -> None:
        runner = self.sender()
        if not isinstance(runner, GitRunner):
            self.operation_failed.emit("Git returned commit files from an unknown operation")
            return
        request = self._commit_files_requests.pop(runner, None)
        self._release_runner(runner)
        if request is None or not isinstance(result, GitResult):
            self.operation_failed.emit("Git returned an unexpected commit file result")
            return
        repository, commit_oid, request_id = request
        if self._latest_commit_files_request.get(repository) != request_id:
            return
        self._latest_commit_files_request.pop(repository, None)
        if result.cancelled:
            self.operation_cancelled.emit()
            return
        if not result.succeeded:
            self.operation_failed.emit(result.error_text or "Could not read commit files")
            return
        try:
            files = parse_commit_files(result.stdout)
        except (ValueError, RuntimeError) as error:
            self.operation_failed.emit(str(error))
            return
        self.commit_files_ready.emit(CommitFilesSnapshot(repository, commit_oid, files))

    @Slot(object)
    def _handle_amend_preview(self, result: object) -> None:
        runner = self.sender()
        if not isinstance(runner, GitRunner):
            self.operation_failed.emit("Git returned an amend preview from an unknown operation")
            return
        request = self._amend_preview_requests.pop(runner, None)
        self._release_runner(runner)
        if request is None or not isinstance(result, GitResult):
            self.operation_failed.emit("Git returned an unexpected amend preview result")
            return
        repository, commit_oid, request_id = request
        if self._latest_amend_preview_request.get(repository) != request_id:
            return
        self._latest_amend_preview_request.pop(repository, None)
        if result.cancelled:
            self.operation_cancelled.emit()
            return
        if not result.succeeded:
            self.operation_failed.emit(result.error_text or "Could not read amend preview")
            return
        try:
            subject, parent_oid, description, diff = parse_amend_preview(result.stdout)
        except (ValueError, RuntimeError) as error:
            self.operation_failed.emit(str(error))
            return
        self.amend_preview_ready.emit(
            AmendPreview(repository, commit_oid, parent_oid, subject, description, diff)
        )

    @Slot(object)
    def _handle_amend_diff(self, result: object) -> None:
        runner = self.sender()
        if not isinstance(runner, GitRunner):
            self.operation_failed.emit("Git returned an amend diff from an unknown operation")
            return
        request = self._amend_diff_requests.pop(runner, None)
        self._release_runner(runner)
        if request is None or not isinstance(result, GitResult):
            self.operation_failed.emit("Git returned an unexpected amend diff result")
            return
        repository, commit_oid, path, request_id = request
        key = (repository, path)
        if self._latest_amend_diff_request.get(key) != request_id:
            return
        self._latest_amend_diff_request.pop(key, None)
        if result.cancelled:
            self.operation_cancelled.emit()
            return
        if not result.succeeded:
            self.operation_failed.emit(result.error_text or "Could not read amend diff")
            return
        diff = parse_unified_diff(result.stdout, path or "HEAD", staged=True)
        self.amend_diff_ready.emit(
            AmendDiffSnapshot(repository, commit_oid, path, diff, diff_paths(diff))
        )

    @Slot(object)
    def _handle_commit_diff(self, result: object) -> None:
        runner = self.sender()
        if not isinstance(runner, GitRunner):
            self.operation_failed.emit("Git returned a commit diff from an unknown operation")
            return
        request = self._commit_diff_requests.pop(runner, None)
        self._release_runner(runner)
        if request is None or not isinstance(result, GitResult):
            self.operation_failed.emit("Git returned an unexpected commit diff result")
            return
        repository, commit_oid, path, request_id = request
        if self._latest_commit_diff_request.get(repository) != request_id:
            return
        self._latest_commit_diff_request.pop(repository, None)
        if result.cancelled:
            self.operation_cancelled.emit()
            return
        if not result.succeeded:
            self.operation_failed.emit(result.error_text or "Could not read commit diff")
            return
        diff = parse_unified_diff(result.stdout, path, staged=False)
        self.commit_diff_ready.emit(CommitDiffSnapshot(repository, commit_oid, diff))

    @Slot(object)
    def _handle_diff(self, result: object) -> None:
        runner = self.sender()
        if not isinstance(runner, GitRunner):
            self.operation_failed.emit("Git returned a diff from an unknown operation")
            return
        request = self._diff_requests.pop(runner, None)
        self._release_runner(runner)
        if request is None or not isinstance(result, GitResult):
            self.operation_failed.emit("Git returned an unexpected diff result")
            return
        repository, path, staged, accepts_difference, request_id = request
        key = (repository, path, staged)
        if self._latest_diff_request.get(key) != request_id:
            return
        self._latest_diff_request.pop(key, None)
        if result.cancelled:
            self.operation_cancelled.emit()
            return
        if not result.succeeded and not (accepts_difference and result.exit_code == 1):
            self.operation_failed.emit(result.error_text or "Could not read file diff")
            return
        diff = parse_unified_diff(result.stdout, path, staged=staged)
        self.diff_ready.emit(DiffSnapshot(repository, diff))

    @Slot(object)
    def _handle_mutation(self, result: object) -> None:
        runner = self.sender()
        if not isinstance(runner, GitRunner):
            self.operation_failed.emit("Git returned a result from an unknown mutation")
            return
        path = self._mutation_requests.pop(runner, None)
        self._release_runner(runner)
        if path is None or not isinstance(result, GitResult):
            self.operation_failed.emit("Git returned an unexpected mutation result")
            return
        if result.cancelled:
            self.operation_cancelled.emit()
            return
        if not result.succeeded:
            self.operation_failed.emit(
                format_git_error(
                    result.error_text, operation=result.command.operation
                )
            )
            return
        self.mutation_ready.emit(path)


def detect_repository_operation(git_dir: Path) -> RepositoryOperation | None:
    for directory_name in ("rebase-merge", "rebase-apply"):
        directory = git_dir / directory_name
        if directory.is_dir():
            return RepositoryOperation(
                "rebase",
                _read_operation_number(directory / "msgnum", directory / "next"),
                _read_operation_number(directory / "end", directory / "last"),
            )
    if (git_dir / "CHERRY_PICK_HEAD").is_file():
        return RepositoryOperation("cherry-pick")
    if (git_dir / "REVERT_HEAD").is_file():
        return RepositoryOperation("revert")
    if (git_dir / "MERGE_HEAD").is_file():
        return RepositoryOperation("merge")
    return None


def resolve_git_dir(repository: Path) -> Path:
    dot_git = repository / ".git"
    if dot_git.is_dir():
        return dot_git
    try:
        marker = dot_git.read_text(
            encoding="utf-8", errors="surrogateescape"
        ).strip()
    except OSError:
        return dot_git
    prefix = "gitdir:"
    if not marker.casefold().startswith(prefix):
        return dot_git
    path = Path(marker[len(prefix) :].strip())
    return path if path.is_absolute() else (repository / path).resolve()


def _read_operation_number(*paths: Path) -> int | None:
    for path in paths:
        try:
            return int(path.read_text(encoding="ascii").strip())
        except (OSError, ValueError):
            continue
    return None
