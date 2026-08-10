from __future__ import annotations

import mimetypes
from difflib import SequenceMatcher
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QSize, Qt, Signal, Slot
from PySide6.QtGui import QColor, QFontDatabase, QPixmap, QTextCursor
from PySide6.QtPdf import QPdfDocument
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
    binary_choice_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("conflictEditor")
        self._path: Path | None = None
        self._current_conflict = 0
        self._updating = False
        self._base_text = ""
        self._current_text = ""
        self._incoming_text = ""
        self._binary = False

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

        self.binary_current = QLabel()
        self.binary_current.setObjectName("binaryCurrentPreview")
        self.binary_current.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.binary_incoming = QLabel()
        self.binary_incoming.setObjectName("binaryIncomingPreview")
        self.binary_incoming.setAlignment(Qt.AlignmentFlag.AlignCenter)
        binary_splitter = QSplitter(Qt.Orientation.Horizontal)
        binary_splitter.addWidget(
            self._labeled_preview(QLabel("Current"), self.binary_current)
        )
        binary_splitter.addWidget(
            self._labeled_preview(QLabel("Incoming"), self.binary_incoming)
        )
        self.mode_stack.addWidget(binary_splitter)

        self.use_current_button = QPushButton("Use current")
        self.use_current_button.setObjectName("useCurrentConflictBlockButton")
        self.use_both_button = QPushButton("Use both")
        self.use_both_button.setObjectName("useBothConflictBlockButton")
        self.use_incoming_button = QPushButton("Use incoming")
        self.use_incoming_button.setObjectName("useIncomingConflictBlockButton")
        self.delete_binary_button = QPushButton("Delete result")
        self.delete_binary_button.setObjectName("deleteBinaryConflictButton")
        self.delete_binary_button.setVisible(False)
        self.save_button = QPushButton("Save and mark resolved")
        self.save_button.setObjectName("saveResolvedConflictButton")
        self.mergetool_button = QPushButton("External merge tool…")
        self.mergetool_button.setObjectName("externalMergeToolButton")
        actions = QHBoxLayout()
        actions.addWidget(self.use_current_button)
        actions.addWidget(self.use_both_button)
        actions.addWidget(self.use_incoming_button)
        actions.addWidget(self.delete_binary_button)
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
        self.delete_binary_button.clicked.connect(
            lambda: self.binary_choice_requested.emit("delete")
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

    @staticmethod
    def _labeled_preview(label: QLabel, preview: QLabel) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(label)
        layout.addWidget(preview, 1)
        return container

    def load_file(self, path: Path, display_path: str) -> None:
        if self._path == path and self.result_edit.document().isModified():
            return
        try:
            data = path.read_bytes()
        except OSError as error:
            self.clear()
            self.file_label.setText(display_path)
            self.result_edit.setPlainText(f"Could not read conflicted file:\n{error}")
            self.result_edit.setReadOnly(True)
            return
        self._path = path
        self.file_label.setText(display_path)
        self._binary = b"\0" in data
        text = "" if self._binary else data.decode("utf-8", errors="replace")
        self.result_edit.setReadOnly(False)
        self._updating = True
        self.result_edit.setPlainText(text)
        self.result_edit.document().setModified(False)
        self._updating = False
        self._current_conflict = 0
        self._refresh()

    def set_versions(
        self,
        base: bytes,
        current: bytes,
        incoming: bytes,
        attributes: tuple[tuple[str, str], ...] = (),
    ) -> None:
        attribute_map = dict(attributes)
        self._binary = (
            attribute_map.get("binary") == "set"
            or attribute_map.get("diff") == "unset"
            or any(b"\0" in value for value in (base, current, incoming))
        )
        if self._binary:
            self._show_binary_versions(current, incoming, attribute_map)
            return
        self.result_button.setEnabled(True)
        self.comparison_combo.setEnabled(True)
        self.use_both_button.setVisible(True)
        self.delete_binary_button.setVisible(False)
        self._set_compare_mode(False)
        self._base_text = base.decode("utf-8", errors="replace")
        self._current_text = current.decode("utf-8", errors="replace")
        self._incoming_text = incoming.decode("utf-8", errors="replace")
        self._refresh_comparison()

    def _show_binary_versions(
        self, current: bytes, incoming: bytes, attributes: dict[str, str]
    ) -> None:
        self.mode_stack.setCurrentIndex(2)
        self.status_label.setText("Binary conflict")
        self.result_button.setEnabled(False)
        self.compare_button.setEnabled(False)
        self.comparison_combo.setEnabled(False)
        self.use_both_button.setVisible(False)
        self.delete_binary_button.setVisible(True)
        self.use_current_button.setEnabled(bool(current))
        self.use_incoming_button.setEnabled(bool(incoming))
        self.save_button.setEnabled(False)
        self._set_binary_preview(self.binary_current, current, attributes)
        self._set_binary_preview(self.binary_incoming, incoming, attributes)

    def _set_binary_preview(
        self, label: QLabel, data: bytes, attributes: dict[str, str]
    ) -> None:
        pixmap = QPixmap()
        if data and pixmap.loadFromData(data):
            scaled = pixmap.scaled(
                720, 720, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            label.setPixmap(scaled)
            label.setToolTip(self._binary_details(data, attributes, pixmap))
            return
        suffix = Path(self.file_label.text()).suffix.casefold()
        if suffix == ".pdf" and self._set_pdf_preview(label, data, attributes):
            return
        if suffix in {".zip", ".docx", ".xlsx", ".pptx", ".odt", ".ods", ".odp"}:
            archive = self._archive_details(data)
            if archive is not None:
                label.setPixmap(QPixmap())
                label.setText(f"{archive}\n\n{self._binary_details(data, attributes, None)}")
                return
        if suffix in {".ttf", ".otf", ".ttc"} and self._set_font_preview(
            label, data, attributes
        ):
            return
        label.setPixmap(QPixmap())
        label.setText(self._binary_details(data, attributes, None))

    def _set_pdf_preview(
        self, label: QLabel, data: bytes, attributes: dict[str, str]
    ) -> bool:
        buffer = QBuffer(label)
        buffer.setData(QByteArray(data))
        if not buffer.open(QIODevice.OpenModeFlag.ReadOnly):
            return False
        document = QPdfDocument(label)
        document.load(buffer)
        if document.error() != QPdfDocument.Error.None_ or document.pageCount() < 1:
            return False
        image = document.render(0, QSize(720, 720))
        if image.isNull():
            return False
        label.setPixmap(QPixmap.fromImage(image))
        label.setToolTip(
            f"PDF · {document.pageCount()} pages\n"
            f"{self._binary_details(data, attributes, None)}"
        )
        return True

    @staticmethod
    def _archive_details(data: bytes) -> str | None:
        try:
            with ZipFile(BytesIO(data)) as archive:
                names = [info.filename for info in archive.infolist() if not info.is_dir()]
        except (BadZipFile, OSError):
            return None
        shown = names[:18]
        listing = "\n".join(f"• {name}" for name in shown)
        remaining = len(names) - len(shown)
        if remaining:
            listing += f"\n… and {remaining} more"
        return f"Archive contents · {len(names)} files\n{listing or '(empty archive)'}"

    def _set_font_preview(
        self, label: QLabel, data: bytes, attributes: dict[str, str]
    ) -> bool:
        font_id = QFontDatabase.addApplicationFontFromData(QByteArray(data))
        if font_id < 0:
            return False
        families = QFontDatabase.applicationFontFamilies(font_id)
        if not families:
            return False
        font = label.font()
        font.setFamily(families[0])
        font.setPointSize(22)
        label.setFont(font)
        label.setText(
            f"{families[0]}\n\nAa Бб 0123\nThe quick brown fox\n"
            f"Съешь ещё этих мягких французских булок\n\n"
            f"{self._binary_details(data, attributes, None)}"
        )
        return True

    def _binary_details(
        self, data: bytes, attributes: dict[str, str], pixmap: QPixmap | None
    ) -> str:
        mime = mimetypes.guess_type(self.file_label.text())[0] or "binary data"
        dimensions = ""
        if pixmap is not None:
            dimensions = f"\n{pixmap.width()} × {pixmap.height()} px"
        merge = attributes.get("merge", "unspecified")
        return (
            f"{mime}{dimensions}\n{len(data):,} bytes\nSHA-256: {sha256(data).hexdigest()}"
            f"\nGit merge attribute: {merge}"
        )

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
        self._binary = False
        self._updating = False
        self.file_label.setText("Select a conflicted file.")
        self.status_label.clear()
        self.result_button.setEnabled(True)
        self.comparison_combo.setEnabled(True)
        self.use_both_button.setVisible(True)
        self.delete_binary_button.setVisible(False)
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
        if self._binary:
            if choice != "both":
                self.binary_choice_requested.emit(
                    "ours" if choice == "current" else "theirs"
                )
            return
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
