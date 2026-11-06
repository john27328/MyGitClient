from __future__ import annotations

from PySide6.QtWidgets import QMessageBox, QWidget
from pytest import MonkeyPatch
from pytestqt.qtbot import QtBot

from mygitclient.ui.message_boxes import (
    MAX_LINE_LENGTH,
    MAX_SUMMARY_CHARS,
    MAX_SUMMARY_LINES,
    shorten_message,
    show_message,
)


def test_short_messages_are_not_shortened() -> None:
    assert shorten_message("Checkout failed.\n\nCommit or stash your changes.") is None


def test_many_lines_are_cut_and_counted() -> None:
    message = "\n".join(["Affected files:", *(f"• file{index}.cs" for index in range(500))])

    excerpt = shorten_message(message)

    assert excerpt is not None
    lines = excerpt.splitlines()
    assert lines[:MAX_SUMMARY_LINES] == message.splitlines()[:MAX_SUMMARY_LINES]
    assert f"… {501 - MAX_SUMMARY_LINES} more line(s)." in lines[-1]
    assert len(excerpt) < MAX_SUMMARY_CHARS + 200


def test_very_long_line_is_truncated() -> None:
    excerpt = shorten_message("x" * 10_000)

    assert excerpt is not None
    first = excerpt.splitlines()[0]
    assert len(first) == MAX_LINE_LENGTH
    assert first.endswith("…")


def test_long_message_keeps_full_text_in_details(qtbot: QtBot, monkeypatch: MonkeyPatch) -> None:
    parent = QWidget()
    qtbot.addWidget(parent)
    shown: list[QMessageBox] = []

    def capture(box: QMessageBox) -> int:
        shown.append(box)
        return int(QMessageBox.StandardButton.Ok.value)

    monkeypatch.setattr(QMessageBox, "exec", capture)
    message = "\n".join(f"line {index}" for index in range(100))

    show_message(parent, QMessageBox.Icon.Critical, "Git error", message)

    assert len(shown) == 1
    box = shown[0]
    assert box.detailedText() == message
    assert box.text().count("\n") < 20
    assert box.icon() == QMessageBox.Icon.Critical


def test_short_message_uses_the_static_dialog(monkeypatch: MonkeyPatch) -> None:
    calls: list[str] = []

    def warning(_parent: QWidget | None, title: str, text: str) -> None:
        calls.append(f"{title}: {text}")

    monkeypatch.setattr(QMessageBox, "warning", warning)

    show_message(None, QMessageBox.Icon.Warning, "Clone failed", "Network unreachable")

    assert calls == ["Clone failed: Network unreachable"]
