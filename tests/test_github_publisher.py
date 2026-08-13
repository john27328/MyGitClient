from __future__ import annotations

import json

import pytest

from mygitclient.github import parse_published_repository


def test_parse_published_repository_reads_urls() -> None:
    payload = json.dumps(
        {
            "full_name": "octocat/project",
            "html_url": "https://github.com/octocat/project",
            "clone_url": "https://github.com/octocat/project.git",
            "ssh_url": "git@github.com:octocat/project.git",
        }
    ).encode()

    repository = parse_published_repository(payload)

    assert repository.full_name == "octocat/project"
    assert repository.html_url.endswith("octocat/project")
    assert repository.clone_url.endswith("project.git")
    assert repository.ssh_url.startswith("git@github.com:")


@pytest.mark.parametrize("payload", [b"not json", b"{}"])
def test_parse_published_repository_rejects_invalid_payload(payload: bytes) -> None:
    with pytest.raises(ValueError, match="GitHub returned"):
        parse_published_repository(payload)
