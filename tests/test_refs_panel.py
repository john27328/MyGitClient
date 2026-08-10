from pathlib import Path

from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from mygitclient.git.models import (
    BranchesSnapshot,
    BranchInfo,
    StashesSnapshot,
    StashInfo,
    TagInfo,
    TagsSnapshot,
)
from mygitclient.ui.refs_panel import RefsPanel
from mygitclient.workspace import LinkedRepository


def test_refs_panel_groups_filters_and_selects_refs(qtbot: QtBot) -> None:
    panel = RefsPanel()
    qtbot.addWidget(panel)
    current = BranchInfo("refs/heads/main", "main", "1" * 40, False, current=True)
    feature = BranchInfo("refs/heads/feature", "feature", "2" * 40, False)
    remote = BranchInfo(
        "refs/remotes/origin/main", "origin/main", "1" * 40, True
    )
    selected: list[object] = []
    panel.refs_selected.connect(selected.append)

    panel.show_branches(
        BranchesSnapshot(Path("repository"), (current, feature, remote))
    )
    panel.show_tags(
        TagsSnapshot(
            Path("repository"),
            (TagInfo("v1.0", "3" * 40, "3" * 40, False, "Release"),),
        )
    )

    assert panel.tree.topLevelItemCount() == 5
    assert panel.selected_ref == "refs/heads/main"
    assert selected == [("refs/heads/main",)]
    remotes = panel.tree.topLevelItem(1)
    tags = panel.tree.topLevelItem(2)
    assert remotes is not None and remotes.child(0).text(0) == "origin"
    assert tags is not None and tags.child(0).text(0) == "v1.0"

    panel.filter_edit.setText("feature")

    branches = panel.tree.topLevelItem(0)
    assert branches is not None
    assert branches.child(0).isHidden()
    assert not branches.child(1).isHidden()
    assert remotes.isHidden()
    assert tags.isHidden()

    panel.filter_edit.clear()
    feature_index = panel.compare_combo.findData("refs/heads/feature")
    assert feature_index > 0
    panel.compare_combo.setCurrentIndex(feature_index)
    assert panel.selected_refs == ("refs/heads/main", "refs/heads/feature")
    assert selected[-1] == ("refs/heads/main", "refs/heads/feature")

    panel.compare_combo.setCurrentIndex(0)
    assert panel.selected_refs == ("refs/heads/main",)


def test_refs_panel_exposes_branch_context_actions(qtbot: QtBot) -> None:
    panel = RefsPanel()
    qtbot.addWidget(panel)
    branch = BranchInfo("refs/heads/feature", "feature", "2" * 40, False)
    panel.show_branches(BranchesSnapshot(Path("repository"), (branch,)))
    branches = panel.tree.topLevelItem(0)
    assert branches is not None
    panel.tree.setCurrentItem(branches.child(0))
    deleted: list[object] = []
    forced: list[object] = []
    rebased: list[object] = []
    panel.delete_requested.connect(deleted.append)
    panel.force_delete_requested.connect(forced.append)
    panel.rebase_requested.connect(rebased.append)

    panel.delete_action.trigger()
    panel.force_delete_action.trigger()
    panel.rebase_action.trigger()

    assert deleted == [branch]
    assert forced == [branch]
    assert rebased == [branch]


def test_refs_panel_marks_local_branch_sync_states(qtbot: QtBot) -> None:
    panel = RefsPanel()
    qtbot.addWidget(panel)
    current = BranchInfo(
        "refs/heads/main",
        "main",
        "1" * 40,
        False,
        current=True,
        upstream="origin/main",
        ahead=2,
        behind=1,
    )
    unpublished = BranchInfo("refs/heads/draft", "draft", "2" * 40, False)
    gone = BranchInfo(
        "refs/heads/old",
        "old",
        "3" * 40,
        False,
        upstream="origin/old",
        upstream_gone=True,
    )

    panel.show_branches(
        BranchesSnapshot(Path("repository"), (current, unpublished, gone))
    )

    branches = panel.tree.topLevelItem(0)
    assert branches is not None
    assert branches.child(0).text(0) == "main  ✓ ↑2 ↓1"
    assert "Upstream: origin/main" in branches.child(0).toolTip(0)
    assert branches.child(0).font(0).bold()
    assert branches.child(1).text(0) == "draft  ○"
    assert "Not published" in branches.child(1).toolTip(0)
    assert branches.child(2).text(0) == "old  ⚠"
    assert "Upstream gone: origin/old" in branches.child(2).toolTip(0)


