from __future__ import annotations

from PySide6.QtCore import Qt, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class GitHubSignInDialog(QDialog):
    cancelled = Signal()
    browser_start_requested = Signal(str, str)

    def __init__(
        self,
        login: str | None = None,
        client_id: str = "",
        parent: QWidget | None = None,
        client_secret: str = "",
    ) -> None:
        super().__init__(parent)
        self.setObjectName("githubSignInDialog")
        self.setWindowTitle("Connect GitHub account")
        self.setModal(False)
        self.resize(560, 320)

        layout = QVBoxLayout(self)
        account = f"Reconnect <b>{login}</b>." if login else "Connect a GitHub account."
        self.instructions = QLabel(
            f"{account} One-time setup: create a GitHub OAuth App with a callback URL of "
            "<code>http://127.0.0.1/callback</code>, then paste its Client ID and Client "
            "Secret below. Both stay on this computer, and the secret is what lets the "
            "sign-in renew itself instead of expiring after a few hours."
        )
        self.instructions.setWordWrap(True)
        self.instructions.setTextFormat(Qt.TextFormat.RichText)
        self.instructions.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.instructions)

        setup_actions = QHBoxLayout()
        self.client_id = QLineEdit(client_id)
        self.client_id.setObjectName("githubOAuthClientId")
        self.client_id.setPlaceholderText("OAuth App Client ID")
        self.client_id.setClearButtonEnabled(True)
        self.setup_button = QPushButton("Open OAuth App settings")
        self.setup_button.setObjectName("githubOAuthSettingsButton")
        self.setup_button.clicked.connect(self._open_oauth_settings)
        setup_actions.addWidget(self.client_id, 1)
        setup_actions.addWidget(self.setup_button)
        layout.addLayout(setup_actions)

        self.client_secret = QLineEdit(client_secret)
        self.client_secret.setObjectName("githubOAuthClientSecret")
        self.client_secret.setPlaceholderText("OAuth App Client Secret")
        self.client_secret.setEchoMode(QLineEdit.EchoMode.Password)
        self.client_secret.setClearButtonEnabled(True)
        layout.addWidget(self.client_secret)

        self.browser_button = QPushButton("Sign in with your browser")
        self.browser_button.setObjectName("githubBrowserSignInButton")
        self.browser_button.clicked.connect(self._request_browser_sign_in)
        layout.addWidget(self.browser_button)
        layout.addStretch(1)

        self.client_id.textChanged.connect(self._credentials_changed)
        self.client_secret.textChanged.connect(self._credentials_changed)
        self._credentials_changed(client_id)

        self.status = QLabel("Enter the Client ID and Client Secret, then sign in.")
        self.status.setObjectName("githubSignInStatus")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def show_browser_pending(self, authorize_url: str) -> None:
        QDesktopServices.openUrl(QUrl(authorize_url))
        self.client_id.setEnabled(False)
        self.client_secret.setEnabled(False)
        self.setup_button.setEnabled(False)
        self.browser_button.setEnabled(False)
        self.status.setText("Waiting for you to finish signing in in your browser…")

    def show_error(self, message: str) -> None:
        self.status.setText(message)
        self.client_id.setEnabled(True)
        self.client_secret.setEnabled(True)
        self.setup_button.setEnabled(True)
        self._credentials_changed(self.client_id.text())

    @Slot()
    def _open_oauth_settings(self) -> None:
        QDesktopServices.openUrl(QUrl("https://github.com/settings/applications/new"))

    @Slot()
    def _request_browser_sign_in(self) -> None:
        client_id = self.client_id.text().strip()
        client_secret = self.client_secret.text().strip()
        if client_id and client_secret:
            self.status.setText("Opening your browser to sign in to GitHub…")
            self.browser_start_requested.emit(client_id, client_secret)

    @Slot(str)
    def _credentials_changed(self, _value: str) -> None:
        self.browser_button.setEnabled(
            bool(self.client_id.text().strip() and self.client_secret.text().strip())
        )

    def reject(self) -> None:
        self.cancelled.emit()
        super().reject()
