from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Protocol, cast

import keyring
from keyring.errors import KeyringError, PasswordDeleteError

_SERVICE_NAME = "MyGitClient GitHub API"

# Refresh a little before GitHub's own deadline so a token cannot expire in flight.
_EXPIRY_LEEWAY_SECONDS = 300.0


class TokenBackend(Protocol):
    def get_password(self, service: str, username: str) -> str | None: ...

    def set_password(self, service: str, username: str, password: str) -> None: ...

    def delete_password(self, service: str, username: str) -> None: ...


class SystemKeyringBackend:
    def get_password(self, service: str, username: str) -> str | None:
        return keyring.get_password(service, username)

    def set_password(self, service: str, username: str, password: str) -> None:
        keyring.set_password(service, username, password)

    def delete_password(self, service: str, username: str) -> None:
        keyring.delete_password(service, username)


@dataclass(frozen=True, slots=True)
class StoredToken:
    """A GitHub access token plus what is needed to renew it.

    ``expires_at`` is a POSIX timestamp; ``0`` means the token has no known expiry,
    which is the case for personal access tokens entered by hand and for OAuth Apps
    that do not expire user authorization tokens.
    """

    access_token: str
    refresh_token: str = ""
    expires_at: float = 0.0

    @property
    def expires(self) -> bool:
        return self.expires_at > 0

    @property
    def can_refresh(self) -> bool:
        return bool(self.refresh_token)

    def is_stale(self, now: float | None = None) -> bool:
        if not self.expires:
            return False
        moment = time.time() if now is None else now
        return moment >= self.expires_at - _EXPIRY_LEEWAY_SECONDS


class GitHubTokenStore:
    def __init__(self, backend: TokenBackend | None = None) -> None:
        self._backend = backend or SystemKeyringBackend()

    def credentials(self, login: str) -> StoredToken | None:
        stored = self._read(_credential_key(login))
        return parse_stored_token(stored) if stored else None

    def token(self, login: str) -> str | None:
        credentials = self.credentials(login)
        return credentials.access_token if credentials is not None else None

    def has_token(self, login: str) -> bool:
        return bool(self.token(login))

    def save(self, login: str, token: str) -> None:
        """Store a token entered by hand, which carries no way to renew itself."""
        clean_token = token.strip()
        if not clean_token:
            raise ValueError("GitHub token cannot be empty")
        self.save_credentials(login, StoredToken(clean_token))

    def save_credentials(self, login: str, credentials: StoredToken) -> None:
        if not credentials.access_token.strip():
            raise ValueError("GitHub token cannot be empty")
        self._write(_credential_key(login), json.dumps(serialize_stored_token(credentials)))

    def remove(self, login: str) -> None:
        self._delete(_credential_key(login))

    def oauth_client_secret(self, client_id: str) -> str | None:
        """The client secret of the user's own OAuth App, needed to renew tokens."""
        return self._read(_client_secret_key(client_id))

    def save_oauth_client_secret(self, client_id: str, secret: str) -> None:
        clean_secret = secret.strip()
        if not clean_secret:
            raise ValueError("GitHub OAuth client secret cannot be empty")
        self._write(_client_secret_key(client_id), clean_secret)

    def _read(self, key: str) -> str | None:
        try:
            return self._backend.get_password(_SERVICE_NAME, key)
        except KeyringError as error:
            raise TokenStoreError(f"Could not read the system credential store: {error}") from error

    def _write(self, key: str, value: str) -> None:
        try:
            self._backend.set_password(_SERVICE_NAME, key, value)
        except KeyringError as error:
            raise TokenStoreError(
                f"Could not write to the system credential store: {error}"
            ) from error

    def _delete(self, key: str) -> None:
        try:
            self._backend.delete_password(_SERVICE_NAME, key)
        except PasswordDeleteError:
            pass
        except KeyringError as error:
            raise TokenStoreError(
                f"Could not remove the token from the system credential store: {error}"
            ) from error


class TokenStoreError(RuntimeError):
    pass


def parse_stored_token(value: str) -> StoredToken | None:
    """Read a stored credential, accepting entries saved as a bare token.

    Releases before token renewal existed stored the access token on its own, so
    anything that is not the current JSON record is treated as such a token.
    """
    clean_value = value.strip()
    if not clean_value:
        return None
    try:
        decoded = cast("object", json.loads(clean_value))
    except json.JSONDecodeError:
        return StoredToken(clean_value)
    if not isinstance(decoded, dict):
        return StoredToken(clean_value)
    record = cast("dict[str, object]", decoded)
    access_token = record.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        return None
    refresh_token = record.get("refresh_token")
    expires_at = record.get("expires_at")
    return StoredToken(
        access_token,
        refresh_token if isinstance(refresh_token, str) else "",
        float(expires_at) if isinstance(expires_at, (int, float)) else 0.0,
    )


def stored_token(
    access_token: str, refresh_token: str, expires_in: int, now: float | None = None
) -> StoredToken:
    """Build a stored record, turning GitHub's relative lifetime into an absolute one."""
    moment = time.time() if now is None else now
    return StoredToken(
        access_token, refresh_token, moment + expires_in if expires_in else 0.0
    )


def serialize_stored_token(credentials: StoredToken) -> dict[str, object]:
    record: dict[str, object] = {"access_token": credentials.access_token}
    if credentials.refresh_token:
        record["refresh_token"] = credentials.refresh_token
    if credentials.expires:
        record["expires_at"] = credentials.expires_at
    return record


def _credential_key(login: str) -> str:
    clean_login = login.strip()
    if not clean_login:
        raise ValueError("GitHub login cannot be empty")
    return f"github.com:{clean_login.casefold()}"


def _client_secret_key(client_id: str) -> str:
    clean_client_id = client_id.strip()
    if not clean_client_id:
        raise ValueError("GitHub OAuth client ID cannot be empty")
    return f"oauth-app:{clean_client_id}"
