from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from mygitclient.git.models import GitCommand, GitResult
from mygitclient.git.parsers import parse_status_porcelain_v2
from mygitclient.git.runner import GitRunner


class GitService(QObject):
    status_ready = Signal(object)
    operation_failed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._runners: set[GitRunner] = set()

    def request_status(self, repository: Path) -> GitRunner:
        runner = GitRunner(parent=self)
        self._runners.add(runner)
        runner.completed.connect(self._handle_status)
        runner.failed_to_start.connect(self._handle_start_error)
        runner.run(
            GitCommand(
                arguments=("status", "--porcelain=v2", "--branch", "-z"),
                working_directory=repository,
                operation="read repository status",
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
        self.operation_failed.emit(message)
