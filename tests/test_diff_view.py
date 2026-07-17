from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QPlainTextEdit, QStackedWidget, QToolButton
from pytestqt.qtbot import QtBot

from mygitclient.git.parsers import parse_unified_diff
from mygitclient.ui.diff_gutter import DiffGutter
from mygitclient.ui.diff_view import DiffView


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
    assert view.findChild(QStackedWidget) is view.stack
    assert view.findChild(QToolButton, "diffWrapButton") is view.wrap_button
    assert view.findChild(QToolButton, "diffWhitespaceButton") is view.whitespace_button


def test_diff_view_restores_saved_mode(qtbot: QtBot, tmp_path: Path) -> None:
    settings = QSettings(str(tmp_path / "diff-mode.ini"), QSettings.Format.IniFormat)
    settings.setValue("diff/viewMode", "side-by-side")

    view = DiffView(settings)
    qtbot.addWidget(view)

    assert view.view_mode_combo.currentData() == "side-by-side"
    assert view.stack.currentIndex() == 1


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
