from __future__ import annotations

from collections.abc import Iterator

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication


@pytest.fixture(autouse=True)
def dispose_top_level_widgets_after_qt_test(qapp: QApplication) -> Iterator[None]:
    """Give every test a QApplication and leave no Qt state for the next one."""
    yield

    for widget in tuple(qapp.topLevelWidgets()):
        widget.close()
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
