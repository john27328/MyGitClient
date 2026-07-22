from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QLabel, QPlainTextEdit, QStackedWidget, QToolButton
from pytestqt.qtbot import QtBot

from mygitclient.git.parsers import parse_unified_diff
from mygitclient.ui.diff_gutter import DiffGutter
from mygitclient.ui.diff_view import DiffView, inline_change_ranges


def test_diff_view_owns_presentation_widgets(qtbot: QtBot, tmp_path: Path) -> None:
    settings = QSettings(str(tmp_path / "diff-view.ini"), QSettings.Format.IniFormat)
    view = DiffView(settings)
    qtbot.addWidget(view)

    assert "palette(base)" in view.gutter.styleSheet()
    assert "alternate-base" not in view.gutter.styleSheet()

    assert view.findChild(QPlainTextEdit, "diffPanel") is view.diff
    assert view.findChild(DiffGutter, "diffGutter") is view.gutter
    assert view.findChild(QPlainTextEdit, "sideBySideOld") is view.side_old
    assert view.findChild(QPlainTextEdit, "sideBySideNew") is view.side_new
    assert view.findChild(DiffGutter, "sideBySideOldGutter") is view.side_old_gutter
    assert view.findChild(DiffGutter, "sideBySideNewGutter") is view.side_new_gutter
    assert view.findChild(QStackedWidget) is view.stack
    assert view.findChild(QToolButton, "diffWrapButton") is view.wrap_button
    assert view.findChild(QToolButton, "diffWhitespaceButton") is view.whitespace_button
    assert (
        view.findChild(QToolButton, "diffIgnoreWhitespaceButton")
        is view.ignore_whitespace_button
    )
    assert view.findChild(QLabel, "diffVersionLabel") is view.version_label
    assert view.findChild(QLabel, "diffFileHeader") is view.file_header


def test_single_diff_source_is_a_label_and_two_sources_are_selectable(
    qtbot: QtBot, tmp_path: Path
) -> None:
    settings = QSettings(str(tmp_path / "diff-source.ini"), QSettings.Format.IniFormat)
    view = DiffView(settings)
    qtbot.addWidget(view)

    view.version_combo.addItem("Working tree", False)
    view.refresh_version_selector()
    assert not view.version_label.isHidden()
    assert view.version_label.text() == "Working tree"
    assert view.version_combo.isHidden()

    view.version_combo.addItem("Staged", True)
    view.refresh_version_selector()
    assert view.version_label.isHidden()
    assert not view.version_combo.isHidden()


def test_inline_highlight_is_skipped_for_unrelated_lines() -> None:
    old = "mutable std::mutex m_sync;"
    new = "// A comment describing a new synchronization strategy"

    assert inline_change_ranges(old, new) == ([], [])


def test_inline_highlight_keeps_focused_ranges_for_similar_lines() -> None:
    old_ranges, new_ranges = inline_change_ranges(
        "mutable bool m_saved = false;",
        "mutable std::atomic_bool m_saved = false;",
    )

    assert old_ranges == []
    assert new_ranges


def test_diff_view_restores_saved_mode(qtbot: QtBot, tmp_path: Path) -> None:
    settings = QSettings(str(tmp_path / "diff-mode.ini"), QSettings.Format.IniFormat)
    settings.setValue("diff/viewMode", "side-by-side")

    view = DiffView(settings)
    qtbot.addWidget(view)

    assert view.view_mode_combo.currentData() == "side-by-side"
    assert view.stack.currentIndex() == 1


def test_diff_view_restores_and_updates_font_size(qtbot: QtBot, tmp_path: Path) -> None:
    settings = QSettings(str(tmp_path / "diff-font.ini"), QSettings.Format.IniFormat)
    settings.setValue("diff/fontSize", 14)
    view = DiffView(settings)
    qtbot.addWidget(view)

    assert view.diff.font().pointSize() == 14
    assert view.side_old_gutter.font().pointSize() == 14

    view.set_font_size(16)

    assert view.diff.font().pointSize() == 16
    assert view.gutter.font().pointSize() == 16
    assert view.side_old.font().pointSize() == 16
    assert view.side_new_gutter.font().pointSize() == 16


def test_diff_view_reset_clears_both_presentations(qtbot: QtBot, tmp_path: Path) -> None:
    settings = QSettings(str(tmp_path / "diff-reset.ini"), QSettings.Format.IniFormat)
    settings.setValue("diff/viewMode", "side-by-side")
    view = DiffView(settings)
    qtbot.addWidget(view)
    diff = parse_unified_diff(
        b"diff --git a/file.txt b/file.txt\n"
        b"--- a/file.txt\n"
        b"+++ b/file.txt\n"
        b"@@ -1 +1 @@\n"
        b"-before\n"
        b"+after\n",
        "file.txt",
        staged=False,
    )
    view.display_diff(
        diff,
        selection_key=(tmp_path, diff.path, False),
        preserve_scroll=False,
        whole_file_staged=False,
    )
    assert "before" in view.side_old.toPlainText()
    assert "after" in view.side_new.toPlainText()

    view.reset()

    assert view.current_diff is None
    assert view.diff.toPlainText() == ""
    assert view.side_old.toPlainText() == ""
    assert view.side_new.toPlainText() == ""
    assert view.side_old_gutter.toPlainText() == ""
    assert view.side_new_gutter.toPlainText() == ""
    assert view.file_header.text() == ""


