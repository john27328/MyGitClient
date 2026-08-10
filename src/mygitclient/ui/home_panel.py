from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)


class HomePanel(QWidget):
    choose_repository_requested = Signal()
    open_repository_requested = Signal(object)
    open_workspace_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("homePanel")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 32, 32, 32)
        layout.setSpacing(16)

        title = QLabel("MyGitClient")
        title.setObjectName("homeTitle")
        title_font = title.font()
        title_font.setPointSize(title_font.pointSize() + 6)
        title_font.setBold(True)
        title.setFont(title_font)
        layout.addWidget(title)

        subtitle = QLabel(
            "Open a repository in its own tab. Repository state and Git operations "
            "stay isolated between tabs."
        )
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        actions = QHBoxLayout()
        self.open_button = QPushButton("Open local repository…")
        self.open_button.setObjectName("homeOpenRepositoryButton")
        self.open_button.clicked.connect(self.choose_repository_requested)
        actions.addWidget(self.open_button)
        actions.addStretch(1)
        layout.addLayout(actions)

        layout.addWidget(QLabel("Recent repositories"))
        self.recent_tree = QTreeWidget()
        self.recent_tree.setObjectName("homeRecentRepositories")
        self.recent_tree.setHeaderLabels(["Repository", "Location"])
        self.recent_tree.setRootIsDecorated(False)
        self.recent_tree.setAlternatingRowColors(True)
        self.recent_tree.itemDoubleClicked.connect(self._recent_activated)
        layout.addWidget(self.recent_tree, 2)

        layout.addWidget(QLabel("Workspaces"))
        self.workspace_tree = QTreeWidget()
        self.workspace_tree.setObjectName("homeWorkspaces")
        self.workspace_tree.setHeaderHidden(True)
        self.workspace_tree.setRootIsDecorated(False)
        self.workspace_tree.itemDoubleClicked.connect(self._workspace_activated)
        layout.addWidget(self.workspace_tree, 1)

    def set_recent(self, repositories: tuple[Path, ...]) -> None:
        self.recent_tree.clear()
        for repository in repositories:
            item = QTreeWidgetItem([repository.name, str(repository.parent)])
            item.setData(0, Qt.ItemDataRole.UserRole, repository)
            item.setToolTip(0, str(repository))
            self.recent_tree.addTopLevelItem(item)
        self.recent_tree.setVisible(bool(repositories))

    def set_workspaces(self, names: tuple[str, ...]) -> None:
        self.workspace_tree.clear()
        for name in names:
            item = QTreeWidgetItem([name])
            item.setData(0, Qt.ItemDataRole.UserRole, name)
            self.workspace_tree.addTopLevelItem(item)
        self.workspace_tree.setVisible(bool(names))

    def _recent_activated(self, item: QTreeWidgetItem) -> None:
        repository = item.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(repository, Path):
            self.open_repository_requested.emit(repository)

    def _workspace_activated(self, item: QTreeWidgetItem) -> None:
        name = item.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(name, str):
            self.open_workspace_requested.emit(name)
