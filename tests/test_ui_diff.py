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

from mygitclient.git.models import FileStatus
from mygitclient.theme import Theme
from mygitclient.ui.diff_gutter import DiffGutter
from mygitclient.ui.main_window import MainWindow


def test_split_changes_tree_focus_selects_working_or_staged_diff(
    qapp: QApplication, qtbot: QtBot, tmp_path: Path
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    subprocess.run(["git", "init", "--initial-branch=main"], cwd=repository, check=True)
    tracked = repository / "tracked.txt"
    tracked.write_text("base\n", encoding="utf-8")
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
    tracked.write_text("staged\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=repository, check=True)
    tracked.write_text("working\n", encoding="utf-8")
    settings = QSettings(str(tmp_path / "split.ini"), QSettings.Format.IniFormat)
    settings.setValue("changes/presentationMode", "split")
    window = MainWindow(settings, Theme.SYSTEM)
    unstaged = window.findChild(QTreeWidget, "unstagedChangesTree")
    staged = window.findChild(QTreeWidget, "stagedChangesTree")
    diff_panel = window.findChild(QPlainTextEdit, "diffPanel")
    assert unstaged is not None and staged is not None and diff_panel is not None

    window.show()
    window.open_repository(repository)
    qtbot.waitUntil(
        lambda: unstaged.topLevelItemCount() == 1 and staged.topLevelItemCount() == 1,
        timeout=5000,
    )
    unstaged_item = unstaged.topLevelItem(0)
    staged_item = staged.topLevelItem(0)
    assert unstaged_item is not None and staged_item is not None
    assert unstaged_item.checkState(0) is Qt.CheckState.Unchecked
    assert staged_item.checkState(0) is Qt.CheckState.Checked
    unstaged.setFocus()
    unstaged.setCurrentItem(unstaged_item)
    qtbot.waitUntil(lambda: "+working" in diff_panel.toPlainText(), timeout=5000)

    staged.setFocus()
    staged.setCurrentItem(staged_item)
    qtbot.waitUntil(lambda: "+staged" in diff_panel.toPlainText(), timeout=5000)


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


def test_split_staging_selected_lines_adds_file_to_staged_tree(
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
    settings = QSettings(str(tmp_path / "split-lines.ini"), QSettings.Format.IniFormat)
    settings.setValue("changes/presentationMode", "split")
    window = MainWindow(settings, Theme.SYSTEM)
    unstaged = window.findChild(QTreeWidget, "unstagedChangesTree")
    staged = window.findChild(QTreeWidget, "stagedChangesTree")
    diff_panel = window.findChild(QPlainTextEdit, "diffPanel")
    gutter = window.findChild(DiffGutter, "diffGutter")
    apply_lines = window.findChild(QToolButton, "diffSelectedLinesButton")
    assert unstaged is not None and staged is not None
    assert diff_panel is not None and gutter is not None and apply_lines is not None

    window.show()
    window.open_repository(repository)
    qtbot.waitUntil(lambda: unstaged.topLevelItemCount() == 1, timeout=5000)
    item = unstaged.topLevelItem(0)
    assert item is not None
    unstaged.setFocus()
    unstaged.setCurrentItem(item)
    qtbot.waitUntil(lambda: "+TWO" in diff_panel.toPlainText(), timeout=5000)
    assert apply_lines.isHidden()
    hunk_header = diff_panel.document().find("Old lines")
    assert not hunk_header.isNull()
    gutter.line_activated.emit(hunk_header.blockNumber(), False)

    qtbot.waitUntil(lambda: staged.topLevelItemCount() == 1, timeout=5000)
    staged_item = staged.topLevelItem(0)
    assert staged_item is not None
    staged_file = staged_item.data(0, Qt.ItemDataRole.UserRole)
    assert isinstance(staged_file, FileStatus)
    assert staged_file.path == "tracked.txt"
    assert unstaged.topLevelItemCount() == 0
    qtbot.waitUntil(lambda: bool(staged.selectedItems()), timeout=5000)
    assert staged.selectedItems()[0] is staged_item

    staged_item.setCheckState(0, Qt.CheckState.Unchecked)
    qtbot.waitUntil(lambda: staged.topLevelItemCount() == 0, timeout=5000)
    cached = subprocess.run(
        ["git", "diff", "--cached", "--", "tracked.txt"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert not cached
    assert unstaged.topLevelItemCount() == 1
    qtbot.waitUntil(lambda: bool(unstaged.selectedItems()), timeout=5000)
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
    apply_lines = window.findChild(QToolButton, "diffSelectedLinesButton")
    view_mode = window.findChild(QComboBox, "diffViewModeCombo")
    side_old = window.findChild(QPlainTextEdit, "sideBySideOld")
    side_new = window.findChild(QPlainTextEdit, "sideBySideNew")
    splitter = window.findChild(QSplitter, "mainSplitter")
    assert changes is not None
    assert diff_panel is not None
    assert diff_gutter is not None
    assert apply_lines is not None
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
    assert apply_lines.isHidden()
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
    settings.setValue("changes/presentationMode", "split")
    window = MainWindow(settings, Theme.SYSTEM)
    changes = window.findChild(QTreeWidget, "unstagedChangesTree")
    staged_changes = window.findChild(QTreeWidget, "stagedChangesTree")
    diff_panel = window.findChild(QPlainTextEdit, "diffPanel")
    gutter = window.findChild(DiffGutter, "diffGutter")
    hunk_button = window.findChild(QToolButton, "diffHunkButton")
    assert changes is not None
    assert staged_changes is not None
    assert diff_panel is not None
    assert gutter is not None
    assert hunk_button is not None
    window.open_repository(repository)
    qtbot.waitUntil(lambda: changes.topLevelItemCount() == 1, timeout=5000)
    item = changes.topLevelItem(0)
    assert item is not None
    changes.setCurrentItem(item)
    qtbot.waitUntil(lambda: "+first changed" in diff_panel.toPlainText(), timeout=5000)
    assert hunk_button.isHidden()
    hunk_header = diff_panel.document().find("Old lines")
    assert not hunk_header.isNull()
    gutter.line_activated.emit(hunk_header.blockNumber(), False)

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


def test_diff_line_checkbox_applies_stage_and_unstage_immediately(
    qapp: QApplication, qtbot: QtBot, tmp_path: Path
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    subprocess.run(["git", "init", "--initial-branch=main"], cwd=repository, check=True)
    tracked = repository / "tracked.txt"
    tracked.write_text("one\nthree\n", encoding="utf-8")
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
    tracked.write_text("one\ntwo\nthree\n", encoding="utf-8")
    settings = QSettings(str(tmp_path / "lines.ini"), QSettings.Format.IniFormat)
    settings.setValue("changes/presentationMode", "split")
    window = MainWindow(settings, Theme.SYSTEM)
    changes = window.findChild(QTreeWidget, "unstagedChangesTree")
    staged_changes = window.findChild(QTreeWidget, "stagedChangesTree")
    diff_panel = window.findChild(QPlainTextEdit, "diffPanel")
    gutter = window.findChild(DiffGutter, "diffGutter")
    apply_lines = window.findChild(QToolButton, "diffSelectedLinesButton")
    clear_lines = window.findChild(QToolButton, "diffClearSelectionButton")
    assert changes is not None
    assert staged_changes is not None
    assert diff_panel is not None
    assert gutter is not None
    assert apply_lines is not None
    assert clear_lines is not None
    assert apply_lines.isHidden()
    assert clear_lines.isHidden()
    window.open_repository(repository)
    qtbot.waitUntil(lambda: changes.topLevelItemCount() == 1, timeout=5000)
    item = changes.topLevelItem(0)
    assert item is not None
    changes.setCurrentItem(item)
    qtbot.waitUntil(lambda: "+two" in diff_panel.toPlainText(), timeout=5000)
    assert "□" in gutter.toPlainText()
    added = diff_panel.document().find("+two")
    assert not added.isNull()
    gutter.line_activated.emit(added.blockNumber(), False)

    def line_is_staged() -> bool:
        cached = subprocess.run(
            ["git", "diff", "--cached", "--", "tracked.txt"],
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        return "+two" in cached

    qtbot.waitUntil(line_is_staged, timeout=5000)
    qtbot.waitUntil(lambda: staged_changes.topLevelItemCount() == 1, timeout=5000)
    current_staged = staged_changes.topLevelItem(0)
    assert current_staged is not None
    assert current_staged.checkState(0) is Qt.CheckState.Checked
    qtbot.waitUntil(lambda: "+two" in diff_panel.toPlainText(), timeout=5000)
    staged_added = diff_panel.document().find("+two")
    assert not staged_added.isNull()
    gutter.line_activated.emit(staged_added.blockNumber(), False)

    def selected_lines_are_unstaged() -> bool:
        result = subprocess.run(
            ["git", "diff", "--cached", "--", "tracked.txt"],
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
        )
        return "+two" not in result.stdout

    qtbot.waitUntil(selected_lines_are_unstaged, timeout=5000)
    qtbot.waitUntil(lambda: changes.topLevelItemCount() == 1, timeout=5000)
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
    settings.setValue("changes/presentationMode", "split")
    window = MainWindow(settings, Theme.SYSTEM)
    changes = window.findChild(QTreeWidget, "unstagedChangesTree")
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

    def line_is_staged() -> bool:
        cached = subprocess.run(
            ["git", "diff", "--cached", "--", "tracked.txt"],
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        return bool(cached)

    qtbot.waitUntil(line_is_staged, timeout=5000)

    assert diff_panel.verticalScrollBar().value() == target
    current = changes.topLevelItem(0)
    assert current is not None
    assert current.checkState(0) is Qt.CheckState.Unchecked
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
