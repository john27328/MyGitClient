from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from mygitclient.git.models import FileStatus, GitCommand, GitResult
from mygitclient.git.parsers import parse_status_porcelain_v2, parse_unified_diff
from mygitclient.git.runner import GitRunner


class GitService(QObject):
    status_ready = Signal(object)
    diff_ready = Signal(object)
    operation_failed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._runners: set[GitRunner] = set()
        self._diff_requests: dict[GitRunner, tuple[str, bool, bool]] = {}

    def request_status(self, repository: Path) -> GitRunner:
        runner = GitRunner(parent=self)
        self._runners.add(runner)
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

    @Slot(object)
    def _handle_status(self, result: object) -> None:
        runner = self.sender()
        if not isinstance(runner, GitRunner):
            self.operation_failed.emit("Git returned a result from an unknown operation")
            return
        self._runners.discard(runner)
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
        self.status_ready.emit(status)

    @Slot(str)
    def _handle_start_error(self, message: str) -> None:
        runner = self.sender()
        if not isinstance(runner, GitRunner):
            return
        self._runners.discard(runner)
        self._diff_requests.pop(runner, None)
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
