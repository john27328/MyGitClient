import subprocess
from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QMenu, QToolBar
from pytestqt.qtbot import QtBot

from mygitclient.git.service import GitService
from mygitclient.github import DeviceFlowResult, GitHubProfile, GitHubTokenStore
from mygitclient.theme import Theme
from mygitclient.ui.app_shell import AppShell, RepositorySessionTab


class _MemoryTokenBackend:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.values.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.values[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        self.values.pop((service, username), None)


class _TestAppShell(AppShell):
    def use_memory_github_tokens(self) -> None:
        self._github_tokens = GitHubTokenStore(_MemoryTokenBackend())

    def save_github_profile(self, profile: GitHubProfile) -> None:
        self._github_profiles.save(profile)

    def complete_new_github_connection(self, result: DeviceFlowResult) -> None:
        self._github_device_add_new = True
        self._github_device_completed(result)

    @property
    def github_profiles(self) -> tuple[GitHubProfile, ...]:
        return self._github_profiles.profiles()

    def has_github_token(self, login: str) -> bool:
        return self._github_tokens.has_token(login)


def _make_repository(path: Path) -> None:
    path.mkdir()
    subprocess.run(
        ["git", "init", "--initial-branch=main"],
        cwd=path,
        check=True,
        capture_output=True,
    )


def test_repositories_open_in_isolated_tabs(qtbot: QtBot, tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    _make_repository(first)
    _make_repository(second)
    settings = QSettings(str(tmp_path / "shell.ini"), QSettings.Format.IniFormat)
    shell = AppShell(settings, Theme.SYSTEM)
    qtbot.addWidget(shell)

    shell.open_repository(first)
    shell.open_repository(second)

    assert shell.tabs.count() == 3
    first_session = shell.tabs.widget(1)
    second_session = shell.tabs.widget(2)
    assert isinstance(first_session, RepositorySessionTab)
    assert isinstance(second_session, RepositorySessionTab)
    first_service = first_session.controller.findChild(GitService)
    second_service = second_session.controller.findChild(GitService)
    assert first_service is not None
    assert second_service is not None
    assert first_service is not second_service

    shell.open_repository(first)
    assert shell.tabs.count() == 3
    assert shell.tabs.currentWidget() is first_session
    shell.close()


def test_repository_request_from_session_opens_another_tab(
    qtbot: QtBot, tmp_path: Path
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    _make_repository(first)
    _make_repository(second)
    settings = QSettings(str(tmp_path / "routing.ini"), QSettings.Format.IniFormat)
    shell = AppShell(settings, Theme.SYSTEM)
    qtbot.addWidget(shell)
    shell.open_repository(first)
    first_session = shell.tabs.widget(1)
    assert isinstance(first_session, RepositorySessionTab)

    first_session.open_repository(second)

    assert shell.tabs.count() == 3
    assert shell.tabs.tabText(2) == "second"
    shell.close()


def test_active_repository_exposes_its_menus(qtbot: QtBot, tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    _make_repository(repository)
    settings = QSettings(str(tmp_path / "menus.ini"), QSettings.Format.IniFormat)
    shell = AppShell(settings, Theme.SYSTEM)
    qtbot.addWidget(shell)

    assert [action.text().replace("&", "") for action in shell.menuBar().actions()] == [
        "File",
        "Workspace",
        "View",
        "Help",
    ]

    shell.open_repository(repository)
    repository_menus = {
        action.text().replace("&", "") for action in shell.menuBar().actions()
    }
    assert {"File", "Workspace", "View", "Help"} <= repository_menus

    shell.tabs.setCurrentIndex(0)
    home_menus = {
        action.text().replace("&", "") for action in shell.menuBar().actions()
    }
    assert {"File", "Workspace", "View", "Help"} <= home_menus
    shell.close()


def test_home_owns_global_menus_without_open_repository(
    qtbot: QtBot, tmp_path: Path
) -> None:
    settings = QSettings(str(tmp_path / "home-menus.ini"), QSettings.Format.IniFormat)
    shell = AppShell(settings, Theme.SYSTEM)
    qtbot.addWidget(shell)

    menus = {action.text().replace("&", "") for action in shell.menuBar().actions()}
    assert {"File", "Workspace", "View", "Help"} <= menus
    view_action = next(
        action for action in shell.menuBar().actions() if action.text().replace("&", "") == "View"
    )
    view_menu = view_action.menu()
    assert isinstance(view_menu, QMenu)
    assert any(action.text() == "Font Sizes…" for action in view_menu.actions())
    shell.close()


def test_repository_toolbar_remains_visible_in_session_tab(
    qtbot: QtBot, tmp_path: Path
) -> None:
    repository = tmp_path / "repository"
    _make_repository(repository)
    settings = QSettings(str(tmp_path / "toolbar.ini"), QSettings.Format.IniFormat)
    shell = AppShell(settings, Theme.SYSTEM)
    qtbot.addWidget(shell)
    shell.show()

    shell.open_repository(repository)
    session = shell.tabs.currentWidget()
    assert isinstance(session, RepositorySessionTab)
    toolbar = session.findChild(QToolBar, "repositoryToolbar")
    assert toolbar is not None
    assert toolbar.isVisibleTo(session)
    shell.close()


def test_connecting_new_github_account_creates_profile_from_authorized_login(
    qtbot: QtBot, tmp_path: Path
) -> None:
    settings = QSettings(str(tmp_path / "github.ini"), QSettings.Format.IniFormat)
    shell = _TestAppShell(settings, Theme.SYSTEM)
    qtbot.addWidget(shell)
    shell.use_memory_github_tokens()

    shell.complete_new_github_connection(DeviceFlowResult("octocat", "secret-token"))

    assert shell.github_profiles == (GitHubProfile("octocat", "octocat"),)
    assert shell.has_github_token("octocat")
    shell.close()


def test_connecting_known_github_login_reuses_existing_profile(
    qtbot: QtBot, tmp_path: Path
) -> None:
    settings = QSettings(str(tmp_path / "github-existing.ini"), QSettings.Format.IniFormat)
    shell = _TestAppShell(settings, Theme.SYSTEM)
    qtbot.addWidget(shell)
    profile = GitHubProfile("Personal", "octocat", "ssh", "Octo", "octo@example.invalid")
    shell.save_github_profile(profile)
    shell.use_memory_github_tokens()

    shell.complete_new_github_connection(DeviceFlowResult("OctoCat", "secret-token"))

    assert shell.github_profiles == (profile,)
    assert shell.has_github_token("octocat")
    shell.close()
