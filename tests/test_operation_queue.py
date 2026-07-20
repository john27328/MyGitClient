from __future__ import annotations

import subprocess
from pathlib import Path

from pytestqt.qtbot import QtBot

from mygitclient.git.models import GitCommand
from mygitclient.git.operation_queue import GitOperationQueue, OperationQueueSnapshot
from mygitclient.git.runner import GitRunner


def test_network_operations_run_in_order_and_pending_operation_can_be_removed(
    qtbot: QtBot, tmp_path: Path
) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    queue = GitOperationQueue()
    snapshots: list[OperationQueueSnapshot] = []
    queue.changed.connect(snapshots.append)
    first = GitRunner()
    second = GitRunner()
    second_results: list[object] = []
    second.completed.connect(second_results.append)

    queue.enqueue(first, GitCommand(("status",), tmp_path, "first operation"))
    queue.enqueue(second, GitCommand(("status",), tmp_path, "second operation"))

    snapshot = snapshots[-1]
    assert snapshot.active is not None
    assert snapshot.active.operation == "first operation"
    assert [item.operation for item in snapshot.pending] == ["second operation"]
    queue.cancel(snapshot.pending[0].operation_id)

    assert snapshots[-1].pending == ()
    assert len(second_results) == 1
    qtbot.waitUntil(lambda: snapshots[-1].active is None, timeout=5000)