def test_refs_panel_exposes_remote_delete_and_copy_actions(qtbot: QtBot) -> None:
    panel = RefsPanel()
    qtbot.addWidget(panel)
    branch = BranchInfo(
        "refs/remotes/origin/feature", "origin/feature", "2" * 40, True
    )
    panel.show_branches(BranchesSnapshot(Path("repository"), (branch,)))
    remotes = panel.tree.topLevelItem(1)
    assert remotes is not None
    origin = remotes.child(0)
    assert origin is not None
    panel.tree.setCurrentItem(origin.child(0))
    deleted: list[object] = []
    panel.remote_delete_requested.connect(deleted.append)

    panel.copy_branch_action.trigger()
    panel.remote_delete_action.trigger()

    assert QApplication.clipboard().text() == "origin/feature"
    assert deleted == [branch]


def test_refs_panel_creates_publishes_and_compares_from_context(qtbot: QtBot) -> None:
    panel = RefsPanel()
    qtbot.addWidget(panel)
    local = BranchInfo(
        "refs/heads/feature",
        "feature",
        "2" * 40,
        False,
        upstream="origin/feature",
    )
    unpublished = BranchInfo("refs/heads/draft", "draft", "3" * 40, False)
    remote = BranchInfo(
        "refs/remotes/origin/feature", "origin/feature", "2" * 40, True
    )
    panel.show_branches(
        BranchesSnapshot(Path("repository"), (local, unpublished, remote))
    )
    created: list[object] = []
    published: list[object] = []
    selected: list[object] = []
    panel.create_branch_from_requested.connect(created.append)
    panel.publish_branch_requested.connect(published.append)
    panel.refs_selected.connect(selected.append)
    branches = panel.tree.topLevelItem(0)
    assert branches is not None

    panel.tree.setCurrentItem(branches.child(0))
    panel.create_branch_from_action.trigger()
    panel.compare_upstream_action.trigger()
    panel.tree.setCurrentItem(branches.child(1))
    panel.publish_branch_action.trigger()

    assert created == [local]
    assert ("refs/heads/feature", "refs/remotes/origin/feature") in selected
    assert published == [unpublished]


def test_cleanup_gone_branches_emits_only_safe_candidates(qtbot: QtBot) -> None:
    panel = RefsPanel()
    qtbot.addWidget(panel)
    gone = BranchInfo(
        "refs/heads/old",
        "old",
        "1" * 40,
        False,
        upstream="origin/old",
        upstream_gone=True,
    )
    current_gone = BranchInfo(
        "refs/heads/current",
        "current",
        "2" * 40,
        False,
        current=True,
        upstream="origin/current",
        upstream_gone=True,
    )
    live = BranchInfo(
        "refs/heads/live",
        "live",
        "3" * 40,
        False,
        upstream="origin/live",
    )
    panel.show_branches(
        BranchesSnapshot(Path("repository"), (gone, current_gone, live))
    )
    requested: list[object] = []
    panel.cleanup_gone_requested.connect(requested.append)

    panel.cleanup_gone_action.trigger()

    assert requested == [(gone,)]


def test_refs_panel_shows_stashes_and_submodules(qtbot: QtBot, tmp_path: Path) -> None:
    panel = RefsPanel()
    qtbot.addWidget(panel)
    stash = StashInfo("stash@{0}", "4" * 40, "On main: saved work")
    submodule = LinkedRepository(tmp_path / "library", "submodule")
    panel.show_stashes(StashesSnapshot(Path("repository"), (stash,)))
    panel.show_linked_repositories((submodule,))

    stashes = panel.tree.topLevelItem(3)
    submodules = panel.tree.topLevelItem(4)
    assert stashes is not None and "saved work" in stashes.child(0).text(0)
    assert submodules is not None and submodules.child(0).text(0) == "library"
    applied: list[object] = []
    popped: list[object] = []
    dropped: list[object] = []
    opened: list[object] = []
    panel.stash_apply_requested.connect(applied.append)
    panel.stash_pop_requested.connect(popped.append)
    panel.stash_drop_requested.connect(dropped.append)
    panel.repository_requested.connect(opened.append)

    panel.tree.setCurrentItem(stashes.child(0))
    panel.apply_stash_action.trigger()
    panel.pop_stash_action.trigger()
    panel.drop_stash_action.trigger()
    panel.tree.setCurrentItem(submodules.child(0))
    panel.open_repository_action.trigger()

    assert applied == [stash]
    assert popped == [stash]
    assert dropped == [stash]
    assert opened == [submodule]


def test_refs_panel_nests_recursive_submodules(qtbot: QtBot, tmp_path: Path) -> None:
    panel = RefsPanel()
    qtbot.addWidget(panel)
    parent = LinkedRepository(tmp_path / "vendor" / "library", "submodule")
    child = LinkedRepository(parent.path / "dependencies" / "codec", "submodule")

    panel.show_linked_repositories((child, parent))

    root = panel.tree.topLevelItem(4)
    assert root is not None
    assert root.childCount() == 1
    parent_item = root.child(0)
    assert parent_item.text(0) == "library"
    assert parent_item.childCount() == 1
    assert parent_item.child(0).text(0) == "codec"
