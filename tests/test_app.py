from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QTreeWidget

from mygitclient.theme import Theme
from mygitclient.ui.main_window import MainWindow


def test_main_window_is_created(qapp: QApplication) -> None:
    settings = QSettings(QSettings.Format.IniFormat, QSettings.Scope.UserScope, "test", "app")
    settings.clear()
    window = MainWindow(settings, Theme.SYSTEM)

    assert window.windowTitle() == "MyGitClient"
    assert window.centralWidget() is not None

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


def test_invalid_theme_falls_back_to_system() -> None:
    assert Theme.from_value("unknown") is Theme.SYSTEM


def test_theme_actions_are_exclusive_and_persisted(
    qapp: QApplication, tmp_path: Path
) -> None:
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
