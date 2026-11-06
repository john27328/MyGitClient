from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QTreeWidgetItem
from pytestqt.qtbot import QtBot

from mygitclient.git.models import CommitFileChange
from mygitclient.ui.change_file_tree import FOLDER_ROLE, ChangeFileTree, FileViewModeCombo

FILES = (
    CommitFileChange("M", "src/vcs/app/main.cs"),
    CommitFileChange("D", "src/vcs/app/Old.cs"),
    CommitFileChange("A", "README.md"),
    CommitFileChange("M", "src/vcs/lib/util.cs"),
)


def _labels(item: QTreeWidgetItem) -> list[str]:
    return [child.text(0) for index in range(item.childCount()) if (child := item.child(index))]


def test_list_mode_keeps_git_order_and_full_paths(qtbot: QtBot) -> None:
    tree = ChangeFileTree()
    qtbot.addWidget(tree)

    tree.show_changes(FILES)

    assert not tree.rootIsDecorated()
    assert [item.text(0) for item in tree.file_items()] == [change.path for change in FILES]


def test_tree_mode_groups_compacts_and_lists_folders_first(qtbot: QtBot) -> None:
    tree = ChangeFileTree()
    qtbot.addWidget(tree)
    tree.set_tree_mode(True)

    tree.show_changes(FILES)

    roots = [tree.topLevelItem(index) for index in range(tree.topLevelItemCount())]
    folder, readme = (item for item in roots if item is not None)
    assert tree.rootIsDecorated()
    assert folder.text(0) == "src/vcs"
    assert folder.data(0, FOLDER_ROLE) == "src/vcs"
    assert ChangeFileTree.change(folder) is None
    assert readme.text(0) == "README.md"
    assert _labels(folder) == ["app", "lib"]
    app = folder.child(0)
    assert app is not None
    assert _labels(app) == ["main.cs", "Old.cs"]
    assert folder.isExpanded() and app.isExpanded()
    assert [item.text(0) for item in tree.file_items()] == [
        "main.cs",
        "Old.cs",
        "util.cs",
        "README.md",
    ]


def test_tree_mode_selects_files_not_folders_and_keeps_collapsed_folders(
    qtbot: QtBot,
) -> None:
    tree = ChangeFileTree()
    qtbot.addWidget(tree)
    tree.set_tree_mode(True)
    tree.show_changes(FILES)

    assert tree.select_first_file()
    assert tree.selected_change == FILES[0]
    folder = tree.topLevelItem(0)
    assert folder is not None
    lib = folder.child(1)
    assert lib is not None
    lib.setExpanded(False)

    tree.show_changes(FILES)

    assert tree.selected_change == FILES[0]
    folder = tree.topLevelItem(0)
    assert folder is not None
    lib = folder.child(1)
    assert lib is not None
    assert not lib.isExpanded()
    assert tree.select_path("src/vcs/lib/util.cs")
    assert tree.selected_change == FILES[3]


def test_view_mode_combo_persists_the_choice(qtbot: QtBot, tmp_path: Path) -> None:
    settings = QSettings(str(tmp_path / "view.ini"), QSettings.Format.IniFormat)
    combo = FileViewModeCombo(settings, "diff/filesViewMode")
    qtbot.addWidget(combo)
    modes: list[bool] = []
    combo.mode_changed.connect(modes.append)

    combo.setCurrentIndex(combo.findData("tree"))

    assert modes == [True]
    assert settings.value("diff/filesViewMode") == "tree"
    restored = FileViewModeCombo(settings, "diff/filesViewMode")
    qtbot.addWidget(restored)
    assert restored.tree_mode
