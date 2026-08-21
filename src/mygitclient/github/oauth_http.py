from __future__ import annotations

import json
from dataclasses import dataclass
from typing import cast

from PySide6.QtCore import QUrl
from PySide6.QtNetwork import QNetworkReply, QNetworkRequest


class OAuthHttpError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class TokenResponse:
    """The access-token half of an OAuth exchange, or the reason it is not ready.

    OAuth Apps that expire user authorization tokens answer with a refresh token and
    the access token's lifetime; apps that do not leave both empty.
    """

    access_token: str = ""
    refresh_token: str = ""
    expires_in: int = 0
    error: str = ""


def parse_token_response(payload: dict[str, object]) -> TokenResponse:
    return TokenResponse(
        optional_string(payload, "access_token"),
        optional_string(payload, "refresh_token"),
        optional_int(payload, "expires_in"),
        optional_string(payload, "error"),
    )


def optional_string(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    return value if isinstance(value, str) else ""


def optional_int(payload: dict[str, object], key: str) -> int:
    value = payload.get(key)
    return value if isinstance(value, int) else 0


def json_request(url: QUrl) -> QNetworkRequest:
    request = QNetworkRequest(url)
    request.setRawHeader(b"Accept", b"application/json")
    request.setRawHeader(b"User-Agent", b"MyGitClient")
    return request


def reply_payload(reply: QNetworkReply) -> dict[str, object]:
    raw = bytes(reply.readAll().data())
    if reply.error() != QNetworkReply.NetworkError.NoError:
        detail = reply.errorString()
        try:
            decoded = cast("object", json.loads(raw.decode("utf-8")))
            if isinstance(decoded, dict):
                error_payload = cast("dict[str, object]", decoded)
                message = error_payload.get("error_description") or error_payload.get("message")
                if isinstance(message, str):
                    detail = message
        except (UnicodeDecodeError, json.JSONDecodeError):
            pass
        raise OAuthHttpError(f"GitHub request failed: {detail}")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise OAuthHttpError("GitHub returned an unreadable response.") from error
    if not isinstance(value, dict):
        raise OAuthHttpError("GitHub returned an unexpected response.")
    return cast("dict[str, object]", value)
