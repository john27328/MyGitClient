import pytest
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


@pytest.mark.parametrize(
    ("path", "text", "token"),
    [
        ("example.cpp", '+const auto value = 42; // note', "const"),
        ("component.tsx", '+const value = "ready";', "const"),
        ("settings.json", '+"enabled": true', '"enabled"'),
        ("workflow.yml", "+enabled: true # note", "enabled"),
        ("script.sh", "+if test -f file; then", "if"),
        ("README.md", "+## Heading", "Heading"),
    ],
)
def test_supported_languages_receive_syntax_foreground(
    qtbot: QtBot, path: str, text: str, token: str
) -> None:
    editor = QPlainTextEdit()
    qtbot.addWidget(editor)
    highlighter = DiffHighlighter(editor)
    highlighter.set_language(path)
    highlighter.set_line_kinds(("addition",))
    editor.setPlainText(text)
    highlighter.rehighlight()

    position = text.index(token)
    syntax_range = next(
        item
        for item in editor.document().firstBlock().layout().formats()
        if item.start <= position < item.start + item.length
    )

    assert syntax_range.format.foreground().style() is not Qt.BrushStyle.NoBrush
    assert syntax_range.format.background().style() is not Qt.BrushStyle.NoBrush


def test_cpp_strings_comments_and_numbers_use_distinct_colors(qtbot: QtBot) -> None:
    editor = QPlainTextEdit()
    qtbot.addWidget(editor)
    highlighter = DiffHighlighter(editor)
    highlighter.set_language("example.cpp")
    highlighter.set_line_kinds(("addition",))
    text = '+const char* value = "item 42"; // comment'
    editor.setPlainText(text)
    highlighter.rehighlight()
    formats = editor.document().firstBlock().layout().formats()

    def color_at(token: str):
        position = text.index(token)
        item = next(
            value
            for value in formats
            if value.start <= position < value.start + value.length
        )
        return item.format.foreground().color()

    assert color_at("const") != color_at('"item 42"')
    assert color_at('"item 42"') != color_at("// comment")
