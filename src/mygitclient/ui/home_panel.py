from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from mygitclient.github import GitHubProfile


class HomePanel(QWidget):
    choose_repository_requested = Signal()
    open_repository_requested = Signal(object)
    open_workspace_requested = Signal(str)
    clone_repository_requested = Signal(str)
    add_github_profile_requested = Signal()
    edit_github_profile_requested = Signal(object)
    remove_github_profile_requested = Signal(object)
    connect_github_requested = Signal(object)
    browse_github_requested = Signal(object)
    set_github_token_requested = Signal(object)
    remove_github_token_requested = Signal(object)

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

        actions = QHBoxLayout()
        self.open_button = QPushButton("Open local repository…")
        self.open_button.setObjectName("homeOpenRepositoryButton")
        self.open_button.clicked.connect(self.choose_repository_requested)
        actions.addWidget(self.open_button)
        self.clone_url = QLineEdit()
        self.clone_url.setObjectName("homeCloneUrlEdit")
        self.clone_url.setPlaceholderText("https://github.com/owner/repository.git")
        self.clone_url.setClearButtonEnabled(True)
        self.clone_button = QPushButton("Clone from URL…")
        self.clone_button.setObjectName("homeCloneRepositoryButton")
        self.clone_button.setEnabled(False)
        self.clone_url.textChanged.connect(self._clone_url_changed)
        self.clone_url.returnPressed.connect(self._clone_requested)
        self.clone_button.clicked.connect(self._clone_requested)
        actions.addWidget(self.clone_url, 1)
        actions.addWidget(self.clone_button)
        actions.addStretch(1)
        layout.addLayout(actions)

        github_header = QHBoxLayout()
        github_header.addWidget(QLabel("GitHub accounts"))
        github_header.addStretch(1)
        self.add_github_button = QPushButton("Connect GitHub account…")
        self.add_github_button.setObjectName("homeAddGitHubProfileButton")
        self.add_github_button.clicked.connect(self.add_github_profile_requested)
        self.edit_github_button = QPushButton("Edit…")
        self.edit_github_button.setObjectName("homeEditGitHubProfileButton")
        self.edit_github_button.setEnabled(False)
        self.edit_github_button.clicked.connect(self._edit_github_profile)
        self.remove_github_button = QPushButton("Remove")
        self.remove_github_button.setObjectName("homeRemoveGitHubProfileButton")
        self.remove_github_button.setEnabled(False)
        self.remove_github_button.clicked.connect(self._remove_github_profile)
        self.set_github_token_button = QPushButton("Set token…")
        self.set_github_token_button.setObjectName("homeSetGitHubTokenButton")
        self.set_github_token_button.setEnabled(False)
        self.set_github_token_button.clicked.connect(self._set_github_token)
        self.connect_github_button = QPushButton("Reconnect…")
        self.connect_github_button.setObjectName("homeConnectGitHubButton")
        self.connect_github_button.setEnabled(False)
        self.connect_github_button.clicked.connect(self._connect_github)
        self.browse_github_button = QPushButton("Repositories…")
        self.browse_github_button.setObjectName("homeBrowseGitHubButton")
        self.browse_github_button.setEnabled(False)
        self.browse_github_button.clicked.connect(self._browse_github)
        self.remove_github_token_button = QPushButton("Forget token")
        self.remove_github_token_button.setObjectName("homeRemoveGitHubTokenButton")
        self.remove_github_token_button.setEnabled(False)
        self.remove_github_token_button.clicked.connect(self._remove_github_token)
        github_header.addWidget(self.add_github_button)
        github_header.addWidget(self.edit_github_button)
        github_header.addWidget(self.remove_github_button)
        github_header.addWidget(self.connect_github_button)
        github_header.addWidget(self.browse_github_button)
        github_header.addWidget(self.set_github_token_button)
        github_header.addWidget(self.remove_github_token_button)
        layout.addLayout(github_header)

        self.github_tree = QTreeWidget()
        self.github_tree.setObjectName("homeGitHubProfiles")
        self.github_tree.setHeaderLabels(
            ["Profile", "GitHub login", "API", "Clone", "Commit identity"]
        )
        self.github_tree.setRootIsDecorated(False)
        self.github_tree.itemSelectionChanged.connect(self._github_selection_changed)
        self.github_tree.itemDoubleClicked.connect(self._github_profile_activated)
        layout.addWidget(self.github_tree, 1)

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

    @Slot(str)
    def _clone_url_changed(self, value: str) -> None:
        self.clone_button.setEnabled(bool(value.strip()))

    def set_recent(self, repositories: tuple[Path, ...]) -> None:
        self.recent_tree.clear()
        for repository in repositories:
            item = QTreeWidgetItem([repository.name, str(repository.parent)])
            item.setData(0, Qt.ItemDataRole.UserRole, repository)
            item.setToolTip(0, str(repository))
            self.recent_tree.addTopLevelItem(item)
        self.recent_tree.setVisible(bool(repositories))

    def set_github_profiles(
        self, profiles: tuple[GitHubProfile, ...], connected_logins: frozenset[str] = frozenset()
    ) -> None:
        self.github_tree.clear()
        for profile in profiles:
            identity = profile.user_name
            if profile.user_email:
                identity = f"{identity} <{profile.user_email}>" if identity else profile.user_email
            item = QTreeWidgetItem(
                [
                    profile.label,
                    profile.login,
                    (
                        "Token saved"
                        if profile.login.casefold() in connected_logins
                        else "Not connected"
                    ),
                    profile.clone_transport.upper(),
                    identity,
                ]
            )
            item.setData(0, Qt.ItemDataRole.UserRole, profile)
            self.github_tree.addTopLevelItem(item)
        self._github_selection_changed()

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

    def _clone_requested(self) -> None:
        url = self.clone_url.text().strip()
        if url:
            self.clone_repository_requested.emit(url)

    def _selected_github_profile(self) -> GitHubProfile | None:
        items = self.github_tree.selectedItems()
        if not items:
            return None
        profile = items[0].data(0, Qt.ItemDataRole.UserRole)
        return profile if isinstance(profile, GitHubProfile) else None

    def _github_selection_changed(self) -> None:
        selected = self._selected_github_profile() is not None
        self.edit_github_button.setEnabled(selected)
        self.remove_github_button.setEnabled(selected)
        profile = self._selected_github_profile()
        connected = self._connected_github_logins()
        self.connect_github_button.setEnabled(
            profile is not None and profile.login.casefold() not in connected
        )
        self.set_github_token_button.setEnabled(selected)
        self.remove_github_token_button.setEnabled(
            profile is not None and profile.login.casefold() in connected
        )
        self.browse_github_button.setEnabled(
            profile is not None and profile.login.casefold() in connected
        )

    def _connected_github_logins(self) -> frozenset[str]:
        connected: set[str] = set()
        for index in range(self.github_tree.topLevelItemCount()):
            item = self.github_tree.topLevelItem(index)
            if item is not None and item.text(2) == "Token saved":
                profile = item.data(0, Qt.ItemDataRole.UserRole)
                if isinstance(profile, GitHubProfile):
                    connected.add(profile.login.casefold())
        return frozenset(connected)

    def _github_profile_activated(self, item: QTreeWidgetItem) -> None:
        profile = item.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(profile, GitHubProfile):
            self.edit_github_profile_requested.emit(profile)

    def _edit_github_profile(self) -> None:
        profile = self._selected_github_profile()
        if profile is not None:
            self.edit_github_profile_requested.emit(profile)

    def _remove_github_profile(self) -> None:
        profile = self._selected_github_profile()
        if profile is not None:
            self.remove_github_profile_requested.emit(profile)

    def _set_github_token(self) -> None:
        profile = self._selected_github_profile()
        if profile is not None:
            self.set_github_token_requested.emit(profile)

    def _connect_github(self) -> None:
        profile = self._selected_github_profile()
        if profile is not None:
            self.connect_github_requested.emit(profile)

    def _browse_github(self) -> None:
        profile = self._selected_github_profile()
        if profile is not None:
            self.browse_github_requested.emit(profile)

    def _remove_github_token(self) -> None:
        profile = self._selected_github_profile()
        if profile is not None:
            self.remove_github_token_requested.emit(profile)
