from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from PySide6.QtCore import QSettings

from mygitclient.git.models import UnifiedDiff

_SESSIONS_KEY = "reviews/sessions"


@dataclass(frozen=True, slots=True)
class ReviewSession:
    repository: Path
    branch: str
    base_oid: str
    base_subject: str
    start_oid: str = ""
    start_at: str = ""

    @property
    def key(self) -> str:
        return f"{self.repository.resolve()}\0{self.branch}\0{self.start_oid or self.base_oid}"

    @property
    def displayed_start_oid(self) -> str:
        return self.start_oid or self.base_oid


def review_file_fingerprint(diff: UnifiedDiff) -> str:
    """Return the exact file diff that was reviewed.

    A changed diff must be reviewed again; partial hunk state is deliberately not retained.
    """

    payload = "\n".join((diff.path, *(line.kind + "\0" + line.text for line in diff.lines)))
    return hashlib.sha256(payload.encode("utf-8", errors="surrogateescape")).hexdigest()


class ReviewStore:
    """Persists local self-review sessions without touching the repository."""

    def __init__(self, settings: QSettings) -> None:
        self._settings = settings

    def sessions(self, repository: Path) -> tuple[ReviewSession, ...]:
        normalized = repository.resolve()
        sessions: list[ReviewSession] = []
        for value in self._read():
            if value.repository == normalized:
                sessions.append(value)
        return tuple(sessions)

    def save(self, session: ReviewSession) -> None:
        sessions = [item for item in self._read() if item.key != session.key]
        sessions.append(session)
        self._write(sessions)

    def delete(self, session: ReviewSession) -> None:
        self._write(item for item in self._read() if item.key != session.key)
        self._settings.remove(self._checked_key(session))
        self._settings.remove(self._reviewed_files_key(session))

    def reviewed_file(self, session: ReviewSession, path: str) -> str | None:
        value = self._settings.value(self._reviewed_file_key(session, path))
        return value if isinstance(value, str) and value else None

    def set_reviewed_file(self, session: ReviewSession, path: str, fingerprint: str) -> None:
        self._settings.setValue(self._reviewed_file_key(session, path), fingerprint)

    def _read(self) -> tuple[ReviewSession, ...]:
        value = self._settings.value(_SESSIONS_KEY, "[]")
        if not isinstance(value, str):
            return ()
        try:
            raw = json.loads(value)
        except json.JSONDecodeError:
            return ()
        sessions: list[ReviewSession] = []
        if not isinstance(raw, list):
            return ()
        for item in cast(list[object], raw):
            if not isinstance(item, dict):
                continue
            record = cast(dict[str, object], item)
            repository = record.get("repository")
            branch = record.get("branch")
            base_oid = record.get("base_oid")
            base_subject = record.get("base_subject")
            start_oid = record.get("start_oid", base_oid)
            start_at = record.get("start_at", "")
            if (
                not isinstance(repository, str)
                or not isinstance(branch, str)
                or not isinstance(base_oid, str)
                or not isinstance(base_subject, str)
                or not isinstance(start_oid, str)
                or not isinstance(start_at, str)
            ):
                continue
            sessions.append(
                ReviewSession(
                    Path(repository).resolve(), branch, base_oid, base_subject, start_oid, start_at
                )
            )
        return tuple(sessions)

    def _write(self, sessions: Iterable[ReviewSession]) -> None:
        values = [
            {
                "repository": str(session.repository.resolve()),
                "branch": session.branch,
                "base_oid": session.base_oid,
                "base_subject": session.base_subject,
                "start_oid": session.start_oid,
                "start_at": session.start_at,
            }
            for session in sessions
        ]
        self._settings.setValue(_SESSIONS_KEY, json.dumps(values, ensure_ascii=False))

    @staticmethod
    def _checked_key(session: ReviewSession, path: str | None = None) -> str:
        digest = hashlib.sha256(session.key.encode("utf-8", errors="surrogateescape")).hexdigest()
        return f"reviews/checked/{digest}" if path is None else f"reviews/checked/{digest}/{path}"

    @staticmethod
    def _reviewed_file_key(session: ReviewSession, path: str) -> str:
        return f"{ReviewStore._reviewed_files_key(session)}/{path}"

    @staticmethod
    def _reviewed_files_key(session: ReviewSession) -> str:
        digest = hashlib.sha256(session.key.encode("utf-8", errors="surrogateescape")).hexdigest()
        return f"reviews/files/{digest}"
