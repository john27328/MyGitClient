from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPaintEvent
from PySide6.QtWidgets import QPlainTextEdit, QWidget

from mygitclient.git.models import DiffLineKind


class DiffOverview(QWidget):
    """Compact, clickable map of changed lines beside a diff editor."""

    def __init__(self, editor: QPlainTextEdit, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._editor = editor
        self._kinds: tuple[DiffLineKind, ...] = ()
        self.setObjectName("diffOverview")
        self.setFixedWidth(9)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Changed lines; click to jump")
        scrollbar = editor.verticalScrollBar()
        scrollbar.valueChanged.connect(self.update)
        scrollbar.rangeChanged.connect(self._range_changed)

    def set_line_kinds(self, kinds: tuple[DiffLineKind, ...]) -> None:
        self._kinds = tuple(kinds)
        self.setVisible(any(kind in {"addition", "deletion"} for kind in self._kinds))
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.fillRect(self.rect(), self.palette().alternateBase())
        count = max(len(self._kinds), 1)
        dark = self.palette().base().color().lightness() < 128
        colors = {
            "addition": QColor("#2f9e5b" if dark else "#49a96c"),
            "deletion": QColor("#d65a68" if dark else "#d95b64"),
        }
        for index, kind in enumerate(self._kinds):
            color = colors.get(kind)
            if color is None:
                continue
            top = round(index * self.height() / count)
            bottom = max(top + 2, round((index + 1) * self.height() / count))
            painter.fillRect(1, top, self.width() - 2, bottom - top, color)

        scrollbar = self._editor.verticalScrollBar()
        maximum = scrollbar.maximum()
        if maximum > 0:
            visible_ratio = min(
                1.0,
                scrollbar.pageStep() / max(maximum + scrollbar.pageStep(), 1),
            )
            indicator_height = max(8, round(self.height() * visible_ratio))
            available = max(self.height() - indicator_height, 0)
            top = round(available * scrollbar.value() / maximum)
            painter.setPen(self.palette().highlight().color())
            painter.drawRect(0, top, self.width() - 1, indicator_height - 1)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            scrollbar = self._editor.verticalScrollBar()
            ratio = max(0.0, min(1.0, event.position().y() / max(self.height(), 1)))
            scrollbar.setValue(round(scrollbar.maximum() * ratio))
            event.accept()
            return
        super().mousePressEvent(event)

    def _range_changed(self, _minimum: int, _maximum: int) -> None:
        self.update()
