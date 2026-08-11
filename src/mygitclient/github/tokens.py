from __future__ import annotations

from typing import Protocol

import keyring
from keyring.errors import KeyringError, PasswordDeleteError

_SERVICE_NAME = "MyGitClient GitHub API"


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


class GitHubTokenStore:
    def __init__(self, backend: TokenBackend | None = None) -> None:
        self._backend = backend or SystemKeyringBackend()

    def token(self, login: str) -> str | None:
        try:
            return self._backend.get_password(_SERVICE_NAME, _credential_key(login))
        except KeyringError as error:
            raise TokenStoreError(f"Could not read the system credential store: {error}") from error

    def has_token(self, login: str) -> bool:
        return bool(self.token(login))

    def save(self, login: str, token: str) -> None:
        clean_token = token.strip()
        if not clean_token:
            raise ValueError("GitHub token cannot be empty")
        try:
            self._backend.set_password(_SERVICE_NAME, _credential_key(login), clean_token)
        except KeyringError as error:
            raise TokenStoreError(
                f"Could not write to the system credential store: {error}"
            ) from error

    def remove(self, login: str) -> None:
        try:
            self._backend.delete_password(_SERVICE_NAME, _credential_key(login))
        except PasswordDeleteError:
            pass
        except KeyringError as error:
            raise TokenStoreError(
                f"Could not remove the token from the system credential store: {error}"
            ) from error


class TokenStoreError(RuntimeError):
    pass


def _credential_key(login: str) -> str:
    clean_login = login.strip()
    if not clean_login:
        raise ValueError("GitHub login cannot be empty")
    return f"github.com:{clean_login.casefold()}"
