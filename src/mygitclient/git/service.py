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
    CommitDiffSnapshot,
    CommitFilesSnapshot,
    CommitPage,
    DiffSnapshot,
    FileStatus,
    GitCommand,
    GitResult,
    RepositoryStatusSnapshot,
    UnifiedDiff,
)
from mygitclient.git.operation_queue import GitOperationQueue
from mygitclient.git.parsers import (
    diff_paths,
    parse_amend_preview,
    parse_branches,
    parse_commit_files,
    parse_commit_log,
    parse_status_porcelain_v2,
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


class GitService(QObject):
    amend_diff_ready = Signal(object)
    amend_preview_ready = Signal(object)
    history_ready = Signal(object)
    branches_ready = Signal(object)
    commit_files_ready = Signal(object)
    commit_diff_ready = Signal(object)
    status_ready = Signal(object)
    diff_ready = Signal(object)
    mutation_ready = Signal(str)
    operation_cancelled = Signal()
    operation_failed = Signal(str)
    queue_changed = Signal(object)

    _EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._runners: set[GitRunner] = set()
        self._request_ids = count(1)
        self._status_requests: dict[GitRunner, tuple[Path, int]] = {}
        self._latest_status_request: dict[Path, int] = {}
        self._diff_requests: dict[GitRunner, tuple[Path, str, bool, bool, int]] = {}
        self._latest_diff_request: dict[tuple[Path, str, bool], int] = {}
        self._mutation_requests: dict[GitRunner, str] = {}
        self._history_requests: dict[GitRunner, tuple[Path, int, int, int]] = {}
        self._latest_history_request: dict[Path, int] = {}
        self._branch_requests: dict[GitRunner, tuple[Path, int]] = {}
        self._latest_branch_request: dict[Path, int] = {}
        self._commit_files_requests: dict[GitRunner, tuple[Path, str, int]] = {}
        self._latest_commit_files_request: dict[Path, int] = {}
        self._commit_diff_requests: dict[GitRunner, tuple[Path, str, str, int]] = {}
        self._latest_commit_diff_request: dict[Path, int] = {}
        self._amend_preview_requests: dict[GitRunner, tuple[Path, str, int]] = {}
        self._latest_amend_preview_request: dict[Path, int] = {}
        self._amend_diff_requests: dict[
            GitRunner, tuple[Path, str, str | None, int]
        ] = {}
        self._latest_amend_diff_request: dict[tuple[Path, str | None], int] = {}
        self._checkout_workflows: dict[GitRunner, _CheckoutWorkflow] = {}
        self._network_queue = GitOperationQueue(self)
        self._network_queue.changed.connect(self.queue_changed)

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
        runner.run(GitCommand(arguments, repository, "checkout branch"))
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
        runner.run(GitCommand(arguments, workflow.repository, operation))
        return runner

    def request_create_branch(self, repository: Path, name: str) -> GitRunner:
        runner = GitRunner(parent=self)
        self._runners.add(runner)
        self._mutation_requests[runner] = f"branch:{name}"
        runner.completed.connect(self._handle_mutation)
        runner.failed_to_start.connect(self._handle_start_error)
        runner.run(GitCommand(("switch", "-c", name), repository, "create branch"))
        return runner

    def request_rename_branch(
        self, repository: Path, branch: BranchInfo, new_name: str
    ) -> GitRunner:
        runner = GitRunner(parent=self)
        self._runners.add(runner)
        self._mutation_requests[runner] = "branches:renamed"
        runner.completed.connect(self._handle_mutation)
        runner.failed_to_start.connect(self._handle_start_error)
        runner.run(
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
        runner.run(GitCommand(("branch", flag, branch.name), repository, "delete branch"))
        return runner

    def request_pull(
        self, repository: Path, *, rebase: bool, autostash: bool
    ) -> GitRunner:
        arguments = ["pull", "--rebase" if rebase else "--no-rebase"]
        if autostash:
            arguments.append("--autostash")
        runner = GitRunner(parent=self)
        self._runners.add(runner)
        self._mutation_requests[runner] = "pull"
        runner.completed.connect(self._handle_mutation)
        runner.failed_to_start.connect(self._handle_start_error)
        self._network_queue.enqueue(
            runner, GitCommand(tuple(arguments), repository, "pull changes")
        )
        return runner

    def request_fetch(self, repository: Path) -> GitRunner:
        runner = GitRunner(parent=self)
        self._runners.add(runner)
        self._mutation_requests[runner] = "fetch"
        runner.completed.connect(self._handle_mutation)
        runner.failed_to_start.connect(self._handle_start_error)
        self._network_queue.enqueue(
            runner, GitCommand(("fetch", "--prune"), repository, "fetch changes")
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
        arguments = ["push"]
        if force_with_lease:
            arguments.append("--force-with-lease")
        if set_upstream:
            arguments.extend(("--set-upstream", "origin", branch))
        runner = GitRunner(parent=self)
        self._runners.add(runner)
        self._mutation_requests[runner] = "push"
        runner.completed.connect(self._handle_mutation)
        runner.failed_to_start.connect(self._handle_start_error)
        self._network_queue.enqueue(
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
        runner.run(GitCommand(arguments, repository, operation))
        return runner

    def request_commit_diff(
        self,
        repository: Path,
        commit_oid: str,
        path: str,
        *,
        parent_oid: str | None,
    ) -> GitRunner:
        runner = GitRunner(parent=self)
        self._runners.add(runner)
        request_id = next(self._request_ids)
        self._latest_commit_diff_request[repository] = request_id
        self._commit_diff_requests[runner] = (repository, commit_oid, path, request_id)
        runner.completed.connect(self._handle_commit_diff)
        runner.failed_to_start.connect(self._handle_start_error)
        arguments = (
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
        runner.run(GitCommand(arguments, repository, "read commit diff"))
        return runner

    def request_history(
        self, repository: Path, *, offset: int = 0, limit: int = 100
    ) -> GitRunner:
        runner = GitRunner(parent=self)
        self._runners.add(runner)
        request_id = next(self._request_ids)
        self._latest_history_request[repository] = request_id
        self._history_requests[runner] = (repository, offset, limit, request_id)
        runner.completed.connect(self._handle_history)
        runner.failed_to_start.connect(self._handle_start_error)
        runner.run(
            GitCommand(
                (
                    "log",
                    "--branches",
                    "--remotes",
                    "--tags",
                    f"--skip={offset}",
                    f"--max-count={limit + 1}",
                    "--date=iso-strict",
                    "--pretty=format:%x1e%H%x00%P%x00%an%x00%ae%x00%aI%x00%s",
                ),
                repository,
                "read commit history",
            )
        )
        return runner

    def request_status(self, repository: Path) -> GitRunner:
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

    def request_diff(self, repository: Path, file: FileStatus, *, staged: bool) -> GitRunner:
        untracked = file.index_status == "?"
        if untracked:
            arguments = ["diff", "--no-index", "--no-color", "--", "/dev/null", file.path]
        else:
            arguments = ["diff", "--no-ext-diff", "--no-color"]
            if staged:
                arguments.append("--cached")
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
        runner.run(GitCommand(arguments, repository, operation))
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
        runner.run(GitCommand(arguments, repository, operation))
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
        runner.run(
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
        runner.run(
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
        runner.run(
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
        runner.run(GitCommand(arguments, repository, "discard file changes"))
        return runner

    def request_stash_files(
        self, repository: Path, files: tuple[FileStatus, ...]
    ) -> GitRunner:
        runner = GitRunner(parent=self)
        self._runners.add(runner)
        self._mutation_requests[runner] = "stash"
        runner.completed.connect(self._handle_mutation)
        runner.failed_to_start.connect(self._handle_start_error)
        runner.run(
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
        self._network_queue.cancel(operation_id)

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

    @Slot(str)
    def _handle_start_error(self, message: str) -> None:
        runner = self.sender()
        if not isinstance(runner, GitRunner):
            return
        self._release_runner(runner)
        self._status_requests.pop(runner, None)
        self._diff_requests.pop(runner, None)
        self._mutation_requests.pop(runner, None)
        self._history_requests.pop(runner, None)
        self._branch_requests.pop(runner, None)
        checkout = self._checkout_workflows.pop(runner, None)
        self._commit_files_requests.pop(runner, None)
        self._commit_diff_requests.pop(runner, None)
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
