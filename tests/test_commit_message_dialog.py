from __future__ import annotations

from PySide6.QtWidgets import QDialogButtonBox
from pytestqt.qtbot import QtBot

from mygitclient.ui.commit_message_dialog import CommitMessageDialog


def test_commit_message_dialog_prefills_and_requires_a_subject(qtbot: QtBot) -> None:
    dialog = CommitMessageDialog("Fix crash", "Explain why.")
    qtbot.addWidget(dialog)
    ok = dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)

    assert dialog.subject == "Fix crash"
    assert dialog.description == "Explain why."
    assert ok.isEnabled()

    dialog.subject_edit.setText("   ")

    assert not ok.isEnabled()
