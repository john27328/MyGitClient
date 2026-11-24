from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from weakref import WeakMethod, ref

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
        # The widget owns this QObject. Holding the widget or its controller's
        # bound methods here would form a Python cycle, delaying QWidget deletion
        # until cyclic GC (which can run inside a Qt paint callback).
        self._widget = ref(widget)
        self._reveal = WeakMethod(reveal)
        self._has_file = WeakMethod(has_file)
        widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        widget.customContextMenuRequested.connect(self._show_menu)

    @Slot(QPoint)
    def _show_menu(self, position: QPoint) -> None:
        widget = self._widget()
        reveal = self._reveal()
        has_file = self._has_file()
        if widget is None or reveal is None or has_file is None:
            return
        menu = (
            widget.createStandardContextMenu()
            if isinstance(widget, QPlainTextEdit) else QMenu(widget)
        )
        if menu.actions():
            menu.addSeparator()
        action = menu.addAction("Show in File Manager")
        action.setObjectName("revealFileAction")
        action.setEnabled(has_file())
        action.triggered.connect(reveal)
        source = widget.viewport() if isinstance(widget, QPlainTextEdit) else widget
        try:
            menu.exec(source.mapToGlobal(position))
        finally:
            menu.deleteLater()
