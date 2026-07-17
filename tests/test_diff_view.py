from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QPlainTextEdit, QStackedWidget, QToolButton
from pytestqt.qtbot import QtBot

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
