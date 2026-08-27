from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings

from mygitclient.git.parsers import parse_unified_diff
from mygitclient.workspace.reviews import ReviewSession, ReviewStore, review_file_fingerprint


def test_review_sessions_and_reviewed_files_are_local_and_persisted(tmp_path: Path) -> None:
    settings = QSettings(str(tmp_path / "reviews.ini"), QSettings.Format.IniFormat)
    repository = tmp_path / "repository"
    repository.mkdir()
    session = ReviewSession(repository, "refs/heads/topic", "a" * 40, "Start point")
    store = ReviewStore(settings)

    store.save(session)
    store.set_reviewed_file(session, "src/example.py", "reviewed-version")

    restored = ReviewStore(QSettings(str(tmp_path / "reviews.ini"), QSettings.Format.IniFormat))
    assert restored.sessions(repository) == (session,)
    assert restored.reviewed_file(session, "src/example.py") == "reviewed-version"

    restored.delete(session)
    assert restored.sessions(repository) == ()
    assert restored.reviewed_file(session, "src/example.py") is None


def test_review_file_fingerprint_changes_when_any_part_of_the_diff_changes() -> None:
    original = parse_unified_diff(
        b"diff --git a/example.py b/example.py\n@@ -1 +1 @@\n-old\n+new\n",
        "example.py",
        staged=False,
    )
    changed = parse_unified_diff(
        b"diff --git a/example.py b/example.py\n@@ -1 +1 @@\n-old\n+different\n",
        "example.py",
        staged=False,
    )

    assert review_file_fingerprint(original) != review_file_fingerprint(changed)
