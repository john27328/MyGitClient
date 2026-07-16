from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from mygitclient.git.models import (
    FileStatus,
    GitCommand,
    GitResult,
    RepositoryStatusSnapshot,
    UnifiedDiff,
)
from mygitclient.git.parsers import parse_status_porcelain_v2, parse_unified_diff
from mygitclient.git.runner import GitRunner


class GitService(QObject):
    status_ready = Signal(object)
    diff_ready = Signal(object)
    mutation_ready = Signal(str)
    operation_failed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._runners: set[GitRunner] = set()
        self._status_requests: dict[GitRunner, Path] = {}
        self._diff_requests: dict[GitRunner, tuple[str, bool, bool]] = {}
        self._mutation_requests: dict[GitRunner, str] = {}

    def request_status(self, repository: Path) -> GitRunner:
        runner = GitRunner(parent=self)
        self._runners.add(runner)
        self._status_requests[runner] = repository
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
        self._diff_requests[runner] = (file.path, staged, untracked)
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

    def request_commit(self, repository: Path, message: str, *, amend: bool) -> GitRunner:
        arguments = ["commit"]
        if amend:
            arguments.append("--amend")
        arguments.extend(("-m", message))
        runner = GitRunner(parent=self)
        self._runners.add(runner)
        self._mutation_requests[runner] = "commit"
        runner.completed.connect(self._handle_mutation)
        runner.failed_to_start.connect(self._handle_start_error)
        runner.run(GitCommand(tuple(arguments), repository, "create commit"))
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

    def cancel_all(self) -> None:
        for runner in tuple(self._runners):
            runner.cancel()

    @Slot(object)
    def _handle_status(self, result: object) -> None:
        runner = self.sender()
        if not isinstance(runner, GitRunner):
            self.operation_failed.emit("Git returned a result from an unknown operation")
            return
        self._runners.discard(runner)
        repository = self._status_requests.pop(runner, None)
        if not isinstance(result, GitResult):
            self.operation_failed.emit("Git returned an unexpected result")
            return
        if not result.succeeded:
            self.operation_failed.emit(result.error_text or "Could not read repository status")
            return
        try:
            status = parse_status_porcelain_v2(result.stdout)
        except (ValueError, RuntimeError) as error:
            self.operation_failed.emit(str(error))
            return
        if repository is None:
            self.operation_failed.emit("Git returned status without a repository")
            return
        self.status_ready.emit(RepositoryStatusSnapshot(repository, status))

    @Slot(str)
    def _handle_start_error(self, message: str) -> None:
        runner = self.sender()
        if not isinstance(runner, GitRunner):
            return
        self._runners.discard(runner)
        self._status_requests.pop(runner, None)
        self._diff_requests.pop(runner, None)
        self._mutation_requests.pop(runner, None)
        self.operation_failed.emit(message)

    @Slot(object)
    def _handle_diff(self, result: object) -> None:
        runner = self.sender()
        if not isinstance(runner, GitRunner):
            self.operation_failed.emit("Git returned a diff from an unknown operation")
            return
        self._runners.discard(runner)
        request = self._diff_requests.pop(runner, None)
        if request is None or not isinstance(result, GitResult):
            self.operation_failed.emit("Git returned an unexpected diff result")
            return
        path, staged, accepts_difference = request
        if not result.succeeded and not (accepts_difference and result.exit_code == 1):
            self.operation_failed.emit(result.error_text or "Could not read file diff")
            return
        self.diff_ready.emit(parse_unified_diff(result.stdout, path, staged=staged))

    @Slot(object)
    def _handle_mutation(self, result: object) -> None:
        runner = self.sender()
        if not isinstance(runner, GitRunner):
            self.operation_failed.emit("Git returned a result from an unknown mutation")
            return
        self._runners.discard(runner)
        path = self._mutation_requests.pop(runner, None)
        if path is None or not isinstance(result, GitResult):
            self.operation_failed.emit("Git returned an unexpected mutation result")
            return
        if not result.succeeded:
            self.operation_failed.emit(result.error_text or "Could not update staging area")
            return
        self.mutation_ready.emit(path)
