from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, cast

from PySide6.QtCore import QObject, QProcess, QUrl, Signal, Slot
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from mygitclient import __version__

LATEST_RELEASE_URL = QUrl("https://api.github.com/repos/john27328/MyGitClient/releases/latest")
_VERSION = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:[-+].*)?$")
_WINDOWS_ARCHIVE = re.compile(r"^MyGitClient-.+-windows-x64\.zip$")


@dataclass(frozen=True, slots=True)
class UpdateInfo:
    version: str
    page_url: str
    name: str
    archive_url: str | None = None
    checksum_url: str | None = None


def version_key(value: str) -> tuple[int, int, int] | None:
    match = _VERSION.fullmatch(value.strip())
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def _asset_urls(document: dict[str, object]) -> tuple[str | None, str | None]:
    assets = document.get("assets")
    if not isinstance(assets, list):
        return None, None
    urls: dict[str, str] = {}
    for value in cast(list[object], assets):
        if not isinstance(value, dict):
            continue
        asset = cast(dict[str, object], value)
        name = asset.get("name")
        url = asset.get("browser_download_url")
        if isinstance(name, str) and isinstance(url, str):
            urls[name] = url
    archive_name = next((name for name in urls if _WINDOWS_ARCHIVE.fullmatch(name)), None)
    if archive_name is None:
        return None, None
    return urls[archive_name], urls.get(f"{archive_name}.sha256")


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
    archive_url, checksum_url = _asset_urls(document)
    return UpdateInfo(
        tag.removeprefix("v"),
        page_url,
        name if isinstance(name, str) else tag,
        archive_url,
        checksum_url,
    )


def portable_install_directory() -> Path | None:
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return None
    executable = Path(sys.executable).resolve()
    if executable.name.casefold() != "mygitclient.exe":
        return None
    return executable.parent


def parse_checksum(payload: bytes) -> str:
    value = payload.decode("ascii").strip().split(maxsplit=1)[0].casefold()
    if re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError("The release checksum is invalid")
    return value


def verify_archive(path: Path, checksum_payload: bytes) -> None:
    expected = parse_checksum(checksum_payload)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != expected:
        raise ValueError("The downloaded update failed its SHA-256 verification")


def _powershell_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def create_updater_script(archive: Path, install_directory: Path) -> Path:
    update_root = archive.parent
    script = update_root / "install-update.ps1"
    target = str(install_directory.resolve())
    staging = str((update_root / "expanded").resolve())
    backup = str((install_directory.parent / f"{install_directory.name}.update-backup").resolve())
    executable = str((install_directory / "MyGitClient.exe").resolve())
    content = f"""$ErrorActionPreference = \"Stop\"
$archive = {_powershell_literal(str(archive.resolve()))}
$target = {_powershell_literal(target)}
$staging = {_powershell_literal(staging)}
$backup = {_powershell_literal(backup)}
$executable = {_powershell_literal(executable)}
try {{
    Wait-Process -Id {os.getpid()} -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $staging -Recurse -Force -ErrorAction SilentlyContinue
    Expand-Archive -LiteralPath $archive -DestinationPath $staging -Force
    $source = Join-Path $staging \"MyGitClient\"
    if (-not (Test-Path -LiteralPath (Join-Path $source \"MyGitClient.exe\"))) {{
        throw \"The update archive does not contain MyGitClient.exe.\"
    }}
    Remove-Item -LiteralPath $backup -Recurse -Force -ErrorAction SilentlyContinue
    Move-Item -LiteralPath $target -Destination $backup
    try {{
        Move-Item -LiteralPath $source -Destination $target
    }} catch {{
        Move-Item -LiteralPath $backup -Destination $target
        throw
    }}
    Start-Process -FilePath $executable -WorkingDirectory $target
    Remove-Item -LiteralPath $backup -Recurse -Force -ErrorAction SilentlyContinue
}} catch {{
    Add-Type -AssemblyName PresentationFramework
    [System.Windows.MessageBox]::Show($_.Exception.Message, \"MyGitClient update failed\")
}}
"""
    script.write_text(content, encoding="utf-8-sig")
    return script


