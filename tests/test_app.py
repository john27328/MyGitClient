from __future__ import annotations

import subprocess
from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTabWidget,
    QToolBar,
    QToolButton,
    QTreeWidget,
    QWidget,
)
from pytest import MonkeyPatch
from pytestqt.qtbot import QtBot

from mygitclient.theme import Theme
from mygitclient.ui.diff_gutter import DiffGutter
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


def test_diff_and_line_numbers_scroll_together(qapp: QApplication, qtbot: QtBot) -> None:
    settings = QSettings(QSettings.Format.IniFormat, QSettings.Scope.UserScope, "test", "scroll")
    settings.clear()
    window = MainWindow(settings, Theme.SYSTEM)
    diff_panel = window.findChild(QPlainTextEdit, "diffPanel")
    diff_gutter = window.findChild(QPlainTextEdit, "diffGutter")
    assert diff_panel is not None
    assert diff_gutter is not None
    content = "\n".join(f"line {number}" for number in range(200))
    numbers = "\n".join(str(number) for number in range(200))
    diff_panel.setPlainText(content)
    diff_gutter.setPlainText(numbers)
    diff_panel.show()
    diff_gutter.show()
    window.resize(800, 300)
    window.show()
    qtbot.waitUntil(lambda: diff_panel.verticalScrollBar().maximum() > 0)

    diff_panel.verticalScrollBar().setValue(40)
    assert diff_gutter.verticalScrollBar().value() == 40

    diff_gutter.verticalScrollBar().setValue(80)
    assert diff_panel.verticalScrollBar().value() == 80
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
    assert switcher is not None
    assert switcher.count() == 2
    qtbot.waitUntil(lambda: window.windowTitle().startswith("second —"), timeout=5000)

    switcher.setCurrentIndex(0)
    qtbot.waitUntil(lambda: window.windowTitle().startswith("first —"), timeout=5000)
    assert settings.value("workspace/lastRepository") == str(repositories[0])
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
    diff_gutter = window.findChild(QPlainTextEdit, "diffGutter")
    view_mode = window.findChild(QComboBox, "diffViewModeCombo")
    side_old = window.findChild(QPlainTextEdit, "sideBySideOld")
    side_new = window.findChild(QPlainTextEdit, "sideBySideNew")
    splitter = window.findChild(QSplitter, "mainSplitter")
    assert changes is not None
    assert diff_panel is not None
    assert diff_gutter is not None
    assert view_mode is not None
    assert side_old is not None
    assert side_new is not None
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
    assert "│" not in diff_panel.toPlainText()
    gutter_lines = [line.strip() for line in diff_gutter.toPlainText().splitlines()[-2:]]
    assert all(line.startswith("□") and line.endswith("1") for line in gutter_lines)
    assert diff_panel.font().fixedPitch()
    tracked.write_text("changed again\n", encoding="utf-8")
    qtbot.waitUntil(lambda: "+changed again" in diff_panel.toPlainText(), timeout=5000)
    view_mode.setCurrentIndex(1)
    assert "before" in side_old.toPlainText()
    assert "changed again" in side_new.toPlainText()
    assert settings.value("diff/viewMode") == "side-by-side"
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


