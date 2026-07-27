from pathlib import Path

from mygitclient.git.conflicts import conflict_marker_lines


def test_conflict_marker_lines_finds_only_marker_shaped_lines(tmp_path: Path) -> None:
    path = tmp_path / "conflict.txt"
    path.write_text(
        "normal <<<<<<< text\n"
        "<<<<<<< HEAD\n"
        "ours\n"
        "=======\n"
        "theirs\n"
        ">>>>>>> feature\n",
        encoding="utf-8",
    )

    assert conflict_marker_lines(path) == (2, 4, 6)


def test_conflict_marker_lines_handles_missing_file(tmp_path: Path) -> None:
    assert conflict_marker_lines(tmp_path / "missing.txt") == ()
