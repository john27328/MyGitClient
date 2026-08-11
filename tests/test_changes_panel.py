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
    assert panel.findChild(QPushButton, "stageSelectedButton") is panel.stage_button
    assert panel.findChild(QPushButton, "stashSelectedButton") is panel.stash_button
    assert panel.findChild(QPushButton, "unstageSelectedButton") is panel.unstage_button
    assert panel.findChild(QPushButton, "discardSelectedButton") is panel.discard_button
    assert panel.findChild(QAction, "stageChangesAction") is panel.stage_action
    assert panel.findChild(QAction, "unstageChangesAction") is panel.unstage_action
    assert panel.findChild(QAction, "discardChangesAction") is panel.discard_action
    assert panel.findChild(QAction, "stashSelectedAction") is panel.stash_action
    assert panel.findChild(QAction, "ignoreFileAction") is panel.ignore_action
    assert panel.findChild(QAction, "initializeSubmoduleAction") is panel.submodule_init_action
    assert panel.findChild(QAction, "updateSubmoduleAction") is panel.submodule_update_action
    assert panel.findChild(QAction, "syncSubmoduleAction") is panel.submodule_sync_action
    assert (
        panel.findChild(QAction, "initializeSubmoduleRecursiveAction")
        is panel.submodule_init_recursive_action
    )
    assert (
        panel.findChild(QAction, "updateSubmoduleRecursiveAction")
        is panel.submodule_update_recursive_action
    )
    assert (
        panel.findChild(QAction, "syncSubmoduleRecursiveAction")
        is panel.submodule_sync_recursive_action
    )
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


def test_current_file_is_action_target_when_no_checkbox_is_selected(
    qtbot: QtBot,
) -> None:
    panel = ChangesPanel()
    qtbot.addWidget(panel)
    file = FileStatus("src/example.py", ".", "M")
    item = panel.show_files([(file, Qt.CheckState.Unchecked)], file.path)

    assert item is not None
    panel.tree.setCurrentItem(item)
    assert panel.checked_files() == ()
    assert panel.action_files() == (file,)
    assert panel.stage_button.isEnabled()
    assert panel.stash_button.isEnabled()
    assert panel.discard_button.isEnabled()
    assert panel.stage_action.isEnabled()
    assert panel.stash_action.isEnabled()
    assert panel.discard_action.isEnabled()
    assert not panel.unstage_action.isEnabled()


def test_submodule_is_labelled_shows_sync_and_activates(qtbot: QtBot) -> None:
    panel = ChangesPanel()
    qtbot.addWidget(panel)
    submodule = FileStatus("plugins/board-notes", ".", "M", submodule="SC..")
    item = panel.show_files([(submodule, Qt.CheckState.Unchecked)], submodule.path)
    activated = QSignalSpy(panel.file_activated)

    assert item is not None
    assert "submodule" in item.text(0)
    assert "Double-click" in item.toolTip(0)

    panel.set_submodule_sync(submodule.path, ahead=2, behind=1)

    assert "Push ↑2" in item.text(0)
    assert "Pull ↓1" in item.text(0)
    panel.tree.itemDoubleClicked.emit(item, 0)
    assert activated.count() == 1
    assert activated.at(0)[0] == submodule


def test_submodule_shows_expected_checkout_and_context_actions(qtbot: QtBot) -> None:
    panel = ChangesPanel()
    qtbot.addWidget(panel)
    submodule = FileStatus(
        "plugins/board-notes",
        ".",
        "M",
        submodule="SC..",
        submodule_expected_oid="expected123456",
    )
    item = panel.show_files([(submodule, Qt.CheckState.Unchecked)], submodule.path)
    assert item is not None
    panel.tree.setCurrentItem(item)

    panel.set_submodule_checkout(
        submodule.path, checked_oid="checked987654", initialized=True
    )

    assert "expected expecte" in item.text(0)
    assert "checked out checked" in item.text(0)
    assert panel.submodule_update_action.isVisible()
    assert panel.submodule_sync_action.isVisible()
    assert panel.submodule_update_recursive_action.isVisible()
    assert panel.submodule_sync_recursive_action.isVisible()
    assert not panel.submodule_init_action.isVisible()

    panel.set_submodule_checkout(submodule.path, checked_oid=None, initialized=False)
    assert "not initialized" in item.text(0)
    assert panel.submodule_init_action.isVisible()
    assert panel.submodule_init_recursive_action.isVisible()
    assert not panel.submodule_update_action.isVisible()


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
    assert src.checkState(0) is Qt.CheckState.Unchecked

    src.setCheckState(0, Qt.CheckState.Checked)

    assert src.child(0).checkState(0) is Qt.CheckState.Checked
    assert src.child(1).checkState(0) is Qt.CheckState.Checked
    assert panel.checked_files() == (first, second)
    assert panel.stage_button.isEnabled()


def test_tree_mode_compacts_directories_but_keeps_file_as_a_separate_leaf(
    qtbot: QtBot, tmp_path: Path
) -> None:
    settings = QSettings(str(tmp_path / "changes.ini"), QSettings.Format.IniFormat)
    settings.setValue("changes/viewMode", "tree")
    panel = ChangesPanel(settings)
    qtbot.addWidget(panel)
    file = FileStatus("src/package/only.py", ".", "M")

    selected = panel.show_files([(file, Qt.CheckState.Checked)], file.path)

    assert panel.tree.topLevelItemCount() == 1
    folder = panel.tree.topLevelItem(0)
    assert folder is not None
    assert folder.text(0) == "src/package"
    assert folder.childCount() == 1
    item = folder.child(0)
    assert item is selected
    assert item.text(0) == "only.py"
    assert item.childCount() == 0
    assert item.data(0, Qt.ItemDataRole.UserRole) == file
    assert item.checkState(0) is Qt.CheckState.Unchecked
    assert not item.icon(0).isNull()


