from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QAction
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QPlainTextEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
)
from pytestqt.qtbot import QtBot

from mygitclient.git.models import FileStatus
from mygitclient.ui.changes_panel import ChangesPanel, ChangesTreeWidget


def test_changes_panel_owns_tree_and_commit_widgets(qtbot: QtBot) -> None:
    panel = ChangesPanel()
    qtbot.addWidget(panel)

    assert panel.findChild(QTreeWidget, "changesTree") is panel.tree
    assert panel.findChild(QCheckBox, "stageAllCheckBox") is panel.stage_all
    assert panel.findChild(QComboBox, "changesViewModeCombo") is panel.view_mode
    assert (
        panel.findChild(QComboBox, "changesPresentationModeCombo")
        is panel.presentation_mode
    )
    assert panel.findChild(QTreeWidget, "unstagedChangesTree") is panel.unstaged_tree
    assert panel.findChild(QTreeWidget, "stagedChangesTree") is panel.staged_tree
    assert panel.findChild(QPlainTextEdit, "commitMessageEdit") is panel.commit_message
    assert (
        panel.findChild(QPlainTextEdit, "commitDescriptionEdit")
        is panel.commit_description
    )
    assert panel.findChild(QCheckBox, "amendCheckBox") is panel.amend
    assert panel.findChild(QPushButton, "commitButton") is panel.commit_button
    assert panel.findChild(QAction, "discardChangesAction") is panel.discard_action
    assert panel.findChild(QAction, "stashSelectedAction") is panel.stash_action
    assert panel.findChild(QAction, "ignoreFileAction") is panel.ignore_action
    assert panel.tree.columnCount() == 1
    assert panel.tree.headerItem().text(0) == "Changes"


def test_clicking_file_text_does_not_toggle_checkbox(qtbot: QtBot) -> None:
    tree = ChangesTreeWidget()
    tree.setHeaderLabel("Changes")
    tree.setRootIsDecorated(False)
    tree.resize(500, 200)
    item = QTreeWidgetItem(["src/example.py", "", "Modified"])
    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
    item.setCheckState(0, Qt.CheckState.PartiallyChecked)
    tree.addTopLevelItem(item)
    tree.show()
    item_changed = QSignalSpy(tree.itemChanged)

    rect = tree.visualItemRect(item)
    QTest.mouseClick(
        tree.viewport(),
        Qt.MouseButton.LeftButton,
        pos=rect.center(),
    )

    assert tree.currentItem() is item
    assert item.checkState(0) is Qt.CheckState.PartiallyChecked
    assert item_changed.count() == 0

    indicator = tree.indicator_rect(item)
    QTest.mouseClick(
        tree.viewport(),
        Qt.MouseButton.LeftButton,
        pos=indicator.center(),
    )

    assert item.checkState(0) is Qt.CheckState.Unchecked
    assert item_changed.count() == 1
    tree.close()


def test_tree_mode_groups_files_and_folder_checkbox_selects_descendants(
    qtbot: QtBot, tmp_path: Path
) -> None:
    settings = QSettings(str(tmp_path / "changes.ini"), QSettings.Format.IniFormat)
    settings.setValue("changes/viewMode", "tree")
    panel = ChangesPanel(settings)
    qtbot.addWidget(panel)
    first = FileStatus("src/package/first.py", ".", "M")
    second = FileStatus("src/package/second.py", ".", "M")
    root_file = FileStatus("README.md", ".", "M")
    requests: list[tuple[object, bool]] = []

    def capture(files: object, staged: bool) -> None:
        requests.append((files, staged))

    panel.folder_stage_requested.connect(capture)

    panel.show_files(
        [
            (first, Qt.CheckState.Unchecked),
            (second, Qt.CheckState.Checked),
            (root_file, Qt.CheckState.Unchecked),
        ],
        None,
    )

    assert panel.tree.topLevelItemCount() == 2
    readme = panel.tree.topLevelItem(0)
    assert readme is not None
    assert readme.text(0) == "README.md"
    src = panel.tree.topLevelItem(1)
    assert src is not None
    assert src.text(0) == "src/package"
    assert src.childCount() == 2
    assert src.checkState(0) is Qt.CheckState.PartiallyChecked

    src.setCheckState(0, Qt.CheckState.Checked)

    assert src.child(0).checkState(0) is Qt.CheckState.Checked
    assert src.child(1).checkState(0) is Qt.CheckState.Checked
    assert requests == [((first, second), True)]


