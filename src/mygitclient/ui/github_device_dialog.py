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
    QVBoxLayout,
    QWidget,
)

from mygitclient.github.device_flow import DeviceAuthorization


class GitHubDeviceDialog(QDialog):
    cancelled = Signal()
    start_requested = Signal(str)

    def __init__(
        self, login: str | None = None, client_id: str = "", parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._verification_uri = "https://github.com/login/device"
        self.setObjectName("githubDeviceDialog")
        self.setWindowTitle("Connect GitHub account")
        self.setModal(False)
        self.resize(540, 330)

        layout = QVBoxLayout(self)
        account = f"Reconnect <b>{login}</b>." if login else "Connect a GitHub account."
        self.instructions = QLabel(
            f"{account} No additional software or browser sign-in on this computer is required."
            "<br><br>One-time setup: create a GitHub OAuth App, enable <b>Device Flow</b>, "
            "then paste its Client ID below. A client secret is not needed. You can authorize "
            "the code on this or another device."
        )
        self.instructions.setWordWrap(True)
        self.instructions.setTextFormat(Qt.TextFormat.RichText)
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

        self.request_button = QPushButton("Request authorization code")
        self.request_button.setObjectName("githubDeviceRequestButton")
        self.request_button.setEnabled(bool(client_id.strip()))
        self.client_id.textChanged.connect(self._client_id_changed)
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

        self.status = QLabel("Enter the Client ID and request an authorization code.")
        self.status.setObjectName("githubDeviceStatus")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def show_authorization(self, authorization: DeviceAuthorization) -> None:
        self._verification_uri = authorization.verification_uri
        self.code.setText(authorization.user_code)
        self.copy_button.setEnabled(True)
        self.open_button.setEnabled(True)
        self.client_id.setEnabled(False)
        self.setup_button.setEnabled(False)
        self.request_button.setEnabled(False)
        self.status.setText("Waiting for authorization in GitHub…")

    def show_error(self, message: str) -> None:
        self.status.setText(message)

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

    @Slot(str)
    def _client_id_changed(self, value: str) -> None:
        self.request_button.setEnabled(bool(value.strip()))

    def reject(self) -> None:
        self.cancelled.emit()
        super().reject()
