from pathlib import Path

from mygitclient.git.conflicts import (
    conflict_marker_lines,
    parse_conflict_blocks,
    resolve_conflict_block,
)


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


def test_conflict_blocks_are_parsed_and_resolved_one_at_a_time() -> None:
    text = (
        "before\n"
        "<<<<<<< HEAD\n"
        "current one\n"
        "=======\n"
        "incoming one\n"
        ">>>>>>> feature\n"
        "middle\n"
        "<<<<<<< HEAD\n"
        "current two\n"
        "=======\n"
        "incoming two\n"
        ">>>>>>> feature\n"
        "after\n"
    )

    blocks = parse_conflict_blocks(text)

    assert len(blocks) == 2
    assert blocks[0].current_label == "HEAD"
    assert blocks[0].incoming_label == "feature"
    assert blocks[0].current == ("current one\n",)
    assert blocks[0].incoming == ("incoming one\n",)

    resolved = resolve_conflict_block(text, 0, "both")

    assert "current one\nincoming one\n" in resolved
    assert len(parse_conflict_blocks(resolved)) == 1
    assert resolve_conflict_block(resolved, 0, "incoming") == (
        "before\ncurrent one\nincoming one\nmiddle\nincoming two\nafter\n"
    )


def test_resolving_unknown_conflict_raises() -> None:
    try:
        resolve_conflict_block("clean\n", 0, "current")
    except IndexError as error:
        assert "out of range" in str(error)
    else:
        raise AssertionError("Expected an out-of-range conflict to fail")
