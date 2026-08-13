from __future__ import annotations

import json
from dataclasses import dataclass
from typing import cast

from PySide6.QtCore import QObject, QUrl, Signal, Slot
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest


@dataclass(frozen=True, slots=True)
class PublishedGitHubRepository:
    full_name: str
    html_url: str
    clone_url: str
    ssh_url: str


class GitHubRepositoryPublisher(QObject):
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._network = QNetworkAccessManager(self)
        self._reply: QNetworkReply | None = None

    @property
    def is_running(self) -> bool:
        return self._reply is not None

    def create(self, token: str, name: str, *, private: bool) -> None:
        self.cancel()
        request = QNetworkRequest(QUrl("https://api.github.com/user/repos"))
        request.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/json")
        request.setRawHeader(b"Accept", b"application/vnd.github+json")
        request.setRawHeader(b"Authorization", f"Bearer {token}".encode())
        request.setRawHeader(b"X-GitHub-Api-Version", b"2022-11-28")
        request.setRawHeader(b"User-Agent", b"MyGitClient")
        payload = json.dumps({"name": name, "private": private}).encode("utf-8")
        reply = self._network.post(request, payload)
        self._reply = reply
        reply.finished.connect(self._finished)

    def cancel(self) -> None:
        if self._reply is not None:
            self._reply.abort()
            self._reply.deleteLater()
            self._reply = None

    @Slot()
    def _finished(self) -> None:
        reply = self._reply
        self._reply = None
        if reply is None:
            return
        payload = bytes(reply.readAll().data())
        error = reply.error()
        fallback = reply.errorString()
        reply.deleteLater()
        if error != QNetworkReply.NetworkError.NoError:
            self.failed.emit(_api_error(payload, fallback))
            return
        try:
            result = parse_published_repository(payload)
        except ValueError as exception:
            self.failed.emit(str(exception))
            return
        self.completed.emit(result)


def parse_published_repository(payload: bytes) -> PublishedGitHubRepository:
    try:
        value: object = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("GitHub returned an invalid repository") from error
    if not isinstance(value, dict):
        raise ValueError("GitHub returned an unexpected repository")
    record = cast(dict[str, object], value)
    fields = tuple(record.get(key) for key in ("full_name", "html_url", "clone_url", "ssh_url"))
    if not all(isinstance(field, str) and field for field in fields):
        raise ValueError("GitHub returned an incomplete repository")
    full_name, html_url, clone_url, ssh_url = cast(tuple[str, str, str, str], fields)
    return PublishedGitHubRepository(full_name, html_url, clone_url, ssh_url)


def _api_error(payload: bytes, fallback: str) -> str:
    try:
        value: object = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return f"Could not create the GitHub repository: {fallback}"
    if isinstance(value, dict):
        message = cast(dict[str, object], value).get("message")
        if isinstance(message, str) and message:
            return f"GitHub: {message}"
    return f"Could not create the GitHub repository: {fallback}"
