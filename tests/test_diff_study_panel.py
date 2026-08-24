from __future__ import annotations

from pathlib import Path

from pytestqt.qtbot import QtBot

from mygitclient.git.models import CommitPage, CommitSummary
from mygitclient.ui.diff_study_panel import DiffStudyPanel


def test_selected_commit_shows_details_above_files(qtbot: QtBot) -> None:
    panel = DiffStudyPanel()
    qtbot.addWidget(panel)
    commit = CommitSummary(
        oid="0123456789abcdef",
        parent_oids=("fedcba9876543210",),
        author_name="Test Author",
        author_email="author@example.invalid",
        authored_at="2026-08-24T14:00:00+03:00",
        subject="Add commit details",
    )
    panel.show_page(CommitPage(Path("repository"), (commit,), 0, False))
    item = panel.commits.topLevelItem(0)
    assert item is not None

    panel.commits.setCurrentItem(item)

    assert panel.commit_details_label.text() == (
        "Add commit details\n\n"
        "Commit: 0123456789abcdef\n"
        "Author: Test Author <author@example.invalid>\n"
        "Date: 2026-08-24T14:00:00+03:00\n"
        "Parents: fedcba98"
    )
