from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from itertools import count
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from mygitclient.git.models import GitCommand
from mygitclient.git.runner import GitRunner


@dataclass(frozen=True, slots=True)
class QueuedOperation:
    operation_id: int
    operation: str
    repository: Path


@dataclass(frozen=True, slots=True)
class OperationQueueSnapshot:
    active: QueuedOperation | None
    pending: tuple[QueuedOperation, ...]


@dataclass(slots=True)
class _QueueEntry:
    operation_id: int
    runner: GitRunner
    command: GitCommand
    input_data: bytes | None

    @property
    def operation(self) -> QueuedOperation:
        repository = self.command.working_directory or Path()
        return QueuedOperation(self.operation_id, self.command.operation, repository)


class GitOperationQueue(QObject):
    changed = Signal(object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._active: _QueueEntry | None = None
        self._pending: deque[_QueueEntry] = deque()
        self._operation_ids = count(1)

    def enqueue(
        self, runner: GitRunner, command: GitCommand, input_data: bytes | None = None
    ) -> None:
        entry = _QueueEntry(next(self._operation_ids), runner, command, input_data)
        runner.completed.connect(self._operation_finished)
        runner.failed_to_start.connect(self._operation_failed_to_start)
        self._pending.append(entry)
        self._publish()
        if self._active is None:
            self._start_next()

    def cancel(self, operation_id: int) -> None:
        if self._active is not None and self._active.operation_id == operation_id:
            self._active.runner.cancel()
            return
        removed = next(
            (entry for entry in self._pending if entry.operation_id == operation_id), None
        )
        retained = deque(entry for entry in self._pending if entry is not removed)
        if len(retained) != len(self._pending):
            self._pending = retained
            self._publish()
            if removed is not None:
                removed.runner.cancel_queued(removed.command)

    def _start_next(self) -> None:
        if self._active is not None or not self._pending:
            return
        self._active = self._pending.popleft()
        self._publish()
        self._active.runner.run(self._active.command, self._active.input_data)

    @Slot(object)
    def _operation_finished(self, _result: object) -> None:
        self._finish_sender()

    @Slot(str)
    def _operation_failed_to_start(self, _message: str) -> None:
        self._finish_sender()

    def _finish_sender(self) -> None:
        sender = self.sender()
        if self._active is None or sender is not self._active.runner:
            return
        self._active = None
        self._publish()
        QTimer.singleShot(0, self._start_next)

    def _publish(self) -> None:
        self.changed.emit(
            OperationQueueSnapshot(
                self._active.operation if self._active is not None else None,
                tuple(entry.operation for entry in self._pending),
            )
        )
