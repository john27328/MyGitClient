from __future__ import annotations

from importlib.resources import files

from PySide6.QtGui import QIcon


def load_icon(name: str) -> QIcon:
    path = files("mygitclient.resources").joinpath("icons", name)
    return QIcon(str(path))


__all__ = ["load_icon"]
