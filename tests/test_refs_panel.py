from pathlib import Path

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
    panel.delete_requested.connect(deleted.append)
    panel.force_delete_requested.connect(forced.append)

    panel.delete_action.trigger()
    panel.force_delete_action.trigger()

    assert deleted == [branch]
    assert forced == [branch]


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
