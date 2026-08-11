import pytest

from mygitclient.github import GitHubTokenStore


class MemoryTokenBackend:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.values.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.values[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        self.values.pop((service, username), None)


def test_github_token_store_uses_credential_backend() -> None:
    backend = MemoryTokenBackend()
    store = GitHubTokenStore(backend)

    store.save("OctoCat", " github_pat_secret ")

    assert store.has_token("octocat")
    assert store.token("OCTOCAT") == "github_pat_secret"
    store.remove("octocat")
    assert not store.has_token("octocat")


def test_github_token_store_rejects_empty_values() -> None:
    store = GitHubTokenStore(MemoryTokenBackend())

    with pytest.raises(ValueError):
        store.save("octocat", "  ")
