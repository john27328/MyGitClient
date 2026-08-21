from __future__ import annotations

from urllib.parse import urlencode

from PySide6.QtCore import QByteArray, QObject, QUrl, Signal, Slot
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from mygitclient.github.oauth_http import (
    OAuthHttpError,
    json_request,
    parse_token_response,
    reply_payload,
)
from mygitclient.github.tokens import stored_token

_ACCESS_TOKEN_URL = QUrl("https://github.com/login/oauth/access_token")


class GitHubTokenRefresher(QObject):
    """Exchanges a refresh token for a fresh access token.

    OAuth Apps that expire user authorization tokens hand out access tokens that last
    eight hours, so without this the account has to be reconnected by hand every day.
    GitHub requires the app's client secret for this exchange, which is why connecting
    through the browser stores it.
    """

    refreshed = Signal(str, object)
    failed = Signal(str, str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._network = QNetworkAccessManager(self)
        self._logins: dict[QNetworkReply, str] = {}

    def refresh(
        self, login: str, refresh_token: str, client_id: str, client_secret: str
    ) -> bool:
        """Start a renewal, returning whether every credential it needs was present."""
        if not (login.strip() and refresh_token and client_id.strip() and client_secret.strip()):
            return False
        payload = urlencode(
            {
                "client_id": client_id.strip(),
                "client_secret": client_secret.strip(),
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            }
        ).encode("ascii")
        request = json_request(_ACCESS_TOKEN_URL)
        request.setHeader(
            QNetworkRequest.KnownHeaders.ContentTypeHeader,
            "application/x-www-form-urlencoded",
        )
        reply = self._network.post(request, QByteArray(payload))
        self._logins[reply] = login.strip()
        reply.finished.connect(self._finished)
        return True

    @Slot()
    def _finished(self) -> None:
        reply = self.sender()
        if not isinstance(reply, QNetworkReply):
            return
        login = self._logins.pop(reply, None)
        try:
            payload = reply_payload(reply)
        except OAuthHttpError as error:
            if login is not None:
                self.failed.emit(login, str(error))
            return
        finally:
            reply.deleteLater()
        if login is None:
            return
        granted = parse_token_response(payload)
        if not granted.access_token:
            self.failed.emit(
                login,
                "GitHub could not renew the sign-in for this account. "
                "Reconnect it to continue.",
            )
            return
        self.refreshed.emit(
            login,
            stored_token(granted.access_token, granted.refresh_token, granted.expires_in),
        )
