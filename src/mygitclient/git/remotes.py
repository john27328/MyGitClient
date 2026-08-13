from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from mygitclient.git.models import GitCommand, GitResult
from mygitclient.git.runner import GitRunner


class GitRemoteReader(QObject):
    """Reads configured remote URLs asynchronously through the system Git."""

    completed = Signal(object, object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._runners: dict[GitRunner, Path] = {}

    def request(self, repository: Path) -> None:
        repository = repository.resolve()
        if repository in self._runners.values():
            return
        runner = GitRunner(parent=self)
        self._runners[runner] = repository
        runner.completed.connect(self._completed)
        runner.failed_to_start.connect(self._failed_to_start)
        runner.run(
            GitCommand(
                ("config", "--null", "--get-regexp", r"^remote\..*\.url$"),
                repository,
                "read repository remotes",
            )
        )

    def shutdown(self) -> None:
        for runner in tuple(self._runners):
            runner.shutdown()
        self._runners.clear()

    @Slot(object)
    def _completed(self, value: object) -> None:
        if not isinstance(value, GitResult):
            return
        runner = self.sender()
        if not isinstance(runner, GitRunner):
            return
        urls = parse_remote_config(value.stdout) if value.succeeded else ()
        self._finish(runner, urls)

    @Slot(str)
    def _failed_to_start(self, _message: str) -> None:
        runner = self.sender()
        if isinstance(runner, GitRunner):
            self._finish(runner, ())

    def _finish(self, runner: GitRunner, urls: tuple[str, ...]) -> None:
        repository = self._runners.pop(runner, None)
        runner.deleteLater()
        if repository is not None:
            self.completed.emit(repository, urls)


def parse_remote_config(output: bytes) -> tuple[str, ...]:
    urls: list[str] = []
    for record in output.split(b"\0"):
        if not record:
            continue
        _key, separator, value = record.partition(b"\n")
        if not separator:
            continue
        url = value.decode("utf-8", errors="surrogateescape").strip()
        if url and url not in urls:
            urls.append(url)
    return tuple(urls)
