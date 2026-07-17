from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPlainTextEdit
from pytestqt.qtbot import QtBot

from mygitclient.ui.diff_highlighter import DiffHighlighter


def test_python_keyword_keeps_diff_line_background(qtbot: QtBot) -> None:
    editor = QPlainTextEdit()
    qtbot.addWidget(editor)
    highlighter = DiffHighlighter(editor)
    highlighter.set_language("example.py")
    highlighter.set_line_kinds(("addition",))
    editor.setPlainText("+if value:")
    highlighter.rehighlight()

    formats = editor.document().firstBlock().layout().formats()
    keyword = next(item for item in formats if item.start == 1 and item.length == 2)

    assert keyword.format.background().style() is not Qt.BrushStyle.NoBrush
    assert keyword.format.foreground().style() is not Qt.BrushStyle.NoBrush
