from __future__ import annotations

from contextlib import suppress
from difflib import SequenceMatcher
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QTimer, Signal, Slot
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QFontMetrics,
    QTextCursor,
    QTextOption,
)
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
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
from mygitclient.ui.diff_selection import DiffSelection, LineFingerprint

SelectionKey = tuple[Path, str, bool]


class DiffView(QWidget):
    """Owns the diff presentation widgets while orchestration remains outside."""

    selection_changed = Signal()
    lines_requested = Signal(object, object)
    hunk_requested = Signal(object, int)

    def __init__(self, settings: QSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.current_diff: UnifiedDiff | None = None
        self._current_selection_key: SelectionKey | None = None
        self._saved_selections: dict[SelectionKey, set[LineFingerprint]] = {}
        self._interactive = True
        self._auto_apply_hunks = True
        self._pending_scroll_positions: tuple[int, int, int, int, int] | None = None
        self._scroll_restore_timer = QTimer(self)
        self._scroll_restore_timer.setSingleShot(True)
        self._scroll_restore_timer.timeout.connect(self._restore_pending_scroll_positions)
        self.selection = DiffSelection()
        self.setObjectName("diffContainer")

        diff_font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        diff_font.setStyleHint(QFont.StyleHint.Monospace)
        diff_font.setFixedPitch(True)
        saved_font_size = settings.value("diff/fontSize", diff_font.pointSize())
        if isinstance(saved_font_size, (int, str)):
            with suppress(ValueError):
                diff_font.setPointSize(max(7, min(32, int(saved_font_size))))

        self.diff = QPlainTextEdit()
        self.diff.setObjectName("diffPanel")
        self.diff.setReadOnly(True)
        self.diff.setPlaceholderText("Select a changed file to view its diff.")
        self.diff.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.diff.setMinimumWidth(400)
        self.diff.setFont(diff_font)
        self.diff.hide()
        self.diff_highlighter = DiffHighlighter(self.diff)

        self.file_header = QLabel()
        self.file_header.setObjectName("diffFileHeader")
        self.file_header.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.file_header.setStyleSheet(
            "QLabel { padding: 5px 8px; background: palette(alternate-base); "
            "border-bottom: 1px solid palette(midlight); }"
        )
        self.file_header.hide()

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
            "QPlainTextEdit { background: palette(base); color: palette(mid); "
            "border: 0; border-right: 1px solid palette(midlight); }"
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
        self.version_label = QLabel()
        self.version_label.setObjectName("diffVersionLabel")
        self.version_label.setToolTip(
            "The selected file has only this version of the diff"
        )
        self.version_label.hide()

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
        self.side_old_gutter = self._make_side_gutter("sideBySideOldGutter")
        self.side_new_gutter = self._make_side_gutter("sideBySideNewGutter")
        for widget in (
            self.side_old,
            self.side_new,
            self.side_old_gutter,
            self.side_new_gutter,
        ):
            widget.setFont(diff_font)
        self._side_old_line_indexes: list[int | None] = []
        self._side_new_line_indexes: list[int | None] = []
        self.side_old_highlighter = DiffHighlighter(self.side_old)
        self.side_new_highlighter = DiffHighlighter(self.side_new)
        self.side_old.verticalScrollBar().valueChanged.connect(
            self.side_new.verticalScrollBar().setValue
        )
        self.side_new.verticalScrollBar().valueChanged.connect(
            self.side_old.verticalScrollBar().setValue
        )
        self.side_old.verticalScrollBar().valueChanged.connect(
            self.side_old_gutter.verticalScrollBar().setValue
        )
        self.side_new.verticalScrollBar().valueChanged.connect(
            self.side_new_gutter.verticalScrollBar().setValue
        )
        self.side_old_gutter.line_activated.connect(self._side_old_line_activated)
        self.side_new_gutter.line_activated.connect(self._side_new_line_activated)
        old_body = QWidget()
        old_layout = QHBoxLayout(old_body)
        old_layout.setContentsMargins(0, 0, 0, 0)
        old_layout.setSpacing(0)
        old_layout.addWidget(self.side_old_gutter)
        old_layout.addWidget(self.side_old, 1)
        new_body = QWidget()
        new_layout = QHBoxLayout(new_body)
        new_layout.setContentsMargins(0, 0, 0, 0)
        new_layout.setSpacing(0)
        new_layout.addWidget(self.side_new_gutter)
        new_layout.addWidget(self.side_new, 1)
        side_splitter = QSplitter(Qt.Orientation.Horizontal)
        side_splitter.addWidget(old_body)
        side_splitter.addWidget(new_body)
        side_splitter.setSizes([500, 500])

        self.wrap_button = self._toggle_button("diffWrapButton", "Wrap")
        self.wrap_button.setToolTip("Wrap long diff lines")
        self.whitespace_button = self._toggle_button(
            "diffWhitespaceButton", "Whitespace"
        )
        self.whitespace_button.setToolTip("Show spaces and tab characters")
        self.ignore_whitespace_button = self._toggle_button(
            "diffIgnoreWhitespaceButton", "Ignore spaces"
        )
        self.ignore_whitespace_button.setToolTip(
            "Ignore whitespace changes when loading the diff"
        )
        self.hunk_button = QToolButton()
        self.hunk_button.setObjectName("diffHunkButton")
        self.hunk_button.setText("Stage hunk")
        self.hunk_button.setToolTip("Stage the hunk under the cursor")
        self.hunk_button.setEnabled(False)
        self.selected_lines_button = QToolButton()
        self.selected_lines_button.setObjectName("diffSelectedLinesButton")
        self.selected_lines_button.setText("Stage selected \u2193")
        self.selected_lines_button.setEnabled(False)
        self.selected_lines_button.hide()
        self.clear_lines_button = QToolButton()
        self.clear_lines_button.setObjectName("diffClearSelectionButton")
        self.clear_lines_button.setText("Clear")
        self.clear_lines_button.setEnabled(False)
        self.clear_lines_button.hide()

        toolbar = QWidget()
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(0, 0, 0, 0)
        toolbar_layout.addWidget(self.version_label)
        toolbar_layout.addWidget(self.version_combo)
        toolbar_layout.addStretch(1)
        toolbar_layout.addWidget(self.wrap_button)
        toolbar_layout.addWidget(self.whitespace_button)
        toolbar_layout.addWidget(self.ignore_whitespace_button)
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
        layout.addWidget(self.file_header)
        layout.addWidget(self.stack)
        self.hide()
        self.gutter.line_activated.connect(self._gutter_line_activated)
        self.diff.cursorPositionChanged.connect(self._update_hunk_button)
        self.view_mode_combo.currentIndexChanged.connect(self._update_hunk_button)
        self.version_combo.currentTextChanged.connect(self._version_text_changed)
        self.clear_lines_button.clicked.connect(self.clear_selection)
        self.selected_lines_button.clicked.connect(self._request_selected_lines)
        self.hunk_button.clicked.connect(self._request_selected_hunk)
        self._update_gutter_visibility(False)

    def refresh_version_selector(self) -> None:
        count = self.version_combo.count()
        self.version_label.setText(self.version_combo.currentText())
        self.version_label.setVisible(count == 1)
        self.version_combo.setVisible(count > 1)

    @Slot(str)
    def _version_text_changed(self, text: str) -> None:
        self.version_label.setText(text)

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
    def _make_side_gutter(object_name: str) -> DiffGutter:
        gutter = DiffGutter()
        gutter.setObjectName(object_name)
        gutter.setReadOnly(True)
        gutter.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        gutter.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        gutter.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        gutter.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        gutter.setCursor(Qt.CursorShape.PointingHandCursor)
        gutter.setFixedWidth(28)
        gutter.setStyleSheet(
            "QPlainTextEdit { background: palette(base); color: palette(mid); "
            "border: 0; border-right: 1px solid palette(midlight); }"
        )
        return gutter

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

    def set_auto_apply_hunks(self, enabled: bool) -> None:
        self._auto_apply_hunks = enabled
        self.hunk_button.setVisible(self._interactive and not enabled)
        self.gutter.setToolTip(
            "Click a hunk checkbox to apply the whole block immediately. "
            "Individual lines are collected for the selected-lines action."
            if enabled
            else "Click a checkbox to select a changed line. "
            "Click a hunk checkbox to select the whole block."
        )

    def has_saved_selection(self, repository: Path, path: str) -> bool:
        return any(
            bool(self._saved_selections.get((repository, path, staged)))
            for staged in (False, True)
        )

    def retain_changed_paths(self, repository: Path, paths: set[str]) -> None:
        self._saved_selections = {
            key: selection
            for key, selection in self._saved_selections.items()
            if key[0] != repository or key[1] in paths
        }

    def display_diff(
        self,
        diff: UnifiedDiff,
        *,
        selection_key: SelectionKey | None,
        preserve_scroll: bool,
        whole_file_staged: bool,
        interactive: bool = True,
    ) -> None:
        self._scroll_restore_timer.stop()
        self._pending_scroll_positions = None
        positions = self._scroll_positions()
        self._remember_selection()
        self.current_diff = diff
        self._interactive = interactive
        self.hunk_button.setVisible(interactive and not self._auto_apply_hunks)
        self.selected_lines_button.hide()
        self.clear_lines_button.hide()
        self._current_selection_key = selection_key if interactive else None
        if not interactive:
            self.selection.clear()
        elif whole_file_staged:
            self.selection.select_whole_file(diff)
        else:
            assert selection_key is not None
            self.selection.restore(diff, self._saved_selections.get(selection_key, set()))
        self.diff_highlighter.set_diff(diff)
        self.file_header.setText(diff.path)
        self.file_header.setToolTip(diff.path)
        self.file_header.setVisible(bool(diff.lines))
        self.diff.setPlainText(
            "\n".join(self._display_lines(diff)) or "No textual changes to display."
        )
        self._render_gutter(diff, self.selection)
        self._hide_unified_service_blocks(diff)
        self._render_side_by_side(diff)
        if preserve_scroll:
            self._restore_scroll_positions(positions)
            # Headless Qt platforms may update scrollbar ranges on the next event-loop
            # pass. Restore once more after layout so an unchanged asynchronous refresh
            # cannot clamp the saved position to zero.
            self._pending_scroll_positions = positions
            self._scroll_restore_timer.start(0)
        self.render_selection()
        self._update_hunk_button()
        self.selection_changed.emit()

    def reset(self) -> None:
        self._remember_selection()
        self.current_diff = None
        self._current_selection_key = None
        self._interactive = True
        self.selection.clear()
        self.diff.clear()
        self.gutter.clear()
        self.side_old.clear()
        self.side_new.clear()
        self.side_old_gutter.clear()
        self.side_new_gutter.clear()
        self.file_header.clear()
        self.file_header.hide()
        self._side_old_line_indexes = []
        self._side_new_line_indexes = []
        self.side_old_highlighter.set_inline_ranges({})
        self.side_new_highlighter.set_inline_ranges({})
        self.side_old_highlighter.set_line_kinds(())
        self.side_new_highlighter.set_line_kinds(())
        self.diff.setExtraSelections([])
        self.side_old.setExtraSelections([])
        self.side_new.setExtraSelections([])

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
            kind = diff.lines[line_index].kind
            dark = self.diff.palette().base().color().lightness() < 128
            if kind == "addition":
                color = QColor("#2f7548" if dark else "#b7e8c3")
            elif kind == "deletion":
                color = QColor("#843944" if dark else "#f2b8b8")
            else:
                color = QColor("#365b8c" if dark else "#dbeafe")
            extra.format.setBackground(color)
            selections.append(extra)
        self.diff.setExtraSelections(selections)
        self._render_side_selection(diff)
        has_selection = self._interactive and bool(self.selection.selected_lines)
        self.selected_lines_button.setEnabled(has_selection)
        self.clear_lines_button.setEnabled(has_selection)
        self.selected_lines_button.setText(
            "Unstage selected \u2191" if diff.staged else "Stage selected \u2193"
        )

    @Slot()
    def clear_selection(self) -> None:
        self.selection.clear()
        self._remember_selection()
        self.render_selection()
        self.selection_changed.emit()

    @Slot(int, bool)
    def _gutter_line_activated(self, line_index: int, extend: bool) -> None:
        diff = self.current_diff
        if diff is None or not self._interactive:
            return
        if (
            not extend
            and 0 <= line_index < len(diff.lines)
            and diff.lines[line_index].kind == "hunk"
        ):
            hunk_index = diff.hunk_index_for_line(line_index)
            if hunk_index is not None:
                self.hunk_requested.emit(diff, hunk_index)
            return
        selected_before = set(self.selection.selected_lines)
        whole_file_before = self.selection.whole_file
        if self.selection.toggle(diff, line_index, extend=extend):
            changed_lines = selected_before ^ self.selection.selected_lines
            self.selection.selected_lines = selected_before
            self.selection.whole_file = whole_file_before
            if changed_lines:
                self.lines_requested.emit(diff, changed_lines)

    @Slot(int, bool)
    def _side_old_line_activated(self, row_index: int, extend: bool) -> None:
        self._side_line_activated(self._side_old_line_indexes, row_index, extend)

    @Slot(int, bool)
    def _side_new_line_activated(self, row_index: int, extend: bool) -> None:
        self._side_line_activated(self._side_new_line_indexes, row_index, extend)

    def _side_line_activated(
        self, indexes: list[int | None], row_index: int, extend: bool
    ) -> None:
        if row_index < 0 or row_index >= len(indexes):
            return
        line_index = indexes[row_index]
        if line_index is not None:
            self._gutter_line_activated(line_index, extend)

    def _remember_selection(self) -> None:
        diff = self.current_diff
        key = self._current_selection_key
        if diff is None or key is None:
            return
        if self.selection.selected_lines and not self.selection.whole_file:
            self._saved_selections[key] = self.selection.fingerprints(diff)
        else:
            self._saved_selections.pop(key, None)

    @Slot()
    def _request_selected_lines(self) -> None:
        diff = self.current_diff
        if diff is None or not self.selection.selected_lines:
            return
        self.lines_requested.emit(diff, set(self.selection.selected_lines))
        self.clear_selection()

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
        self.hunk_button.setEnabled(
            self._interactive and unified and hunk_index is not None
        )
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
        self._update_gutter_visibility(enabled)
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

    def set_font_size(self, point_size: int) -> None:
        for editor in (
            self.diff,
            self.gutter,
            self.side_old,
            self.side_new,
            self.side_old_gutter,
            self.side_new_gutter,
        ):
            font = editor.font()
            font.setPointSize(point_size)
            editor.setFont(font)
        if self.current_diff is not None:
            self._render_gutter(self.current_diff, self.selection)

    def set_view_mode(self, mode: str) -> None:
        self.stack.setCurrentIndex(1 if mode == "side-by-side" else 0)
        self._update_gutter_visibility(
            self.diff.lineWrapMode() != QPlainTextEdit.LineWrapMode.NoWrap
        )

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
            marker = selection.marker(diff, line_index) if self._interactive else " "
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
        line_indexes = {id(line): index for index, line in enumerate(diff.lines)}
        self._side_old_line_indexes = []
        self._side_new_line_indexes = []
        display_rows = tuple(
            row
            for row in diff.side_by_side_rows
            if not self._is_service_row(row.old, row.new)
        )
        for row_index, row in enumerate(display_rows):
            old_text = self._side_line_text(row.old, old_width, old=True)
            new_text = self._side_line_text(row.new, new_width, old=False)
            if row.old is not None and row.old.kind == "hunk":
                old_text = new_text = self._hunk_label(diff, row.old)
            old_lines.append(old_text)
            new_lines.append(new_text)
            old_kinds.append(row.old.kind if row.old is not None else "metadata")
            new_kinds.append(row.new.kind if row.new is not None else "metadata")
            self._side_old_line_indexes.append(
                line_indexes.get(id(row.old)) if row.old is not None else None
            )
            self._side_new_line_indexes.append(
                line_indexes.get(id(row.new)) if row.new is not None else None
            )
            if (
                row.old is not None
                and row.new is not None
                and row.old.kind == "deletion"
                and row.new.kind == "addition"
            ):
                old_content = row.old.text[1:]
                new_content = row.new.text[1:]
                old_ranges, new_ranges = inline_change_ranges(
                    old_content,
                    new_content,
                    old_offset=old_width + 2,
                    new_offset=new_width + 2,
                )
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

    def _render_side_selection(self, diff: UnifiedDiff) -> None:
        self.side_old_gutter.setPlainText(
            "\n".join(self._side_marker(diff, index) for index in self._side_old_line_indexes)
        )
        self.side_new_gutter.setPlainText(
            "\n".join(self._side_marker(diff, index) for index in self._side_new_line_indexes)
        )
        self.side_old.setExtraSelections(
            self._side_extra_selections(self.side_old, self._side_old_line_indexes, diff)
        )
        self.side_new.setExtraSelections(
            self._side_extra_selections(self.side_new, self._side_new_line_indexes, diff)
        )

    def _side_marker(self, diff: UnifiedDiff, line_index: int | None) -> str:
        if line_index is None or not self._interactive:
            return " "
        return self.selection.marker(diff, line_index)

    def _side_extra_selections(
        self,
        editor: QPlainTextEdit,
        indexes: list[int | None],
        diff: UnifiedDiff,
    ) -> list[QTextEdit.ExtraSelection]:
        selections: list[QTextEdit.ExtraSelection] = []
        dark = editor.palette().base().color().lightness() < 128
        for row_index, line_index in enumerate(indexes):
            if line_index is None or line_index not in self.selection.selected_lines:
                continue
            extra = QTextEdit.ExtraSelection()
            cursor = QTextCursor(editor.document().findBlockByNumber(row_index))
            cursor.select(QTextCursor.SelectionType.BlockUnderCursor)
            extra.cursor = cursor
            kind = diff.lines[line_index].kind
            if kind == "addition":
                color = QColor("#2f7548" if dark else "#b7e8c3")
            elif kind == "deletion":
                color = QColor("#843944" if dark else "#f2b8b8")
            else:
                color = QColor("#365b8c" if dark else "#dbeafe")
            extra.format.setBackground(color)
            selections.append(extra)
        return selections
    def _update_gutter_visibility(self, wrap_enabled: bool) -> None:
        unified = self.view_mode_combo.currentData() == "unified"
        self.gutter.setVisible(unified and not wrap_enabled)
        self.side_old_gutter.setVisible(not unified and not wrap_enabled)
        self.side_new_gutter.setVisible(not unified and not wrap_enabled)

    @staticmethod
    def _side_line_text(line: DiffLine | None, width: int, *, old: bool) -> str:
        if line is None:
            return ""
        number = line.old_line if old else line.new_line
        number_text = str(number) if number is not None else ""
        content = line.text[1:] if line.kind in {"addition", "deletion", "context"} else line.text
        return f"{number_text:>{width}}  {content}"

    @staticmethod
    def _is_service_row(old: DiffLine | None, new: DiffLine | None) -> bool:
        line = old or new
        return line is not None and line.kind in {"header", "metadata"}

    def _display_lines(self, diff: UnifiedDiff) -> tuple[str, ...]:
        if not diff.hunks:
            return tuple(line.text for line in diff.lines)
        rendered: list[str] = []
        for line in diff.lines:
            if line.kind in {"header", "metadata"}:
                rendered.append("")
            elif line.kind == "hunk":
                rendered.append(self._hunk_label(diff, line))
            else:
                rendered.append(line.text)
        return tuple(rendered)

    def _hide_unified_service_blocks(self, diff: UnifiedDiff) -> None:
        for editor in (self.diff, self.gutter):
            document = editor.document()
            for index, line in enumerate(diff.lines):
                block = document.findBlockByNumber(index)
                visible = line.kind not in {"header", "metadata"}
                block.setVisible(visible)
                block.setLineCount(1 if visible else 0)
            document.markContentsDirty(0, document.characterCount())

    @staticmethod
    def _hunk_label(diff: UnifiedDiff, line: DiffLine | None) -> str:
        if line is None:
            return ""
        hunk = next((candidate for candidate in diff.hunks if candidate.header == line.text), None)
        if hunk is None:
            return line.text
        old_end = hunk.old_start + max(hunk.old_count - 1, 0)
        new_end = hunk.new_start + max(hunk.new_count - 1, 0)
        old_range = (
            str(hunk.old_start)
            if old_end == hunk.old_start
            else f"{hunk.old_start}–{old_end}"
        )
        new_range = (
            str(hunk.new_start)
            if new_end == hunk.new_start
            else f"{hunk.new_start}–{new_end}"
        )
        return f"── Old lines {old_range} · New lines {new_range} ──"

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

    @Slot()
    def _restore_pending_scroll_positions(self) -> None:
        """Retry non-zero positions that Qt clamped before recalculating ranges."""
        positions = self._pending_scroll_positions
        self._pending_scroll_positions = None
        if positions is None:
            return
        widgets = (
            self.diff.verticalScrollBar(),
            self.diff.horizontalScrollBar(),
            self.side_old.verticalScrollBar(),
            self.side_old.horizontalScrollBar(),
            self.side_new.horizontalScrollBar(),
        )
        for scrollbar, position in zip(widgets, positions, strict=True):
            if position > 0 and scrollbar.value() == 0:
                scrollbar.setValue(position)


def inline_change_ranges(
    old: str,
    new: str,
    *,
    old_offset: int = 0,
    new_offset: int = 0,
) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    matcher = SequenceMatcher(None, old, new, autojunk=False)
    if matcher.ratio() < 0.55:
        return [], []
    old_ranges: list[tuple[int, int]] = []
    new_ranges: list[tuple[int, int]] = []
    for tag, old_start, old_end, new_start, new_end in matcher.get_opcodes():
        if tag == "equal":
            continue
        if old_end > old_start:
            old_ranges.append((old_offset + old_start, old_end - old_start))
        if new_end > new_start:
            new_ranges.append((new_offset + new_start, new_end - new_start))
    return old_ranges, new_ranges
