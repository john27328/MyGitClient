from __future__ import annotations

from PySide6.QtCore import Slot
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)


class CommitMessageDialog(QDialog):
    """Edits a commit's subject and description."""

    def __init__(
        self,
        subject: str,
        description: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("commitMessageDialog")
        self.setWindowTitle("Edit commit message")
        self.subject_edit = QLineEdit(subject)
        self.subject_edit.setObjectName("commitMessageSubjectEdit")
        self.subject_edit.setPlaceholderText("Commit message")
        self.description_edit = QPlainTextEdit(description)
        self.description_edit.setObjectName("commitMessageDescriptionEdit")
        self.description_edit.setPlaceholderText("Description (optional)")
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Message"))
        layout.addWidget(self.subject_edit)
        layout.addWidget(QLabel("Description"))
        layout.addWidget(self.description_edit, 1)
        layout.addWidget(self.buttons)
        self.subject_edit.textChanged.connect(self._update_buttons)
        self._update_buttons()
        self.resize(640, 360)

    @property
    def subject(self) -> str:
        return self.subject_edit.text().strip()

    @property
    def description(self) -> str:
        return self.description_edit.toPlainText().strip()

    @Slot()
    def _update_buttons(self) -> None:
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(bool(self.subject))
