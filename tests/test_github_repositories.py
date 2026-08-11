from __future__ import annotations

import json

import pytest

from mygitclient.github import parse_repositories


def test_parse_repositories_reads_clone_urls_and_visibility() -> None:
    payload = json.dumps(
        [
            {
                "full_name": "octocat/private-project",
                "owner": {"login": "octocat"},
                "private": True,
                "clone_url": "https://github.com/octocat/private-project.git",
                "ssh_url": "git@github.com:octocat/private-project.git",
                "updated_at": "2026-08-11T10:20:30Z",
            },
            {"full_name": "incomplete"},
        ]
    ).encode()

    repositories = parse_repositories(payload)

    assert len(repositories) == 1
    repository = repositories[0]
    assert repository.full_name == "octocat/private-project"
    assert repository.owner == "octocat"
    assert repository.private
    assert repository.clone_url.endswith("private-project.git")
    assert repository.ssh_url.startswith("git@github.com:")
    assert repository.updated_at == "2026-08-11T10:20:30Z"


@pytest.mark.parametrize("payload", [b"not json", b"{}"])
def test_parse_repositories_rejects_invalid_payload(payload: bytes) -> None:
    with pytest.raises(ValueError, match="GitHub returned"):
        parse_repositories(payload)
