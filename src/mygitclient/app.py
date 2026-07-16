from __future__ import annotations

import logging
from collections.abc import Sequence

from PySide6.QtCore import QCoreApplication, QSettings
from PySide6.QtWidgets import QApplication

from mygitclient.logging_config import configure_logging
from mygitclient.theme import Theme, apply_theme
from mygitclient.ui.main_window import MainWindow


def create_application(arguments: Sequence[str]) -> tuple[QApplication, MainWindow]:
    QCoreApplication.setOrganizationName("MyGitClient")
    QCoreApplication.setApplicationName("MyGitClient")
    QCoreApplication.setApplicationVersion("0.1.0")

    configure_logging()
    logging.getLogger(__name__).info("Starting MyGitClient")

    app = QApplication(list(arguments))
    app.setApplicationDisplayName("MyGitClient")

    settings = QSettings()
    theme = Theme.from_value(settings.value("appearance/theme", Theme.SYSTEM.value))
    apply_theme(app, theme)

    window = MainWindow(settings=settings, theme=theme)
    return app, window

