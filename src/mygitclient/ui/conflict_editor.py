from __future__ import annotations

from difflib import SequenceMatcher
from pathlib import Path

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QColor, QTextCursor
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from mygitclient.git.conflicts import (
    ConflictChoice,
    parse_conflict_blocks,
    resolve_conflict_block,
)


class ConflictEditor(QWidget):
    """Edits the worktree result and optionally compares the selected conflict."""

    save_requested = Signal(object, str)
    mergetool_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("conflictEditor")
        self._path: Path | None = None
        self._current_conflict = 0
        self._updating = False
        self._base_text = ""
        self._current_text = ""
        self._incoming_text = ""

        self.file_label = QLabel()
        self.file_label.setObjectName("conflictFileLabel")
        self.status_label = QLabel()
        self.status_label.setObjectName("conflictStatusLabel")
        self.previous_button = QPushButton("Previous")
        self.previous_button.setObjectName("previousConflictButton")
        self.next_button = QPushButton("Next")
        self.next_button.setObjectName("nextConflictButton")
        self.result_button = QPushButton("Result")
        self.result_button.setObjectName("conflictResultModeButton")
        self.result_button.setCheckable(True)
        self.compare_button = QPushButton("Compare changes")
        self.compare_button.setObjectName("conflictCompareModeButton")
        self.compare_button.setCheckable(True)
        self.comparison_combo = QComboBox()
        self.comparison_combo.setObjectName("conflictComparisonCombo")
        self.comparison_combo.addItem("Current ↔ Incoming", "blocks")
        self.comparison_combo.addItem("Base → Current", "base-current")
        self.comparison_combo.addItem("Base → Incoming", "base-incoming")

        header = QHBoxLayout()
        header.addWidget(self.file_label, 1)
        header.addWidget(self.status_label)
        header.addWidget(self.previous_button)
        header.addWidget(self.next_button)
        header.addWidget(self.result_button)
        header.addWidget(self.compare_button)
        header.addWidget(self.comparison_combo)

        self.result_edit = QPlainTextEdit()
        self.result_edit.setObjectName("conflictResultEdit")
        self.result_edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)

        self.current_edit = self._make_compare_edit("conflictCurrentEdit")
        self.incoming_edit = self._make_compare_edit("conflictIncomingEdit")
        self.current_label = QLabel("Current")
        self.current_label.setObjectName("conflictCurrentLabel")
        self.incoming_label = QLabel("Incoming")
        self.incoming_label.setObjectName("conflictIncomingLabel")
        compare_splitter = QSplitter(Qt.Orientation.Horizontal)
        compare_splitter.setObjectName("conflictCompareSplitter")
        compare_splitter.addWidget(self._labeled_edit(self.current_label, self.current_edit))
        compare_splitter.addWidget(self._labeled_edit(self.incoming_label, self.incoming_edit))

        self.mode_stack = QStackedWidget()
        self.mode_stack.setObjectName("conflictModeStack")
        self.mode_stack.addWidget(self.result_edit)
        self.mode_stack.addWidget(compare_splitter)

        self.use_current_button = QPushButton("Use current")
        self.use_current_button.setObjectName("useCurrentConflictBlockButton")
        self.use_both_button = QPushButton("Use both")
        self.use_both_button.setObjectName("useBothConflictBlockButton")
        self.use_incoming_button = QPushButton("Use incoming")
        self.use_incoming_button.setObjectName("useIncomingConflictBlockButton")
        self.save_button = QPushButton("Save and mark resolved")
        self.save_button.setObjectName("saveResolvedConflictButton")
        self.mergetool_button = QPushButton("External merge tool…")
        self.mergetool_button.setObjectName("externalMergeToolButton")
        actions = QHBoxLayout()
        actions.addWidget(self.use_current_button)
        actions.addWidget(self.use_both_button)
        actions.addWidget(self.use_incoming_button)
        actions.addStretch(1)
        actions.addWidget(self.mergetool_button)
        actions.addWidget(self.save_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(header)
        layout.addWidget(self.mode_stack, 1)
        layout.addLayout(actions)

        self.previous_button.clicked.connect(lambda: self._move_conflict(-1))
        self.next_button.clicked.connect(lambda: self._move_conflict(1))
        self.result_button.clicked.connect(lambda: self._set_compare_mode(False))
        self.compare_button.clicked.connect(lambda: self._set_compare_mode(True))
        self.use_current_button.clicked.connect(
            lambda: self._resolve_current("current")
        )
        self.use_both_button.clicked.connect(lambda: self._resolve_current("both"))
        self.use_incoming_button.clicked.connect(
            lambda: self._resolve_current("incoming")
        )
        self.save_button.clicked.connect(self._save)
        self.mergetool_button.clicked.connect(self.mergetool_requested)
        self.comparison_combo.currentIndexChanged.connect(self._refresh_comparison)
        self.result_edit.textChanged.connect(self._refresh)
        self._set_compare_mode(False)
        self.clear()

    @staticmethod
    def _make_compare_edit(name: str) -> QPlainTextEdit:
        edit = QPlainTextEdit()
        edit.setObjectName(name)
        edit.setReadOnly(True)
        edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        return edit

    @staticmethod
    def _labeled_edit(label: QLabel, edit: QPlainTextEdit) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(label)
        layout.addWidget(edit, 1)
        return container

    def load_file(self, path: Path, display_path: str) -> None:
        if self._path == path and self.result_edit.document().isModified():
            return
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as error:
            self.clear()
            self.file_label.setText(display_path)
            self.result_edit.setPlainText(f"Could not read conflicted file:\n{error}")
            self.result_edit.setReadOnly(True)
            return
        self._path = path
        self.file_label.setText(display_path)
        self.result_edit.setReadOnly(False)
        self._updating = True
        self.result_edit.setPlainText(text)
        self.result_edit.document().setModified(False)
        self._updating = False
        self._current_conflict = 0
        self._refresh()

    def set_versions(self, base: str, current: str, incoming: str) -> None:
        self._base_text = base
        self._current_text = current
        self._incoming_text = incoming
        self._refresh_comparison()

    def clear(self) -> None:
        self._path = None
        self._current_conflict = 0
        self._updating = True
        self.result_edit.clear()
        self.current_edit.clear()
        self.incoming_edit.clear()
        self._base_text = ""
        self._current_text = ""
        self._incoming_text = ""
        self._updating = False
        self.file_label.setText("Select a conflicted file.")
        self.status_label.clear()
        self._update_controls(0)

    @Slot()
    def _refresh(self) -> None:
        if self._updating:
            return
        text = self.result_edit.toPlainText()
        blocks = parse_conflict_blocks(text)
        count = len(blocks)
        if count:
            self._current_conflict = min(self._current_conflict, count - 1)
            block = blocks[self._current_conflict]
            self.current_edit.setPlainText("".join(block.current))
            self.incoming_edit.setPlainText("".join(block.incoming))
            self.status_label.setText(
                f"Conflict {self._current_conflict + 1} of {count}"
            )
            self._decorate_result(block.start, block.separator, block.end)
        else:
            self._current_conflict = 0
            self.current_edit.clear()
            self.incoming_edit.clear()
            self.status_label.setText("No conflict markers")
            self.result_edit.setExtraSelections([])
        self._update_controls(count)
        self._refresh_comparison()

    @Slot()
    def _refresh_comparison(self) -> None:
        mode = self.comparison_combo.currentData()
        if mode == "blocks":
            self.current_label.setText("Current")
            self.incoming_label.setText("Incoming")
            blocks = parse_conflict_blocks(self.result_edit.toPlainText())
            if blocks:
                block = blocks[min(self._current_conflict, len(blocks) - 1)]
                self.current_edit.setPlainText("".join(block.current))
                self.incoming_edit.setPlainText("".join(block.incoming))
            self.current_edit.setExtraSelections([])
            self.incoming_edit.setExtraSelections([])
            return
        self.current_label.setText("Base")
        self.incoming_label.setText(
            "Current" if mode == "base-current" else "Incoming"
        )
        right = self._current_text if mode == "base-current" else self._incoming_text
        self.current_edit.setPlainText(self._base_text)
        self.incoming_edit.setPlainText(right)
        self._decorate_full_diff(self._base_text, right)

    def _decorate_full_diff(self, left: str, right: str) -> None:
        left_lines = left.splitlines()
        right_lines = right.splitlines()
        left_changed: set[int] = set()
        right_changed: set[int] = set()
        for tag, left_start, left_end, right_start, right_end in SequenceMatcher(
            None, left_lines, right_lines, autojunk=False
        ).get_opcodes():
            if tag != "equal":
                left_changed.update(range(left_start, left_end))
                right_changed.update(range(right_start, right_end))
        self.current_edit.setExtraSelections(
            self._line_selections(self.current_edit, left_changed, self.palette().mid().color())
        )
        self.incoming_edit.setExtraSelections(
            self._line_selections(self.incoming_edit, right_changed, self.palette().link().color())
        )

    def _line_selections(
        self, edit: QPlainTextEdit, lines: set[int], color: QColor
    ) -> list[QTextEdit.ExtraSelection]:
        selections: list[QTextEdit.ExtraSelection] = []
        background = self._soft_color(color, 55)
        for line in lines:
            selection = QTextEdit.ExtraSelection()
            cursor = QTextCursor(edit.document().findBlockByNumber(line))
            cursor.select(QTextCursor.SelectionType.BlockUnderCursor)
            selection.cursor = cursor
            selection.format.setBackground(background)
            selections.append(selection)
        return selections

    def _update_controls(self, conflict_count: int) -> None:
        has_conflict = conflict_count > 0
        self.previous_button.setEnabled(conflict_count > 1)
        self.next_button.setEnabled(conflict_count > 1)
        self.compare_button.setEnabled(has_conflict)
        self.use_current_button.setEnabled(has_conflict)
        self.use_both_button.setEnabled(has_conflict)
        self.use_incoming_button.setEnabled(has_conflict)
        self.save_button.setEnabled(self._path is not None and not has_conflict)

    def _decorate_result(self, start: int, separator: int, end: int) -> None:
        selections: list[QTextEdit.ExtraSelection] = []
        current_color = self._soft_color(self.palette().highlight().color(), 38)
        incoming_color = self._soft_color(self.palette().link().color(), 38)
        for first, last, color in (
            (start, separator, current_color),
            (separator + 1, end, incoming_color),
        ):
            for line_number in range(first, last + 1):
                selection = QTextEdit.ExtraSelection()
                block = self.result_edit.document().findBlockByNumber(line_number)
                cursor = QTextCursor(block)
                cursor.select(QTextCursor.SelectionType.BlockUnderCursor)
                selection.cursor = cursor
                selection.format.setBackground(color)
                selections.append(selection)
        self.result_edit.setExtraSelections(selections)
        block = self.result_edit.document().findBlockByNumber(start)
        cursor = QTextCursor(block)
        self.result_edit.setTextCursor(cursor)
        self.result_edit.centerCursor()

    def refresh_theme(self) -> None:
        """Recreate palette-derived conflict decorations for the active theme."""

        blocks = parse_conflict_blocks(self.result_edit.toPlainText())
        if blocks:
            self._current_conflict = min(self._current_conflict, len(blocks) - 1)
            block = blocks[self._current_conflict]
            self._decorate_result(block.start, block.separator, block.end)
        else:
            self.result_edit.setExtraSelections([])
        self._refresh_comparison()
        self.update()

    @staticmethod
    def _soft_color(color: QColor, alpha: int) -> QColor:
        result = QColor(color)
        result.setAlpha(alpha)
        return result

    def _move_conflict(self, offset: int) -> None:
        count = len(parse_conflict_blocks(self.result_edit.toPlainText()))
        if count < 2:
            return
        self._current_conflict = (self._current_conflict + offset) % count
        self._refresh()

    def _set_compare_mode(self, compare: bool) -> None:
        self.mode_stack.setCurrentIndex(1 if compare else 0)
        self.result_button.setChecked(not compare)
        self.compare_button.setChecked(compare)

    def _resolve_current(self, choice: ConflictChoice) -> None:
        text = self.result_edit.toPlainText()
        try:
            resolved = resolve_conflict_block(text, self._current_conflict, choice)
        except IndexError:
            return
        self._updating = True
        self.result_edit.setPlainText(resolved)
        self.result_edit.document().setModified(True)
        self._updating = False
        self._refresh()
        self._set_compare_mode(False)

    @Slot()
    def _save(self) -> None:
        if self._path is None or parse_conflict_blocks(self.result_edit.toPlainText()):
            return
        self.save_requested.emit(self._path, self.result_edit.toPlainText())
