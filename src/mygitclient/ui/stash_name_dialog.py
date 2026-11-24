from __future__ import annotations

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QLineEdit, QVBoxLayout, QWidget

from mygitclient.git.stashes import DEFAULT_STASH_MESSAGE, validate_stash_message


class StashNameDialog(QDialog):
    def __init__(self, parent: QWidget, *, current_name: str | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("stashNameDialog")
        self.setWindowTitle("Rename stash" if current_name is not None else "Stash selected files")
        self.resize(440, 140)
        self.name_edit = QLineEdit()
        self.name_edit.setObjectName("stashNameEdit")
        self.name_edit.setPlaceholderText(current_name or DEFAULT_STASH_MESSAGE)
        if current_name is not None:
            self.name_edit.setText(current_name)
            self.name_edit.selectAll()
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Stash name:"))
        layout.addWidget(self.name_edit)
        if current_name is not None:
            note = QLabel("The renamed stash will move to the top of the list.")
            note.setWordWrap(True)
            layout.addWidget(note)
        layout.addWidget(buttons)
        self.name_edit.setFocus()

    def accept(self) -> None:
        try:
            validate_stash_message(self.stash_name)
        except ValueError:
            self.name_edit.setFocus()
            return
        super().accept()

    @property
    def stash_name(self) -> str:
        return self.name_edit.text().strip() or self.name_edit.placeholderText()
