from __future__ import annotations

import subprocess
from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QStackedWidget, QTabWidget, QWidget
from pytest import mark
from pytestqt.qtbot import QtBot

from mygitclient.git.models import BranchesSnapshot, CommitFileChange
from mygitclient.git.service import GitService
from mygitclient.ui.diff_view import DiffView
from mygitclient.ui.review_controller import ReviewController
from mygitclient.ui.review_panel import ReviewPanel
from mygitclient.workspace.reviews import ReviewSession, ReviewStore


def _git(repository: Path, *arguments: str) -> str:
    return subprocess.check_output(
        [
            "git", "-c", "user.name=Review Test", "-c", "user.email=test@example.invalid",
            *arguments,
        ],
        cwd=repository,
        stderr=subprocess.PIPE,
    ).decode().strip()


@mark.parametrize("deleted_before_selection", [False, True])
@mark.parametrize("remote", [False, True])
def test_deleted_branch_review_is_removed_without_repeated_errors(
    qtbot: QtBot, tmp_path: Path, deleted_before_selection: bool, remote: bool
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    _git(repository, "init", "--initial-branch=main")
    tracked = repository / "tracked.txt"
    tracked.write_text("base\n", encoding="utf-8")
    _git(repository, "add", ".")
    _git(repository, "commit", "-m", "base")
    base = _git(repository, "rev-parse", "HEAD")
    _git(repository, "switch", "-c", "topic")
    tracked.write_text("changed\n", encoding="utf-8")
    _git(repository, "commit", "-am", "topic")
    branch_ref = "refs/remotes/origin/topic" if remote else "refs/heads/topic"
    if remote:
        _git(repository, "update-ref", branch_ref, "HEAD")
    _git(repository, "switch", "main")

    settings = QSettings(str(tmp_path / "reviews.ini"), QSettings.Format.IniFormat)
    store = ReviewStore(settings)
    session = ReviewSession(repository, branch_ref, base, "base")
    kept = ReviewSession(repository, "refs/heads/main", base, "base")
    elsewhere = ReviewSession(tmp_path / "elsewhere", branch_ref, base, "base")
    for saved in (session, kept, elsewhere):
        store.save(saved)
    store.set_reviewed_file(session, "tracked.txt", "fingerprint")
    store.set_reviewed_file(kept, "tracked.txt", "keep-fingerprint")

    parent = QWidget()
    qtbot.addWidget(parent)
    tabs = QTabWidget(parent)
    tabs.addTab(QWidget(), "Changes")
    panel = ReviewPanel(settings)
    tabs.addTab(panel, "Review")
    tabs.setCurrentIndex(1)
    container = QStackedWidget(parent)
    diff = DiffView(settings)
    container.addWidget(diff)
    service = GitService(parent=parent)
    controller = ReviewController(
        settings, service, panel, diff, container, tabs,
        review_tab=1, context_lines=lambda: 3, ignore_whitespace=lambda: False,
        parent_widget=parent,
    )

    def show_branches(value: object) -> None:
        assert isinstance(value, BranchesSnapshot)
        controller.set_branches(value.branches)

    service.branches_ready.connect(show_branches)
    service.comparison_ready.connect(controller.handle_comparison)
    service.comparison_diff_ready.connect(controller.handle_comparison_diff)
    errors: list[str] = []
    service.operation_failed.connect(errors.append)
    controller.activate_repository(repository)

    if not deleted_before_selection:
        with qtbot.waitSignal(service.comparison_ready, timeout=5000):
            panel.select_session(session)
        with qtbot.waitSignal(service.comparison_diff_ready, timeout=5000):
            controller.select_file(CommitFileChange("M", "tracked.txt"))
        assert diff.current_diff is not None
        assert panel.files.topLevelItemCount() == 1

    _git(repository, "update-ref", "-d", branch_ref)
    with qtbot.waitSignal(service.branches_ready, timeout=5000):
        if deleted_before_selection:
            panel.select_session(session)
        else:
            controller.refresh()

    assert store.sessions(repository) == (kept,)
    assert store.sessions(elsewhere.repository) == (elsewhere,)
    assert store.reviewed_file(session, "tracked.txt") is None
    assert store.reviewed_file(kept, "tracked.txt") == "keep-fingerprint"
    assert panel.sessions.topLevelItemCount() == 1
    assert panel.selected_session is None
    assert panel.files.topLevelItemCount() == 0
    assert not panel.delete_button.isEnabled()
    assert panel.boundary_combo.count() == 0
    assert diff.current_diff is None

    for _ in range(3):
        controller.refresh()
    assert errors == []

    # Removing the stale review must leave the remaining session usable.
    with qtbot.waitSignal(service.comparison_ready, timeout=5000):
        panel.select_session(kept)
    assert errors == []

    # A branch-list update can also remove an unselected review. Reload the
    # surviving selection after rebuilding the list, without requesting branches again.
    store.save(session)
    with qtbot.waitSignal(service.comparison_ready, timeout=5000):
        service.request_branches(repository)
    assert panel.selected_session == kept
    assert store.sessions(repository) == (kept,)
    assert errors == []
