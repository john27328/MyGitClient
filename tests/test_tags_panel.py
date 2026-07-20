from pathlib import Path

from pytestqt.qtbot import QtBot

from mygitclient.git.models import TagInfo, TagsSnapshot
from mygitclient.ui.tags_panel import TagsPanel


def test_tags_panel_lists_tags_and_emits_selected_actions(qtbot: QtBot) -> None:
    panel = TagsPanel()
    qtbot.addWidget(panel)
    tag = TagInfo("v1.0", "tag-object", "commit-object", True, "Release 1.0")
    panel.show_tags(TagsSnapshot(Path("repository"), (tag,)))

    item = panel.tree.topLevelItem(0)
    assert item is not None
    panel.tree.setCurrentItem(item)
    assert item.text(1) == "Annotated"
    assert item.text(2) == "commit-o"
    assert panel.delete_button.isEnabled()
    assert panel.push_button.isEnabled()

    deleted: list[object] = []
    pushed: list[object] = []
    panel.delete_requested.connect(deleted.append)
    panel.push_requested.connect(pushed.append)
    panel.delete_button.click()
    panel.push_button.click()
    assert deleted == [tag]
    assert pushed == [tag]
