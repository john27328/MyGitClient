from __future__ import annotations

from PySide6.QtWidgets import QMessageBox, QWidget

MAX_SUMMARY_LINES = 15
MAX_LINE_LENGTH = 200
MAX_SUMMARY_CHARS = 1_500


def shorten_message(message: str) -> str | None:
    """Return a screen-sized excerpt of ``message``, or ``None`` when it already fits."""

    lines = message.splitlines()
    if (
        len(lines) <= MAX_SUMMARY_LINES
        and len(message) <= MAX_SUMMARY_CHARS
        and all(len(line) <= MAX_LINE_LENGTH for line in lines)
    ):
        return None
    shown: list[str] = []
    length = 0
    for line in lines[:MAX_SUMMARY_LINES]:
        if len(line) > MAX_LINE_LENGTH:
            line = f"{line[: MAX_LINE_LENGTH - 1]}…"
        if shown and length + len(line) > MAX_SUMMARY_CHARS:
            break
        shown.append(line)
        length += len(line) + 1
    hidden = len(lines) - len(shown)
    note = f"… {hidden} more line(s)." if hidden > 0 else "…"
    return "\n".join([*shown, "", f"{note} Use Show Details for the full message."])


def show_message(
    parent: QWidget | None,
    icon: QMessageBox.Icon,
    title: str,
    message: str,
) -> None:
    """Show an error or warning without letting a long message outgrow the screen.

    Short messages keep the stock static dialogs; long ones show an excerpt and put the
    full text in the scrollable details area.
    """

    excerpt = shorten_message(message)
    if excerpt is None:
        if icon == QMessageBox.Icon.Critical:
            QMessageBox.critical(parent, title, message)
        else:
            QMessageBox.warning(parent, title, message)
        return
    box = QMessageBox(icon, title, excerpt, QMessageBox.StandardButton.Ok, parent)
    box.setObjectName("longMessageBox")
    box.setDetailedText(message)
    box.exec()
