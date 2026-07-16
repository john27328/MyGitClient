from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Signal

from mygitclient.git.executable import find_git_executable
from mygitclient.git.models import GitCommand, GitResult

logger = logging.getLogger(__name__)


class GitRunner(QObject):
    """Runs one Git command asynchronously without blocking Qt's event loop."""

    started = Signal(object)
    completed = Signal(object)
    failed_to_start = Signal(str)
    output_available = Signal(bytes, bytes)

    def __init__(self, executable: Path | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._executable = executable or find_git_executable()
        self._process = QProcess(self)
        self._command: GitCommand | None = None
        self._stdout = bytearray()
        self._stderr = bytearray()

        self._process.readyReadStandardOutput.connect(self._read_stdout)
        self._process.readyReadStandardError.connect(self._read_stderr)
        self._process.finished.connect(self._on_finished)
        self._process.errorOccurred.connect(self._on_error)

    @property
    def is_running(self) -> bool:
        return self._process.state() is not QProcess.ProcessState.NotRunning

    def run(self, command: GitCommand, input_data: bytes | None = None) -> None:
        if self.is_running:
            raise RuntimeError("This Git runner is already executing a command")

        self._command = command
        self._stdout.clear()
        self._stderr.clear()
        if command.working_directory is not None:
            self._process.setWorkingDirectory(str(command.working_directory))

        environment = QProcessEnvironment.systemEnvironment()
        environment.insert("GIT_TERMINAL_PROMPT", "0")
        environment.insert("LC_ALL", "C")
        self._process.setProcessEnvironment(environment)

        logger.info("Running git operation %s", command.operation)
        self._process.start(str(self._executable), list(command.arguments))
        if input_data is not None:
            self._process.write(input_data)
            self._process.closeWriteChannel()
        self.started.emit(command)

    def cancel(self) -> None:
        if not self.is_running:
            return
        logger.info("Cancelling git operation")
        self._process.terminate()
        QTimer.singleShot(1500, self._kill_if_running)

    def _kill_if_running(self) -> None:
        if self.is_running:
            self._process.kill()

    def _read_stdout(self) -> None:
        chunk = self._process.readAllStandardOutput().data()
        self._stdout.extend(chunk)
        self.output_available.emit(chunk, b"")

    def _read_stderr(self) -> None:
        chunk = self._process.readAllStandardError().data()
        self._stderr.extend(chunk)
        self.output_available.emit(b"", chunk)

    def _on_finished(self, exit_code: int, _exit_status: QProcess.ExitStatus) -> None:
        self._read_stdout()
        self._read_stderr()
        command = self._command
        if command is None:
            return
        result = GitResult(command, exit_code, bytes(self._stdout), bytes(self._stderr))
        logger.info("Git operation %s finished with code %d", command.operation, exit_code)
        self._command = None
        self.completed.emit(result)

    def _on_error(self, error: QProcess.ProcessError) -> None:
        if error is QProcess.ProcessError.FailedToStart:
            message = self._process.errorString()
            logger.error("Could not start Git: %s", message)
            self.failed_to_start.emit(message)
