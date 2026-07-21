from __future__ import annotations

import json

from mygitclient.updates import parse_release, version_key


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
        }
    ).encode()

    update = parse_release(payload, "0.1.0")

    assert update is not None
    assert update.version == "0.2.0"
    assert update.page_url.endswith("v0.2.0")


def test_parse_release_ignores_current_or_older_release() -> None:
    payload = json.dumps(
        {"tag_name": "v0.1.0", "html_url": "https://example.invalid/release"}
    ).encode()

    assert parse_release(payload, "0.1.0") is None
    assert parse_release(payload, "0.2.0") is None
