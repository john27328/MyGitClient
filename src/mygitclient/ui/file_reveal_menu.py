from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, QPoint, Qt, Slot
from PySide6.QtWidgets import QMenu, QPlainTextEdit, QWidget


def nearest_existing_path(path: Path) -> Path | None:
    return next((candidate for candidate in (path, *path.parents) if candidate.exists()), None)


class FileRevealMenu(QObject):
    """Add file navigation while keeping the editor's standard text actions."""

    def __init__(
        self, widget: QWidget, *, reveal: Callable[[], None], has_file: Callable[[], bool]
    ) -> None:
        super().__init__(widget)
        self._widget = widget
        self._reveal = reveal
        self._has_file = has_file
        widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        widget.customContextMenuRequested.connect(self._show_menu)

    @Slot(QPoint)
    def _show_menu(self, position: QPoint) -> None:
        widget = self._widget
        menu = (
            widget.createStandardContextMenu()
            if isinstance(widget, QPlainTextEdit) else QMenu(widget)
        )
        if menu.actions():
            menu.addSeparator()
        action = menu.addAction("Show in File Manager")
        action.setObjectName("revealFileAction")
        action.setEnabled(self._has_file())
        action.triggered.connect(self._reveal)
        source = widget.viewport() if isinstance(widget, QPlainTextEdit) else widget
        try:
            menu.exec(source.mapToGlobal(position))
        finally:
            menu.deleteLater()
