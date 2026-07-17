from pathlib import Path

from PySide6.QtCore import Qt
from pytestqt.qtbot import QtBot

from mygitclient.ui.repositories_panel import RepositoriesPanel


def test_recent_repository_activation_emits_path(qtbot: QtBot, tmp_path: Path) -> None:
    panel = RepositoriesPanel()
    qtbot.addWidget(panel)
    repository = tmp_path / "project"

    panel.set_recent((repository,))
    item = panel.tree.topLevelItem(0)
    assert item is not None
    received: list[object] = []
    panel.repository_activated.connect(received.append)

    with qtbot.waitSignal(panel.repository_activated):
        panel.tree.itemActivated.emit(item, 0)
    assert received == [repository]


def test_remove_selected_repository_emits_path(qtbot: QtBot, tmp_path: Path) -> None:
    panel = RepositoriesPanel()
    qtbot.addWidget(panel)
    repository = tmp_path / "project"
    panel.set_recent((repository,))
    item = panel.tree.topLevelItem(0)
    assert item is not None
    item.setSelected(True)
    received: list[object] = []
    panel.remove_requested.connect(received.append)

    with qtbot.waitSignal(panel.remove_requested):
        panel.remove_action.trigger()
    assert received == [repository]


def test_repository_switcher_emits_selected_path(qtbot: QtBot, tmp_path: Path) -> None:
    panel = RepositoriesPanel()
    qtbot.addWidget(panel)
    first = tmp_path / "first"
    second = tmp_path / "second"

    panel.set_open([first, second], first)
    received: list[object] = []
    panel.switch_requested.connect(received.append)

    with qtbot.waitSignal(panel.switch_requested):
        panel.switcher.setCurrentIndex(1)
    assert received == [second]


def test_empty_recent_list_has_disabled_placeholder(qtbot: QtBot) -> None:
    panel = RepositoriesPanel()
    qtbot.addWidget(panel)

    panel.set_recent(())

    placeholder = panel.tree.topLevelItem(0)
    assert placeholder is not None
    assert placeholder.text(0) == "No recent repositories"
    assert placeholder.flags() == Qt.ItemFlag.NoItemFlags