def test_tree_mode_compacts_a_single_file_path_and_preserves_selection(
    qtbot: QtBot, tmp_path: Path
) -> None:
    settings = QSettings(str(tmp_path / "changes.ini"), QSettings.Format.IniFormat)
    settings.setValue("changes/viewMode", "tree")
    panel = ChangesPanel(settings)
    qtbot.addWidget(panel)
    file = FileStatus("src/package/only.py", ".", "M")

    selected = panel.show_files([(file, Qt.CheckState.Checked)], file.path)

    assert panel.tree.topLevelItemCount() == 1
    item = panel.tree.topLevelItem(0)
    assert item is not None
    assert item is selected
    assert item.text(0) == "src/package/only.py"
    assert item.childCount() == 0
    assert item.data(0, Qt.ItemDataRole.UserRole) == file
    assert item.checkState(0) is Qt.CheckState.Checked
    assert not item.icon(0).isNull()


def test_status_refresh_preserves_changes_tree_scroll_position(
    qtbot: QtBot, tmp_path: Path
) -> None:
    settings = QSettings(str(tmp_path / "changes.ini"), QSettings.Format.IniFormat)
    settings.setValue("changes/viewMode", "tree")
    panel = ChangesPanel(settings)
    qtbot.addWidget(panel)
    panel.resize(320, 240)
    panel.show()
    files = [
        (FileStatus(f"src/folder-{index}/file.py", ".", "M"), Qt.CheckState.Unchecked)
        for index in range(40)
    ]
    panel.show_files(files, None)
    qtbot.waitUntil(lambda: panel.tree.verticalScrollBar().maximum() > 0)
    scroll = panel.tree.verticalScrollBar()
    scroll.setValue(scroll.maximum() // 2)
    expected = scroll.value()

    refreshed = [(file, Qt.CheckState.Checked) for file, _state in files]
    panel.show_files(refreshed, None)
    qtbot.waitUntil(lambda: scroll.value() == expected)

    assert scroll.value() == expected


def test_file_row_uses_status_icon_and_detailed_tooltip(qtbot: QtBot) -> None:
    panel = ChangesPanel()
    qtbot.addWidget(panel)
    file = FileStatus("src/example.py", "M", "M")

    panel.show_files([(file, Qt.CheckState.PartiallyChecked)], None)

    item = panel.tree.topLevelItem(0)
    assert item is not None
    assert not item.icon(0).isNull()
    assert item.text(0) == "src/example.py"
    assert "Staged: Modified" in item.toolTip(0)
    assert "Not staged: Modified" in item.toolTip(0)


def test_changed_files_are_sorted_by_path_independently_of_git_status_order(
    qtbot: QtBot,
) -> None:
    panel = ChangesPanel()
    qtbot.addWidget(panel)
    files = [
        FileStatus("src/Zebra.py", ".", "M"),
        FileStatus("README.md", ".", "M"),
        FileStatus("src/alpha.py", "M", "."),
    ]

    panel.show_files(
        [(file, Qt.CheckState.Unchecked) for file in files],
        None,
    )

    labels: list[str] = []
    for index in range(panel.tree.topLevelItemCount()):
        item = panel.tree.topLevelItem(index)
        assert item is not None
        labels.append(item.text(0))
    assert labels == ["README.md", "src/alpha.py", "src/Zebra.py"]


def test_changes_view_mode_is_saved(qtbot: QtBot, tmp_path: Path) -> None:
    settings = QSettings(str(tmp_path / "changes.ini"), QSettings.Format.IniFormat)
    panel = ChangesPanel(settings)
    qtbot.addWidget(panel)

    panel.view_mode.setCurrentIndex(panel.view_mode.findData("tree"))

    assert settings.value("changes/viewMode") == "tree"


def test_split_presentation_separates_versions_and_is_saved(
    qtbot: QtBot, tmp_path: Path
) -> None:
    settings = QSettings(str(tmp_path / "changes.ini"), QSettings.Format.IniFormat)
    panel = ChangesPanel(settings)
    qtbot.addWidget(panel)
    staged_only = FileStatus("staged.py", "M", ".")
    unstaged_only = FileStatus("unstaged.py", ".", "M")
    partial = FileStatus("partial.py", "M", "M")

    panel.presentation_mode.setCurrentIndex(
        panel.presentation_mode.findData("split")
    )
    panel.show_files(
        [
            (staged_only, Qt.CheckState.Checked),
            (unstaged_only, Qt.CheckState.Unchecked),
            (partial, Qt.CheckState.PartiallyChecked),
        ],
        None,
    )

    assert panel.split_mode
    assert settings.value("changes/presentationMode") == "split"
    assert panel.unstaged_tree.topLevelItemCount() == 2
    assert panel.staged_tree.topLevelItemCount() == 2
    unstaged_item = panel.unstaged_tree.topLevelItem(0)
    staged_item = panel.staged_tree.topLevelItem(0)
    assert unstaged_item is not None and staged_item is not None
    assert unstaged_item.text(0) == "partial.py"
    assert unstaged_item.checkState(0) is Qt.CheckState.Unchecked
    assert staged_item.text(0) == "partial.py"
    assert staged_item.checkState(0) is Qt.CheckState.Checked
