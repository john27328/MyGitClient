from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import (
    QCheckBox,
    QPlainTextEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
)
from pytestqt.qtbot import QtBot

from mygitclient.ui.changes_panel import ChangesPanel, ChangesTreeWidget


def test_changes_panel_owns_tree_and_commit_widgets(qtbot: QtBot) -> None:
    panel = ChangesPanel()
    qtbot.addWidget(panel)

    assert panel.findChild(QTreeWidget, "changesTree") is panel.tree
    assert panel.findChild(QCheckBox, "stageAllCheckBox") is panel.stage_all
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


def test_clicking_file_text_does_not_toggle_checkbox(qtbot: QtBot) -> None:
    tree = ChangesTreeWidget()
    tree.setHeaderLabels(["File", "Index", "Working tree"])
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

    assert item.checkState(0) is Qt.CheckState.Checked
    assert item_changed.count() == 1
    tree.close()
