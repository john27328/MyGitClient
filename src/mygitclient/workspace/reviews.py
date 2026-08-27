from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from PySide6.QtCore import QSettings

from mygitclient.git.models import DiffHunk

_SESSIONS_KEY = "reviews/sessions"


@dataclass(frozen=True, slots=True)
class ReviewSession:
    repository: Path
    branch: str
    base_oid: str
    base_subject: str
    start_oid: str = ""

    @property
    def key(self) -> str:
        return f"{self.repository.resolve()}\0{self.branch}\0{self.start_oid or self.base_oid}"

    @property
    def displayed_start_oid(self) -> str:
        return self.start_oid or self.base_oid


def hunk_fingerprint(path: str, hunk: DiffHunk) -> str:
    """A content identity that survives line movement but rejects edited blocks."""

    payload = "\n".join((path, *(line.kind + "\0" + line.text for line in hunk.lines)))
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

    def checked_hunks(self, session: ReviewSession, path: str) -> frozenset[str]:
        value = self._settings.value(self._checked_key(session, path), "[]")
        if not isinstance(value, str):
            return frozenset()
        try:
            raw = json.loads(value)
        except json.JSONDecodeError:
            return frozenset()
        return frozenset(item for item in raw if isinstance(item, str))

    def set_checked_hunks(self, session: ReviewSession, path: str, values: set[str]) -> None:
        key = self._checked_key(session, path)
        if values:
            self._settings.setValue(key, json.dumps(sorted(values)))
        else:
            self._settings.remove(key)

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
            if (
                not isinstance(repository, str)
                or not isinstance(branch, str)
                or not isinstance(base_oid, str)
                or not isinstance(base_subject, str)
                or not isinstance(start_oid, str)
            ):
                continue
            sessions.append(
                ReviewSession(Path(repository).resolve(), branch, base_oid, base_subject, start_oid)
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
            }
            for session in sessions
        ]
        self._settings.setValue(_SESSIONS_KEY, json.dumps(values, ensure_ascii=False))

    @staticmethod
    def _checked_key(session: ReviewSession, path: str | None = None) -> str:
        digest = hashlib.sha256(session.key.encode("utf-8", errors="surrogateescape")).hexdigest()
        return f"reviews/checked/{digest}" if path is None else f"reviews/checked/{digest}/{path}"
