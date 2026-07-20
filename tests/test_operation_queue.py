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


def test_workflow_continuation_runs_before_other_pending_mutations(
    qtbot: QtBot, tmp_path: Path
) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    queue = GitOperationQueue()
    first = GitRunner()
    second = GitRunner()
    continuation = GitRunner()
    started: list[str] = []

    def record_started(command: object) -> None:
        assert isinstance(command, GitCommand)
        started.append(command.operation)

    for runner in (first, second, continuation):
        runner.started.connect(record_started)

    def enqueue_continuation(_result: object) -> None:
        queue.enqueue(
            continuation,
            GitCommand(("status",), tmp_path, "workflow continuation"),
            continuation=True,
        )

    first.completed.connect(enqueue_continuation)
    queue.enqueue(first, GitCommand(("status",), tmp_path, "workflow start"))
    queue.enqueue(second, GitCommand(("status",), tmp_path, "ordinary mutation"))

    qtbot.waitUntil(lambda: len(started) == 3, timeout=5000)
    assert started == ["workflow start", "workflow continuation", "ordinary mutation"]
