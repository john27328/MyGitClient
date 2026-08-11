from __future__ import annotations

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from mygitclient.github import GitHubProfile, GitHubRepository


class GitHubRepositoriesDialog(QDialog):
    clone_requested = Signal(str)

    def __init__(self, profile: GitHubProfile, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._profile = profile
        self._repositories: tuple[GitHubRepository, ...] = ()
        self.setObjectName("githubRepositoriesDialog")
        self.setWindowTitle(f"GitHub repositories — {profile.login}")
        self.resize(760, 520)

        layout = QVBoxLayout(self)
        self.status = QLabel(f"Loading repositories for {profile.login}…")
        self.status.setObjectName("githubRepositoriesStatus")
        layout.addWidget(self.status)
        self.search = QLineEdit()
        self.search.setObjectName("githubRepositoriesSearch")
        self.search.setPlaceholderText("Filter by owner or repository name…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._apply_filter)
        layout.addWidget(self.search)
        self.tree = QTreeWidget()
        self.tree.setObjectName("githubRepositoriesTree")
        self.tree.setHeaderLabels(["Repository", "Visibility", "Updated"])
        self.tree.setRootIsDecorated(False)
        self.tree.itemSelectionChanged.connect(self._selection_changed)
        self.tree.itemDoubleClicked.connect(self._activated)
        layout.addWidget(self.tree, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        self.clone_button = QPushButton("Clone…")
        self.clone_button.setObjectName("githubRepositoryCloneButton")
        self.clone_button.setEnabled(False)
        self.clone_button.clicked.connect(self._clone_selected)
        buttons.addButton(self.clone_button, QDialogButtonBox.ButtonRole.AcceptRole)
        layout.addWidget(buttons)

    def show_repositories(self, repositories: tuple[GitHubRepository, ...]) -> None:
        self._repositories = repositories
        self.status.setText(f"{len(repositories)} repositories available")
        self._apply_filter()

    def show_error(self, message: str) -> None:
        self.status.setText(message)

    @Slot()
    def _apply_filter(self) -> None:
        query = self.search.text().strip().casefold()
        self.tree.clear()
        for repository in self._repositories:
            if query and query not in repository.full_name.casefold():
                continue
            item = QTreeWidgetItem(
                [
                    repository.full_name,
                    "Private" if repository.private else "Public",
                    repository.updated_at.replace("T", " ").removesuffix("Z"),
                ]
            )
            item.setData(0, Qt.ItemDataRole.UserRole, repository)
            self.tree.addTopLevelItem(item)
        self._selection_changed()

    def _selected_repository(self) -> GitHubRepository | None:
        items = self.tree.selectedItems()
        if not items:
            return None
        value = items[0].data(0, Qt.ItemDataRole.UserRole)
        return value if isinstance(value, GitHubRepository) else None

    @Slot()
    def _selection_changed(self) -> None:
        self.clone_button.setEnabled(self._selected_repository() is not None)

    @Slot()
    def _clone_selected(self) -> None:
        repository = self._selected_repository()
        if repository is None:
            return
        url = repository.ssh_url if self._profile.clone_transport == "ssh" else repository.clone_url
        self.clone_requested.emit(url)
        self.accept()

    @Slot(QTreeWidgetItem, int)
    def _activated(self, _item: QTreeWidgetItem, _column: int) -> None:
        self._clone_selected()
