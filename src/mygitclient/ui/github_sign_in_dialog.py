from __future__ import annotations

from PySide6.QtCore import Qt, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


class GitHubSignInDialog(QDialog):
    cancelled = Signal()
    browser_start_requested = Signal(str, str)
    credential_start_requested = Signal()

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
            f"{account} Sign in in your browser and confirm access on GitHub. "
            "Your account will be connected automatically when you finish."
        )
        self.instructions.setWordWrap(True)
        self.instructions.setTextFormat(Qt.TextFormat.RichText)
        self.instructions.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.instructions)

        self.browser_button = QPushButton("Sign in with your browser")
        self.browser_button.setObjectName("githubBrowserSignInButton")
        self.browser_button.setDefault(True)
        self.browser_button.clicked.connect(self.credential_start_requested)
        layout.addWidget(self.browser_button)
        self.install_button = QPushButton("Install Git Credential Manager")
        self.install_button.setObjectName("githubInstallCredentialManagerButton")
        self.install_button.clicked.connect(self._open_credential_manager_setup)
        self.install_button.hide()
        layout.addWidget(self.install_button)
        self.advanced_toggle = QToolButton()
        self.advanced_toggle.setText("Advanced sign-in settings")
        self.advanced_toggle.setObjectName("githubAdvancedSignInButton")
        self.advanced_toggle.setCheckable(True)
        layout.addWidget(self.advanced_toggle)
        self.advanced = QWidget()
        self.advanced.setObjectName("githubAdvancedSignInSettings")
        advanced_layout = QVBoxLayout(self.advanced)
        advanced_layout.setContentsMargins(0, 0, 0, 0)
        setup_note = QLabel(
            "Use your own OAuth app instead of Git Credential Manager. "
            "Set its callback URL to http://127.0.0.1/callback."
        )
        setup_note.setWordWrap(True)
        advanced_layout.addWidget(setup_note)
        self.advanced.hide()
        self.advanced_toggle.toggled.connect(self._toggle_advanced)
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
        advanced_layout.addLayout(setup_actions)

        self.client_secret = QLineEdit(client_secret)
        self.client_secret.setObjectName("githubOAuthClientSecret")
        self.client_secret.setPlaceholderText("OAuth App Client Secret")
        self.client_secret.setEchoMode(QLineEdit.EchoMode.Password)
        self.client_secret.setClearButtonEnabled(True)
        advanced_layout.addWidget(self.client_secret)

        self.oauth_button = QPushButton("Sign in using this OAuth app")
        self.oauth_button.setObjectName("githubCustomOAuthSignInButton")
        self.oauth_button.clicked.connect(self._request_browser_sign_in)
        advanced_layout.addWidget(self.oauth_button)
        layout.addWidget(self.advanced)
        layout.addStretch(1)

        self.client_id.textChanged.connect(self._credentials_changed)
        self.client_secret.textChanged.connect(self._credentials_changed)
        self._credentials_changed(client_id)

        self.progress = QProgressBar()
        self.progress.setObjectName("githubSignInProgress")
        self.progress.setRange(0, 0)
        self.progress.hide()
        layout.addWidget(self.progress)
        self.status = QLabel("Ready to sign in. Git Credential Manager opens your browser.")
        self.status.setObjectName("githubSignInStatus")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def show_browser_pending(self, authorize_url: str) -> bool:
        self.show_pending("Waiting for you to finish signing in in your browser…")
        opened = QDesktopServices.openUrl(QUrl(authorize_url))
        if not opened:
            self.show_error("Could not open your browser. Check your default browser and retry.")
        return opened

    def show_pending(self, message: str) -> None:
        self.install_button.hide()
        self.client_id.setEnabled(False)
        self.client_secret.setEnabled(False)
        self.setup_button.setEnabled(False)
        self.browser_button.setEnabled(False)
        self.oauth_button.setEnabled(False)
        self.advanced_toggle.setEnabled(False)
        self.progress.show()
        self.status.setText(message)

    def show_error(self, message: str) -> None:
        self.status.setText(message)
        self.client_id.setEnabled(True)
        self.client_secret.setEnabled(True)
        self.setup_button.setEnabled(True)
        self.browser_button.setEnabled(True)
        self.advanced_toggle.setEnabled(True)
        self.progress.hide()
        self.install_button.setVisible("Git Credential Manager was not found" in message)
        self._credentials_changed(self.client_id.text())

    @Slot(bool)
    def _toggle_advanced(self, visible: bool) -> None:
        self.advanced.setVisible(visible)
        self.oauth_button.setDefault(visible)
        self.browser_button.setDefault(not visible)

    @Slot()
    def _open_credential_manager_setup(self) -> None:
        QDesktopServices.openUrl(QUrl(
            "https://github.com/git-ecosystem/git-credential-manager/blob/main/docs/install.md"
        ))

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
        self.oauth_button.setEnabled(
            bool(self.client_id.text().strip() and self.client_secret.text().strip())
        )

    def reject(self) -> None:
        self.cancelled.emit()
        super().reject()
