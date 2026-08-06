from __future__ import annotations

from typing import Literal, cast

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from mygitclient.git.models import CommitSummary, RebaseTodoItem


class InteractiveRebaseDialog(QDialog):
    _ACTIONS = ("pick", "reword", "edit", "squash", "fixup", "drop")

    def __init__(self, commits: tuple[CommitSummary, ...], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("interactiveRebaseDialog")
        self.setWindowTitle("Interactive rebase")
        layout = QVBoxLayout(self)
        label = QLabel(
            "Choose an action and replay order. Edit the subject for reword commits."
        )
        label.setWordWrap(True)
        layout.addWidget(label)
        self.tree = QTreeWidget()
        self.tree.setObjectName("interactiveRebaseTree")
        self.tree.setHeaderLabels(["Action", "Commit", "Subject"])
        self.tree.setRootIsDecorated(False)
        for commit in commits:
            item = QTreeWidgetItem(["", commit.oid[:8], commit.subject])
            item.setData(0, Qt.ItemDataRole.UserRole, commit.oid)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
            self.tree.addTopLevelItem(item)
            action = QComboBox()
            action.addItems(self._ACTIONS)
            action.currentTextChanged.connect(self._validate)
            self.tree.setItemWidget(item, 0, action)
        self.tree.itemChanged.connect(self._validate)
        self.tree.header().setStretchLastSection(True)
        layout.addWidget(self.tree, 1)
        row = QHBoxLayout()
        up = QPushButton("Move up")
        down = QPushButton("Move down")
        up.clicked.connect(lambda: self._move(-1))
        down.clicked.connect(lambda: self._move(1))
        row.addWidget(up)
        row.addWidget(down)
        row.addStretch(1)
        layout.addLayout(row)
        self.error = QLabel()
        self.error.setObjectName("interactiveRebaseError")
        layout.addWidget(self.error)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Start rebase")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.resize(760, 520)
        self._validate()

    def items(self) -> tuple[RebaseTodoItem, ...]:
        result: list[RebaseTodoItem] = []
        for index in range(self.tree.topLevelItemCount()):
            item = cast(QTreeWidgetItem, self.tree.topLevelItem(index))
            action = self.tree.itemWidget(item, 0)
            assert isinstance(action, QComboBox)
            result.append(
                RebaseTodoItem(
                    cast(
                        Literal["pick", "reword", "edit", "squash", "fixup", "drop"],
                        action.currentText(),
                    ),
                    str(item.data(0, Qt.ItemDataRole.UserRole)),
                    item.text(2),
                )
            )
        return tuple(result)

    @Slot()
    def _validate(self) -> None:
        items = self.items()
        first = next((item for item in items if item.action != "drop"), None)
        message = ""
        if first is not None and first.action in {"squash", "fixup"}:
            message = "The first retained commit cannot be squashed or fixed up."
        elif any(item.action == "reword" and not item.subject.strip() for item in items):
            message = "Reword commits need a non-empty subject."
        self.error.setText(message)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(not message)

    def _move(self, offset: int) -> None:
        current = self.tree.currentItem()
        index = self.tree.indexOfTopLevelItem(current)
        target = index + offset
        if target < 0 or target >= self.tree.topLevelItemCount():
            return
        action = self.tree.itemWidget(current, 0)
        action_name = action.currentText() if isinstance(action, QComboBox) else "pick"
        item = cast(QTreeWidgetItem, self.tree.takeTopLevelItem(index))
        self.tree.insertTopLevelItem(target, item)
        combo = QComboBox()
        combo.addItems(self._ACTIONS)
        combo.setCurrentText(action_name)
        combo.currentTextChanged.connect(self._validate)
        self.tree.setItemWidget(item, 0, combo)
        self.tree.setCurrentItem(item)
        self._validate()
