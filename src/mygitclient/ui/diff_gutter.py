from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QPlainTextEdit


class DiffGutter(QPlainTextEdit):
    line_activated = Signal(int, bool)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() is Qt.MouseButton.LeftButton:
            block = self.cursorForPosition(event.position().toPoint()).blockNumber()
            extend = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            self.line_activated.emit(block, extend)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.buttons() & Qt.MouseButton.LeftButton:
            block = self.cursorForPosition(event.position().toPoint()).blockNumber()
            self.line_activated.emit(block, True)
            event.accept()
            return
        super().mouseMoveEvent(event)
