from __future__ import annotations

import sys
from pathlib import Path
from typing import cast
from urllib.parse import quote

from PySide6.QtCore import QProcess, QSettings, Qt, QUrl, Slot
from PySide6.QtGui import QAction, QActionGroup, QCloseEvent, QDesktopServices, QFontDatabase
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QInputDialog,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from mygitclient import __version__
from mygitclient.git.clone_service import (
    CloneService,
    is_valid_clone_folder_name,
    suggested_clone_name,
)
from mygitclient.git.remotes import GitRemoteReader
from mygitclient.github import (
    DeviceAuthorization,
    DeviceFlowResult,
    GitHubBrowserFlow,
    GitHubDeviceFlow,
    GitHubProfile,
    GitHubProfileStore,
    GitHubRepository,
    GitHubRepositoryBindingStore,
    GitHubRepositoryPublisher,
    GitHubRepositoryService,
    GitHubTokenStore,
    PublishedGitHubRepository,
    TokenStoreError,
    first_github_remote,
    github_remote,
)
from mygitclient.resources import load_icon
from mygitclient.theme import Theme
from mygitclient.ui.github_device_dialog import GitHubDeviceDialog
from mygitclient.ui.github_profile_dialog import GitHubProfileDialog
from mygitclient.ui.github_publish_dialog import GitHubPublishDialog
from mygitclient.ui.github_repositories_dialog import GitHubRepositoriesDialog
from mygitclient.ui.home_panel import HomePanel
from mygitclient.ui.main_window import MainWindow
from mygitclient.updates import (
    UpdateChecker,
    UpdateDownloader,
    UpdateInfo,
    launch_updater,
    portable_install_directory,
)
from mygitclient.workspace import WorkspaceManager, find_repository_root


