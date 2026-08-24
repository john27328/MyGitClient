from __future__ import annotations

from contextlib import suppress

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QFont, QFontDatabase, QFontMetrics
from PySide6.QtWidgets import QPlainTextEdit, QWidget

from mygitclient.git.models import UnifiedDiff
from mygitclient.ui.diff_highlighter import DiffHighlighter

_INLINE_DIFF_STYLE = (
    "QPlainTextEdit { border: 0; border-left: 2px solid palette(midlight); "
    "selection-background-color: palette(highlight); "
    "selection-color: palette(highlighted-text); }"
)

MAXIMUM_INLINE_HEIGHT = 420
"""Tallest an expanded row may grow before it scrolls on its own."""


class InlineDiffWidget(QPlainTextEdit):
    """Read-only diff rendered inside a file row of the history file list.

    Deliberately lighter than :class:`~mygitclient.ui.diff_view.DiffView`: no toolbar,
    no gutter, no staging interaction, and a content-derived height so the row can size
    itself inside a tree.
    """

    def __init__(
        self,
        settings: QSettings | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("inlineDiffPanel")
        self.setReadOnly(True)
        self.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setFrameShape(QPlainTextEdit.Shape.NoFrame)
        self.setStyleSheet(_INLINE_DIFF_STYLE)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setFont(_diff_font(settings))
        self._highlighter = DiffHighlighter(self)
        self._diff: UnifiedDiff | None = None

    @property
    def diff(self) -> UnifiedDiff | None:
        return self._diff

    def set_diff(self, diff: UnifiedDiff) -> None:
        self._diff = diff
        if diff.binary:
            self.setPlainText("Binary file — no textual diff.")
            self._highlighter.set_diff(None)
        else:
            self.setPlainText(diff.display_text)
            self._highlighter.set_diff(diff)
        self._apply_content_height()

    def set_placeholder(self, message: str) -> None:
        self._diff = None
        self._highlighter.set_diff(None)
        self.setPlainText(message)
        self._apply_content_height()

    def set_font_size(self, point_size: int) -> None:
        font = self.font()
        font.setPointSize(max(7, min(32, point_size)))
        self.setFont(font)
        self._apply_content_height()

    def _apply_content_height(self) -> None:
        rows = max(self.document().blockCount(), 1)
        line_height = QFontMetrics(self.font()).lineSpacing()
        margins = self.contentsMargins()
        content = rows * line_height + margins.top() + margins.bottom() + 8
        height = min(content, MAXIMUM_INLINE_HEIGHT)
        self.setFixedHeight(height)


def _diff_font(settings: QSettings | None) -> QFont:
    """Match the diff font the main diff view uses so both read alike."""

    font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
    font.setStyleHint(QFont.StyleHint.Monospace)
    font.setFixedPitch(True)
    if settings is None:
        return font
    saved = settings.value("diff/fontSize", font.pointSize())
    if isinstance(saved, (int, str)):
        with suppress(ValueError):
            font.setPointSize(max(7, min(32, int(saved))))
    return font
