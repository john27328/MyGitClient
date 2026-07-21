from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import pytest

from mygitclient.updates import (
    UpdateDownloader,
    create_updater_script,
    parse_checksum,
    parse_release,
    verify_archive,
    version_key,
)


def test_version_key_accepts_release_tags() -> None:
    assert version_key("v1.2.3") == (1, 2, 3)
    assert version_key("1.2.3") == (1, 2, 3)
    assert version_key("not-a-version") is None


def test_parse_release_reports_newer_release() -> None:
    payload = json.dumps(
        {
            "tag_name": "v0.2.0",
            "html_url": "https://example.invalid/releases/v0.2.0",
            "name": "MyGitClient 0.2.0",
            "assets": [
                {
                    "name": "MyGitClient-0.2.0-windows-x64.zip",
                    "browser_download_url": "https://example.invalid/app.zip",
                },
                {
                    "name": "MyGitClient-0.2.0-windows-x64.zip.sha256",
                    "browser_download_url": "https://example.invalid/app.zip.sha256",
                },
            ],
        }
    ).encode()

    update = parse_release(payload, "0.1.0")

    assert update is not None
    assert update.version == "0.2.0"
    assert update.page_url.endswith("v0.2.0")
    assert update.archive_url == "https://example.invalid/app.zip"
    assert update.checksum_url == "https://example.invalid/app.zip.sha256"


def test_parse_release_ignores_current_or_older_release() -> None:
    payload = json.dumps(
        {"tag_name": "v0.1.0", "html_url": "https://example.invalid/release"}
    ).encode()

    assert parse_release(payload, "0.1.0") is None
    assert parse_release(payload, "0.2.0") is None


def test_verify_archive_accepts_matching_checksum(tmp_path: Path) -> None:
    archive = tmp_path / "update.zip"
    archive.write_bytes(b"portable archive")
    checksum = sha256(archive.read_bytes()).hexdigest().encode("ascii")

    verify_archive(archive, checksum + b"  update.zip\n")


def test_verify_archive_rejects_mismatch(tmp_path: Path) -> None:
    archive = tmp_path / "update.zip"
    archive.write_bytes(b"portable archive")

    with pytest.raises(ValueError, match="SHA-256"):
        verify_archive(archive, b"0" * 64)


def test_parse_checksum_rejects_invalid_value() -> None:
    with pytest.raises(ValueError, match="checksum"):
        parse_checksum(b"not-a-checksum")


def test_updater_script_replaces_portable_directory(tmp_path: Path) -> None:
    archive = tmp_path / "download" / "update.zip"
    archive.parent.mkdir()
    install = tmp_path / "installed" / "MyGitClient"
    install.mkdir(parents=True)

    script = create_updater_script(archive, install)
    text = script.read_text(encoding="utf-8-sig")

    assert "Wait-Process" in text
    assert "Expand-Archive" in text
    assert "Move-Item -LiteralPath $target" in text
    assert "Start-Process -FilePath $executable" in text


def test_downloader_forwards_large_qt_progress_values() -> None:
    class TestDownloader(UpdateDownloader):
        def forward_progress(self, received: int, total: int) -> None:
            self._download_progress(received, total)

    downloader = TestDownloader()
    progress: list[tuple[int, int]] = []

    def capture_progress(received: int, total: int) -> None:
        progress.append((received, total))

    downloader.progress.connect(capture_progress)

    downloader.forward_progress(51_000_000, 52_000_000)

    assert progress == [(51_000_000, 52_000_000)]
