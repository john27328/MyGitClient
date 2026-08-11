from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from mygitclient.github import GitHubProfile


class GitHubProfileDialog(QDialog):
    def __init__(
        self, profile: GitHubProfile | None = None, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("GitHub account profile")
        self.setObjectName("githubProfileDialog")

        self.label_edit = QLineEdit(profile.label if profile else "")
        self.label_edit.setObjectName("githubProfileLabelEdit")
        self.login_edit = QLineEdit(profile.login if profile else "")
        self.login_edit.setObjectName("githubProfileLoginEdit")
        self.transport_combo = QComboBox()
        self.transport_combo.setObjectName("githubProfileTransportCombo")
        self.transport_combo.addItem("HTTPS", "https")
        self.transport_combo.addItem("SSH", "ssh")
        if profile:
            self.transport_combo.setCurrentIndex(
                self.transport_combo.findData(profile.clone_transport)
            )
        self.name_edit = QLineEdit(profile.user_name if profile else "")
        self.name_edit.setObjectName("githubProfileUserNameEdit")
        self.email_edit = QLineEdit(profile.user_email if profile else "")
        self.email_edit.setObjectName("githubProfileUserEmailEdit")

        form = QFormLayout()
        form.addRow("Profile name:", self.label_edit)
        form.addRow("GitHub login:", self.login_edit)
        form.addRow("Clone using:", self.transport_combo)
        form.addRow("Commit name:", self.name_edit)
        form.addRow("Commit email:", self.email_edit)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept_profile)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def profile(self) -> GitHubProfile:
        transport = self.transport_combo.currentData()
        return GitHubProfile(
            self.label_edit.text().strip(),
            self.login_edit.text().strip(),
            transport if isinstance(transport, str) else "https",
            self.name_edit.text().strip(),
            self.email_edit.text().strip(),
        )

    def _accept_profile(self) -> None:
        try:
            self.profile()
        except ValueError as error:
            QMessageBox.warning(self, "Invalid GitHub profile", str(error))
            return
        self.accept()
