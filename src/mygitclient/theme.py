from __future__ import annotations

from enum import StrEnum
from importlib.resources import files

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

_system_style_name: str | None = None
_system_palette: QPalette | None = None


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
    global _system_palette, _system_style_name
    if _system_style_name is None:
        _system_style_name = app.style().objectName()
        _system_palette = QPalette(app.palette())

    if theme is Theme.SYSTEM:
        app.setStyleSheet("")
        if _system_style_name:
            app.setStyle(_system_style_name)
        if _system_palette is not None:
            app.setPalette(_system_palette)
        return

    app.setStyle("Fusion")
    if theme is Theme.DARK:
        app.setPalette(_dark_palette())
    elif _system_palette is not None:
        app.setPalette(_system_palette)
    app.setStyleSheet(_dark_stylesheet() if theme is Theme.DARK else _LIGHT_STYLESHEET)


def _dark_palette() -> QPalette:
    palette = QPalette()
    colors = {
        QPalette.ColorRole.Window: "#202226",
        QPalette.ColorRole.WindowText: "#e6e8eb",
        QPalette.ColorRole.Base: "#181a1d",
        QPalette.ColorRole.AlternateBase: "#24272c",
        QPalette.ColorRole.Text: "#e6e8eb",
        QPalette.ColorRole.Button: "#343840",
        QPalette.ColorRole.ButtonText: "#e6e8eb",
        QPalette.ColorRole.Highlight: "#2f80ed",
        QPalette.ColorRole.HighlightedText: "#ffffff",
        QPalette.ColorRole.Mid: "#7d8794",
        QPalette.ColorRole.Midlight: "#484d56",
        QPalette.ColorRole.PlaceholderText: "#9aa3ad",
    }
    for role, color in colors.items():
        palette.setColor(role, QColor(color))
    return palette


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


def _dark_stylesheet() -> str:
    icons = files("mygitclient.resources").joinpath("icons")
    checked = str(icons.joinpath("checkbox-checked.svg")).replace("\\", "/")
    partial = str(icons.joinpath("checkbox-partial.svg")).replace("\\", "/")
    indicators = f"""
QTreeWidget::indicator, QCheckBox::indicator {{
    width: 15px; height: 15px; border: 1px solid #7d8794;
    border-radius: 3px; background: #24272c;
}}
QTreeWidget::indicator:hover, QCheckBox::indicator:hover {{ border-color: #9fc5ff; }}
QTreeWidget::indicator:checked, QCheckBox::indicator:checked {{
    background: #2f80ed; border-color: #78b0ff; image: url("{checked}");
}}
QTreeWidget::indicator:indeterminate, QCheckBox::indicator:indeterminate {{
    background: #2f80ed; border-color: #78b0ff; image: url("{partial}");
}}
QTreeWidget::indicator:disabled, QCheckBox::indicator:disabled {{
    border-color: #4b515b; background: #202226;
}}
"""
    return _DARK_STYLESHEET + indicators
