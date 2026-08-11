from __future__ import annotations

import json
from dataclasses import dataclass
from typing import cast

from PySide6.QtCore import QObject, QUrl, Signal, Slot
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

_REPOSITORIES_URL = QUrl(
    "https://api.github.com/user/repos?affiliation=owner,collaborator,organization_member"
    "&sort=updated&per_page=100"
)


@dataclass(frozen=True, slots=True)
class GitHubRepository:
    full_name: str
    owner: str
    private: bool
    clone_url: str
    ssh_url: str
    updated_at: str


class GitHubRepositoryService(QObject):
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._network = QNetworkAccessManager(self)
        self._reply: QNetworkReply | None = None

    @property
    def is_running(self) -> bool:
        return self._reply is not None

    def load(self, token: str) -> None:
        self.cancel()
        request = QNetworkRequest(_REPOSITORIES_URL)
        request.setRawHeader(b"Accept", b"application/vnd.github+json")
        request.setRawHeader(b"Authorization", f"Bearer {token}".encode())
        request.setRawHeader(b"X-GitHub-Api-Version", b"2022-11-28")
        request.setRawHeader(b"User-Agent", b"MyGitClient")
        reply = self._network.get(request)
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
        error_text = reply.errorString()
        reply.deleteLater()
        if error != QNetworkReply.NetworkError.NoError:
            self.failed.emit(_api_error(payload, error_text))
            return
        try:
            repositories = parse_repositories(payload)
        except ValueError as exception:
            self.failed.emit(str(exception))
            return
        self.completed.emit(repositories)


def parse_repositories(payload: bytes) -> tuple[GitHubRepository, ...]:
    try:
        value: object = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("GitHub returned an invalid repository list") from error
    if not isinstance(value, list):
        raise ValueError("GitHub returned an unexpected repository list")
    repositories: list[GitHubRepository] = []
    for raw in cast(list[object], value):
        if not isinstance(raw, dict):
            continue
        record = cast(dict[str, object], raw)
        owner_value = record.get("owner")
        owner_record = cast(dict[str, object], owner_value) if isinstance(owner_value, dict) else {}
        full_name = _text(record, "full_name")
        clone_url = _text(record, "clone_url")
        ssh_url = _text(record, "ssh_url")
        if not full_name or not clone_url or not ssh_url:
            continue
        repositories.append(
            GitHubRepository(
                full_name=full_name,
                owner=_text(owner_record, "login"),
                private=record.get("private") is True,
                clone_url=clone_url,
                ssh_url=ssh_url,
                updated_at=_text(record, "updated_at"),
            )
        )
    return tuple(repositories)


def _text(record: dict[str, object], key: str) -> str:
    value = record.get(key, "")
    return value if isinstance(value, str) else ""


def _api_error(payload: bytes, fallback: str) -> str:
    try:
        value: object = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return f"Could not load GitHub repositories: {fallback}"
    if isinstance(value, dict):
        message = cast(dict[str, object], value).get("message")
        if isinstance(message, str) and message:
            return f"GitHub: {message}"
    return f"Could not load GitHub repositories: {fallback}"
