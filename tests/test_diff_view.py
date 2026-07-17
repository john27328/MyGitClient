from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QPlainTextEdit, QStackedWidget, QToolButton
from pytestqt.qtbot import QtBot

from mygitclient.git.parsers import parse_unified_diff
from mygitclient.ui.diff_gutter import DiffGutter
from mygitclient.ui.diff_view import DiffView


def test_diff_view_owns_presentation_widgets(qtbot: QtBot, tmp_path: Path) -> None:
    settings = QSettings(str(tmp_path / "diff-view.ini"), QSettings.Format.IniFormat)
    view = DiffView(settings)
    qtbot.addWidget(view)

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
    view.display_diff(diff, preserve_scroll=False, whole_file_staged=False)

    view.gutter.line_activated.emit(4, False)
    view.selected_lines_button.click()

    assert view.selection.selected_lines == {4}
    assert requests == [(diff, {4})]
