from __future__ import annotations

from dataclasses import dataclass
from itertools import count
from pathlib import Path
from threading import Event

from PySide6.QtCore import QObject, QThread, Signal, Slot

from mygitclient.workspace.manager import LinkedRepository, discover_linked_repositories


@dataclass(frozen=True, slots=True)
class LinkedRepositoriesSnapshot:
    request_id: int
    repository: Path
    repositories: tuple[LinkedRepository, ...]


@dataclass(frozen=True, slots=True)
class _DiscoveryFailure:
    request_id: int
    message: str


class _DiscoveryWorker(QObject):
    completed = Signal(object)
    failed = Signal(object)
    finished = Signal()

    def __init__(self, request_id: int, repository: Path, cancelled: Event) -> None:
        super().__init__()
        self._request_id = request_id
        self._repository = repository
        self._cancelled = cancelled

    @Slot()
    def run(self) -> None:
        try:
            repositories = discover_linked_repositories(
                self._repository, cancelled=self._cancelled.is_set
            )
            if not self._cancelled.is_set():
                self.completed.emit(
                    LinkedRepositoriesSnapshot(
                        self._request_id, self._repository, repositories
                    )
                )
        except (OSError, ValueError) as error:
            if not self._cancelled.is_set():
                self.failed.emit(
                    _DiscoveryFailure(
                        self._request_id,
                        f"Could not discover linked repositories: {error}",
                    )
                )
        finally:
            self.finished.emit()


class WorkspaceDiscoveryService(QObject):
    linked_repositories_ready = Signal(object)
    operation_failed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._request_ids = count(1)
        self._latest_request: int | None = None
        self._requests: dict[QThread, tuple[_DiscoveryWorker, Event]] = {}

    @property
    def is_running(self) -> bool:
        return bool(self._requests)

    def request_linked_repositories(self, repository: Path) -> None:
        self.cancel_all()
        request_id = next(self._request_ids)
        self._latest_request = request_id
        cancelled = Event()
        thread = QThread(self)
        worker = _DiscoveryWorker(request_id, repository, cancelled)
        worker.moveToThread(thread)
        self._requests[thread] = (worker, cancelled)
        thread.started.connect(worker.run)
        worker.completed.connect(self._handle_completed)
        worker.failed.connect(self._handle_failed)
        worker.finished.connect(worker.deleteLater)
        worker.finished.connect(thread.quit)
        thread.finished.connect(self._release)
        thread.start()

    def cancel_all(self) -> None:
        self._latest_request = None
        for _worker, cancelled in self._requests.values():
            cancelled.set()

    @Slot(object)
    def _handle_completed(self, value: object) -> None:
        if isinstance(value, LinkedRepositoriesSnapshot) and (
            value.request_id == self._latest_request
        ):
            self._latest_request = None
            self.linked_repositories_ready.emit(value)

    @Slot(object)
    def _handle_failed(self, value: object) -> None:
        if isinstance(value, _DiscoveryFailure) and value.request_id == self._latest_request:
            self._latest_request = None
            self.operation_failed.emit(value.message)

    @Slot()
    def _release(self) -> None:
        thread = self.sender()
        if not isinstance(thread, QThread):
            return
        self._requests.pop(thread, None)
        thread.deleteLater()
