from __future__ import annotations

import hashlib
from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QColor
from pytestqt.qtbot import QtBot

from mygitclient.git.models import (
    BranchesSnapshot,
    BranchInfo,
    BranchPointSnapshot,
    CommitFileChange,
    CommitFilesSnapshot,
    CommitPage,
    CommitSummary,
    IncomingCommitsSnapshot,
    RefComparisonSnapshot,
    TagInfo,
    TagsSnapshot,
)
from mygitclient.ui.commit_graph import GRAPH_ROLE, CommitGraphRow
from mygitclient.ui.history_panel import BADGES_ROLE, FILTER_HIGHLIGHT_ROLE, HistoryPanel


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
    assert first.text(2) == "Merge feature"
    assert first.text(3) == "Test Author"
    assert first.text(5) == "merge"
    assert isinstance(first.data(0, GRAPH_ROLE), CommitGraphRow)
    assert not panel.load_more_button.isHidden()


def test_history_panel_prepends_incoming_commits_to_graph(qtbot: QtBot) -> None:
    panel = HistoryPanel()
    qtbot.addWidget(panel)
    local = _commit("local", "Local tip", "root")
    incoming = _commit("remote", "Remote change", "local")
    branch = BranchInfo(
        "refs/heads/main",
        "main",
        local.oid,
        False,
        current=True,
        upstream="origin/main",
        behind=1,
    )
    remote = BranchInfo(
        "refs/remotes/origin/main", "origin/main", incoming.oid, True
    )
    panel.show_branches(BranchesSnapshot(Path("repository"), (branch, remote)))
    panel.show_page(CommitPage(Path("repository"), (local,), 0, False))

    panel.show_incoming_commits(
        IncomingCommitsSnapshot(
            Path("repository"),
            branch.full_name,
            branch.upstream or "",
            (incoming,),
            False,
        )
    )

    assert panel.commit_count == 2
    assert panel.history_offset == 1
    first = panel.tree.topLevelItem(0)
    second = panel.tree.topLevelItem(1)
    assert first is not None and second is not None
    assert first.text(2) == "Remote change"
    assert first.text(1) == "origin/main"
    assert second.text(2) == "Local tip"
    branches = panel.refs_panel.tree.topLevelItem(0)
    assert branches is not None
    assert branches.child(0).childCount() == 0


def test_history_panel_emits_load_more_request(qtbot: QtBot) -> None:
    panel = HistoryPanel()
    qtbot.addWidget(panel)

    with qtbot.waitSignal(panel.load_more_requested, timeout=1000):
        panel.load_more_button.click()


def test_history_panel_orders_selected_cherry_pick_commits_oldest_first(
    qtbot: QtBot,
) -> None:
    panel = HistoryPanel()
    qtbot.addWidget(panel)
    newest = _commit("newest", "Newest", "older")
    older = _commit("older", "Older", "root")
    panel.show_page(CommitPage(Path("repository"), (newest, older), 0, False))
    newest_item = panel.tree.topLevelItem(0)
    older_item = panel.tree.topLevelItem(1)
    assert newest_item is not None and older_item is not None

    newest_item.setSelected(True)
    older_item.setSelected(True)

    assert panel.selected_commits == (older, newest)


def test_history_layout_stacks_commit_details_and_can_focus_diff(
    qtbot: QtBot, tmp_path: Path
) -> None:
    settings = QSettings(str(tmp_path / "history.ini"), QSettings.Format.IniFormat)
    panel = HistoryPanel(settings)
    qtbot.addWidget(panel)

    assert panel.splitter.count() == 2
    assert panel.splitter.widget(0) is panel.refs_panel
    assert panel.splitter.widget(1) is panel.content_splitter
    assert panel.content_splitter.orientation() is Qt.Orientation.Vertical
    assert panel.content_splitter.widget(1) is panel.details
    assert not panel.tree.isColumnHidden(3)
    assert panel.tree.isColumnHidden(4)
    assert panel.tree.isColumnHidden(5)

    with qtbot.waitSignal(panel.focus_mode_changed, timeout=1000):
        panel.focus_button.click()

    assert panel.focus_mode
    assert panel.refs_panel.isHidden()
    assert settings.value("history/focusDiff", type=bool) is True

    restored = HistoryPanel(settings)
    qtbot.addWidget(restored)
    assert restored.focus_mode
    assert restored.refs_panel.isHidden()


def test_history_panel_persists_author_color(qtbot: QtBot, tmp_path: Path) -> None:
    settings_path = tmp_path / "history-author-color.ini"
    settings = QSettings(str(settings_path), QSettings.Format.IniFormat)
    commit = _commit("colored", "Highlighted work", "root")
    panel = HistoryPanel(settings)
    qtbot.addWidget(panel)
    identity = commit.author_email.casefold().encode()
    key = f"history/authorColors/{hashlib.sha256(identity).hexdigest()}"
    settings.setValue(key, QColor("#c65d21").name())
    settings.sync()
    restored_settings = QSettings(str(settings_path), QSettings.Format.IniFormat)
    restored = HistoryPanel(restored_settings)
    qtbot.addWidget(restored)
    restored.show_page(CommitPage(Path("repository"), (commit,), 0, False))
    restored_item = restored.tree.topLevelItem(0)
    assert restored_item is not None
    assert restored_item.foreground(3).color().name() == "#c65d21"


