from __future__ import annotations

import secrets
from dataclasses import dataclass
from urllib.parse import parse_qs, urlencode, urlparse

from PySide6.QtCore import QByteArray, QObject, QTimer, QUrl, Signal, Slot
from PySide6.QtNetwork import (
    QHostAddress,
    QNetworkAccessManager,
    QNetworkReply,
    QNetworkRequest,
    QTcpServer,
    QTcpSocket,
)

from mygitclient.github.oauth_http import (
    OAuthHttpError,
    TokenResponse,
    json_request,
    parse_token_response,
    reply_payload,
)

_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
_ACCESS_TOKEN_URL = QUrl("https://github.com/login/oauth/access_token")
_USER_URL = QUrl("https://api.github.com/user")
_CALLBACK_TIMEOUT_MS = 5 * 60 * 1000


@dataclass(frozen=True, slots=True)
class SignInResult:
    login: str
    token: str
    refresh_token: str = ""
    expires_in: int = 0


class GitHubBrowserFlow(QObject):
    """Authorization Code flow via a loopback (127.0.0.1-only) redirect listener.

    GitHub's token exchange for this grant type requires the app's client secret. Each
    user registers their own OAuth App, so the secret they provide never leaves their
    machine and is stored the same way as the resulting access token.
    """

    authorization_url_ready = Signal(str)
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._network = QNetworkAccessManager(self)
        self._server = QTcpServer(self)
        self._server.newConnection.connect(self._accept_connection)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._on_timeout)
        self._reply: QNetworkReply | None = None
        self._client_id = ""
        self._client_secret = ""
        self._redirect_uri = ""
        self._state = ""
        self._granted: TokenResponse | None = None
        self._cancelled = False
        self._sockets: dict[QTcpSocket, bytes] = {}

    @property
    def is_running(self) -> bool:
        return self._server.isListening() or self._reply is not None

    def start(self, client_id: str, client_secret: str, *, scope: str = "repo read:user") -> None:
        self.cancel()
        self._cancelled = False
        self._client_id = client_id.strip()
        self._client_secret = client_secret.strip()
        if not self._client_id or not self._client_secret:
            self.failed.emit("GitHub OAuth client ID and client secret are required.")
            return
        if not self._server.listen(QHostAddress.SpecialAddress.LocalHost):
            self.failed.emit("Could not start a local listener for the GitHub sign-in redirect.")
            return
        self._state = secrets.token_urlsafe(24)
        self._redirect_uri = f"http://127.0.0.1:{self._server.serverPort()}/callback"
        query = urlencode(
            {
                "client_id": self._client_id,
                "redirect_uri": self._redirect_uri,
                "scope": scope,
                "state": self._state,
            }
        )
        self._timer.start(_CALLBACK_TIMEOUT_MS)
        self.authorization_url_ready.emit(f"{_AUTHORIZE_URL}?{query}")

    def cancel(self) -> None:
        self._cancelled = True
        self._timer.stop()
        if self._server.isListening():
            self._server.close()
        for socket in tuple(self._sockets):
            socket.abort()
            socket.deleteLater()
        self._sockets.clear()
        self._granted = None
        if self._reply is not None:
            self._reply.abort()
            self._reply.deleteLater()
            self._reply = None

    @Slot()
    def _accept_connection(self) -> None:
        socket = self._server.nextPendingConnection()
        if socket is None:  # pyright: ignore[reportUnnecessaryComparison]
            return
        self._sockets[socket] = b""
        socket.readyRead.connect(lambda: self._socket_ready(socket))
        socket.disconnected.connect(lambda: self._forget_socket(socket))

    def _forget_socket(self, socket: QTcpSocket) -> None:
        self._sockets.pop(socket, None)
        socket.deleteLater()

    def _socket_ready(self, socket: QTcpSocket) -> None:
        if socket not in self._sockets:
            return
        self._sockets[socket] += bytes(socket.readAll().data())
        if b"\r\n\r\n" not in self._sockets[socket]:
            return
        data = self._sockets.pop(socket)
        request_line = data.split(b"\r\n", 1)[0].decode("ascii", errors="replace")
        parts = request_line.split(" ")
        path = parts[1] if len(parts) >= 2 else ""
        code, error = parse_callback_query(path, self._state)
        self._respond(socket, success=error is None)
        if self._cancelled or not self._server.isListening():
            return
        self._server.close()
        self._timer.stop()
        if error is not None:
            self._fail(error)
            return
        assert code is not None
        self._exchange_code(code)

    def _respond(self, socket: QTcpSocket, *, success: bool) -> None:
        body = (
            b"<html><body style='font-family: sans-serif; text-align: center; "
            b"padding-top: 3em;'><h2>MyGitClient</h2>"
            + (
                b"<p>Signed in. You can close this tab.</p>"
                if success
                else b"<p>Sign-in was not completed. Return to MyGitClient and try again.</p>"
            )
            + b"</body></html>"
        )
        response = (
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: text/html; charset=utf-8\r\n"
            b"Content-Length: " + str(len(body)).encode("ascii") + b"\r\n"
            b"Connection: close\r\n\r\n" + body
        )
        socket.write(response)
        socket.flush()
        socket.disconnectFromHost()

    def _exchange_code(self, code: str) -> None:
        payload = urlencode(
            {
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "code": code,
                "redirect_uri": self._redirect_uri,
            }
        ).encode("ascii")
        request = json_request(_ACCESS_TOKEN_URL)
        request.setHeader(
            QNetworkRequest.KnownHeaders.ContentTypeHeader,
            "application/x-www-form-urlencoded",
        )
        reply = self._network.post(request, QByteArray(payload))
        self._reply = reply
        reply.finished.connect(self._token_finished)

    @Slot()
    def _token_finished(self) -> None:
        reply = self._take_reply()
        if reply is None:
            return
        try:
            payload = reply_payload(reply)
        except OAuthHttpError as error:
            self._fail(str(error))
            return
        finally:
            reply.deleteLater()
        granted = parse_token_response(payload)
        if not granted.access_token:
            description = payload.get("error_description") or payload.get("error")
            self._fail(f"GitHub authorization failed: {description or 'unknown response'}")
            return
        self._request_user(granted)

    def _request_user(self, granted: TokenResponse) -> None:
        request = json_request(_USER_URL)
        request.setRawHeader(
            b"Authorization", QByteArray(f"Bearer {granted.access_token}".encode("ascii"))
        )
        reply = self._network.get(request)
        self._granted = granted
        self._reply = reply
        reply.finished.connect(self._user_finished)

    @Slot()
    def _user_finished(self) -> None:
        reply = self._take_reply()
        if reply is None:
            return
        granted = self._granted
        self._granted = None
        try:
            payload = reply_payload(reply)
            login = payload.get("login")
            if not isinstance(login, str) or not login.strip():
                raise OAuthHttpError("GitHub did not return the authorized account login.")
        except OAuthHttpError as error:
            self._fail(str(error))
            return
        finally:
            reply.deleteLater()
        if granted is None:
            self._fail("GitHub authorization token was lost before it could be saved.")
            return
        self.completed.emit(
            SignInResult(
                login.strip(), granted.access_token, granted.refresh_token, granted.expires_in
            )
        )

    def _take_reply(self) -> QNetworkReply | None:
        reply = self._reply
        self._reply = None
        if self._cancelled:
            return None
        return reply

    def _on_timeout(self) -> None:
        if self._server.isListening():
            self._server.close()
        self._fail("Timed out waiting for the GitHub sign-in redirect. Try again.")

    def _fail(self, message: str) -> None:
        self._timer.stop()
        if not self._cancelled:
            self.failed.emit(message)


def parse_callback_query(path: str, expected_state: str) -> tuple[str | None, str | None]:
    """Extract the authorization code from a loopback redirect request path.

    Returns ``(code, None)`` on success or ``(None, error_message)`` otherwise.
    """
    query = parse_qs(urlparse(path).query)
    error = query.get("error", [None])[0]
    if error:
        description = query.get("error_description", [error])[0]
        return None, f"GitHub authorization failed: {description}"
    state = query.get("state", [None])[0]
    if not state or state != expected_state:
        return None, "GitHub sign-in response failed validation. Please try again."
    code = query.get("code", [None])[0]
    if not code:
        return None, "GitHub did not return an authorization code."
    return code, None
