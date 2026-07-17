from __future__ import annotations

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QCheckBox, QPlainTextEdit, QPushButton, QTreeWidget
from pytestqt.qtbot import QtBot

from mygitclient.ui.changes_panel import ChangesPanel


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
