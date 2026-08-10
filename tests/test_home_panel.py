from pathlib import Path

from pytestqt.qtbot import QtBot

from mygitclient.ui.home_panel import HomePanel


def test_home_panel_opens_recent_repository(qtbot: QtBot, tmp_path: Path) -> None:
    panel = HomePanel()
    qtbot.addWidget(panel)
    repository = tmp_path / "example"
    requested: list[Path] = []
    panel.open_repository_requested.connect(requested.append)
    panel.set_recent((repository,))

    item = panel.recent_tree.topLevelItem(0)
    assert item is not None
    panel.recent_tree.itemDoubleClicked.emit(item, 0)

    assert requested == [repository]


def test_home_panel_opens_named_workspace(qtbot: QtBot) -> None:
    panel = HomePanel()
    qtbot.addWidget(panel)
    requested: list[str] = []
    panel.open_workspace_requested.connect(requested.append)
    panel.set_workspaces(("Work", "Personal"))

    item = panel.workspace_tree.topLevelItem(1)
    assert item is not None
    panel.workspace_tree.itemDoubleClicked.emit(item, 0)

    assert requested == ["Personal"]
