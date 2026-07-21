from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import cast

from PySide6.QtCore import QObject, QUrl, Signal, Slot
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from mygitclient import __version__

LATEST_RELEASE_URL = QUrl("https://api.github.com/repos/john27328/MyGitClient/releases/latest")
_VERSION = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:[-+].*)?$")


@dataclass(frozen=True, slots=True)
class UpdateInfo:
    version: str
    page_url: str
    name: str


def version_key(value: str) -> tuple[int, int, int] | None:
    match = _VERSION.fullmatch(value.strip())
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def parse_release(payload: bytes, current_version: str = __version__) -> UpdateInfo | None:
    document_value: object = json.loads(payload.decode("utf-8"))
    if not isinstance(document_value, dict):
        raise ValueError("GitHub returned an invalid release response")
    document = cast(dict[str, object], document_value)
    tag = document.get("tag_name")
    page_url = document.get("html_url")
    name = document.get("name")
    if not isinstance(tag, str) or not isinstance(page_url, str):
        raise ValueError("GitHub release response is missing its tag or page URL")
    latest = version_key(tag)
    current = version_key(current_version)
    if latest is None or current is None:
        raise ValueError("Could not understand the release version")
    if latest <= current:
        return None
    return UpdateInfo(tag.removeprefix("v"), page_url, name if isinstance(name, str) else tag)


class UpdateChecker(QObject):
    update_available = Signal(object)
    up_to_date = Signal()
    failed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._network = QNetworkAccessManager(self)
        self._reply: QNetworkReply | None = None

    def check(self) -> None:
        if self._reply is not None:
            return
        request = QNetworkRequest(LATEST_RELEASE_URL)
        request.setRawHeader(b"Accept", b"application/vnd.github+json")
        request.setRawHeader(b"User-Agent", f"MyGitClient/{__version__}".encode("ascii"))
        request.setAttribute(
            QNetworkRequest.Attribute.RedirectPolicyAttribute,
            QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy,
        )
        reply = self._network.get(request)
        self._reply = reply
        reply.finished.connect(self._finished)

    @Slot()
    def _finished(self) -> None:
        reply = self._reply
        self._reply = None
        if reply is None:
            return
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                self.failed.emit(reply.errorString())
                return
            try:
                data = reply.readAll().data()
                payload = data if isinstance(data, bytes) else bytes(data)
                update = parse_release(payload)
            except (UnicodeError, ValueError, json.JSONDecodeError) as error:
                self.failed.emit(str(error))
                return
            if update is None:
                self.up_to_date.emit()
            else:
                self.update_available.emit(update)
        finally:
            reply.deleteLater()
