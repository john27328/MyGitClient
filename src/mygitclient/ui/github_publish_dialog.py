from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QWidget,
)

from mygitclient.github import GitHubProfile


class GitHubPublishDialog(QDialog):
    def __init__(
        self,
        profiles: tuple[GitHubProfile, ...],
        default_profile: str,
        repository_name: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Publish to GitHub")
        self.setObjectName("githubPublishDialog")
        layout = QFormLayout(self)
        self.profile = QComboBox()
        self.profile.setObjectName("githubPublishProfileCombo")
        for profile in profiles:
            self.profile.addItem(f"{profile.label} ({profile.login})", profile.label)
        selected = self.profile.findData(default_profile)
        if selected >= 0:
            self.profile.setCurrentIndex(selected)
        self.name = QLineEdit(repository_name)
        self.name.setObjectName("githubPublishNameEdit")
        self.visibility = QComboBox()
        self.visibility.setObjectName("githubPublishVisibilityCombo")
        self.visibility.addItem("Private", True)
        self.visibility.addItem("Public", False)
        layout.addRow("GitHub account:", self.profile)
        layout.addRow("Repository name:", self.name)
        layout.addRow("Visibility:", self.visibility)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    @property
    def profile_label(self) -> str:
        value = self.profile.currentData()
        return value if isinstance(value, str) else ""

    @property
    def repository_name(self) -> str:
        return self.name.text().strip()

    @property
    def private(self) -> bool:
        return self.visibility.currentData() is True

    def accept(self) -> None:
        if not self.repository_name:
            self.name.setFocus()
            return
        super().accept()
