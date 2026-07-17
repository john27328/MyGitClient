from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTreeWidget,
    QVBoxLayout,
    QWidget,
)

from mygitclient.resources import load_icon


class ChangesPanel(QWidget):
    """Owns the changed-files tree and commit form widgets."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.tree = QTreeWidget()
        self.tree.setObjectName("changesTree")
        self.tree.setHeaderLabels(["File", "Index", "Working tree"])
        self.tree.setRootIsDecorated(False)
        self.tree.setMinimumWidth(280)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.ActionsContextMenu)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)

        self.discard_action = QAction("Discard changes…", self.tree)
        self.discard_action.setObjectName("discardChangesAction")
        self.discard_action.setEnabled(False)
        self.ignore_action = QAction("Add to .gitignore", self.tree)
        self.ignore_action.setObjectName("ignoreFileAction")
        self.ignore_action.setEnabled(False)
        self.stash_action = QAction("Stash selected changes", self.tree)
        self.stash_action.setObjectName("stashSelectedAction")
        self.stash_action.setEnabled(False)
        self.tree.addAction(self.discard_action)
        self.tree.addAction(self.stash_action)
        self.tree.addAction(self.ignore_action)

        self.stage_all = QCheckBox("Stage all changes")
        self.stage_all.setObjectName("stageAllCheckBox")
        self.stage_all.setTristate(True)

        self.commit_message = QPlainTextEdit()
        self.commit_message.setObjectName("commitMessageEdit")
        self.commit_message.setPlaceholderText("Commit message")
        self.commit_message.setMaximumHeight(90)
        self.commit_description = QPlainTextEdit()
        self.commit_description.setObjectName("commitDescriptionEdit")
        self.commit_description.setPlaceholderText("Description (optional)")
        self.commit_description.setMaximumHeight(110)

        self.amend = QCheckBox("Amend")
        self.amend.setObjectName("amendCheckBox")
        self.commit_button = QPushButton(load_icon("commit.svg"), "Commit")
        self.commit_button.setObjectName("commitButton")
        self.commit_error = QLabel()
        self.commit_error.setObjectName("commitErrorLabel")
        self.commit_error.setStyleSheet("color: palette(bright-text);")

        commit_actions = QWidget()
        commit_actions_layout = QHBoxLayout(commit_actions)
        commit_actions_layout.setContentsMargins(0, 0, 0, 0)
        commit_actions_layout.addWidget(self.amend)
        commit_actions_layout.addStretch(1)
        commit_actions_layout.addWidget(self.commit_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.stage_all)
        layout.addWidget(self.tree)
        layout.addWidget(self.commit_message)
        layout.addWidget(self.commit_description)
        layout.addWidget(commit_actions)
        layout.addWidget(self.commit_error)
        self.hide()