def test_split_folder_checkbox_selects_files_without_applying_git(
    qtbot: QtBot, tmp_path: Path
) -> None:
    settings = QSettings(str(tmp_path / "changes.ini"), QSettings.Format.IniFormat)
    settings.setValue("changes/viewMode", "tree")
    settings.setValue("changes/presentationMode", "split")
    panel = ChangesPanel(settings)
    qtbot.addWidget(panel)
    first = FileStatus("src/package/first.py", ".", "M")
    second = FileStatus("src/package/second.py", ".", "M")
    panel.show_files(
        [
            (first, Qt.CheckState.Unchecked),
            (second, Qt.CheckState.Unchecked),
        ],
        None,
    )
    root = panel.unstaged_tree.topLevelItem(0)
    assert root is not None
    item_changed = QSignalSpy(panel.unstaged_tree.itemChanged)

    root.setCheckState(0, Qt.CheckState.Checked)

    assert item_changed.count() == 1
    assert panel.checked_files() == (first, second)
    assert root.child(0).checkState(0) is Qt.CheckState.Checked
    assert root.child(1).checkState(0) is Qt.CheckState.Checked


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


def test_file_icon_badge_distinguishes_staged_and_unstaged(qtbot: QtBot) -> None:
    panel = ChangesPanel()
    qtbot.addWidget(panel)
    staged = FileStatus("staged.py", "M", ".")
    unstaged = FileStatus("unstaged.py", ".", "M")

    panel.show_files(
        [
            (staged, Qt.CheckState.Unchecked),
            (unstaged, Qt.CheckState.Unchecked),
        ],
        None,
    )

    staged_item = panel.tree.topLevelItem(0)
    unstaged_item = panel.tree.topLevelItem(1)
    assert staged_item is not None and unstaged_item is not None
    staged_badge = staged_item.icon(0).pixmap(27, 20).toImage().pixelColor(2, 8)
    unstaged_badge = unstaged_item.icon(0).pixmap(27, 20).toImage().pixelColor(2, 8)
    assert staged_badge.blue() > staged_badge.red()
    assert unstaged_badge.red() > unstaged_badge.blue()


def test_combined_file_icon_badge_shows_both_states_for_partial_file(
    qtbot: QtBot,
) -> None:
    panel = ChangesPanel()
    qtbot.addWidget(panel)
    partial = FileStatus("partial.py", "M", "M")

    panel.show_files([(partial, Qt.CheckState.Unchecked)], None)

    item = panel.tree.topLevelItem(0)
    assert item is not None
    image = item.icon(0).pixmap(27, 20).toImage()
    staged_half = image.pixelColor(2, 5)
    unstaged_half = image.pixelColor(2, 14)
    assert staged_half.blue() > staged_half.red()
    assert unstaged_half.red() > unstaged_half.blue()


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
    assert staged_item.checkState(0) is Qt.CheckState.Unchecked
    unstaged_badge = unstaged_item.icon(0).pixmap(27, 20).toImage().pixelColor(2, 8)
    staged_badge = staged_item.icon(0).pixmap(27, 20).toImage().pixelColor(2, 8)
    assert unstaged_badge.red() > unstaged_badge.blue()
    assert staged_badge.blue() > staged_badge.red()


def test_checkbox_selection_survives_status_refresh(qtbot: QtBot) -> None:
    panel = ChangesPanel()
    qtbot.addWidget(panel)
    first = FileStatus("first.py", ".", "M")
    second = FileStatus("second.py", "M", ".")
    panel.show_files(
        [(first, Qt.CheckState.Unchecked), (second, Qt.CheckState.Checked)], None
    )
    first_item = panel.tree.topLevelItem(0)
    assert first_item is not None
    first_item.setCheckState(0, Qt.CheckState.Checked)

    panel.show_files(
        [(first, Qt.CheckState.Unchecked), (second, Qt.CheckState.Checked)], None
    )

    refreshed_first = panel.tree.topLevelItem(0)
    refreshed_second = panel.tree.topLevelItem(1)
    assert refreshed_first is not None and refreshed_second is not None
    assert refreshed_first.checkState(0) is Qt.CheckState.Checked
    assert refreshed_second.checkState(0) is Qt.CheckState.Unchecked


def test_conflicted_file_is_checkable_only_in_unstaged_split_tree(
    qtbot: QtBot,
) -> None:
    panel = ChangesPanel()
    qtbot.addWidget(panel)
    panel.presentation_mode.setCurrentIndex(
        panel.presentation_mode.findData("split")
    )
    conflict = FileStatus("conflict.txt", "U", "U", unmerged=True)

    panel.show_files([(conflict, Qt.CheckState.Unchecked)], None)

    assert panel.unstaged_tree.topLevelItemCount() == 1
    assert panel.staged_tree.topLevelItemCount() == 0
    item = panel.unstaged_tree.topLevelItem(0)
    assert item is not None
    assert item.flags() & Qt.ItemFlag.ItemIsUserCheckable
    assert item.checkState(0) is Qt.CheckState.Unchecked
