from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, QSettings, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMenu, QToolButton
from pytest import MonkeyPatch
from pytestqt.qtbot import QtBot

from mygitclient.git.operation_queue import OperationQueueSnapshot, QueuedOperation
from mygitclient.git.service import GitService
from mygitclient.theme import Theme
from mygitclient.ui.main_window import MainWindow
from mygitclient.ui.operation_output import OperationOutputDialog


def test_queue_click_opens_live_log_and_keeps_it_available_after_completion(
    qtbot: QtBot, monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    settings = QSettings(str(tmp_path / "queue.ini"), QSettings.Format.IniFormat)
    window = MainWindow(settings, Theme.SYSTEM)
    qtbot.addWidget(window)
    window.resize(2200, 800)
    window.show()
    service = window.findChild(GitService)
    button = window.findChild(QToolButton, "queueButton")
    assert service is not None
    assert button is not None
    assert not button.isEnabled()
    cancelled: list[int] = []
    monkeypatch.setattr(service, "cancel_operation", cancelled.append)

    active = QueuedOperation(1, "fetch changes", tmp_path, "Fetching objects")
    pending = QueuedOperation(2, "push changes", tmp_path)
    service.queue_changed.emit(OperationQueueSnapshot(active, (pending,)))
    assert button.isEnabled()
    assert button.text().startswith("Queue 2")
    QTest.mouseClick(button, Qt.MouseButton.LeftButton, pos=QPoint(10, button.height() // 2))
    dialog = window.findChild(OperationOutputDialog)
    assert dialog is not None
    assert dialog.isVisible()
    assert dialog.property("operationId") == 1
    assert dialog.output.toPlainText() == "Fetching objects"
    assert cancelled == []

    updated = QueuedOperation(1, "fetch changes", tmp_path, "Fetching objects\nDone")
    service.queue_changed.emit(OperationQueueSnapshot(updated, (pending,)))
    assert dialog.output.toPlainText() == "Fetching objects\nDone"
    button.click()
    assert window.findChildren(OperationOutputDialog) == [dialog]
    dialog.close()

    service.queue_changed.emit(OperationQueueSnapshot(None, ()))
    assert button.isEnabled()
    assert button.text() == "Queue"
    button.click()
    visible = [item for item in window.findChildren(OperationOutputDialog) if item.isVisible()]
    assert len(visible) == 1
    assert visible[0].output.toPlainText() == "Fetching objects\nDone"
    assert cancelled == []
    window.close()


def test_queue_arrow_opens_menu_with_cancel_and_remove_actions(
    qtbot: QtBot, monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    settings = QSettings(str(tmp_path / "queue-menu.ini"), QSettings.Format.IniFormat)
    window = MainWindow(settings, Theme.SYSTEM)
    qtbot.addWidget(window)
    window.resize(2200, 800)
    window.show()
    service = window.findChild(GitService)
    button = window.findChild(QToolButton, "queueButton")
    assert service is not None
    assert button is not None
    cancelled: list[int] = []
    monkeypatch.setattr(service, "cancel_operation", cancelled.append)
    service.queue_changed.emit(OperationQueueSnapshot(
        QueuedOperation(1, "fetch changes", tmp_path),
        (QueuedOperation(2, "push changes", tmp_path),),
    ))
    assert button.popupMode() == QToolButton.ToolButtonPopupMode.MenuButtonPopup
    menu = button.menu()
    assert menu is not None
    shown: list[bool] = []
    menu.aboutToShow.connect(lambda: shown.append(True))
    QTimer.singleShot(100, menu.close)
    QTest.mouseClick(
        button, Qt.MouseButton.LeftButton, pos=QPoint(button.width() - 3, button.height() // 2)
    )
    qtbot.waitUntil(lambda: bool(shown))
    assert window.findChild(OperationOutputDialog) is None
    assert cancelled == []
    active_menu = menu.actions()[0].menu()
    pending_menu = menu.actions()[1].menu()
    assert isinstance(active_menu, QMenu)
    assert isinstance(pending_menu, QMenu)
    cancel = next(action for action in active_menu.actions() if action.text() == "Cancel operation")
    remove = next(
        action for action in pending_menu.actions() if action.text() == "Remove from queue"
    )
    cancel.trigger()
    remove.trigger()
    assert cancelled == [1, 2]
    window.close()
