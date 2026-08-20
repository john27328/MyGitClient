from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True, slots=True)
class GitHubRemote:
    owner: str
    repository: str

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.repository}"


def github_remote(url: str) -> GitHubRemote | None:
    value = url.strip()
    if value.startswith("git@github.com:"):
        path = value.removeprefix("git@github.com:")
    else:
        parsed = urlparse(value)
        if parsed.hostname is None or parsed.hostname.casefold() != "github.com":
            return None
        path = parsed.path
    parts = [part for part in path.strip("/").split("/") if part]
    if len(parts) != 2:
        return None
    owner, repository = parts
    if repository.casefold().endswith(".git"):
        repository = repository[:-4]
    if not owner or not repository:
        return None
    return GitHubRemote(owner, repository)


def is_github_https_url(url: str) -> bool:
    parsed = urlparse(url.strip())
    return (
        parsed.scheme.casefold() == "https"
        and (parsed.hostname or "").casefold() == "github.com"
    )


def first_github_remote(urls: tuple[str, ...]) -> GitHubRemote | None:
    return next((remote for url in urls if (remote := github_remote(url)) is not None), None)