def launch_updater(archive: Path, install_directory: Path) -> bool:
    script = create_updater_script(archive, install_directory)
    return QProcess.startDetached(
        "powershell.exe",
        ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
        str(script.parent),
    )[0]


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
        request = _request(LATEST_RELEASE_URL)
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
                update = parse_release(_reply_bytes(reply))
            except (UnicodeError, ValueError, json.JSONDecodeError) as error:
                self.failed.emit(str(error))
                return
            if update is None:
                self.up_to_date.emit()
            else:
                self.update_available.emit(update)
        finally:
            reply.deleteLater()


class UpdateDownloader(QObject):
    progress = Signal(int, int)
    ready = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._network = QNetworkAccessManager(self)
        self._reply: QNetworkReply | None = None
        self._stream: BinaryIO | None = None
        self._directory: Path | None = None
        self._archive: Path | None = None
        self._checksum_url: str | None = None
        self._cancelled = False

    def download(self, update: UpdateInfo) -> None:
        if self._reply is not None:
            return
        if update.archive_url is None or update.checksum_url is None:
            self.failed.emit("This release does not contain a portable update and checksum")
            return
        self._cancelled = False
        self._directory = Path(tempfile.mkdtemp(prefix="mygitclient-update-"))
        self._archive = self._directory / f"MyGitClient-{update.version}-windows-x64.zip"
        self._checksum_url = update.checksum_url
        self._stream = self._archive.open("wb")
        self._start(update.archive_url, self._archive_ready, write=True)

    @Slot()
    def cancel(self) -> None:
        self._cancelled = True
        if self._reply is not None:
            self._reply.abort()

    def _start(self, url: str, finished: Callable[[], None], *, write: bool) -> None:
        reply = self._network.get(_request(QUrl(url)))
        self._reply = reply
        if write:
            reply.readyRead.connect(self._write_ready_data)
            reply.downloadProgress.connect(self.progress)
        reply.finished.connect(finished)

    @Slot()
    def _write_ready_data(self) -> None:
        if self._reply is not None and self._stream is not None:
            self._stream.write(_reply_bytes(self._reply))

    @Slot()
    def _archive_ready(self) -> None:
        reply = self._reply
        self._write_ready_data()
        self._reply = None
        if self._stream is not None:
            self._stream.close()
            self._stream = None
        if reply is None:
            return
        try:
            if self._cancelled:
                self.cancelled.emit()
                return
            if reply.error() != QNetworkReply.NetworkError.NoError:
                self.failed.emit(reply.errorString())
                return
            if self._checksum_url is None:
                self.failed.emit("The release checksum is missing")
                return
            self._start(self._checksum_url, self._checksum_ready, write=False)
        finally:
            reply.deleteLater()

    @Slot()
    def _checksum_ready(self) -> None:
        reply = self._reply
        self._reply = None
        if reply is None:
            return
        try:
            if self._cancelled:
                self.cancelled.emit()
                return
            if reply.error() != QNetworkReply.NetworkError.NoError:
                self.failed.emit(reply.errorString())
                return
            if self._archive is None:
                self.failed.emit("The downloaded update archive is missing")
                return
            try:
                verify_archive(self._archive, _reply_bytes(reply))
            except (OSError, UnicodeError, ValueError) as error:
                self.failed.emit(str(error))
                return
            self.ready.emit(self._archive)
        finally:
            reply.deleteLater()


def _request(url: QUrl) -> QNetworkRequest:
    request = QNetworkRequest(url)
    request.setRawHeader(b"Accept", b"application/vnd.github+json")
    request.setRawHeader(b"User-Agent", f"MyGitClient/{__version__}".encode("ascii"))
    request.setAttribute(
        QNetworkRequest.Attribute.RedirectPolicyAttribute,
        QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy,
    )
    return request


def _reply_bytes(reply: QNetworkReply) -> bytes:
    data = reply.readAll().data()
    return data if isinstance(data, bytes) else bytes(data)
