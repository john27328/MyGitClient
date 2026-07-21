from __future__ import annotations

from pathlib import Path
from typing import cast

from PySide6.QtCore import QSignalBlocker, Qt, Signal, Slot
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QComboBox,
    QMenu,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from mygitclient.resources import load_icon
from mygitclient.workspace import LinkedRepository


class RepositoriesPanel(QWidget):
    repository_activated = Signal(object, bool)
    remove_requested = Signal(object)
    switch_requested = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("repositoriesPanel")
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

        self.recent_menu = QMenu(self)
        self.recent_menu.setObjectName("recentRepositoriesMenu")
        self.recent_menu.triggered.connect(self._recent_action_triggered)
        self.remove_menu = QMenu("Remove from recent", self.recent_menu)
        self.remove_menu.setIcon(load_icon("remove.svg"))
        self.remove_menu.triggered.connect(self._remove_action_triggered)
        self.recent_button = QToolButton()
        self.recent_button.setObjectName("recentRepositoriesButton")
        self.recent_button.setText("Recent")
        self.recent_button.setIcon(load_icon("open.svg"))
        self.recent_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.recent_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.recent_button.setMenu(self.recent_menu)

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
            self._rebuild_recent_menu()
            return
        items: dict[Path, QTreeWidgetItem] = {}
        for repository in repositories:
            item = QTreeWidgetItem([repository.name])
            item.setToolTip(0, str(repository))
            item.setData(0, Qt.ItemDataRole.UserRole, repository)
            items[repository] = item
        for repository, item in items.items():
            parents = [
                candidate
                for candidate in items
                if candidate != repository and repository.is_relative_to(candidate)
            ]
            if not parents:
                self.tree.addTopLevelItem(item)
                continue
            parent_path = max(parents, key=lambda path: len(path.parts))
            item.setText(0, f"{repository.name} (nested)")
            items[parent_path].addChild(item)
            items[parent_path].setExpanded(True)
        self._rebuild_recent_menu()

    def set_open(self, repositories: list[Path], current: Path | None) -> None:
        blocker = QSignalBlocker(self.switcher)
        self.switcher.clear()
        for repository in repositories:
            self.switcher.addItem(repository.name, str(repository))
        if current is not None:
            self.switcher.setCurrentIndex(self.switcher.findData(str(current)))
        del blocker

    def select_repository(self, repository: Path) -> None:
        blocker = QSignalBlocker(self.switcher)
        self.switcher.setCurrentIndex(self.switcher.findData(str(repository)))
        del blocker

    def set_linked(
        self, repository: Path, linked_repositories: tuple[LinkedRepository, ...]
    ) -> None:
        item = self._find_item(repository)
        if item is not None:
            for linked in linked_repositories:
                self._remove_duplicate_top_level(linked.path, except_item=item)
                existing = next(
                    (
                        item.child(index)
                        for index in range(item.childCount())
                        if item.child(index).data(0, Qt.ItemDataRole.UserRole)
                        == linked.path
                    ),
                    None,
                )
                if existing is not None:
                    existing.setText(0, f"{linked.path.name} ({linked.kind})")
                    continue
                child = QTreeWidgetItem([f"{linked.path.name} ({linked.kind})"])
                child.setToolTip(0, str(linked.path))
                child.setData(0, Qt.ItemDataRole.UserRole, linked.path)
                item.addChild(child)
            item.setExpanded(True)
        self._rebuild_recent_menu()

    def _rebuild_recent_menu(self) -> None:
        self.recent_menu.clear()
        items = self._repository_items()
        if not items:
            placeholder = self.recent_menu.addAction("No recent repositories")
            placeholder.setEnabled(False)
            self.recent_button.setEnabled(False)
            return
        self.recent_button.setEnabled(True)
        for item in items:
            repository = item.data(0, Qt.ItemDataRole.UserRole)
            if not isinstance(repository, Path):
                continue
            action = self.recent_menu.addAction(item.text(0))
            action.setToolTip(str(repository))
            action.setProperty("repositoryPath", str(repository))
            parent = cast(QTreeWidgetItem | None, item.parent())
            action.setProperty("rememberRepository", parent is None)
        self.recent_menu.addSeparator()
        self.remove_menu.clear()
        for item in items:
            repository = item.data(0, Qt.ItemDataRole.UserRole)
            if not isinstance(repository, Path):
                continue
            action = self.remove_menu.addAction(item.text(0))
            action.setToolTip(str(repository))
            action.setProperty("repositoryPath", str(repository))
        self.recent_menu.addMenu(self.remove_menu)

    def _repository_items(self) -> list[QTreeWidgetItem]:
        pending = [
            item
            for index in range(self.tree.topLevelItemCount())
            if (item := self.tree.topLevelItem(index)) is not None
        ]
        result: list[QTreeWidgetItem] = []
        while pending:
            item = pending.pop(0)
            if isinstance(item.data(0, Qt.ItemDataRole.UserRole), Path):
                result.append(item)
            pending[0:0] = [item.child(index) for index in range(item.childCount())]
        return result

    def _find_item(self, repository: Path) -> QTreeWidgetItem | None:
        pending = [
            item
            for index in range(self.tree.topLevelItemCount())
            if (item := self.tree.topLevelItem(index)) is not None
        ]
        while pending:
            item = pending.pop()
            if item.data(0, Qt.ItemDataRole.UserRole) == repository:
                return item
            pending.extend(item.child(index) for index in range(item.childCount()))
        return None

    def _remove_duplicate_top_level(
        self, repository: Path, *, except_item: QTreeWidgetItem
    ) -> None:
        for index in reversed(range(self.tree.topLevelItemCount())):
            candidate = self.tree.topLevelItem(index)
            if (
                candidate is not None
                and candidate is not except_item
                and candidate.data(0, Qt.ItemDataRole.UserRole) == repository
            ):
                self.tree.takeTopLevelItem(index)

    @Slot(QTreeWidgetItem, int)
    def _item_activated(self, item: QTreeWidgetItem, _column: int) -> None:
        repository = item.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(repository, Path):
            parent = cast(QTreeWidgetItem | None, item.parent())
            self.repository_activated.emit(repository, parent is None)

    @Slot()
    def _remove_selected(self) -> None:
        selected = self.tree.selectedItems()
        if not selected:
            return
        repository = selected[0].data(0, Qt.ItemDataRole.UserRole)
        if isinstance(repository, Path):
            self.remove_requested.emit(repository)

    @Slot(QAction)
    def _recent_action_triggered(self, action: QAction) -> None:
        value = action.property("repositoryPath")
        remember = action.property("rememberRepository")
        if isinstance(value, str) and isinstance(remember, bool):
            self.repository_activated.emit(Path(value), remember)

    @Slot(QAction)
    def _remove_action_triggered(self, action: QAction) -> None:
        value = action.property("repositoryPath")
        if isinstance(value, str):
            self.remove_requested.emit(Path(value))

    @Slot(int)
    def _switcher_changed(self, index: int) -> None:
        repository = self.switcher.itemData(index)
        if isinstance(repository, str):
            self.switch_requested.emit(Path(repository))
