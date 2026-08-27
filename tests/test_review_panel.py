from __future__ import annotations

from pathlib import Path

from pytestqt.qtbot import QtBot

from mygitclient.git.models import CommitFileChange
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
