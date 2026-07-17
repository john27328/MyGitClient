from pathlib import Path

from pytestqt.qtbot import QtBot

from mygitclient.git.models import BranchesSnapshot, BranchInfo
from mygitclient.ui.branches_panel import BranchesPanel


def test_branches_panel_groups_refs_and_emits_checkout(qtbot: QtBot) -> None:
    panel = BranchesPanel()
    qtbot.addWidget(panel)
    current = BranchInfo("refs/heads/main", "main", "1" * 40, False, current=True)
    feature = BranchInfo(
        "refs/heads/feature",
        "feature",
        "2" * 40,
        False,
        upstream="origin/feature",
        ahead=2,
        behind=1,
    )
    remote = BranchInfo("refs/remotes/origin/main", "origin/main", "1" * 40, True)
    panel.show_branches(BranchesSnapshot(Path("repository"), (current, feature, remote)))
    local_root = panel.tree.topLevelItem(0)
    remote_root = panel.tree.topLevelItem(1)
    assert local_root is not None
    assert remote_root is not None
    assert local_root.childCount() == 2
    assert remote_root.childCount() == 1
    feature_item = local_root.child(1)
    assert feature_item is not None
    assert feature_item.text(2) == "↑ 2  ↓ 1"
    requested: list[object] = []
    panel.checkout_requested.connect(requested.append)

    panel.tree.setCurrentItem(feature_item)
    panel.tree.itemClicked.emit(feature_item, 0)
    assert panel.checkout_button.isEnabled()
    panel.checkout_button.click()

    assert requested == [feature]
    assert panel.autostash.objectName() == "checkoutAutostashCheckBox"
    assert "double-click" in panel.hint.text()
    assert panel.rename_button.isEnabled()
    assert panel.delete_button.isEnabled()
    renamed: list[object] = []
    deleted: list[object] = []
    panel.rename_requested.connect(renamed.append)
    panel.delete_requested.connect(deleted.append)
    panel.rename_button.click()
    panel.delete_button.click()
    assert renamed == [feature]
    assert deleted == [feature]