class RepositorySessionTab(QWidget):
    def __init__(self, controller: MainWindow) -> None:
        super().__init__()
        self.controller = controller
        self._stopped = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        controller.setParent(self)
        controller.setWindowFlags(Qt.WindowType.Widget)
        controller.menuBar().hide()
        layout.addWidget(controller)
        controller.show()

    def open_repository(self, repository: Path) -> None:
        self.controller.open_repository(repository)

    def shutdown(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        self.controller.close()


class AppShell(QMainWindow):
    def __init__(self, settings: QSettings, theme: Theme) -> None:
        super().__init__()
        self._settings = settings
        self._theme = theme
        self._workspace = WorkspaceManager(settings)
        self._github_profiles = GitHubProfileStore(settings)
        self._github_bindings = GitHubRepositoryBindingStore(settings)
        self._github_tokens = GitHubTokenStore()
        self._github_device_flow = GitHubDeviceFlow(self)
        self._github_browser_flow = GitHubBrowserFlow(self)
        self._github_device_dialog: GitHubDeviceDialog | None = None
        self._github_device_profile: GitHubProfile | None = None
        self._github_device_add_new = False
        self._github_device_flow.code_received.connect(self._github_device_code_received)
        self._github_device_flow.completed.connect(self._github_device_completed)
        self._github_device_flow.failed.connect(self._github_device_failed)
        self._github_browser_flow.authorization_url_ready.connect(
            self._github_browser_authorization_ready
        )
        self._github_browser_flow.completed.connect(self._github_device_completed)
        self._github_browser_flow.failed.connect(self._github_device_failed)
        self._github_repositories = GitHubRepositoryService(self)
        self._github_repositories_dialog: GitHubRepositoriesDialog | None = None
        self._github_repositories.completed.connect(self._github_repositories_completed)
        self._github_repositories.failed.connect(self._github_repositories_failed)
        self._github_publisher = GitHubRepositoryPublisher(self)
        self._github_publisher.completed.connect(self._github_publish_completed)
        self._github_publisher.failed.connect(self._github_publish_failed)
        self._pending_github_publish: tuple[MainWindow, GitHubProfile] | None = None
        self._home_remotes = GitRemoteReader(self)
        self._home_remotes.completed.connect(self._home_remotes_completed)
        self._home_remote_names: dict[Path, str] = {}
        self._home_remote_urls: dict[Path, tuple[str, ...]] = {}
        self._sessions: dict[Path, RepositorySessionTab] = {}
        self._closing = False
        self._clone_progress: QProgressDialog | None = None
        self._clone_service = CloneService(self)
        self._clone_service.progress.connect(self._clone_progress_changed)
        self._clone_service.completed.connect(self._clone_completed)
        self._clone_service.failed.connect(self._clone_failed)
        self._clone_service.cancelled.connect(self._clone_cancelled)
        self._manual_update_check = False
        self._update_progress: QProgressDialog | None = None
        self._update_checker = UpdateChecker(self)
        self._update_downloader = UpdateDownloader(self)
        self._update_checker.update_available.connect(self._update_available)
        self._update_checker.up_to_date.connect(self._update_is_current)
        self._update_checker.failed.connect(self._update_check_failed)
        self._update_downloader.progress.connect(self._update_download_progress)
        self._update_downloader.ready.connect(self._update_downloaded)
        self._update_downloader.failed.connect(self._update_download_failed)
        self._update_downloader.cancelled.connect(self._update_download_cancelled)

        self.setObjectName("appShell")
        self.setWindowTitle("MyGitClient")
        self.setWindowIcon(load_icon("app-icon.png"))
        self.resize(1180, 760)
        self._apply_saved_ui_font()

        self.tabs = QTabWidget()
        self.tabs.setObjectName("repositorySessionTabs")
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.tabCloseRequested.connect(self._close_tab)
        self.tabs.currentChanged.connect(self._current_tab_changed)
        self.setCentralWidget(self.tabs)

        self.home = HomePanel()
        self.home.choose_repository_requested.connect(self._choose_repository)
        self.home.open_repository_requested.connect(self._open_home_repository)
        self.home.remove_recent_repository_requested.connect(
            self._remove_home_recent_repository
        )
        self.home.bind_github_profile_requested.connect(self._bind_home_github_profile)
        self.home.open_workspace_requested.connect(self._open_workspace)
        self.home.clone_repository_requested.connect(self._clone_repository)
        self.home.add_github_profile_requested.connect(self._add_github_profile)
        self.home.edit_github_profile_requested.connect(self._edit_github_profile)
        self.home.remove_github_profile_requested.connect(self._remove_github_profile)
        self.home.connect_github_requested.connect(self._connect_github)
        self.home.browse_github_requested.connect(self._browse_github)
        self.home.set_github_token_requested.connect(self._set_github_token)
        self.home.remove_github_token_requested.connect(self._remove_github_token)
        self.tabs.addTab(self.home, "Home")
        self.tabs.tabBar().setTabButton(0, self.tabs.tabBar().ButtonPosition.RightSide, None)

        self._build_global_menu()
        self._refresh_home()

    def _build_global_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        open_action = QAction(load_icon("open.svg"), "&Open Repository…", self)
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self._choose_repository)
        file_menu.addAction(open_action)
        file_menu.addSeparator()
        exit_action = file_menu.addAction("E&xit")
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        workspace_menu = self.menuBar().addMenu("&Workspace")
        save_workspace = workspace_menu.addAction("Save Workspace…")
        save_workspace.triggered.connect(self._save_workspace)
        self._load_workspace_menu = workspace_menu.addMenu("Open Workspace")
        self._populate_workspace_menu()

        view_menu = self.menuBar().addMenu("&View")
        theme_menu = view_menu.addMenu("Theme")
        self._theme_actions = QActionGroup(self)
        self._theme_actions.setExclusive(True)
        for theme in Theme:
            action = theme_menu.addAction(theme.value.title())
            action.setObjectName(f"themeAction_{theme.value}")
            action.setCheckable(True)
            action.setChecked(theme is self._theme)
            action.setData(theme.value)
            self._theme_actions.addAction(action)
        self._theme_actions.triggered.connect(self._theme_selected)
        view_menu.addSeparator()
        font_sizes = view_menu.addAction("Font Sizes…")
        font_sizes.setObjectName("fontSizesAction")
        font_sizes.triggered.connect(self._configure_font_sizes)

        help_menu = self.menuBar().addMenu("&Help")
        check_updates = help_menu.addAction("Check for Updates…")
        check_updates.setObjectName("checkUpdatesAction")
        check_updates.triggered.connect(self._manual_update_check_requested)
        about_action = help_menu.addAction("About MyGitClient")
        about_action.setObjectName("aboutAction")
        about_action.triggered.connect(self._show_about)

    @Slot()
    def _choose_repository(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Open Git Repository")
        if selected:
            self.open_repository(Path(selected))

    @Slot(object)
    def _open_home_repository(self, value: object) -> None:
        if isinstance(value, Path):
            self.open_repository(value)

    @Slot(object)
    def _remove_home_recent_repository(self, value: object) -> None:
        if not isinstance(value, Path):
            return
        self._workspace.forget(value)
        self._refresh_home()

    @Slot(str)
    def _open_workspace(self, name: str) -> None:
        for repository in self._workspace.load_named_workspace(name):
            self.open_repository(repository)

    @Slot(str)
    def _clone_repository(self, url: str) -> None:
        if self._clone_service.is_running:
            QMessageBox.information(self, "Clone in progress", "A repository is already cloning.")
            return
        parent = QFileDialog.getExistingDirectory(self, "Select clone parent directory")
        if not parent:
            return
        name, accepted = QInputDialog.getText(
            self,
            "Clone repository",
            "Folder name:",
            text=suggested_clone_name(url),
        )
        name = name.strip()
        if not accepted:
            return
        if not is_valid_clone_folder_name(name):
            QMessageBox.warning(
                self,
                "Invalid folder name",
                "Enter a single folder name without path separators, '.' or '..'.",
            )
            return
        target = (Path(parent) / name).resolve()
        if target.exists():
            QMessageBox.warning(
                self,
                "Clone destination exists",
                f"Choose a new folder name. This path already exists:\n{target}",
            )
            return
        progress = QProgressDialog("Starting clone…", "Cancel", 0, 0, self)
        progress.setObjectName("cloneRepositoryProgress")
        progress.setWindowTitle("Cloning repository")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.canceled.connect(self._clone_service.cancel)
        self._clone_progress = progress
        progress.show()
        if not self._clone_service.clone(url, target, token=self._resolve_clone_token(url)):
            self._close_clone_progress()

    def _resolve_clone_token(self, url: str) -> str | None:
        """Match the clone URL's owner against a connected GitHub account's token.

        Lets clone authenticate over HTTPS for private repos without depending on
        the system Git credential helper already having valid, unexpired credentials.
        """
        remote = github_remote(url)
        if remote is None:
            return None
        profile = next(
            (
                item
                for item in self._github_profiles.profiles()
                if item.login.casefold() == remote.owner.casefold()
            ),
            None,
        )
        if profile is None:
            return None
        try:
            return self._github_tokens.token(profile.login)
        except TokenStoreError:
            return None

    @Slot(str)
    def _clone_progress_changed(self, message: str) -> None:
        if self._clone_progress is not None:
            self._clone_progress.setLabelText(message)

    @Slot(object)
    def _clone_completed(self, value: object) -> None:
        self._close_clone_progress()
        if not isinstance(value, Path):
            return
        self.home.clone_url.clear()
        self.open_repository(value)

    @Slot(str)
    def _clone_failed(self, message: str) -> None:
        self._close_clone_progress()
        QMessageBox.warning(self, "Clone failed", message)

    @Slot()
    def _clone_cancelled(self) -> None:
        self._close_clone_progress()

    def _close_clone_progress(self) -> None:
        if self._clone_progress is not None:
            self._clone_progress.close()
            self._clone_progress.deleteLater()
            self._clone_progress = None

    @Slot()
    def _add_github_profile(self) -> None:
        self._open_github_device_dialog(None)

    @Slot(object)
    def _edit_github_profile(self, value: object) -> None:
        if not isinstance(value, GitHubProfile):
            return
        dialog = GitHubProfileDialog(value, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._save_github_profile(dialog.profile(), previous_label=value.label)

    @Slot(object)
    def _remove_github_profile(self, value: object) -> None:
        if not isinstance(value, GitHubProfile):
            return
        answer = QMessageBox.question(
            self,
            "Remove GitHub profile",
            f"Remove the local profile '{value.label}'? No GitHub data will be changed.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._github_profiles.remove(value.label)
        self._github_bindings.remove_profile(value.label)
        self._refresh_home()

    def _save_github_profile(
        self, profile: GitHubProfile, *, previous_label: str | None = None
    ) -> None:
        try:
            self._github_profiles.save(profile, previous_label=previous_label)
        except ValueError as error:
            QMessageBox.warning(self, "GitHub profile", str(error))
            return
        self._refresh_home()

    @Slot(object)
    def _set_github_token(self, value: object) -> None:
        if not isinstance(value, GitHubProfile):
            return
        token, accepted = QInputDialog.getText(
            self,
            "GitHub API token",
            f"Fine-grained personal access token for {value.login}:\n"
            "The token is stored in the system credential manager.",
            QLineEdit.EchoMode.Password,
        )
        if not accepted:
            return
        try:
            self._github_tokens.save(value.login, token)
        except (TokenStoreError, ValueError) as error:
            QMessageBox.warning(self, "GitHub token", str(error))
            return
        self._refresh_home()

    @Slot(object)
    def _connect_github(self, value: object) -> None:
        if not isinstance(value, GitHubProfile):
            return
        self._open_github_device_dialog(value)

    def _open_github_device_dialog(self, profile: GitHubProfile | None) -> None:
        client_id = str(self._settings.value("github/oauthClientId", "")).strip()
        self._close_github_device_dialog()
        self._github_device_profile = profile
        self._github_device_add_new = profile is None
        dialog = GitHubDeviceDialog(profile.login if profile is not None else None, client_id, self)
        dialog.cancelled.connect(self._github_device_flow.cancel)
        dialog.cancelled.connect(self._github_browser_flow.cancel)
        dialog.start_requested.connect(self._start_github_device_flow)
        dialog.browser_start_requested.connect(self._start_github_browser_flow)
        dialog.finished.connect(self._github_device_dialog_finished)
        self._github_device_dialog = dialog
        dialog.show()

    @Slot(str)
    def _start_github_device_flow(self, client_id: str) -> None:
        clean_client_id = client_id.strip()
        if not clean_client_id:
            return
        self._settings.setValue("github/oauthClientId", clean_client_id)
        self._github_device_flow.start(clean_client_id)

    @Slot(str, str)
    def _start_github_browser_flow(self, client_id: str, client_secret: str) -> None:
        clean_client_id = client_id.strip()
        clean_client_secret = client_secret.strip()
        if not clean_client_id or not clean_client_secret:
            return
        self._settings.setValue("github/oauthClientId", clean_client_id)
        self._github_browser_flow.start(clean_client_id, clean_client_secret)

    @Slot(object)
    def _github_device_code_received(self, value: object) -> None:
        if isinstance(value, DeviceAuthorization) and self._github_device_dialog is not None:
            self._github_device_dialog.show_authorization(value)

    @Slot(str)
    def _github_browser_authorization_ready(self, url: str) -> None:
        if self._github_device_dialog is not None:
            self._github_device_dialog.show_browser_pending(url)

    @Slot(object)
    def _github_device_completed(self, value: object) -> None:
        profile = self._github_device_profile
        add_new = self._github_device_add_new
        if not isinstance(value, DeviceFlowResult) or (profile is None and not add_new):
            return
        if profile is not None and value.login.casefold() != profile.login.casefold():
            self._github_device_failed(
                f"GitHub authorized '{value.login}', but this profile expects '{profile.login}'."
            )
            return
        if profile is None:
            profile = self._profile_for_authorized_login(value.login)
        try:
            self._github_tokens.save(profile.login, value.token)
            if add_new and profile not in self._github_profiles.profiles():
                self._github_profiles.save(profile)
        except (TokenStoreError, ValueError) as error:
            self._github_device_failed(str(error))
            return
        self._close_github_device_dialog()
        self._github_device_profile = None
        self._github_device_add_new = False
        self._refresh_home()
        self.statusBar().showMessage(f"Connected GitHub account {profile.login}.", 5000)

    def _profile_for_authorized_login(self, login: str) -> GitHubProfile:
        for profile in self._github_profiles.profiles():
            if profile.login.casefold() == login.casefold():
                return profile
        return GitHubProfile(label=login, login=login)

    @Slot(str)
    def _github_device_failed(self, message: str) -> None:
        if self._github_device_dialog is not None:
            self._github_device_dialog.show_error(message)
        else:
            QMessageBox.warning(self, "GitHub authorization", message)

    @Slot(int)
    def _github_device_dialog_finished(self, _result: int) -> None:
        self._github_device_flow.cancel()
        self._github_browser_flow.cancel()
        self._github_device_dialog = None
        self._github_device_profile = None
        self._github_device_add_new = False

    def _close_github_device_dialog(self) -> None:
        if self._github_device_dialog is not None:
            dialog = self._github_device_dialog
            self._github_device_dialog = None
            dialog.close()
            dialog.deleteLater()

    @Slot(object)
    def _remove_github_token(self, value: object) -> None:
        if not isinstance(value, GitHubProfile):
            return
        try:
            self._github_tokens.remove(value.login)
        except TokenStoreError as error:
            QMessageBox.warning(self, "GitHub token", str(error))
            return
        self._refresh_home()

    @Slot(object)
    def _browse_github(self, value: object) -> None:
        if not isinstance(value, GitHubProfile):
            return
        try:
            token = self._github_tokens.token(value.login)
        except TokenStoreError as error:
            QMessageBox.warning(self, "GitHub repositories", str(error))
            return
        if not token:
            QMessageBox.information(
                self,
                "GitHub repositories",
                f"Connect the GitHub account {value.login} first.",
            )
            return
        if self._github_repositories_dialog is not None:
            self._github_repositories_dialog.close()
        dialog = GitHubRepositoriesDialog(value, self)
        dialog.clone_requested.connect(self._clone_repository)
        dialog.finished.connect(self._github_repositories_dialog_finished)
        self._github_repositories_dialog = dialog
        dialog.show()
        self._github_repositories.load(token)

    @Slot(object)
    def _github_repositories_completed(self, value: object) -> None:
        if not isinstance(value, tuple) or self._github_repositories_dialog is None:
            return
        repositories = cast(tuple[object, ...], value)
        if not all(isinstance(repository, GitHubRepository) for repository in repositories):
            self._github_repositories_dialog.show_error(
                "GitHub returned an unexpected repository list"
            )
            return
        self._github_repositories_dialog.show_repositories(
            cast(tuple[GitHubRepository, ...], repositories)
        )

    @Slot(str)
    def _github_repositories_failed(self, message: str) -> None:
        if self._github_repositories_dialog is not None:
            self._github_repositories_dialog.show_error(message)

    @Slot(int)
    def _github_repositories_dialog_finished(self, _result: int) -> None:
        self._github_repositories.cancel()
        self._github_repositories_dialog = None

    def open_repository(self, selected_path: Path) -> None:
        repository = find_repository_root(selected_path)
        if repository is None:
            QMessageBox.warning(
                self,
                "Not a Git repository",
                f"No Git repository was found in or above:\n{selected_path}",
            )
            return
        repository = repository.resolve()
        existing = self._sessions.get(repository)
        if existing is not None:
            self.tabs.setCurrentWidget(existing)
            return

        controller = MainWindow(self._settings, self._theme, session_mode=True)
        controller.repository_tab_requested.connect(self._open_session_repository)
        controller.restart_requested.connect(self._restart_application)
        controller.github_publish_requested.connect(self._publish_repository_to_github)
        controller.github_repository_requested.connect(self._open_github_repository)
        controller.github_pull_request_requested.connect(self._open_github_pull_request)
        controller.open_repository(repository)
        controller.set_github_repository(self._home_remote_names.get(repository, ""))
        self._home_remotes.request(repository)
        session = RepositorySessionTab(controller)
        self._sessions[repository] = session
        index = self.tabs.addTab(session, repository.name)
        self.tabs.setTabToolTip(index, str(repository))
        self.tabs.setCurrentIndex(index)

        repositories = list(self._sessions)
        self._workspace.save_open_repositories(repositories)
        self._workspace.remember(repository)
        self._workspace.set_last_repository(repository)
        self._refresh_home()

    @Slot(object, bool)
    def _open_session_repository(self, value: object, remember: bool) -> None:
        del remember
        if isinstance(value, Path):
            self.open_repository(value)

    @Slot(int)
    def _close_tab(self, index: int) -> None:
        if index <= 0:
            return
        widget = self.tabs.widget(index)
        repository = next(
            (path for path, session in self._sessions.items() if session is widget),
            None,
        )
        self.tabs.removeTab(index)
        if repository is not None:
            session = self._sessions.pop(repository)
            session.shutdown()
            session.deleteLater()
        self._workspace.save_open_repositories(list(self._sessions))
        self._refresh_home()

    @Slot(int)
    def _current_tab_changed(self, index: int) -> None:
        widget = self.tabs.widget(index)
        repository = next(
            (path for path, session in self._sessions.items() if session is widget),
            None,
        )
        self.setWindowTitle(
            "MyGitClient" if repository is None else f"{repository.name} — MyGitClient"
        )

    @Slot()
    def _save_workspace(self) -> None:
        name, accepted = QInputDialog.getText(self, "Save Workspace", "Workspace name:")
        if not accepted or not name.strip():
            return
        self._workspace.save_named_workspace(name.strip(), list(self._sessions))
        self._populate_workspace_menu()
        self._refresh_home()

    def _populate_workspace_menu(self) -> None:
        self._load_workspace_menu.clear()
        names = self._workspace.named_workspaces()
        for name in names:
            action = self._load_workspace_menu.addAction(name)
            action.setData(name)
            action.triggered.connect(self._load_workspace_action)
        self._load_workspace_menu.setEnabled(bool(names))

    @Slot()
    def _load_workspace_action(self) -> None:
        action = self.sender()
        if isinstance(action, QAction) and isinstance(action.data(), str):
            self._open_workspace(action.data())

    @Slot(QAction)
    def _theme_selected(self, action: QAction) -> None:
        theme = Theme.from_value(action.data())
        self._theme = theme
        self._settings.setValue("appearance/theme", theme.value)
        self._settings.sync()
        self._restart_application()

    @Slot()
    def _configure_font_sizes(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Font Sizes")
        form = QFormLayout(dialog)
        interface_size = QSpinBox(dialog)
        interface_size.setObjectName("interfaceFontSizeSpinBox")
        interface_size.setRange(7, 24)
        app = QApplication.instance()
        default_size = QFontDatabase.systemFont(
            QFontDatabase.SystemFont.GeneralFont
        ).pointSize()
        interface_size.setValue(
            app.font().pointSize() if isinstance(app, QApplication) else default_size
        )
        diff_size = QSpinBox(dialog)
        diff_size.setObjectName("diffFontSizeSpinBox")
        diff_size.setRange(7, 32)
        raw_diff_size = self._settings.value("diff/fontSize", 11)
        try:
            saved_diff_size = (
                int(raw_diff_size) if isinstance(raw_diff_size, (int, str)) else 11
            )
        except (TypeError, ValueError):
            saved_diff_size = 11
        diff_size.setValue(saved_diff_size)
        form.addRow("Interface:", interface_size)
        form.addRow("Diff:", diff_size)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=dialog,
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._settings.setValue("appearance/fontSize", interface_size.value())
        self._settings.setValue("diff/fontSize", diff_size.value())
        if isinstance(app, QApplication):
            font = app.font()
            font.setPointSize(interface_size.value())
            app.setFont(font)
        for session in self._sessions.values():
            session.controller.set_diff_font_size(diff_size.value())

    def _apply_saved_ui_font(self) -> None:
        app = QApplication.instance()
        if not isinstance(app, QApplication):
            return
        default_size = QFontDatabase.systemFont(
            QFontDatabase.SystemFont.GeneralFont
        ).pointSize()
        raw_size = self._settings.value("appearance/fontSize", default_size)
        try:
            point_size = int(raw_size) if isinstance(raw_size, (int, str)) else default_size
        except ValueError:
            point_size = default_size
        font = app.font()
        font.setPointSize(max(7, min(24, point_size)))
        app.setFont(font)

    @Slot()
    def _manual_update_check_requested(self) -> None:
        self._manual_update_check = True
        self.statusBar().showMessage("Checking for updates…")
        self._update_checker.check()

    @Slot(object)
    def _update_available(self, value: object) -> None:
        if not isinstance(value, UpdateInfo):
            return
        self._manual_update_check = False
        install_directory = portable_install_directory()
        can_install = (
            install_directory is not None
            and value.archive_url is not None
            and value.checksum_url is not None
        )
        if not can_install:
            answer = QMessageBox.question(
                self,
                "Update available",
                f"MyGitClient {value.version} is available.\n\n"
                f"You are using {__version__}. Open the download page?",
            )
            if answer == QMessageBox.StandardButton.Yes:
                QDesktopServices.openUrl(QUrl(value.page_url))
            return
        answer = QMessageBox.question(
            self,
            "Update available",
            f"MyGitClient {value.version} is available.\n\n"
            "Download it, install it, and restart MyGitClient?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        progress = QProgressDialog("Downloading update…", "Cancel", 0, 0, self)
        progress.setObjectName("updateDownloadProgress")
        progress.setWindowTitle("Updating MyGitClient")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.canceled.connect(self._update_downloader.cancel)
        self._update_progress = progress
        progress.show()
        self._update_downloader.download(value)

    @Slot(int, int)
    def _update_download_progress(self, received: int, total: int) -> None:
        progress = self._update_progress
        if progress is None:
            return
        if total <= 0:
            progress.setRange(0, 0)
        else:
            progress.setRange(0, total)
            progress.setValue(received)
        progress.setLabelText(f"Downloading update… {received / 1024 / 1024:.1f} MB")

    @Slot(object)
    def _update_downloaded(self, value: object) -> None:
        self._close_update_progress()
        if not isinstance(value, Path):
            return
        install_directory = portable_install_directory()
        if install_directory is None:
            QMessageBox.warning(self, "Update failed", "This installation is not portable.")
            return
        if not launch_updater(value, install_directory):
            QMessageBox.warning(self, "Update failed", "Could not start the update installer.")
            return
        app = QApplication.instance()
        if isinstance(app, QApplication):
            app.quit()

    @Slot(str)
    def _update_download_failed(self, message: str) -> None:
        self._close_update_progress()
        QMessageBox.warning(self, "Update failed", message)

    @Slot()
    def _update_download_cancelled(self) -> None:
        self._close_update_progress()
        self.statusBar().showMessage("Update cancelled", 5000)

    def _close_update_progress(self) -> None:
        if self._update_progress is not None:
            self._update_progress.close()
            self._update_progress.deleteLater()
            self._update_progress = None

    @Slot()
    def _update_is_current(self) -> None:
        if self._manual_update_check:
            QMessageBox.information(
                self, "No updates", f"MyGitClient {__version__} is the latest version."
            )
        self._manual_update_check = False

    @Slot(str)
    def _update_check_failed(self, message: str) -> None:
        if self._manual_update_check:
            QMessageBox.warning(self, "Update check failed", message)
        self._manual_update_check = False

    @Slot()
    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            "About MyGitClient",
            f"MyGitClient {__version__}\n\nA focused desktop Git client.",
        )

    def _refresh_home(self) -> None:
        profiles = self._github_profiles.profiles()
        connected_logins: frozenset[str]
        try:
            connected_logins = frozenset(
                profile.login.casefold()
                for profile in profiles
                if self._github_tokens.has_token(profile.login)
            )
        except TokenStoreError as error:
            connected_logins = frozenset()
            self.statusBar().showMessage(str(error), 8000)
        self.home.set_github_profiles(profiles, connected_logins)
        repositories = self._workspace.recent_repositories()
        self.home.set_recent(repositories)
        self._home_remote_names = {
            repository.resolve(): self._home_remote_names.get(repository.resolve(), "")
            for repository in repositories
        }
        for repository in repositories:
            self._home_remotes.request(repository)
        self.home.set_workspaces(self._workspace.named_workspaces())

    @Slot(object, object)
    def _home_remotes_completed(self, repository_value: object, urls_value: object) -> None:
        if not isinstance(repository_value, Path) or not isinstance(urls_value, tuple):
            return
        values = cast(tuple[object, ...], urls_value)
        urls = tuple(url for url in values if isinstance(url, str))
        remote = first_github_remote(urls)
        repository = repository_value.resolve()
        remote_name = remote.full_name if remote is not None else ""
        self._home_remote_urls[repository] = urls
        self._home_remote_names[repository] = remote_name
        self._show_home_github(repository, remote_name)
        session = self._sessions.get(repository)
        if session is not None:
            session.controller.set_github_repository(remote_name)

    @Slot(object, str)
    def _publish_repository_to_github(self, repository_value: object, _branch: str) -> None:
        if not isinstance(repository_value, Path) or self._github_publisher.is_running:
            return
        repository = repository_value.resolve()
        session = self._sessions.get(repository)
        if session is None:
            return
        if self._home_remote_urls.get(repository):
            QMessageBox.information(
                self,
                "Repository already has a remote",
                "Publishing creates a new GitHub repository and adds it as origin. "
                "Remove or rename the existing remote first.",
            )
            return
        profiles = tuple(
            profile
            for profile in self._github_profiles.profiles()
            if self._profile_has_token(profile)
        )
        if not profiles:
            QMessageBox.information(
                self,
                "Connect GitHub",
                "Connect a GitHub account on Home before publishing a repository.",
            )
            self.tabs.setCurrentWidget(self.home)
            return
        default_profile = self._github_bindings.profile_label(repository) or ""
        dialog = GitHubPublishDialog(
            profiles, default_profile, repository.name, self
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        profile = next(
            (item for item in profiles if item.label == dialog.profile_label), None
        )
        if profile is None:
            return
        try:
            token = self._github_tokens.token(profile.login)
        except TokenStoreError as error:
            QMessageBox.warning(self, "GitHub credential error", str(error))
            return
        if not token:
            QMessageBox.warning(self, "GitHub account disconnected", "Connect the account again.")
            return
        self._pending_github_publish = (session.controller, profile)
        self._github_publisher.create(token, dialog.repository_name, private=dialog.private)

    @Slot(object)
    def _github_publish_completed(self, value: object) -> None:
        pending = self._pending_github_publish
        self._pending_github_publish = None
        if pending is None or not isinstance(value, PublishedGitHubRepository):
            return
        controller, profile = pending
        remote_url = value.ssh_url if profile.clone_transport == "ssh" else value.clone_url
        repository = controller.repository
        if repository is not None:
            self._github_bindings.bind(repository, profile.label)
            self._home_remote_names[repository.resolve()] = value.full_name
        controller.publish_created_github_repository(remote_url, value.full_name)

    @Slot(str)
    def _github_publish_failed(self, message: str) -> None:
        self._pending_github_publish = None
        QMessageBox.warning(self, "Could not publish to GitHub", message)

    @Slot(object)
    def _open_github_repository(self, repository_value: object) -> None:
        if not isinstance(repository_value, Path):
            return
        full_name = self._home_remote_names.get(repository_value.resolve(), "")
        if full_name:
            QDesktopServices.openUrl(QUrl(f"https://github.com/{full_name}"))

    @Slot(object, str)
    def _open_github_pull_request(self, repository_value: object, branch: str) -> None:
        if not isinstance(repository_value, Path):
            return
        full_name = self._home_remote_names.get(repository_value.resolve(), "")
        if not full_name:
            return
        encoded_branch = quote(branch, safe="")
        QDesktopServices.openUrl(
            QUrl(f"https://github.com/{full_name}/compare/{encoded_branch}?expand=1")
        )

    def _profile_has_token(self, profile: GitHubProfile) -> bool:
        try:
            return self._github_tokens.has_token(profile.login)
        except TokenStoreError:
            return False

    def _show_home_github(self, repository: Path, remote_name: str) -> None:
        profile_label = self._github_bindings.profile_label(repository)
        if profile_label is None and remote_name:
            owner = remote_name.partition("/")[0]
            profile = next(
                (
                    item
                    for item in self._github_profiles.profiles()
                    if item.login.casefold() == owner.casefold()
                ),
                None,
            )
            profile_label = profile.label if profile is not None else ""
        self.home.set_recent_github(repository, remote_name, profile_label or "")

    @Slot(object, object)
    def _bind_home_github_profile(self, repository_value: object, profile_value: object) -> None:
        if not isinstance(repository_value, Path):
            return
        profile_label = profile_value if isinstance(profile_value, str) else None
        self._github_bindings.bind(repository_value, profile_label)
        self._show_home_github(
            repository_value.resolve(), self._home_remote_names.get(repository_value.resolve(), "")
        )

    @Slot()
    def _restart_application(self) -> None:
        if getattr(sys, "frozen", False):
            program = sys.executable
            arguments = sys.argv[1:]
        else:
            program = sys.executable
            arguments = ["-m", "mygitclient", *sys.argv[1:]]
        started, _process_id = QProcess.startDetached(program, arguments, str(Path.cwd()))
        if not started:
            QMessageBox.warning(
                self,
                "Restart failed",
                "The theme was saved, but MyGitClient could not restart automatically.",
            )
            return
        app = QApplication.instance()
        if isinstance(app, QApplication):
            app.quit()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self._closing:
            super().closeEvent(event)
            return
        self._closing = True
        repositories = list(self._sessions)
        for session in tuple(self._sessions.values()):
            session.shutdown()
        self._sessions.clear()
        self._workspace.save_open_repositories(repositories)
        self._home_remotes.shutdown()
        super().closeEvent(event)
