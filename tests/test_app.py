from __future__ import annotations

import subprocess
from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QComboBox, QPlainTextEdit, QSplitter, QTreeWidget
from pytestqt.qtbot import QtBot

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


def test_invalid_theme_falls_back_to_system() -> None:
    assert Theme.from_value("unknown") is Theme.SYSTEM


def test_selecting_changed_file_displays_diff(
    qapp: QApplication, qtbot: QtBot, tmp_path: Path
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    subprocess.run(
        ["git", "init", "--initial-branch=main"],
        cwd=repository,
        check=True,
        capture_output=True,
    )
    tracked = repository / "tracked.txt"
    tracked.write_text("before\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=repository, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=MyGitClient Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-m",
            "initial",
        ],
        cwd=repository,
        check=True,
        capture_output=True,
    )
    tracked.write_text("after\n", encoding="utf-8")

    settings = QSettings(str(tmp_path / "diff.ini"), QSettings.Format.IniFormat)
    window = MainWindow(settings, Theme.SYSTEM)
    changes = window.findChild(QTreeWidget, "changesTree")
    diff_panel = window.findChild(QPlainTextEdit, "diffPanel")
    splitter = window.findChild(QSplitter, "mainSplitter")
    assert changes is not None
    assert diff_panel is not None
    assert splitter is not None

    window.resize(1400, 800)
    window.show()
    window.open_repository(repository)
    qtbot.waitUntil(lambda: changes.topLevelItemCount() == 1, timeout=5000)
    changed_item = changes.topLevelItem(0)
    assert changed_item is not None
    changes.setCurrentItem(changed_item)
    qtbot.waitUntil(lambda: "+after" in diff_panel.toPlainText(), timeout=5000)

    assert "-before" in diff_panel.toPlainText()
    sizes = splitter.sizes()
    assert len(sizes) == 4
    assert sizes[1] == 0
    assert sizes[3] > sizes[2]
    window.close()


def test_diff_version_can_switch_between_worktree_and_staged(
    qapp: QApplication, qtbot: QtBot, tmp_path: Path
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    subprocess.run(
        ["git", "init", "--initial-branch=main"],
        cwd=repository,
        check=True,
        capture_output=True,
    )
    tracked = repository / "tracked.txt"
    tracked.write_text("original\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=repository, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=MyGitClient Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-m",
            "initial",
        ],
        cwd=repository,
        check=True,
        capture_output=True,
    )
    tracked.write_text("staged version\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=repository, check=True)
    tracked.write_text("working version\n", encoding="utf-8")

    settings = QSettings(str(tmp_path / "versions.ini"), QSettings.Format.IniFormat)
    window = MainWindow(settings, Theme.SYSTEM)
    changes = window.findChild(QTreeWidget, "changesTree")
    diff_panel = window.findChild(QPlainTextEdit, "diffPanel")
    version_combo = window.findChild(QComboBox, "diffVersionCombo")
    assert changes is not None
    assert diff_panel is not None
    assert version_combo is not None

    window.open_repository(repository)
    qtbot.waitUntil(lambda: changes.topLevelItemCount() == 1, timeout=5000)
    changed_item = changes.topLevelItem(0)
    assert changed_item is not None
    changes.setCurrentItem(changed_item)
    qtbot.waitUntil(lambda: "+working version" in diff_panel.toPlainText(), timeout=5000)

    assert [version_combo.itemText(index) for index in range(version_combo.count())] == [
        "Working tree",
        "Staged",
    ]
    version_combo.setCurrentIndex(1)
    qtbot.waitUntil(lambda: "+staged version" in diff_panel.toPlainText(), timeout=5000)
    assert "-original" in diff_panel.toPlainText()
    window.close()


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
