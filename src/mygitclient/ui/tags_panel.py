from __future__ import annotations

from typing import cast

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import (
    QHBoxLayout,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from mygitclient.git.models import TagInfo, TagsSnapshot


class TagsPanel(QWidget):
    create_requested = Signal()
    delete_requested = Signal(object)
    push_requested = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.tree = QTreeWidget()
        self.tree.setObjectName("tagsTree")
        self.tree.setHeaderLabels(["Tag", "Type", "Commit", "Description"])
        self.tree.setColumnWidth(0, 240)
        self.tree.setColumnWidth(1, 100)
        self.tree.setColumnWidth(2, 100)
        self.tree.currentItemChanged.connect(self._selection_changed)

        self.create_button = QPushButton("New tag…")
        self.create_button.setObjectName("createTagButton")
        self.create_button.clicked.connect(self.create_requested)
        self.delete_button = QPushButton("Delete…")
        self.delete_button.setObjectName("deleteTagButton")
        self.delete_button.setEnabled(False)
        self.delete_button.clicked.connect(self._delete_selected)
        self.push_button = QPushButton("Push")
        self.push_button.setObjectName("pushTagButton")
        self.push_button.setEnabled(False)
        self.push_button.clicked.connect(self._push_selected)

        buttons = QHBoxLayout()
        buttons.addWidget(self.create_button)
        buttons.addWidget(self.delete_button)
        buttons.addWidget(self.push_button)
        buttons.addStretch(1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(buttons)
        layout.addWidget(self.tree)

    def show_tags(self, snapshot: TagsSnapshot) -> None:
        self.tree.clear()
        for tag in snapshot.tags:
            item = QTreeWidgetItem(
                [
                    tag.name,
                    "Annotated" if tag.annotated else "Lightweight",
                    tag.commit_oid[:8],
                    tag.subject,
                ]
            )
            item.setData(0, Qt.ItemDataRole.UserRole, tag)
            item.setToolTip(0, tag.object_oid)
            self.tree.addTopLevelItem(item)
        self.tree.resizeColumnToContents(0)
        self._selection_changed()

    def reset(self) -> None:
        self.tree.clear()
        self._selection_changed()

    @Slot()
    def _selection_changed(self) -> None:
        selected = self._selected_tag() is not None
        self.delete_button.setEnabled(selected)
        self.push_button.setEnabled(selected)

    @Slot()
    def _delete_selected(self) -> None:
        tag = self._selected_tag()
        if tag is not None:
            self.delete_requested.emit(tag)

    @Slot()
    def _push_selected(self) -> None:
        tag = self._selected_tag()
        if tag is not None:
            self.push_requested.emit(tag)

    def _selected_tag(self) -> TagInfo | None:
        item = cast(QTreeWidgetItem | None, self.tree.currentItem())
        if item is None:
            return None
        value = item.data(0, Qt.ItemDataRole.UserRole)
        return value if isinstance(value, TagInfo) else None
