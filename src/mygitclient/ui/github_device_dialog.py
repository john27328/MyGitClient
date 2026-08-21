from __future__ import annotations

from PySide6.QtCore import Qt, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from mygitclient.github.device_flow import DeviceAuthorization


class GitHubDeviceDialog(QDialog):
    cancelled = Signal()
    start_requested = Signal(str)
    browser_start_requested = Signal(str, str)

    def __init__(
        self,
        login: str | None = None,
        client_id: str = "",
        parent: QWidget | None = None,
        client_secret: str = "",
    ) -> None:
        super().__init__(parent)
        self._initial_client_secret = client_secret
        self._verification_uri = "https://github.com/login/device"
        self.setObjectName("githubDeviceDialog")
        self.setWindowTitle("Connect GitHub account")
        self.setModal(False)
        self.resize(560, 400)

        layout = QVBoxLayout(self)
        account = f"Reconnect <b>{login}</b>." if login else "Connect a GitHub account."
        self.instructions = QLabel(
            f"{account} One-time setup: create a GitHub OAuth App, then paste its Client ID "
            "below.<br>Enable <b>Device Flow</b> to sign in with a code, or add a callback URL "
            "of <code>http://127.0.0.1/callback</code> and a Client Secret to sign in with your "
            "browser."
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

        tabs = QTabWidget()
        tabs.setObjectName("githubSignInTabs")
        tabs.addTab(self._build_browser_tab(), "Sign in with your browser")
        tabs.addTab(self._build_code_tab(), "Sign in with a code")
        layout.addWidget(tabs, 1)

        self.client_id.textChanged.connect(self._client_id_changed)
        self.client_secret.textChanged.connect(self._client_id_changed)
        self._client_id_changed(client_id)

        self.status = QLabel("Enter the Client ID, then choose how to sign in.")
        self.status.setObjectName("githubDeviceStatus")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _build_browser_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self.client_secret = QLineEdit(self._initial_client_secret)
        self.client_secret.setObjectName("githubOAuthClientSecret")
        self.client_secret.setPlaceholderText("OAuth App Client Secret")
        self.client_secret.setEchoMode(QLineEdit.EchoMode.Password)
        self.client_secret.setClearButtonEnabled(True)
        layout.addWidget(self.client_secret)
        self.browser_button = QPushButton("Sign in with your browser")
        self.browser_button.setObjectName("githubBrowserSignInButton")
        self.browser_button.setEnabled(False)
        self.browser_button.clicked.connect(self._request_browser_sign_in)
        layout.addWidget(self.browser_button)
        layout.addStretch(1)
        return tab

    def _build_code_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self.request_button = QPushButton("Request authorization code")
        self.request_button.setObjectName("githubDeviceRequestButton")
        self.request_button.clicked.connect(self._request_code)
        layout.addWidget(self.request_button)

        self.code = QLineEdit()
        self.code.setObjectName("githubDeviceUserCode")
        self.code.setReadOnly(True)
        self.code.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.code.setPlaceholderText("Requesting a code…")
        layout.addWidget(self.code)

        actions = QHBoxLayout()
        self.copy_button = QPushButton("Copy code")
        self.copy_button.setObjectName("githubDeviceCopyButton")
        self.copy_button.setEnabled(False)
        self.copy_button.clicked.connect(self._copy_code)
        self.open_button = QPushButton("Open GitHub")
        self.open_button.setObjectName("githubDeviceOpenButton")
        self.open_button.setEnabled(False)
        self.open_button.clicked.connect(self._open_github)
        actions.addWidget(self.copy_button)
        actions.addWidget(self.open_button)
        actions.addStretch(1)
        layout.addLayout(actions)
        layout.addStretch(1)
        return tab

    def show_authorization(self, authorization: DeviceAuthorization) -> None:
        self._verification_uri = authorization.verification_uri
        self.code.setText(authorization.user_code)
        self.copy_button.setEnabled(True)
        self.open_button.setEnabled(True)
        self._lock_inputs()
        self.status.setText("Waiting for authorization in GitHub…")

    def show_browser_pending(self, authorize_url: str) -> None:
        self._verification_uri = authorize_url
        QDesktopServices.openUrl(QUrl(authorize_url))
        self._lock_inputs()
        self.status.setText("Waiting for you to finish signing in in your browser…")

    def show_error(self, message: str) -> None:
        self.status.setText(message)
        self.client_id.setEnabled(True)
        self.client_secret.setEnabled(True)
        self.setup_button.setEnabled(True)
        self._client_id_changed(self.client_id.text())

    def _lock_inputs(self) -> None:
        self.client_id.setEnabled(False)
        self.client_secret.setEnabled(False)
        self.setup_button.setEnabled(False)
        self.request_button.setEnabled(False)
        self.browser_button.setEnabled(False)

    @Slot()
    def _copy_code(self) -> None:
        clipboard = QApplication.clipboard()
        clipboard.setText(self.code.text())

    @Slot()
    def _open_github(self) -> None:
        QDesktopServices.openUrl(QUrl(self._verification_uri))

    @Slot()
    def _open_oauth_settings(self) -> None:
        QDesktopServices.openUrl(QUrl("https://github.com/settings/applications/new"))

    @Slot()
    def _request_code(self) -> None:
        client_id = self.client_id.text().strip()
        if client_id:
            self.status.setText("Requesting an authorization code from GitHub…")
            self.start_requested.emit(client_id)

    @Slot()
    def _request_browser_sign_in(self) -> None:
        client_id = self.client_id.text().strip()
        client_secret = self.client_secret.text().strip()
        if client_id and client_secret:
            self.status.setText("Opening your browser to sign in to GitHub…")
            self.browser_start_requested.emit(client_id, client_secret)

    @Slot(str)
    def _client_id_changed(self, _value: str) -> None:
        has_id = bool(self.client_id.text().strip())
        self.request_button.setEnabled(has_id)
        self.browser_button.setEnabled(has_id and bool(self.client_secret.text().strip()))

    def reject(self) -> None:
        self.cancelled.emit()
        super().reject()
