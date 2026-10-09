from __future__ import annotations

from contextlib import suppress

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QFont, QFontDatabase, QFontMetrics
from PySide6.QtWidgets import QPlainTextEdit, QWidget

from mygitclient.git.models import DiffLineKind, UnifiedDiff
from mygitclient.ui.diff_highlighter import DiffHighlighter

_INLINE_DIFF_STYLE = (
    "QPlainTextEdit { border: 0; border-left: 2px solid palette(midlight); "
    "selection-background-color: palette(highlight); "
    "selection-color: palette(highlighted-text); }"
)

MAXIMUM_INLINE_LINES = 200
"""Longest preview an expanded row shows; the Diff tab is for studying the whole file."""


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
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
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
            text, kinds = _preview(diff)
            self.setPlainText(text)
            self._highlighter.set_diff(diff)
            self._highlighter.set_line_kinds(kinds)
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
        scrollbar = self.horizontalScrollBar().sizeHint().height()
        content = rows * line_height + margins.top() + margins.bottom() + scrollbar + 8
        self.setFixedHeight(content)


def _preview(diff: UnifiedDiff) -> tuple[str, tuple[DiffLineKind, ...]]:
    """Readable rows for the diff, capped so the row stays a preview.

    Git's ``diff --git``/``index``/``---``/``+++`` lines are left out and hunk headers get
    the same wording as the main diff view, so the highlighter's kinds follow the shown rows.
    """

    lines = diff.readable_lines
    old_width = max((len(str(line.old_line)) for line in lines if line.old_line), default=1)
    new_width = max((len(str(line.new_line)) for line in lines if line.new_line), default=1)
    rows: list[str] = []
    kinds: list[DiffLineKind] = []
    for line in lines:
        if line.kind == "hunk":
            rows.append(diff.hunk_label(line))
        else:
            old_number = str(line.old_line) if line.old_line is not None else ""
            new_number = str(line.new_line) if line.new_line is not None else ""
            rows.append(f"{old_number:>{old_width}} {new_number:>{new_width}} │ {line.text}")
        kinds.append(line.kind)
    if len(rows) > MAXIMUM_INLINE_LINES:
        hidden = len(rows) - MAXIMUM_INLINE_LINES
        rows = rows[:MAXIMUM_INLINE_LINES]
        kinds = kinds[:MAXIMUM_INLINE_LINES]
        rows.append(f"… {hidden} more lines hidden — double-click the file to open the full diff")
        kinds.append("context")
    return "\n".join(rows), tuple(kinds)


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