def test_diff_view_hides_git_metadata_and_labels_hunks(
    qtbot: QtBot, tmp_path: Path
) -> None:
    settings = QSettings(str(tmp_path / "clean-diff.ini"), QSettings.Format.IniFormat)
    settings.setValue("diff/viewMode", "side-by-side")
    view = DiffView(settings)
    qtbot.addWidget(view)
    diff = parse_unified_diff(
        b"diff --git a/file.cpp b/file.cpp\n"
        b"index 1111111..2222222 100644\n"
        b"--- a/file.cpp\n"
        b"+++ b/file.cpp\n"
        b"@@ -10,2 +10,2 @@\n"
        b"-before\n"
        b"+after\n"
        b" context\n",
        "src/file.cpp",
        staged=False,
    )

    view.display_diff(
        diff,
        selection_key=(tmp_path, diff.path, False),
        preserve_scroll=False,
        whole_file_staged=False,
    )

    assert view.file_header.text() == "src/file.cpp"
    assert "diff --git" not in view.side_old.toPlainText()
    assert "--- a/file.cpp" not in view.side_old.toPlainText()
    assert "Old lines 10–11" in view.side_old.toPlainText()
    assert "New lines 10–11" in view.side_new.toPlainText()


def test_diff_view_owns_line_selection_and_emits_request(
    qtbot: QtBot, tmp_path: Path
) -> None:
    settings = QSettings(str(tmp_path / "selection.ini"), QSettings.Format.IniFormat)
    view = DiffView(settings)
    qtbot.addWidget(view)
    diff = parse_unified_diff(
        b"diff --git a/file.txt b/file.txt\n"
        b"--- a/file.txt\n"
        b"+++ b/file.txt\n"
        b"@@ -1 +1 @@\n"
        b"-before\n"
        b"+after\n",
        "file.txt",
        staged=False,
    )
    requests: list[tuple[object, object]] = []

    def capture_request(value: object, lines: object) -> None:
        requests.append((value, lines))

    view.lines_requested.connect(capture_request)
    view.display_diff(
        diff,
        selection_key=(tmp_path, diff.path, diff.staged),
        preserve_scroll=False,
        whole_file_staged=False,
    )

    view.gutter.line_activated.emit(4, False)
    view.gutter.line_activated.emit(5, True)
    view.selected_lines_button.click()

    assert view.selection.selected_lines == {4, 5}
    rendered = view.diff.extraSelections()
    assert len(rendered) == 2
    deletion_color = rendered[0].format.background().color()
    addition_color = rendered[1].format.background().color()
    assert deletion_color != addition_color
    assert deletion_color.red() > deletion_color.green()
    assert addition_color.green() > addition_color.red()
    assert rendered[0].format.foreground().style() == Qt.BrushStyle.NoBrush
    assert requests == [(diff, {4, 5})]


def test_diff_selection_is_restored_per_file_and_version(
    qtbot: QtBot, tmp_path: Path
) -> None:
    settings = QSettings(str(tmp_path / "saved-selection.ini"), QSettings.Format.IniFormat)
    view = DiffView(settings)
    qtbot.addWidget(view)
    first = parse_unified_diff(
        b"diff --git a/first.txt b/first.txt\n"
        b"--- a/first.txt\n"
        b"+++ b/first.txt\n"
        b"@@ -1 +1 @@\n"
        b"-before\n"
        b"+after\n",
        "first.txt",
        staged=False,
    )
    second = parse_unified_diff(
        b"diff --git a/second.txt b/second.txt\n"
        b"--- a/second.txt\n"
        b"+++ b/second.txt\n"
        b"@@ -1 +1 @@\n"
        b"-old\n"
        b"+new\n",
        "second.txt",
        staged=False,
    )
    first_key = (tmp_path, first.path, False)

    view.display_diff(
        first,
        selection_key=first_key,
        preserve_scroll=False,
        whole_file_staged=False,
    )
    view.gutter.line_activated.emit(4, False)
    view.display_diff(
        second,
        selection_key=(tmp_path, second.path, False),
        preserve_scroll=False,
        whole_file_staged=False,
    )
    assert view.selection.selected_lines == set()

    view.display_diff(
        first,
        selection_key=first_key,
        preserve_scroll=False,
        whole_file_staged=False,
    )
    assert view.selection.selected_lines == {4}

    view.display_diff(
        first,
        selection_key=(tmp_path, first.path, True),
        preserve_scroll=False,
        whole_file_staged=False,
    )
    assert view.selection.selected_lines == set()


def test_side_by_side_gutters_select_lines(qtbot: QtBot, tmp_path: Path) -> None:
    settings = QSettings(str(tmp_path / "side-selection.ini"), QSettings.Format.IniFormat)
    settings.setValue("diff/viewMode", "side-by-side")
    view = DiffView(settings)
    qtbot.addWidget(view)
    diff = parse_unified_diff(
        b"diff --git a/file.txt b/file.txt\n"
        b"--- a/file.txt\n"
        b"+++ b/file.txt\n"
        b"@@ -1 +1 @@\n"
        b"-before\n"
        b"+after\n",
        "file.txt",
        staged=False,
    )
    view.display_diff(
        diff,
        selection_key=(tmp_path, diff.path, diff.staged),
        preserve_scroll=False,
        whole_file_staged=False,
    )

    view.side_old_gutter.line_activated.emit(1, False)
    view.side_new_gutter.line_activated.emit(1, True)

    assert view.selection.selected_lines == {4, 5}
    assert "✓" in view.side_old_gutter.toPlainText()
    assert "✓" in view.side_new_gutter.toPlainText()
    assert len(view.side_old.extraSelections()) == 1
    assert len(view.side_new.extraSelections()) == 1


def test_unified_gutter_visibility_does_not_depend_on_parent_visibility(
    qtbot: QtBot, tmp_path: Path
) -> None:
    settings = QSettings(str(tmp_path / "gutter.ini"), QSettings.Format.IniFormat)
    view = DiffView(settings)
    qtbot.addWidget(view)

    view.set_wrap(False)

    assert not view.gutter.isHidden()
