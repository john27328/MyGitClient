from __future__ import annotations

from typing import cast

from PySide6.QtWidgets import QComboBox, QDialogButtonBox, QTreeWidgetItem
from pytestqt.qtbot import QtBot

from mygitclient.git.models import CommitSummary
from mygitclient.ui.interactive_rebase import InteractiveRebaseDialog


def _commit(oid: str, subject: str) -> CommitSummary:
    return CommitSummary(oid, (), "Test", "test@example.invalid", "", subject)


def test_interactive_rebase_dialog_validates_first_squash(qtbot: QtBot) -> None:
    dialog = InteractiveRebaseDialog((_commit("a" * 40, "one"), _commit("b" * 40, "two")))
    qtbot.addWidget(dialog)
    first = cast(QTreeWidgetItem, dialog.tree.topLevelItem(0))
    combo = dialog.tree.itemWidget(first, 0)
    assert isinstance(combo, QComboBox)
    combo.setCurrentText("squash")

    ok = dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)
    assert not ok.isEnabled()
    assert "cannot be squashed" in dialog.error.text()

    combo.setCurrentText("reword")
    first.setText(2, "renamed")
    assert ok.isEnabled()
    assert dialog.items()[0].subject == "renamed"
