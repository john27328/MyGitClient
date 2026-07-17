from __future__ import annotations

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QPlainTextEdit,
    QSplitter,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from mygitclient.ui.diff_gutter import DiffGutter
from mygitclient.ui.diff_highlighter import DiffHighlighter


class DiffView(QWidget):
    """Owns the diff presentation widgets while orchestration remains outside."""

    def __init__(self, settings: QSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
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
