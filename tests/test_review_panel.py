from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QDateTime, Qt
from pytestqt.qtbot import QtBot

from mygitclient.git.models import CommitFileChange, CommitSummary
from mygitclient.ui.review_panel import ReviewPanel
from mygitclient.workspace.reviews import ReviewSession


def test_review_group_expansion_survives_file_list_refresh(qtbot: QtBot, tmp_path: Path) -> None:
    panel = ReviewPanel()
    qtbot.addWidget(panel)
    session = ReviewSession(tmp_path, "refs/heads/topic", "a" * 40, "Start point")
    change = CommitFileChange("M", "src/example.py")
    panel.show_sessions((session,))
    panel.select_session(session)
    panel.show_files(session, (change,))
    pending = panel.files.topLevelItem(0)

    assert pending is not None
    pending.setExpanded(False)
    panel.update_file_state(change.path, total=2, checked=1)

    refreshed_pending = panel.files.topLevelItem(0)
    assert refreshed_pending is not None
    assert not refreshed_pending.isExpanded()


def test_refreshing_review_files_does_not_reselect_the_current_file(
    qtbot: QtBot, tmp_path: Path
) -> None:
    panel = ReviewPanel()
    qtbot.addWidget(panel)
    session = ReviewSession(tmp_path, "refs/heads/topic", "a" * 40, "Start point")
    change = CommitFileChange("M", "src/example.py")
    selected: list[CommitFileChange] = []
    panel.file_selected.connect(selected.append)
    panel.show_sessions((session,))
    panel.select_session(session)
    panel.show_files(session, (change,))
    group = panel.files.topLevelItem(0)

    assert group is not None
    item = group.child(0)
    assert item is not None
    panel.files.setCurrentItem(item)
    panel.show_files(session, (change,))

    assert selected == [change]


def test_review_boundaries_are_shown_with_local_date_and_time(qtbot: QtBot) -> None:
    panel = ReviewPanel()
    qtbot.addWidget(panel)
    commits = (
        CommitSummary(
            "a" * 40,
            (),
            "Author",
            "author@example.invalid",
            "2026-08-27T12:30:00+03:00",
            "First boundary",
        ),
        CommitSummary(
            "b" * 40,
            (),
            "Author",
            "author@example.invalid",
            "2026-08-27T13:30:00+03:00",
            "Second boundary",
        ),
    )
    selected: list[object] = []
    panel.boundary_selected.connect(selected.append)

    panel.show_boundaries(commits, commits[0].oid)

    assert panel.boundary_combo.count() == 2
    assert "T" not in panel.boundary_combo.itemText(0)
    panel.boundary_combo.setCurrentIndex(1)
    assert selected == [commits[1]]


def test_review_panel_can_mark_the_current_file(qtbot: QtBot) -> None:
    panel = ReviewPanel()
    qtbot.addWidget(panel)
    requested: list[bool] = []
    panel.mark_file_requested.connect(lambda: requested.append(True))

    panel.set_mark_file_enabled(True)
    panel.mark_file_button.click()

    assert requested == [True]


def test_review_session_displays_local_start_date_and_time(qtbot: QtBot, tmp_path: Path) -> None:
    panel = ReviewPanel()
    qtbot.addWidget(panel)
    session = ReviewSession(
        tmp_path,
        "refs/heads/topic",
        "a" * 40,
        "Start point",
        "b" * 40,
        "2026-08-27T13:02:00+03:00",
    )

    panel.show_sessions((session,))

    item = panel.sessions.topLevelItem(0)
    assert item is not None
    expected_time = QDateTime.fromString(session.start_at, Qt.DateFormat.ISODate).toLocalTime()
    assert expected_time.toString("dd.MM.yyyy HH:mm") in item.text(0)
