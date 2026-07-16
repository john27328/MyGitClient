from __future__ import annotations

from enum import StrEnum

from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication


class Theme(StrEnum):
    SYSTEM = "system"
    LIGHT = "light"
    DARK = "dark"

    @classmethod
    def from_value(cls, value: object) -> Theme:
        try:
            return cls(str(value))
        except ValueError:
            return cls.SYSTEM


def apply_theme(app: QApplication, theme: Theme) -> None:
    app.setStyle("Fusion")
    if theme is Theme.SYSTEM:
        app.setPalette(QPalette())
        app.setStyleSheet("")
        return

    app.setStyleSheet(_DARK_STYLESHEET if theme is Theme.DARK else _LIGHT_STYLESHEET)


_LIGHT_STYLESHEET = """
QMainWindow { background: #f5f6f8; }
QToolBar { border: 0; spacing: 6px; padding: 6px; }
QTreeWidget, QPlainTextEdit { background: #ffffff; border: 1px solid #d9dce1; }
"""

_DARK_STYLESHEET = """
QWidget { color: #e6e8eb; background: #202226; }
QMainWindow { background: #202226; }
QMenuBar, QMenu, QToolBar { background: #292c31; }
QTreeWidget, QPlainTextEdit { background: #181a1d; border: 1px solid #3b3f46; }
QPushButton { background: #343840; border: 1px solid #484d56; padding: 5px 10px; }
QPushButton:hover { background: #3c414a; }
"""

