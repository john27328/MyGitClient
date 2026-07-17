from pathlib import Path

from pytestqt.qtbot import QtBot

from mygitclient.workspace import (
    LinkedRepositoriesSnapshot,
    WorkspaceDiscoveryService,
)


def test_linked_repositories_are_discovered_in_background(
    qtbot: QtBot, tmp_path: Path
) -> None:
    repository = tmp_path / "repository"
    nested = repository / "nested"
    (repository / ".git").mkdir(parents=True)
    (nested / ".git").mkdir(parents=True)
    service = WorkspaceDiscoveryService()
    received: list[object] = []
    service.linked_repositories_ready.connect(received.append)

    with qtbot.waitSignal(service.linked_repositories_ready, timeout=5000):
        service.request_linked_repositories(repository)

    assert len(received) == 1
    snapshot = received[0]
    assert isinstance(snapshot, LinkedRepositoriesSnapshot)
    assert snapshot.repository == repository
    assert [(item.path, item.kind) for item in snapshot.repositories] == [
        (nested.resolve(), "nested")
    ]
    qtbot.waitUntil(lambda: not service.is_running, timeout=5000)


def test_cancelled_discovery_does_not_publish_result(qtbot: QtBot, tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    (repository / ".git").mkdir(parents=True)
    service = WorkspaceDiscoveryService()
    received: list[object] = []
    service.linked_repositories_ready.connect(received.append)

    service.request_linked_repositories(repository)
    service.cancel_all()

    qtbot.waitUntil(lambda: not service.is_running, timeout=5000)
    assert received == []
