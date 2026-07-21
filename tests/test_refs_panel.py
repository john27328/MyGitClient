from pathlib import Path

from pytestqt.qtbot import QtBot

from mygitclient.git.models import BranchesSnapshot, BranchInfo, TagInfo, TagsSnapshot
from mygitclient.ui.refs_panel import RefsPanel


def test_refs_panel_groups_filters_and_selects_refs(qtbot: QtBot) -> None:
    panel = RefsPanel()
    qtbot.addWidget(panel)
    current = BranchInfo("refs/heads/main", "main", "1" * 40, False, current=True)
    feature = BranchInfo("refs/heads/feature", "feature", "2" * 40, False)
    remote = BranchInfo(
        "refs/remotes/origin/main", "origin/main", "1" * 40, True
    )
    selected: list[str] = []
    panel.ref_selected.connect(selected.append)

    panel.show_branches(
        BranchesSnapshot(Path("repository"), (current, feature, remote))
    )
    panel.show_tags(
        TagsSnapshot(
            Path("repository"),
            (TagInfo("v1.0", "3" * 40, "3" * 40, False, "Release"),),
        )
    )

    assert panel.tree.topLevelItemCount() == 3
    assert panel.selected_ref == "refs/heads/main"
    assert selected == ["refs/heads/main"]
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
