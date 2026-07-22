from __future__ import annotations

import subprocess
from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QPlainTextEdit,
    QSplitter,
    QToolButton,
    QTreeWidget,
)
from pytestqt.qtbot import QtBot

from mygitclient.theme import Theme
from mygitclient.ui.diff_gutter import DiffGutter
from mygitclient.ui.main_window import MainWindow


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
    gutter = window.findChild(DiffGutter, "diffGutter")
    assert changes is not None
    assert diff_panel is not None
    assert gutter is not None

    window.open_repository(repository)
    qtbot.waitUntil(lambda: changes.topLevelItemCount() == 1, timeout=5000)
    item = changes.topLevelItem(0)
    assert item is not None
    assert item.text(0) == "assets/icon.svg"
    changes.setCurrentItem(item)
    qtbot.waitUntil(lambda: "+<svg>new icon</svg>" in diff_panel.toPlainText(), timeout=5000)
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
    assert item.checkState(0) is Qt.CheckState.PartiallyChecked
    clear_lines.click()
    assert "✓" not in gutter.toPlainText()
    assert item.checkState(0) is Qt.CheckState.Unchecked
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


def test_unchanged_diff_refresh_preserves_scroll_position(
    qapp: QApplication, qtbot: QtBot, tmp_path: Path
) -> None:
    repository = tmp_path / "scroll-refresh"
    repository.mkdir()
    subprocess.run(["git", "init", "--initial-branch=main"], cwd=repository, check=True)
    tracked = repository / "tracked.txt"
    lines = [f"line {number}\n" for number in range(250)]
    tracked.write_text("".join(lines), encoding="utf-8")
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
    lines = [f"changed line {number}\n" for number in range(250)]
    tracked.write_text("".join(lines), encoding="utf-8")
    settings = QSettings(str(tmp_path / "scroll-refresh.ini"), QSettings.Format.IniFormat)
    window = MainWindow(settings, Theme.SYSTEM)
    changes = window.findChild(QTreeWidget, "changesTree")
    diff_panel = window.findChild(QPlainTextEdit, "diffPanel")
    gutter = window.findChild(DiffGutter, "diffGutter")
    assert changes is not None
    assert diff_panel is not None
    assert gutter is not None
    window.resize(900, 300)
    window.show()
    window.open_repository(repository)
    qtbot.waitUntil(lambda: changes.topLevelItemCount() == 1, timeout=5000)
    item = changes.topLevelItem(0)
    assert item is not None
    changes.setCurrentItem(item)
    qtbot.waitUntil(lambda: "+changed line 200" in diff_panel.toPlainText(), timeout=5000)
    qtbot.waitUntil(lambda: diff_panel.verticalScrollBar().maximum() > 0, timeout=5000)
    target = max(1, diff_panel.verticalScrollBar().maximum() // 2)
    diff_panel.verticalScrollBar().setValue(target)
    gutter.line_activated.emit(5, False)
    assert item.checkState(0) is Qt.CheckState.PartiallyChecked

    qtbot.wait(1800)

    assert diff_panel.verticalScrollBar().value() == target
    assert gutter.toPlainText().count("✓") == 1
    assert item.checkState(0) is Qt.CheckState.PartiallyChecked
    window.close()


def test_diff_display_toggles_are_persisted(qapp: QApplication, tmp_path: Path) -> None:
    settings = QSettings(str(tmp_path / "diff-display.ini"), QSettings.Format.IniFormat)
    window = MainWindow(settings, Theme.SYSTEM)
    wrap = window.findChild(QToolButton, "diffWrapButton")
    whitespace = window.findChild(QToolButton, "diffWhitespaceButton")
    ignore_whitespace = window.findChild(QToolButton, "diffIgnoreWhitespaceButton")
    diff_panel = window.findChild(QPlainTextEdit, "diffPanel")
    assert wrap is not None
    assert whitespace is not None
    assert ignore_whitespace is not None
    assert diff_panel is not None

    wrap.setChecked(True)
    whitespace.setChecked(True)
    ignore_whitespace.setChecked(True)

    assert diff_panel.lineWrapMode() is QPlainTextEdit.LineWrapMode.WidgetWidth
    assert settings.value("diff/wrapLines") is True
    assert settings.value("diff/showWhitespace") is True
    assert settings.value("diff/ignoreWhitespace") is True
    window.close()
