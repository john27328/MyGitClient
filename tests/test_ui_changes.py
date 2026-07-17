from __future__ import annotations

import subprocess
from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTreeWidget,
)
from pytest import MonkeyPatch
from pytestqt.qtbot import QtBot

from mygitclient.theme import Theme
from mygitclient.ui.diff_gutter import DiffGutter
from mygitclient.ui.main_window import MainWindow


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
    gutter = window.findChild(DiffGutter, "diffGutter")
    assert changes is not None
    assert gutter is not None
    window.open_repository(repository)
    qtbot.waitUntil(lambda: changes.topLevelItemCount() == 1, timeout=5000)
    item = changes.topLevelItem(0)
    assert item is not None
    assert item.checkState(0) is Qt.CheckState.Unchecked
    changes.setCurrentItem(item)

    def index_text_is(expected: str) -> bool:
        current = changes.topLevelItem(0)
        return current is not None and current.text(1) == expected

    item.setCheckState(0, Qt.CheckState.Checked)
    qtbot.waitUntil(lambda: index_text_is("Modified"), timeout=5000)
    staged_item = changes.topLevelItem(0)
    assert staged_item is not None
    assert staged_item.checkState(0) is Qt.CheckState.Checked
    qtbot.waitUntil(lambda: gutter.toPlainText().count("✓") == 2, timeout=5000)

    staged_item.setCheckState(0, Qt.CheckState.Unchecked)
    qtbot.waitUntil(lambda: index_text_is(""), timeout=5000)
    unstaged_item = changes.topLevelItem(0)
    assert unstaged_item is not None
    assert unstaged_item.checkState(0) is Qt.CheckState.Unchecked
    qtbot.waitUntil(lambda: "✓" not in gutter.toPlainText(), timeout=5000)
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
            (item := changes.topLevelItem(index)) is not None and item.checkState(0) is expected
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
    subprocess.run(["git", "config", "user.name", "MyGitClient Test"], cwd=repository, check=True)
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


def test_discard_requires_confirmation_and_restores_selected_files(
    qapp: QApplication, qtbot: QtBot, monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    subprocess.run(["git", "init", "--initial-branch=main"], cwd=repository, check=True)
    tracked = repository / "tracked.txt"
    second = repository / "second.txt"
    tracked.write_text("before\n", encoding="utf-8")
    second.write_text("second before\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt", "second.txt"], cwd=repository, check=True)
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
    second.write_text("second after\n", encoding="utf-8")
    settings = QSettings(str(tmp_path / "discard.ini"), QSettings.Format.IniFormat)
    window = MainWindow(settings, Theme.SYSTEM)
    changes = window.findChild(QTreeWidget, "changesTree")
    discard = window.findChild(QAction, "discardChangesAction")
    assert changes is not None
    assert discard is not None
    window.open_repository(repository)
    qtbot.waitUntil(lambda: changes.topLevelItemCount() == 2, timeout=5000)
    first_item = changes.topLevelItem(0)
    second_item = changes.topLevelItem(1)
    assert first_item is not None
    assert second_item is not None
    changes.setCurrentItem(first_item)
    second_item.setSelected(True)

    def confirm_discard(*_args: object, **_kwargs: object) -> QMessageBox.StandardButton:
        return QMessageBox.StandardButton.Discard

    monkeypatch.setattr(QMessageBox, "question", confirm_discard)
    discard.trigger()
    qtbot.waitUntil(
        lambda: tracked.exists() and tracked.read_text(encoding="utf-8") == "before\n",
        timeout=5000,
    )
    qtbot.waitUntil(
        lambda: second.exists()
        and second.read_text(encoding="utf-8") == "second before\n",
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
