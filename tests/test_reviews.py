from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings

from mygitclient.git.models import DiffHunk, DiffLine
from mygitclient.workspace.reviews import ReviewSession, ReviewStore, hunk_fingerprint


def test_review_sessions_and_checked_blocks_are_local_and_persisted(tmp_path: Path) -> None:
    settings = QSettings(str(tmp_path / "reviews.ini"), QSettings.Format.IniFormat)
    repository = tmp_path / "repository"
    repository.mkdir()
    session = ReviewSession(repository, "refs/heads/topic", "a" * 40, "Start point")
    store = ReviewStore(settings)

    store.save(session)
    store.set_checked_hunks(session, "src/example.py", {"block-one"})

    restored = ReviewStore(QSettings(str(tmp_path / "reviews.ini"), QSettings.Format.IniFormat))
    assert restored.sessions(repository) == (session,)
    assert restored.checked_hunks(session, "src/example.py") == frozenset({"block-one"})

    restored.delete(session)
    assert restored.sessions(repository) == ()
    assert restored.checked_hunks(session, "src/example.py") == frozenset()


def test_hunk_fingerprint_uses_content_not_line_position() -> None:
    lines = (
        DiffLine(" context", "context"),
        DiffLine("-old", "deletion"),
        DiffLine("+new", "addition"),
    )
    moved = DiffHunk(100, 2, 100, 2, "@@ -100,2 +100,2 @@", lines)
    original = DiffHunk(1, 2, 1, 2, "@@ -1,2 +1,2 @@", lines)
    changed = DiffHunk(
        1,
        2,
        1,
        2,
        "@@ -1,2 +1,2 @@",
        (*lines[:-1], DiffLine("+different", "addition")),
    )

    assert hunk_fingerprint("src/example.py", original) == hunk_fingerprint(
        "src/example.py", moved
    )
    assert hunk_fingerprint("src/example.py", original) != hunk_fingerprint(
        "src/example.py", changed
    )