def test_history_panel_labels_branch_remote_tag_and_branch_point(qtbot: QtBot) -> None:
    panel = HistoryPanel()
    qtbot.addWidget(panel)
    repository = Path("repository")
    fork_oid = "1" * 40
    head_oid = "2" * 40
    panel.show_branches(
        BranchesSnapshot(
            repository,
            (
                BranchInfo("refs/heads/main", "main", fork_oid, False),
                BranchInfo(
                    "refs/heads/feature", "feature", head_oid, False, current=True
                ),
                BranchInfo(
                    "refs/remotes/origin/feature",
                    "origin/feature",
                    head_oid,
                    True,
                ),
            ),
        )
    )
    panel.show_tags(
        TagsSnapshot(repository, (TagInfo("v1.0", head_oid, head_oid, False),))
    )
    panel.show_branch_point(
        BranchPointSnapshot(
            repository, "refs/heads/feature", "refs/heads/main", fork_oid
        )
    )
    panel.show_page(
        CommitPage(
            repository,
            (_commit(head_oid, "Feature work", fork_oid), _commit(fork_oid, "Base")),
            0,
            False,
        )
    )

    head = panel.tree.topLevelItem(0)
    fork = panel.tree.topLevelItem(1)
    assert head is not None and fork is not None
    assert head.data(1, BADGES_ROLE) == (
        ("local", "feature"),
        ("remote", "origin/feature"),
        ("tag", "v1.0"),
    )
    assert fork.data(1, BADGES_ROLE) == (
        ("local", "main"),
        ("fork", "from main"),
    )


def test_history_panel_filters_loaded_commits(qtbot: QtBot) -> None:
    panel = HistoryPanel()
    qtbot.addWidget(panel)
    page = CommitPage(
        Path("repository"),
        (
            _commit("abc123", "Update documentation"),
            _commit("def456", "Fix checkout"),
        ),
        0,
        False,
    )
    panel.show_page(page)

    panel.filter_edit.setText("checkout")

    first = panel.tree.topLevelItem(0)
    second = panel.tree.topLevelItem(1)
    assert first is not None and second is not None
    assert first.isHidden()
    assert not second.isHidden()
    assert panel.filter_count.text() == "1 of 2 commits"
    assert panel.tree.isColumnHidden(0)
    assert second.data(2, FILTER_HIGHLIGHT_ROLE) == "checkout"

    panel.filter_edit.setText("author@example.invalid")
    assert not first.isHidden()
    assert not second.isHidden()
    assert first.data(3, FILTER_HIGHLIGHT_ROLE) is None

    panel.filter_edit.clear()
    assert not panel.tree.isColumnHidden(0)
    assert second.data(2, FILTER_HIGHLIGHT_ROLE) is None


def test_history_panel_shows_commit_details_and_emits_file_selection(
    qtbot: QtBot,
) -> None:
    panel = HistoryPanel()
    qtbot.addWidget(panel)
    commit = _commit("0123456789abcdef", "Update documentation", "parent")
    panel.show_page(CommitPage(Path("repository"), (commit,), 0, False))
    selected_commits: list[object] = []
    selected_files: list[tuple[object, object]] = []
    panel.commit_selected.connect(selected_commits.append)

    def capture_file(selected_commit: object, file: object) -> None:
        selected_files.append((selected_commit, file))

    panel.file_selected.connect(capture_file)

    commit_item = panel.tree.topLevelItem(0)
    assert commit_item is not None
    panel.tree.setCurrentItem(commit_item)
    change = CommitFileChange("M", "README.md")
    panel.show_files(CommitFilesSnapshot(Path("repository"), commit.oid, (change,)))
    file_item = panel.files.topLevelItem(0)
    assert file_item is not None
    panel.files.setCurrentItem(file_item)

    assert selected_commits == [commit]
    assert "Update documentation" in panel.details_label.text()
    assert commit.oid in panel.details_label.text()
    assert selected_files == [(commit, change)]


def test_history_panel_shows_ref_comparison_and_emits_file_selection(
    qtbot: QtBot,
) -> None:
    panel = HistoryPanel()
    qtbot.addWidget(panel)
    change = CommitFileChange("M", "README.md")
    snapshot = RefComparisonSnapshot(
        Path("repository"), "refs/heads/main", "refs/heads/feature", (change,)
    )
    selected: list[tuple[object, object, object]] = []

    def capture(base: str, compare: str, file: object) -> None:
        selected.append((base, compare, file))

    panel.comparison_file_selected.connect(capture)

    panel.show_comparison(snapshot)
    item = panel.files.topLevelItem(0)
    assert item is not None
    panel.files.setCurrentItem(item)

    assert "refs/heads/main → refs/heads/feature" in panel.details_label.text()
    assert selected == [("refs/heads/main", "refs/heads/feature", change)]
