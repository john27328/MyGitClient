from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlencode

from PySide6.QtCore import QByteArray, QObject, QTimer, QUrl, Signal, Slot
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from mygitclient.github.oauth_http import OAuthHttpError, json_request, reply_payload

_DEVICE_CODE_URL = QUrl("https://github.com/login/device/code")
_ACCESS_TOKEN_URL = QUrl("https://github.com/login/oauth/access_token")
_USER_URL = QUrl("https://api.github.com/user")
_GRANT_TYPE = "urn:ietf:params:oauth:grant-type:device_code"


@dataclass(frozen=True, slots=True)
class DeviceAuthorization:
    device_code: str
    user_code: str
    verification_uri: str
    expires_in: int
    interval: int


@dataclass(frozen=True, slots=True)
class DeviceFlowResult:
    login: str
    token: str


class GitHubDeviceFlow(QObject):
    code_received = Signal(object)
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._network = QNetworkAccessManager(self)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._poll)
        self._reply: QNetworkReply | None = None
        self._client_id = ""
        self._authorization: DeviceAuthorization | None = None
        self._deadline = 0.0
        self._cancelled = False

    @property
    def is_running(self) -> bool:
        return self._reply is not None or self._timer.isActive()

    def start(self, client_id: str, *, scope: str = "repo read:user") -> None:
        self.cancel()
        self._cancelled = False
        self._client_id = client_id.strip()
        if not self._client_id:
            self.failed.emit("GitHub OAuth client ID is required.")
            return
        payload = urlencode({"client_id": self._client_id, "scope": scope}).encode("ascii")
        self._post(_DEVICE_CODE_URL, payload, self._device_code_finished)

    def cancel(self) -> None:
        self._cancelled = True
        self._timer.stop()
        if self._reply is not None:
            self._reply.abort()
            self._reply.deleteLater()
            self._reply = None
        self._authorization = None

    def _post(self, url: QUrl, payload: bytes, handler: Callable[[], None]) -> None:
        request = json_request(url)
        request.setHeader(
            QNetworkRequest.KnownHeaders.ContentTypeHeader,
            "application/x-www-form-urlencoded",
        )
        reply = self._network.post(request, QByteArray(payload))
        self._reply = reply
        reply.finished.connect(handler)

    @Slot()
    def _device_code_finished(self) -> None:
        reply = self._take_reply()
        if reply is None:
            return
        try:
            payload = reply_payload(reply)
            authorization = parse_device_authorization(payload)
        except OAuthHttpError as error:
            self._fail(str(error))
            return
        finally:
            reply.deleteLater()
        self._authorization = authorization
        self._deadline = time.monotonic() + authorization.expires_in
        self.code_received.emit(authorization)
        self._schedule_poll(authorization.interval)

    @Slot()
    def _poll(self) -> None:
        authorization = self._authorization
        if authorization is None or self._cancelled:
            return
        if time.monotonic() >= self._deadline:
            self._fail("The GitHub authorization code expired. Start sign-in again.")
            return
        payload = urlencode(
            {
                "client_id": self._client_id,
                "device_code": authorization.device_code,
                "grant_type": _GRANT_TYPE,
            }
        ).encode("ascii")
        self._post(_ACCESS_TOKEN_URL, payload, self._token_finished)

    @Slot()
    def _token_finished(self) -> None:
        reply = self._take_reply()
        if reply is None:
            return
        try:
            payload = reply_payload(reply)
            token, error, interval = parse_token_response(payload)
        except OAuthHttpError as parse_error:
            self._fail(str(parse_error))
            return
        finally:
            reply.deleteLater()
        if token:
            self._request_user(token)
            return
        authorization = self._authorization
        if authorization is None:
            return
        if error == "authorization_pending":
            self._schedule_poll(interval or authorization.interval)
        elif error == "slow_down":
            self._schedule_poll(interval or authorization.interval + 5)
        elif error == "access_denied":
            self._fail("GitHub authorization was denied.")
        elif error in {"expired_token", "token_expired"}:
            self._fail("The GitHub authorization code expired. Start sign-in again.")
        else:
            self._fail(f"GitHub authorization failed: {error or 'unknown response'}")

    def _request_user(self, token: str) -> None:
        request = json_request(_USER_URL)
        request.setRawHeader(b"Authorization", QByteArray(f"Bearer {token}".encode("ascii")))
        reply = self._network.get(request)
        reply.setProperty("oauthToken", token)
        self._reply = reply
        reply.finished.connect(self._user_finished)

    @Slot()
    def _user_finished(self) -> None:
        reply = self._take_reply()
        if reply is None:
            return
        token = reply.property("oauthToken")
        try:
            payload = reply_payload(reply)
            login = payload.get("login")
            if not isinstance(login, str) or not login.strip():
                raise DeviceFlowError("GitHub did not return the authorized account login.")
        except OAuthHttpError as error:
            self._fail(str(error))
            return
        finally:
            reply.deleteLater()
        if not isinstance(token, str):
            self._fail("GitHub authorization token was lost before it could be saved.")
            return
        self._authorization = None
        self.completed.emit(DeviceFlowResult(login.strip(), token))

    def _schedule_poll(self, seconds: int) -> None:
        self._timer.start(max(1, seconds) * 1000)

    def _take_reply(self) -> QNetworkReply | None:
        reply = self._reply
        self._reply = None
        if self._cancelled:
            return None
        return reply

    def _fail(self, message: str) -> None:
        self._timer.stop()
        self._authorization = None
        if not self._cancelled:
            self.failed.emit(message)


class DeviceFlowError(OAuthHttpError):
    pass


def parse_device_authorization(payload: dict[str, object]) -> DeviceAuthorization:
    try:
        device_code = _required_string(payload, "device_code")
        user_code = _required_string(payload, "user_code")
        verification_uri = _required_string(payload, "verification_uri")
        expires_in = _required_int(payload, "expires_in")
        interval_value = payload.get("interval", 5)
        if not isinstance(interval_value, int):
            raise DeviceFlowError("GitHub returned an invalid polling interval.")
    except DeviceFlowError:
        message = payload.get("error_description") or payload.get("error")
        if isinstance(message, str):
            raise DeviceFlowError(f"GitHub authorization failed: {message}") from None
        raise
    return DeviceAuthorization(
        device_code, user_code, verification_uri, expires_in, max(1, interval_value)
    )


def parse_token_response(
    payload: dict[str, object],
) -> tuple[str | None, str | None, int | None]:
    token = payload.get("access_token")
    error = payload.get("error")
    interval = payload.get("interval")
    return (
        token if isinstance(token, str) and token else None,
        error if isinstance(error, str) and error else None,
        interval if isinstance(interval, int) else None,
    )


def _required_string(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise DeviceFlowError(f"GitHub response is missing '{key}'.")
    return value


def _required_int(payload: dict[str, object], key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int):
        raise DeviceFlowError(f"GitHub response is missing '{key}'.")
    return value
