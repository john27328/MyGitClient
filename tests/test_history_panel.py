from __future__ import annotations

from pathlib import Path

from pytestqt.qtbot import QtBot

from mygitclient.git.models import CommitPage, CommitSummary
from mygitclient.ui.commit_graph import GRAPH_ROLE, CommitGraphRow
from mygitclient.ui.history_panel import HistoryPanel


def _commit(oid: str, subject: str, *parents: str) -> CommitSummary:
    return CommitSummary(
        oid=oid,
        parent_oids=parents,
        author_name="Test Author",
        author_email="author@example.invalid",
        authored_at="2026-07-17T10:30:00+03:00",
        subject=subject,
    )


def test_history_panel_renders_page_and_graph(qtbot: QtBot) -> None:
    panel = HistoryPanel()
    qtbot.addWidget(panel)
    page = CommitPage(
        Path("repository"),
        (
            _commit("merge", "Merge feature", "main", "feature"),
            _commit("main", "Main work", "root"),
        ),
        offset=0,
        has_more=True,
    )

    panel.show_page(page)

    assert panel.commit_count == 2
    first = panel.tree.topLevelItem(0)
    assert first is not None
    assert first.text(1) == "Merge feature"
    assert first.text(2) == "Test Author"
    assert first.text(4) == "merge"
    assert isinstance(first.data(0, GRAPH_ROLE), CommitGraphRow)
    assert not panel.load_more_button.isHidden()


def test_history_panel_emits_load_more_request(qtbot: QtBot) -> None:
    panel = HistoryPanel()
    qtbot.addWidget(panel)

    with qtbot.waitSignal(panel.load_more_requested, timeout=1000):
        panel.load_more_button.click()