def test_untracked_file_is_listed_and_displays_diff(
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
    nested = repository / "assets" / "icon.svg"
    nested.parent.mkdir()
    nested.write_text("<svg>new icon</svg>\n", encoding="utf-8")
    settings = QSettings(str(tmp_path / "untracked.ini"), QSettings.Format.IniFormat)
    window = MainWindow(settings, Theme.SYSTEM)
    changes = window.findChild(QTreeWidget, "changesTree")
    diff_panel = window.findChild(QPlainTextEdit, "diffPanel")
    assert changes is not None
    assert diff_panel is not None

    window.open_repository(repository)
    qtbot.waitUntil(lambda: changes.topLevelItemCount() == 1, timeout=5000)
    item = changes.topLevelItem(0)
    assert item is not None
    assert item.text(0) == "assets/icon.svg"
    changes.setCurrentItem(item)
    qtbot.waitUntil(lambda: "+<svg>new icon</svg>" in diff_panel.toPlainText(), timeout=5000)
    window.close()


def test_file_checkbox_stages_and_unstages_changes(
    qapp: QApplication, qtbot: QtBot, tmp_path: Path
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    subprocess.run(["git", "init", "--initial-branch=main"], cwd=repository, check=True)
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
    settings = QSettings(str(tmp_path / "stage.ini"), QSettings.Format.IniFormat)
    window = MainWindow(settings, Theme.SYSTEM)
    changes = window.findChild(QTreeWidget, "changesTree")
    assert changes is not None
    window.open_repository(repository)
    qtbot.waitUntil(lambda: changes.topLevelItemCount() == 1, timeout=5000)
    item = changes.topLevelItem(0)
    assert item is not None
    assert item.checkState(0) is Qt.CheckState.Unchecked

    def index_text_is(expected: str) -> bool:
        current = changes.topLevelItem(0)
        return current is not None and current.text(1) == expected

    item.setCheckState(0, Qt.CheckState.Checked)
    qtbot.waitUntil(lambda: index_text_is("Modified"), timeout=5000)
    staged_item = changes.topLevelItem(0)
    assert staged_item is not None
    assert staged_item.checkState(0) is Qt.CheckState.Checked

    staged_item.setCheckState(0, Qt.CheckState.Unchecked)
    qtbot.waitUntil(lambda: index_text_is(""), timeout=5000)
    unstaged_item = changes.topLevelItem(0)
    assert unstaged_item is not None
    assert unstaged_item.checkState(0) is Qt.CheckState.Unchecked
    window.close()


def test_stage_all_checkbox_updates_every_file(
    qapp: QApplication, qtbot: QtBot, tmp_path: Path
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    subprocess.run(["git", "init", "--initial-branch=main"], cwd=repository, check=True)
    for name in ("first.txt", "second.txt"):
        (repository / name).write_text("before\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repository, check=True)
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
    for name in ("first.txt", "second.txt"):
        (repository / name).write_text("after\n", encoding="utf-8")
    settings = QSettings(str(tmp_path / "stage-all.ini"), QSettings.Format.IniFormat)
    window = MainWindow(settings, Theme.SYSTEM)
    changes = window.findChild(QTreeWidget, "changesTree")
    stage_all = window.findChild(QCheckBox, "stageAllCheckBox")
    assert changes is not None
    assert stage_all is not None
    window.open_repository(repository)
    qtbot.waitUntil(lambda: changes.topLevelItemCount() == 2, timeout=5000)

    def every_file_has_state(expected: Qt.CheckState) -> bool:
        return all(
            (item := changes.topLevelItem(index)) is not None
            and item.checkState(0) is expected
            for index in range(changes.topLevelItemCount())
        )

    assert stage_all.checkState() is Qt.CheckState.Unchecked
    stage_all.setCheckState(Qt.CheckState.Checked)
    qtbot.waitUntil(lambda: every_file_has_state(Qt.CheckState.Checked), timeout=5000)
    assert stage_all.checkState() is Qt.CheckState.Checked

    stage_all.setCheckState(Qt.CheckState.Unchecked)
    qtbot.waitUntil(lambda: every_file_has_state(Qt.CheckState.Unchecked), timeout=5000)
    assert stage_all.checkState() is Qt.CheckState.Unchecked
    window.close()


def test_commit_and_amend_from_commit_panel(
    qapp: QApplication, qtbot: QtBot, tmp_path: Path
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    subprocess.run(["git", "init", "--initial-branch=main"], cwd=repository, check=True)
    tracked = repository / "tracked.txt"
    tracked.write_text("content\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=repository, check=True)
    subprocess.run(
        ["git", "config", "user.name", "MyGitClient Test"], cwd=repository, check=True
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.invalid"], cwd=repository, check=True
    )
    settings = QSettings(str(tmp_path / "commit.ini"), QSettings.Format.IniFormat)
    window = MainWindow(settings, Theme.SYSTEM)
    changes = window.findChild(QTreeWidget, "changesTree")
    message = window.findChild(QPlainTextEdit, "commitMessageEdit")
    description = window.findChild(QPlainTextEdit, "commitDescriptionEdit")
    commit_button = window.findChild(QPushButton, "commitButton")
    amend = window.findChild(QCheckBox, "amendCheckBox")
    assert changes is not None
    assert message is not None
    assert description is not None
    assert commit_button is not None
    assert amend is not None
    window.open_repository(repository)
    qtbot.waitUntil(lambda: changes.topLevelItemCount() == 1, timeout=5000)
    assert message.toPlainText() == "Add tracked.txt"
    assert description.toPlainText() == "- Add tracked.txt"
    assert commit_button.isEnabled()

    message.setPlainText("initial commit")
    assert commit_button.isEnabled()
    commit_button.click()
    qtbot.waitUntil(lambda: changes.topLevelItemCount() == 0, timeout=5000)
    log = subprocess.run(
        ["git", "log", "-1", "--pretty=%s"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )
    assert log.stdout.strip() == "initial commit"
    body = subprocess.run(
        ["git", "log", "-1", "--pretty=%b"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )
    assert body.stdout.strip() == "- Add tracked.txt"

    message.setPlainText("amended commit")
    amend.setChecked(True)
    assert commit_button.isEnabled()
    commit_button.click()
    qtbot.waitUntil(lambda: message.toPlainText() == "", timeout=5000)
    amended_log = subprocess.run(
        ["git", "log", "-1", "--pretty=%s"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )
    assert amended_log.stdout.strip() == "amended commit"
    window.close()


def test_selected_hunk_can_be_staged(qapp: QApplication, qtbot: QtBot, tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    subprocess.run(["git", "init", "--initial-branch=main"], cwd=repository, check=True)
    tracked = repository / "tracked.txt"
    tracked.write_text("".join(f"line {number}\n" for number in range(1, 25)), encoding="utf-8")
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
    lines = tracked.read_text(encoding="utf-8").splitlines()
    lines[1] = "first changed"
    lines[20] = "second changed"
    tracked.write_text("\n".join(lines) + "\n", encoding="utf-8")
    settings = QSettings(str(tmp_path / "hunk.ini"), QSettings.Format.IniFormat)
    window = MainWindow(settings, Theme.SYSTEM)
    changes = window.findChild(QTreeWidget, "changesTree")
    diff_panel = window.findChild(QPlainTextEdit, "diffPanel")
    hunk_button = window.findChild(QToolButton, "diffHunkButton")
    assert changes is not None
    assert diff_panel is not None
    assert hunk_button is not None
    window.open_repository(repository)
    qtbot.waitUntil(lambda: changes.topLevelItemCount() == 1, timeout=5000)
    item = changes.topLevelItem(0)
    assert item is not None
    changes.setCurrentItem(item)
    qtbot.waitUntil(lambda: "+first changed" in diff_panel.toPlainText(), timeout=5000)
    cursor = diff_panel.document().find("first changed")
    assert not cursor.isNull()
    diff_panel.setTextCursor(cursor)
    assert hunk_button.isEnabled()
    hunk_button.click()

    def first_hunk_is_staged() -> bool:
        result = subprocess.run(
            ["git", "diff", "--cached", "--", "tracked.txt"],
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
        )
        return "+first changed" in result.stdout

    qtbot.waitUntil(first_hunk_is_staged, timeout=5000)
    cached = subprocess.run(
        ["git", "diff", "--cached", "--", "tracked.txt"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "+second changed" not in cached
    window.close()


def test_selected_diff_lines_can_be_staged(
    qapp: QApplication, qtbot: QtBot, tmp_path: Path
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    subprocess.run(["git", "init", "--initial-branch=main"], cwd=repository, check=True)
    tracked = repository / "tracked.txt"
    tracked.write_text("one\ntwo\nthree\nfour\nfive\n", encoding="utf-8")
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
    tracked.write_text("one\nTWO\nthree\nFOUR\nfive\n", encoding="utf-8")
    settings = QSettings(str(tmp_path / "lines.ini"), QSettings.Format.IniFormat)
    window = MainWindow(settings, Theme.SYSTEM)
    changes = window.findChild(QTreeWidget, "changesTree")
    diff_panel = window.findChild(QPlainTextEdit, "diffPanel")
    gutter = window.findChild(DiffGutter, "diffGutter")
    apply_lines = window.findChild(QToolButton, "diffSelectedLinesButton")
    clear_lines = window.findChild(QToolButton, "diffClearSelectionButton")
    version_combo = window.findChild(QComboBox, "diffVersionCombo")
    assert changes is not None
    assert diff_panel is not None
    assert gutter is not None
    assert apply_lines is not None
    assert clear_lines is not None
    assert version_combo is not None
    window.open_repository(repository)
    qtbot.waitUntil(lambda: changes.topLevelItemCount() == 1, timeout=5000)
    item = changes.topLevelItem(0)
    assert item is not None
    changes.setCurrentItem(item)
    qtbot.waitUntil(lambda: "+TWO" in diff_panel.toPlainText(), timeout=5000)
    assert "□" in gutter.toPlainText()
    hunk_header = diff_panel.document().find("@@")
    assert not hunk_header.isNull()
    gutter.line_activated.emit(hunk_header.blockNumber(), False)
    assert gutter.toPlainText().count("✓") == 4
    assert "■" in gutter.toPlainText()
    clear_lines.click()
    assert "✓" not in gutter.toPlainText()
    deleted = diff_panel.document().find("-two")
    added = diff_panel.document().find("+TWO")
    assert not deleted.isNull()
    assert not added.isNull()
    gutter.line_activated.emit(deleted.blockNumber(), False)
    gutter.line_activated.emit(added.blockNumber(), False)
    assert apply_lines.isEnabled()
    assert "✓" in gutter.toPlainText()
    qtbot.wait(1800)
    assert gutter.toPlainText().count("✓") == 2
    apply_lines.click()

    def selected_lines_are_staged() -> bool:
        cached = subprocess.run(
            ["git", "diff", "--cached", "--", "tracked.txt"],
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        return "+TWO" in cached

    qtbot.waitUntil(selected_lines_are_staged, timeout=5000)
    cached = subprocess.run(
        ["git", "diff", "--cached", "--", "tracked.txt"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "+FOUR" not in cached

    qtbot.waitUntil(lambda: version_combo.findData(True) >= 0, timeout=5000)
    version_combo.setCurrentIndex(version_combo.findData(True))
    qtbot.waitUntil(lambda: "+TWO" in diff_panel.toPlainText(), timeout=5000)
    staged_deleted = diff_panel.document().find("-two")
    staged_added = diff_panel.document().find("+TWO")
    assert not staged_deleted.isNull()
    assert not staged_added.isNull()
    gutter.line_activated.emit(staged_deleted.blockNumber(), False)
    gutter.line_activated.emit(staged_added.blockNumber(), False)
    assert apply_lines.text() == "Unstage selected"
    apply_lines.click()

    def selected_lines_are_unstaged() -> bool:
        result = subprocess.run(
            ["git", "diff", "--cached", "--", "tracked.txt"],
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
        )
        return "+TWO" not in result.stdout

    qtbot.waitUntil(selected_lines_are_unstaged, timeout=5000)
    window.close()


def test_discard_requires_confirmation_and_restores_file(
    qapp: QApplication, qtbot: QtBot, monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    subprocess.run(["git", "init", "--initial-branch=main"], cwd=repository, check=True)
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
    settings = QSettings(str(tmp_path / "discard.ini"), QSettings.Format.IniFormat)
    window = MainWindow(settings, Theme.SYSTEM)
    changes = window.findChild(QTreeWidget, "changesTree")
    discard = window.findChild(QAction, "discardChangesAction")
    assert changes is not None
    assert discard is not None
    window.open_repository(repository)
    qtbot.waitUntil(lambda: changes.topLevelItemCount() == 1, timeout=5000)
    item = changes.topLevelItem(0)
    assert item is not None
    changes.setCurrentItem(item)
    def confirm_discard(*_args: object, **_kwargs: object) -> QMessageBox.StandardButton:
        return QMessageBox.StandardButton.Discard

    monkeypatch.setattr(QMessageBox, "question", confirm_discard)
    discard.trigger()
    qtbot.waitUntil(
        lambda: tracked.exists() and tracked.read_text(encoding="utf-8") == "before\n",
        timeout=5000,
    )
    window.close()


def test_untracked_file_can_be_added_to_gitignore(
    qapp: QApplication, qtbot: QtBot, tmp_path: Path
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    subprocess.run(["git", "init", "--initial-branch=main"], cwd=repository, check=True)
    untracked = repository / "generated.log"
    untracked.write_text("noise\n", encoding="utf-8")
    settings = QSettings(str(tmp_path / "ignore.ini"), QSettings.Format.IniFormat)
    window = MainWindow(settings, Theme.SYSTEM)
    changes = window.findChild(QTreeWidget, "changesTree")
    ignore = window.findChild(QAction, "ignoreFileAction")
    assert changes is not None
    assert ignore is not None
    window.open_repository(repository)
    qtbot.waitUntil(lambda: changes.topLevelItemCount() == 1, timeout=5000)
    item = changes.topLevelItem(0)
    assert item is not None
    changes.setCurrentItem(item)
    assert ignore.isEnabled()
    ignore.trigger()
    qtbot.waitUntil(lambda: (repository / ".gitignore").exists(), timeout=5000)
    assert (repository / ".gitignore").read_text(encoding="utf-8") == "generated.log\n"
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


def test_diff_display_toggles_are_persisted(qapp: QApplication, tmp_path: Path) -> None:
    settings = QSettings(str(tmp_path / "diff-display.ini"), QSettings.Format.IniFormat)
    window = MainWindow(settings, Theme.SYSTEM)
    wrap = window.findChild(QToolButton, "diffWrapButton")
    whitespace = window.findChild(QToolButton, "diffWhitespaceButton")
    diff_panel = window.findChild(QPlainTextEdit, "diffPanel")
    assert wrap is not None
    assert whitespace is not None
    assert diff_panel is not None

    wrap.setChecked(True)
    whitespace.setChecked(True)

    assert diff_panel.lineWrapMode() is QPlainTextEdit.LineWrapMode.WidgetWidth
    assert settings.value("diff/wrapLines") is True
    assert settings.value("diff/showWhitespace") is True
    window.close()
