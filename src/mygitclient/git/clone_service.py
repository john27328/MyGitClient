from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from mygitclient.git.credentials import github_extraheader_arguments
from mygitclient.git.errors import format_git_error
from mygitclient.git.models import GitCommand, GitResult
from mygitclient.git.operation_queue import sanitize_operation_output
from mygitclient.git.runner import GitRunner


class CloneService(QObject):
    progress = Signal(str)
    completed = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._runner: GitRunner | None = None

    @property
    def is_running(self) -> bool:
        return self._runner is not None

    def clone(self, url: str, target: Path, *, token: str | None = None) -> bool:
        if self._runner is not None:
            return False
        runner = GitRunner(parent=self)
        self._runner = runner
        runner.output_available.connect(self._output_available)
        runner.completed.connect(self._completed)
        runner.failed_to_start.connect(self._failed_to_start)
        auth_arguments = github_extraheader_arguments(token) if token else ()
        runner.run(
            GitCommand(
                (*auth_arguments, "clone", "--progress", "--", url, str(target)),
                target.parent,
                "clone repository",
            )
        )
        return True

    def cancel(self) -> None:
        if self._runner is not None:
            self._runner.cancel()

    @Slot(bytes, bytes)
    def _output_available(self, stdout: bytes, stderr: bytes) -> None:
        output = (stdout + stderr).decode("utf-8", errors="replace")
        lines = [line.strip() for line in output.replace("\r", "\n").splitlines()]
        message = next((line for line in reversed(lines) if line), "")
        if message:
            self.progress.emit(sanitize_operation_output(message))

    @Slot(object)
    def _completed(self, value: object) -> None:
        runner = self._runner
        self._runner = None
        if runner is not None:
            runner.deleteLater()
        if not isinstance(value, GitResult):
            self.failed.emit("Git returned an unexpected clone result")
            return
        if value.cancelled:
            self.cancelled.emit()
        elif value.succeeded:
            target = Path(value.command.arguments[-1])
            self.completed.emit(target)
        else:
            self.failed.emit(format_git_error(value.error_text, operation="clone repository"))

    @Slot(str)
    def _failed_to_start(self, message: str) -> None:
        runner = self._runner
        self._runner = None
        if runner is not None:
            runner.deleteLater()
        self.failed.emit(f"Could not start Git: {message}")


def suggested_clone_name(url: str) -> str:
    value = url.strip().rstrip("/\\")
    name = value.rsplit("/", 1)[-1].rsplit(":", 1)[-1]
    if name.casefold().endswith(".git"):
        name = name[:-4]
    return name or "repository"


def is_valid_clone_folder_name(value: str) -> bool:
    name = value.strip()
    return bool(name) and name not in {".", ".."} and "/" not in name and "\\" not in name
