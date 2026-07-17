from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSignalBlocker, Qt, Signal, Slot
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QComboBox, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from mygitclient.resources import load_icon
from mygitclient.workspace import LinkedRepository


class RepositoriesPanel(QWidget):
    repository_activated = Signal(object)
    remove_requested = Signal(object)
    switch_requested = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(180)
        self.tree = QTreeWidget()
        self.tree.setObjectName("repositoriesTree")
        self.tree.setHeaderLabel("Recent repositories")
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.ActionsContextMenu)
        self.remove_action = QAction("Remove from recent list", self.tree)
        self.remove_action.setIcon(load_icon("remove.svg"))
        self.remove_action.setObjectName("removeRecentAction")
        self.tree.addAction(self.remove_action)

        self.switcher = QComboBox()
        self.switcher.setObjectName("repositorySwitcher")
        self.switcher.setMinimumWidth(180)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.tree)

        self.tree.itemActivated.connect(self._item_activated)
        self.remove_action.triggered.connect(self._remove_selected)
        self.switcher.currentIndexChanged.connect(self._switcher_changed)

    def set_recent(self, repositories: tuple[Path, ...]) -> None:
        self.tree.clear()
        if not repositories:
            placeholder = QTreeWidgetItem(["No recent repositories"])
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            self.tree.addTopLevelItem(placeholder)
            return
        for repository in repositories:
            item = QTreeWidgetItem([repository.name])
            item.setToolTip(0, str(repository))
            item.setData(0, Qt.ItemDataRole.UserRole, repository)
            self.tree.addTopLevelItem(item)

    def set_open(self, repositories: list[Path], current: Path | None) -> None:
        blocker = QSignalBlocker(self.switcher)
        self.switcher.clear()
        for repository in repositories:
            self.switcher.addItem(repository.name, repository)
        if current is not None:
            self.switcher.setCurrentIndex(self.switcher.findData(current))
        del blocker

    def select_repository(self, repository: Path) -> None:
        blocker = QSignalBlocker(self.switcher)
        self.switcher.setCurrentIndex(self.switcher.findData(repository))
        del blocker

    def set_linked(
        self, repository: Path, linked_repositories: tuple[LinkedRepository, ...]
    ) -> None:
        for index in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(index)
            if item is None or item.data(0, Qt.ItemDataRole.UserRole) != repository:
                continue
            for linked in linked_repositories:
                child = QTreeWidgetItem([f"{linked.path.name} ({linked.kind})"])
                child.setToolTip(0, str(linked.path))
                child.setData(0, Qt.ItemDataRole.UserRole, linked.path)
                item.addChild(child)
            item.setExpanded(True)
            return

    @Slot(QTreeWidgetItem, int)
    def _item_activated(self, item: QTreeWidgetItem, _column: int) -> None:
        repository = item.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(repository, Path):
            self.repository_activated.emit(repository)

    @Slot()
    def _remove_selected(self) -> None:
        selected = self.tree.selectedItems()
        if not selected:
            return
        repository = selected[0].data(0, Qt.ItemDataRole.UserRole)
        if isinstance(repository, Path):
            self.remove_requested.emit(repository)

    @Slot(int)
    def _switcher_changed(self, index: int) -> None:
        repository = self.switcher.itemData(index)
        if isinstance(repository, Path):
            self.switch_requested.emit(repository)
