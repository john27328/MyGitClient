import pytest

from mygitclient.github import GitHubTokenStore, StoredToken, stored_token
from mygitclient.github.tokens import parse_stored_token


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


def test_renewal_fields_survive_a_round_trip() -> None:
    store = GitHubTokenStore(MemoryTokenBackend())

    store.save_credentials("octocat", StoredToken("access", "renewal", 1_700_000_000.0))

    credentials = store.credentials("OctoCat")
    assert credentials is not None
    assert credentials.access_token == "access"
    assert credentials.refresh_token == "renewal"
    assert credentials.expires_at == 1_700_000_000.0
    assert store.token("octocat") == "access"


def test_a_token_entered_by_hand_has_nothing_to_renew() -> None:
    store = GitHubTokenStore(MemoryTokenBackend())

    store.save("octocat", "github_pat_secret")

    credentials = store.credentials("octocat")
    assert credentials is not None
    assert not credentials.can_refresh
    assert not credentials.expires
    assert not credentials.is_stale()


def test_tokens_saved_before_renewal_existed_are_still_readable() -> None:
    backend = MemoryTokenBackend()
    backend.values[("MyGitClient GitHub API", "github.com:octocat")] = "bare-legacy-token"
    store = GitHubTokenStore(backend)

    assert store.token("octocat") == "bare-legacy-token"
    credentials = store.credentials("octocat")
    assert credentials is not None
    assert not credentials.can_refresh


def test_parse_stored_token_ignores_records_without_an_access_token() -> None:
    assert parse_stored_token("") is None
    assert parse_stored_token('{"refresh_token": "renewal"}') is None


def test_stored_token_turns_a_lifetime_into_an_absolute_expiry() -> None:
    credentials = stored_token("access", "renewal", 28800, now=1_000.0)

    assert credentials.expires_at == 29_800.0
    assert credentials.can_refresh
    assert not credentials.is_stale(now=1_000.0)
    assert credentials.is_stale(now=29_700.0)


def test_stored_token_without_a_lifetime_never_goes_stale() -> None:
    credentials = stored_token("access", "", 0, now=1_000.0)

    assert not credentials.expires
    assert not credentials.is_stale(now=10_000_000.0)


def test_oauth_client_secret_round_trips_per_client_id() -> None:
    store = GitHubTokenStore(MemoryTokenBackend())

    store.save_oauth_client_secret("client-a", " secret-a ")

    assert store.oauth_client_secret("client-a") == "secret-a"
    assert store.oauth_client_secret("client-b") is None
    with pytest.raises(ValueError):
        store.save_oauth_client_secret("client-a", "  ")
