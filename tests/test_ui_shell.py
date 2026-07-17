from __future__ import annotations

import subprocess
from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QPushButton,
    QTabWidget,
    QToolBar,
    QTreeWidget,
    QWidget,
)
from pytestqt.qtbot import QtBot

from mygitclient.theme import Theme
from mygitclient.ui.main_window import MainWindow


def test_main_window_is_created(qapp: QApplication) -> None:
    settings = QSettings(QSettings.Format.IniFormat, QSettings.Scope.UserScope, "test", "app")
    settings.clear()
    window = MainWindow(settings, Theme.SYSTEM)

    assert window.windowTitle() == "MyGitClient"
    assert window.centralWidget() is not None
    assert not window.windowIcon().isNull()
    toolbar = window.findChild(QToolBar, "repositoryToolbar")
    refresh_action = window.findChild(QAction, "refreshAction")
    assert toolbar is not None
    assert refresh_action is not None
    assert not refresh_action.icon().isNull()

    window.close()


def test_recent_repository_is_displayed(qapp: QApplication, tmp_path: Path) -> None:
    repository = tmp_path / "project"
    repository.mkdir()
    (repository / ".git").mkdir()
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    settings.setValue("workspace/recentRepositories", [str(repository)])

    window = MainWindow(settings, Theme.SYSTEM)
    repositories = window.findChild(QTreeWidget, "repositoriesTree")

    assert repositories is not None
    item = repositories.topLevelItem(0)
    assert item is not None
    assert item.text(0) == "project"
    window.close()


def test_commit_history_is_loaded_asynchronously(
    qapp: QApplication, qtbot: QtBot, tmp_path: Path
) -> None:
    repository = tmp_path / "history"
    repository.mkdir()
    subprocess.run(["git", "init", "--initial-branch=main"], cwd=repository, check=True)
    tracked = repository / "tracked.txt"
    for message in ("First commit", "Second commit"):
        tracked.write_text(f"{message}\n", encoding="utf-8")
        subprocess.run(["git", "add", "tracked.txt"], cwd=repository, check=True)
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=History Test",
                "-c",
                "user.email=history@example.invalid",
                "commit",
                "-m",
                message,
            ],
            cwd=repository,
            check=True,
            capture_output=True,
        )
    settings = QSettings(str(tmp_path / "history.ini"), QSettings.Format.IniFormat)
    window = MainWindow(settings, Theme.SYSTEM)
    history = window.findChild(QTreeWidget, "historyTree")
    load_more = window.findChild(QPushButton, "historyLoadMoreButton")
    tabs = window.findChild(QTabWidget, "workspaceTabs")
    diff_container = window.findChild(QWidget, "diffContainer")
    assert history is not None
    assert load_more is not None
    assert tabs is not None
    assert diff_container is not None

    window.open_repository(repository)
    qtbot.waitUntil(lambda: history.topLevelItemCount() == 2, timeout=5000)

    first = history.topLevelItem(0)
    second = history.topLevelItem(1)
    assert first is not None
    assert second is not None
    assert first.text(1) == "Second commit"
    assert first.text(2) == "History Test"
    assert len(first.text(4)) == 8
    assert second.text(1) == "First commit"
    assert not load_more.isVisible()
    tabs.setCurrentIndex(1)
    assert diff_container.isHidden()
    tabs.setCurrentIndex(0)
    assert not diff_container.isHidden()
    window.close()


def test_deleted_recent_repository_is_removed_when_selected(
    qapp: QApplication, tmp_path: Path
) -> None:
    repository = tmp_path / "project"
    repository.mkdir()
    (repository / ".git").mkdir()
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    settings.setValue("workspace/recentRepositories", [str(repository)])
    window = MainWindow(settings, Theme.SYSTEM)
    repositories = window.findChild(QTreeWidget, "repositoriesTree")
    assert repositories is not None
    item = repositories.topLevelItem(0)
    assert item is not None

    (repository / ".git").rmdir()
    repository.rmdir()
    item_activated = repositories.itemActivated
    item_activated.emit(item, 0)

    placeholder = repositories.topLevelItem(0)
    assert placeholder is not None
    assert placeholder.text(0) == "No recent repositories"
    assert settings.value("workspace/recentRepositories") == []
    window.close()


def test_recent_repository_can_be_removed_with_context_action(
    qapp: QApplication, tmp_path: Path
) -> None:
    repository = tmp_path / "project"
    repository.mkdir()
    (repository / ".git").mkdir()
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    settings.setValue("workspace/recentRepositories", [str(repository)])
    window = MainWindow(settings, Theme.SYSTEM)
    repositories = window.findChild(QTreeWidget, "repositoriesTree")
    remove_action = window.findChild(QAction, "removeRecentAction")
    assert repositories is not None
    assert remove_action is not None
    item = repositories.topLevelItem(0)
    assert item is not None

    repositories.setCurrentItem(item)
    remove_action.trigger()

    placeholder = repositories.topLevelItem(0)
    assert placeholder is not None
    assert placeholder.text(0) == "No recent repositories"
    assert settings.value("workspace/recentRepositories") == []
    window.close()


def test_open_repositories_are_restored_and_switchable(
    qapp: QApplication, qtbot: QtBot, tmp_path: Path
) -> None:
    repositories = [tmp_path / "first", tmp_path / "second"]
    for repository in repositories:
        repository.mkdir()
        subprocess.run(
            ["git", "init", "--initial-branch=main"],
            cwd=repository,
            check=True,
            capture_output=True,
        )
    settings = QSettings(str(tmp_path / "session.ini"), QSettings.Format.IniFormat)
    settings.setValue("workspace/openRepositories", [str(path) for path in repositories])
    settings.setValue("workspace/lastRepository", str(repositories[1]))

    window = MainWindow(settings, Theme.SYSTEM)
    switcher = window.findChild(QComboBox, "repositorySwitcher")
    workspace_tabs = window.findChild(QTabWidget, "workspaceTabs")
    diff_container = window.findChild(QWidget, "diffContainer")
    assert switcher is not None
    assert workspace_tabs is not None
    assert diff_container is not None
    assert switcher.count() == 2
    qtbot.waitUntil(lambda: window.windowTitle().startswith("second —"), timeout=5000)

    workspace_tabs.setCurrentIndex(1)
    switcher.setCurrentIndex(0)
    qtbot.waitUntil(lambda: window.windowTitle().startswith("first —"), timeout=5000)
    assert switcher.currentText() == "first"
    assert diff_container.isHidden()
    assert workspace_tabs.currentIndex() == 1
    assert settings.value("workspace/lastRepository") == str(repositories[0])
    window.close()


def test_invalid_theme_falls_back_to_system() -> None:
    assert Theme.from_value("unknown") is Theme.SYSTEM


def test_theme_actions_are_exclusive_and_persisted(qapp: QApplication, tmp_path: Path) -> None:
    settings = QSettings(str(tmp_path / "theme.ini"), QSettings.Format.IniFormat)
    window = MainWindow(settings, Theme.SYSTEM)
    system_action = window.findChild(QAction, "themeAction_system")
    dark_action = window.findChild(QAction, "themeAction_dark")

    assert system_action is not None
    assert dark_action is not None
    dark_action.trigger()

    assert dark_action.isChecked()
    assert not system_action.isChecked()
    assert settings.value("appearance/theme") == Theme.DARK.value

    system_action.trigger()
    assert system_action.isChecked()
    assert not dark_action.isChecked()
    assert qapp.styleSheet() == ""
    window.close()
