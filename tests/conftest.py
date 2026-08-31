from __future__ import annotations

from collections.abc import Iterator

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication


@pytest.fixture(autouse=True)
def dispose_top_level_widgets_after_qt_test(request: pytest.FixtureRequest) -> Iterator[None]:
    """Leave no Qt windows or deferred deletions for the next UI test."""
    yield

    if "qtbot" not in request.fixturenames and "qapp" not in request.fixturenames:
        return

    application = QCoreApplication.instance()
    if not isinstance(application, QApplication):
        return

    for widget in tuple(application.topLevelWidgets()):
        widget.close()
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
