from __future__ import annotations

import re

from PySide6.QtGui import QColor, QSyntaxHighlighter, QTextCharFormat
from PySide6.QtWidgets import QPlainTextEdit

from mygitclient.git.models import DiffLineKind, UnifiedDiff


class DiffHighlighter(QSyntaxHighlighter):
    """Apply theme-aware semantic colors to a rendered unified diff."""

    def __init__(self, editor: QPlainTextEdit) -> None:
        super().__init__(editor.document())
        self._editor = editor
        self._line_kinds: tuple[DiffLineKind, ...] = ()
        self._inline_ranges: dict[int, tuple[tuple[int, int], ...]] = {}
        self._python = False

    def set_diff(self, diff: UnifiedDiff | None) -> None:
        self._python = diff is not None and diff.path.lower().endswith(".py")
        self.set_line_kinds(() if diff is None else tuple(line.kind for line in diff.lines))

    def set_line_kinds(self, line_kinds: tuple[DiffLineKind, ...]) -> None:
        self._line_kinds = line_kinds
        self.rehighlight()

    def set_language(self, path: str) -> None:
        self._python = path.lower().endswith(".py")
        self.rehighlight()

    def set_inline_ranges(self, ranges: dict[int, tuple[tuple[int, int], ...]]) -> None:
        self._inline_ranges = ranges
        self.rehighlight()

    def highlightBlock(self, text: str) -> None:  # noqa: N802
        block_number = self.currentBlock().blockNumber()
        if block_number < 0 or block_number >= len(self._line_kinds):
            return
        kind = self._line_kinds[block_number]
        colors = self._colors()
        background = colors.get(kind)
        if background is None:
            text_format = QTextCharFormat()
        else:
            text_format = QTextCharFormat()
            text_format.setBackground(background)
            if kind in {"header", "hunk"}:
                text_format.setForeground(colors["header_text"])
            self.setFormat(0, len(text), text_format)
        if self._python and kind in {"addition", "deletion", "context"}:
            keyword_format = QTextCharFormat()
            keyword_format.setForeground(colors["syntax"])
            if background is not None:
                keyword_format.setBackground(background)
            for match in re.finditer(
                r"\b(?:as|class|def|else|except|False|for|from|if|import|None|return|True|try|with)\b",
                text,
            ):
                self.setFormat(match.start(), match.end() - match.start(), keyword_format)
        inline_format = QTextCharFormat()
        inline_format.setBackground(
            colors["inline_addition"]
            if kind == "addition"
            else colors["inline_deletion"]
        )
        for start, length in self._inline_ranges.get(block_number, ()):
            self.setFormat(start, length, inline_format)

    def _colors(self) -> dict[str, QColor]:
        dark = self._editor.palette().base().color().lightness() < 128
        if dark:
            return {
                "addition": QColor("#142f20"),
                "deletion": QColor("#3b1d22"),
                "hunk": QColor("#243955"),
                "header": QColor("#252a31"),
                "header_text": QColor("#9aa7b5"),
                "syntax": QColor("#c792ea"),
                "inline_addition": QColor("#285d3a"),
                "inline_deletion": QColor("#71313a"),
            }
        return {
            "addition": QColor("#edf8f0"),
            "deletion": QColor("#fbecec"),
            "hunk": QColor("#e8f0fa"),
            "header": QColor("#f3f5f7"),
            "header_text": QColor("#64758a"),
            "syntax": QColor("#7b3fc6"),
            "inline_addition": QColor("#b9e7c5"),
            "inline_deletion": QColor("#f1b9b9"),
        }
