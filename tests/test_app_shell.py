import subprocess
from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QMenu, QToolBar
from pytestqt.qtbot import QtBot

from mygitclient.git.service import GitService
from mygitclient.theme import Theme
from mygitclient.ui.app_shell import AppShell, RepositorySessionTab


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
        "File"
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


def test_home_keeps_menus_from_last_active_repository(
    qtbot: QtBot, tmp_path: Path
) -> None:
    repository = tmp_path / "repository"
    _make_repository(repository)
    settings = QSettings(str(tmp_path / "home-menus.ini"), QSettings.Format.IniFormat)
    shell = AppShell(settings, Theme.SYSTEM)
    qtbot.addWidget(shell)
    shell.open_repository(repository)

    shell.tabs.setCurrentWidget(shell.home)

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
