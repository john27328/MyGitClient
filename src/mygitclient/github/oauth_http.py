from __future__ import annotations

import json
from typing import cast

from PySide6.QtCore import QUrl
from PySide6.QtNetwork import QNetworkReply, QNetworkRequest


class OAuthHttpError(RuntimeError):
    pass


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
