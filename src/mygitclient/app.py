from __future__ import annotations

import logging
import sys
from collections.abc import Sequence

from PySide6.QtCore import QCoreApplication, QSettings
from PySide6.QtWidgets import QApplication

from mygitclient import __version__
from mygitclient.logging_config import configure_logging
from mygitclient.resources import load_icon
from mygitclient.theme import Theme, apply_theme
from mygitclient.ui.main_window import MainWindow


def create_application(arguments: Sequence[str]) -> tuple[QApplication, MainWindow]:
    _set_windows_app_id()
    QCoreApplication.setOrganizationName("MyGitClient")
    QCoreApplication.setApplicationName("MyGitClient")
    QCoreApplication.setApplicationVersion(__version__)

    configure_logging()
    logging.getLogger(__name__).info("Starting MyGitClient")

    app = QApplication(list(arguments))
    app.setApplicationDisplayName("MyGitClient")
    app.setWindowIcon(load_icon("app-icon.png"))

    settings = QSettings()
    theme = Theme.from_value(settings.value("appearance/theme", Theme.SYSTEM.value))
    apply_theme(app, theme)

    window = MainWindow(settings=settings, theme=theme)
    return app, window


def _set_windows_app_id() -> None:
    if sys.platform != "win32":
        return
    from ctypes import HRESULT, WINFUNCTYPE, WinDLL, c_wchar_p

    shell32 = WinDLL("shell32")
    set_app_id = WINFUNCTYPE(HRESULT, c_wchar_p)(
        ("SetCurrentProcessExplicitAppUserModelID", shell32)
    )
    set_app_id("MyGitClient.MyGitClient")
