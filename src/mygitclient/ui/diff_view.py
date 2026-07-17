from __future__ import annotations

from difflib import SequenceMatcher

from PySide6.QtCore import QSettings, Qt, Signal, Slot
from PySide6.QtGui import QColor, QFont, QFontDatabase, QFontMetrics, QTextCursor, QTextOption
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QPlainTextEdit,
    QSplitter,
    QStackedWidget,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from mygitclient.git.models import DiffLine, DiffLineKind, UnifiedDiff
from mygitclient.ui.diff_gutter import DiffGutter
from mygitclient.ui.diff_highlighter import DiffHighlighter
from mygitclient.ui.diff_selection import DiffSelection


class DiffView(QWidget):
    """Owns the diff presentation widgets while orchestration remains outside."""

    selection_changed = Signal()
    lines_requested = Signal(object, object)
    hunk_requested = Signal(object, int)

    def __init__(self, settings: QSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.current_diff: UnifiedDiff | None = None
        self.selection = DiffSelection()
        self.setObjectName("diffContainer")

        diff_font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        diff_font.setStyleHint(QFont.StyleHint.Monospace)
        diff_font.setFixedPitch(True)

        self.diff = QPlainTextEdit()
        self.diff.setObjectName("diffPanel")
        self.diff.setReadOnly(True)
        self.diff.setPlaceholderText("Select a changed file to view its diff.")
        self.diff.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.diff.setMinimumWidth(400)
        self.diff.setFont(diff_font)
        self.diff.hide()
        self.diff_highlighter = DiffHighlighter(self.diff)

        self.gutter = DiffGutter()
        self.gutter.setObjectName("diffGutter")
        self.gutter.setReadOnly(True)
        self.gutter.setFont(diff_font)
        self.gutter.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.gutter.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.gutter.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.gutter.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.gutter.setCursor(Qt.CursorShape.PointingHandCursor)
        self.gutter.setToolTip(
            "Click a checkbox to select a changed line. "
            "Click a hunk checkbox to select the whole block."
        )
        self.gutter.setStyleSheet(
            "QPlainTextEdit { background: palette(alternate-base); "
            "color: palette(mid); border: 0; border-right: 1px solid palette(midlight); }"
        )
        self.gutter.hide()
        self.diff.verticalScrollBar().valueChanged.connect(
            self.gutter.verticalScrollBar().setValue
        )
        self.gutter.verticalScrollBar().valueChanged.connect(
            self.diff.verticalScrollBar().setValue
        )

        self.version_combo = QComboBox()
        self.version_combo.setObjectName("diffVersionCombo")
        self.version_combo.setToolTip("Choose which version of the selected file to compare")
        self.version_combo.hide()

        self.view_mode_combo = QComboBox()
        self.view_mode_combo.setObjectName("diffViewModeCombo")
        self.view_mode_combo.addItem("Unified", "unified")
        self.view_mode_combo.addItem("Side-by-side", "side-by-side")
        saved_view = settings.value("diff/viewMode", "unified")
        saved_index = self.view_mode_combo.findData(saved_view)
        self.view_mode_combo.setCurrentIndex(max(saved_index, 0))
        self.view_mode_combo.hide()

        diff_body = QWidget()
        diff_body_layout = QHBoxLayout(diff_body)
        diff_body_layout.setContentsMargins(0, 0, 0, 0)
        diff_body_layout.setSpacing(0)
        diff_body_layout.addWidget(self.gutter)
        diff_body_layout.addWidget(self.diff, 1)

        self.side_old = self._make_side_editor("sideBySideOld")
        self.side_new = self._make_side_editor("sideBySideNew")
        self.side_old_highlighter = DiffHighlighter(self.side_old)
        self.side_new_highlighter = DiffHighlighter(self.side_new)
        self.side_old.verticalScrollBar().valueChanged.connect(
            self.side_new.verticalScrollBar().setValue
        )
        self.side_new.verticalScrollBar().valueChanged.connect(
            self.side_old.verticalScrollBar().setValue
        )
        side_splitter = QSplitter(Qt.Orientation.Horizontal)
        side_splitter.addWidget(self.side_old)
        side_splitter.addWidget(self.side_new)
        side_splitter.setSizes([500, 500])

        self.wrap_button = self._toggle_button("diffWrapButton", "Wrap")
        self.wrap_button.setToolTip("Wrap long diff lines")
        self.whitespace_button = self._toggle_button(
            "diffWhitespaceButton", "Whitespace"
        )
        self.whitespace_button.setToolTip("Show spaces and tab characters")
        self.hunk_button = QToolButton()
        self.hunk_button.setObjectName("diffHunkButton")
        self.hunk_button.setText("Stage hunk")
        self.hunk_button.setToolTip("Stage the hunk under the cursor")
        self.hunk_button.setEnabled(False)
        self.selected_lines_button = QToolButton()
        self.selected_lines_button.setObjectName("diffSelectedLinesButton")
        self.selected_lines_button.setText("Stage selected")
        self.selected_lines_button.setEnabled(False)
        self.clear_lines_button = QToolButton()
        self.clear_lines_button.setObjectName("diffClearSelectionButton")
        self.clear_lines_button.setText("Clear")
        self.clear_lines_button.setEnabled(False)

        toolbar = QWidget()
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(0, 0, 0, 0)
        toolbar_layout.addWidget(self.version_combo, 1)
        toolbar_layout.addWidget(self.wrap_button)
        toolbar_layout.addWidget(self.whitespace_button)
        toolbar_layout.addWidget(self.hunk_button)
        toolbar_layout.addWidget(self.selected_lines_button)
        toolbar_layout.addWidget(self.clear_lines_button)
        toolbar_layout.addWidget(self.view_mode_combo)

        self.stack = QStackedWidget()
        self.stack.addWidget(diff_body)
        self.stack.addWidget(side_splitter)
        self.stack.setCurrentIndex(max(saved_index, 0))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(toolbar)
        layout.addWidget(self.stack)
        self.hide()
        self.gutter.line_activated.connect(self._gutter_line_activated)
        self.diff.cursorPositionChanged.connect(self._update_hunk_button)
        self.view_mode_combo.currentIndexChanged.connect(self._update_hunk_button)
        self.clear_lines_button.clicked.connect(self.clear_selection)
        self.selected_lines_button.clicked.connect(self._request_selected_lines)
        self.hunk_button.clicked.connect(self._request_selected_hunk)

    @staticmethod
    def _make_side_editor(object_name: str) -> QPlainTextEdit:
        editor = QPlainTextEdit()
        editor.setObjectName(object_name)
        editor.setReadOnly(True)
        editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setFixedPitch(True)
        editor.setFont(font)
        return editor

    @staticmethod
    def _toggle_button(object_name: str, text: str) -> QToolButton:
        button = QToolButton()
        button.setObjectName(object_name)
        button.setText(text)
        button.setCheckable(True)
        return button

    @property
    def has_pending_partial_selection(self) -> bool:
        return bool(self.selection.selected_lines) and not self.selection.whole_file

    def display_diff(
        self, diff: UnifiedDiff, *, preserve_scroll: bool, whole_file_staged: bool
    ) -> None:
        positions = self._scroll_positions()
        self.current_diff = diff
        if not preserve_scroll:
            self.selection.clear()
        if whole_file_staged:
            self.selection.select_whole_file(diff)
        self.diff_highlighter.set_diff(diff)
        self.diff.setPlainText(diff.text or "No textual changes to display.")
        self._render_gutter(diff, self.selection)
        self._render_side_by_side(diff)
        if preserve_scroll:
            self._restore_scroll_positions(positions)
        self.render_selection()
        self._update_hunk_button()
        self.selection_changed.emit()

    def render_selection(self) -> None:
        diff = self.current_diff
        if diff is None:
            return
        scroll_value = self.gutter.verticalScrollBar().value()
        self._render_gutter(diff, self.selection)
        self.gutter.verticalScrollBar().setValue(scroll_value)
        selections: list[QTextEdit.ExtraSelection] = []
        for line_index in sorted(self.selection.selected_lines):
            extra = QTextEdit.ExtraSelection()
            block = self.diff.document().findBlockByNumber(line_index)
            cursor = QTextCursor(block)
            cursor.select(QTextCursor.SelectionType.BlockUnderCursor)
            extra.cursor = cursor
            extra.format.setBackground(QColor("#2f80ed"))
            extra.format.setForeground(QColor("#ffffff"))
            selections.append(extra)
        self.diff.setExtraSelections(selections)
        has_selection = bool(self.selection.selected_lines)
        self.selected_lines_button.setEnabled(has_selection)
        self.clear_lines_button.setEnabled(has_selection)
        self.selected_lines_button.setText(
            "Unstage selected" if diff.staged else "Stage selected"
        )

    @Slot()
    def clear_selection(self) -> None:
        self.selection.clear()
        self.render_selection()
        self.selection_changed.emit()

    @Slot(int, bool)
    def _gutter_line_activated(self, line_index: int, extend: bool) -> None:
        diff = self.current_diff
        if diff is None:
            return
        if self.selection.toggle(diff, line_index, extend=extend):
            self.render_selection()
            self.selection_changed.emit()

    @Slot()
    def _request_selected_lines(self) -> None:
        diff = self.current_diff
        if diff is None or not self.selection.selected_lines:
            return
        self.lines_requested.emit(diff, set(self.selection.selected_lines))

    @Slot()
    def _request_selected_hunk(self) -> None:
        diff = self.current_diff
        if diff is None:
            return
        hunk_index = diff.hunk_index_for_line(self.diff.textCursor().blockNumber())
        if hunk_index is not None:
            self.hunk_requested.emit(diff, hunk_index)

    @Slot()
    def _update_hunk_button(self) -> None:
        diff = self.current_diff
        unified = self.view_mode_combo.currentData() == "unified"
        hunk_index = None
        if diff is not None:
            hunk_index = diff.hunk_index_for_line(self.diff.textCursor().blockNumber())
        self.hunk_button.setEnabled(unified and hunk_index is not None)
        if diff is not None and diff.staged:
            self.hunk_button.setText("Unstage hunk")
            self.hunk_button.setToolTip("Unstage the hunk under the cursor")
        else:
            self.hunk_button.setText("Stage hunk")
            self.hunk_button.setToolTip("Stage the hunk under the cursor")

    def set_wrap(self, enabled: bool) -> None:
        mode = (
            QPlainTextEdit.LineWrapMode.WidgetWidth
            if enabled
            else QPlainTextEdit.LineWrapMode.NoWrap
        )
        for editor in (self.diff, self.side_old, self.side_new):
            editor.setLineWrapMode(mode)
        self.gutter.setVisible(not enabled and self.isVisible())
        tooltip = (
            "Turn off Wrap to select individual lines in the gutter"
            if enabled
            else "Apply the lines selected with gutter checkboxes"
        )
        self.selected_lines_button.setToolTip(tooltip)

    def set_whitespace(self, enabled: bool) -> None:
        for editor in (self.diff, self.side_old, self.side_new):
            option = editor.document().defaultTextOption()
            flags = option.flags()
            if enabled:
                flags |= QTextOption.Flag.ShowTabsAndSpaces
            else:
                flags &= ~QTextOption.Flag.ShowTabsAndSpaces
            option.setFlags(flags)
            editor.document().setDefaultTextOption(option)

    def set_view_mode(self, mode: str) -> None:
        self.stack.setCurrentIndex(1 if mode == "side-by-side" else 0)

    def rehighlight(self) -> None:
        self.diff_highlighter.rehighlight()
        self.side_old_highlighter.rehighlight()
        self.side_new_highlighter.rehighlight()

    def _render_gutter(self, diff: UnifiedDiff, selection: DiffSelection) -> None:
        old_width = max(
            (len(str(line.old_line)) for line in diff.lines if line.old_line is not None),
            default=1,
        )
        new_width = max(
            (len(str(line.new_line)) for line in diff.lines if line.new_line is not None),
            default=1,
        )
        numbers: list[str] = []
        for line_index, line in enumerate(diff.lines):
            marker = selection.marker(diff, line_index)
            old_number = str(line.old_line) if line.old_line is not None else ""
            new_number = str(line.new_line) if line.new_line is not None else ""
            numbers.append(f"{marker} {old_number:>{old_width}}  {new_number:>{new_width}}")
        self.gutter.setPlainText("\n".join(numbers))
        metrics = QFontMetrics(self.gutter.font())
        sample = "0" * (old_width + new_width + 5)
        self.gutter.setFixedWidth(metrics.horizontalAdvance(sample) + 12)

    def _render_side_by_side(self, diff: UnifiedDiff) -> None:
        old_width = max(
            (len(str(line.old_line)) for line in diff.lines if line.old_line is not None),
            default=1,
        )
        new_width = max(
            (len(str(line.new_line)) for line in diff.lines if line.new_line is not None),
            default=1,
        )
        old_lines: list[str] = []
        new_lines: list[str] = []
        old_kinds: list[DiffLineKind] = []
        new_kinds: list[DiffLineKind] = []
        old_inline: dict[int, tuple[tuple[int, int], ...]] = {}
        new_inline: dict[int, tuple[tuple[int, int], ...]] = {}
        for row_index, row in enumerate(diff.side_by_side_rows):
            old_text = self._side_line_text(row.old, old_width, old=True)
            new_text = self._side_line_text(row.new, new_width, old=False)
            old_lines.append(old_text)
            new_lines.append(new_text)
            old_kinds.append(row.old.kind if row.old is not None else "metadata")
            new_kinds.append(row.new.kind if row.new is not None else "metadata")
            if (
                row.old is not None
                and row.new is not None
                and row.old.kind == "deletion"
                and row.new.kind == "addition"
            ):
                old_content = row.old.text[1:]
                new_content = row.new.text[1:]
                matcher = SequenceMatcher(None, old_content, new_content)
                old_ranges: list[tuple[int, int]] = []
                new_ranges: list[tuple[int, int]] = []
                for tag, old_start, old_end, new_start, new_end in matcher.get_opcodes():
                    if tag != "equal":
                        if old_end > old_start:
                            old_ranges.append((old_width + 2 + old_start, old_end - old_start))
                        if new_end > new_start:
                            new_ranges.append((new_width + 2 + new_start, new_end - new_start))
                if old_ranges:
                    old_inline[row_index] = tuple(old_ranges)
                if new_ranges:
                    new_inline[row_index] = tuple(new_ranges)
        self.side_old_highlighter.set_language(diff.path)
        self.side_new_highlighter.set_language(diff.path)
        self.side_old_highlighter.set_inline_ranges(old_inline)
        self.side_new_highlighter.set_inline_ranges(new_inline)
        self.side_old_highlighter.set_line_kinds(tuple(old_kinds))
        self.side_new_highlighter.set_line_kinds(tuple(new_kinds))
        self.side_old.setPlainText("\n".join(old_lines))
        self.side_new.setPlainText("\n".join(new_lines))

    @staticmethod
    def _side_line_text(line: DiffLine | None, width: int, *, old: bool) -> str:
        if line is None:
            return ""
        number = line.old_line if old else line.new_line
        number_text = str(number) if number is not None else ""
        content = line.text[1:] if line.kind in {"addition", "deletion", "context"} else line.text
        return f"{number_text:>{width}}  {content}"

    def _scroll_positions(self) -> tuple[int, int, int, int, int]:
        return (
            self.diff.verticalScrollBar().value(),
            self.diff.horizontalScrollBar().value(),
            self.side_old.verticalScrollBar().value(),
            self.side_old.horizontalScrollBar().value(),
            self.side_new.horizontalScrollBar().value(),
        )

    def _restore_scroll_positions(self, positions: tuple[int, int, int, int, int]) -> None:
        diff_vertical, diff_horizontal, side_vertical, old_horizontal, new_horizontal = positions
        self.diff.verticalScrollBar().setValue(diff_vertical)
        self.diff.horizontalScrollBar().setValue(diff_horizontal)
        self.side_old.verticalScrollBar().setValue(side_vertical)
        self.side_old.horizontalScrollBar().setValue(old_horizontal)
        self.side_new.horizontalScrollBar().setValue(new_horizontal)
