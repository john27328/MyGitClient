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

    header = panel.context_label.text().split("\n")
    assert header[0] == "01234567 \u00b7 Add commit details"
    assert header[1].startswith("Test Author \u00b7 ")
    assert panel.context_label.text().count("Add commit details") == 1
    assert "0123456789abcdef" in panel.context_label.toolTip()
    assert "Parents: fedcba98" in panel.context_label.toolTip()
