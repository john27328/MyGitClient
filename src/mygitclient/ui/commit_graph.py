from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QStyledItemDelegate, QStyleOptionViewItem

GRAPH_ROLE = int(Qt.ItemDataRole.UserRole) + 1


@dataclass(frozen=True, slots=True)
class CommitGraphRow:
    lanes_before: tuple[str, ...]
    lanes_after: tuple[str, ...]
    commit_lane: int
    parent_lanes: tuple[int, ...]


class CommitGraphDelegate(QStyledItemDelegate):
    lane_width = 14

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        super().paint(painter, option, index)
        value = index.data(GRAPH_ROLE)
        if not isinstance(value, CommitGraphRow):
            return
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        top = float(option.rect.top())
        middle = float(option.rect.center().y())
        bottom = float(option.rect.bottom() + 1)

        for oid in set(value.lanes_before) & set(value.lanes_after):
            before = value.lanes_before.index(oid)
            after = value.lanes_after.index(oid)
            if before == value.commit_lane:
                continue
            painter.setPen(self._pen(option, before))
            painter.drawLine(
                QPointF(self._x(option, before), top),
                QPointF(self._x(option, after), bottom),
            )

        node_x = self._x(option, value.commit_lane)
        painter.setPen(self._pen(option, value.commit_lane))
        painter.drawLine(QPointF(node_x, top), QPointF(node_x, middle))
        for parent_lane in value.parent_lanes:
            painter.setPen(self._pen(option, parent_lane))
            painter.drawLine(
                QPointF(node_x, middle), QPointF(self._x(option, parent_lane), bottom)
            )

        color = self._color(option, value.commit_lane)
        painter.setPen(QPen(color, 1.5))
        painter.setBrush(color)
        painter.drawEllipse(QRectF(node_x - 3.5, middle - 3.5, 7.0, 7.0))
        painter.restore()

    def sizeHint(
        self, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex
    ) -> QSize:
        hint = super().sizeHint(option, index)
        value = index.data(GRAPH_ROLE)
        if isinstance(value, CommitGraphRow):
            lanes = max(len(value.lanes_before), len(value.lanes_after), 1)
            hint.setWidth(lanes * self.lane_width + 12)
        return hint

    def _x(self, option: QStyleOptionViewItem, lane: int) -> float:
        return float(option.rect.left() + 9 + lane * self.lane_width)

    def _pen(self, option: QStyleOptionViewItem, lane: int) -> QPen:
        return QPen(self._color(option, lane), 1.6)

    @staticmethod
    def _color(option: QStyleOptionViewItem, lane: int) -> QColor:
        colors = ("#2f81f7", "#d29922", "#3fb950", "#a371f7", "#f85149", "#39c5cf")
        color = QColor(colors[lane % len(colors)])
        if option.state & option.state.State_Selected:
            color = option.palette.highlightedText().color()
        return color
