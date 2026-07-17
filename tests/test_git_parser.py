from __future__ import annotations

from pathlib import Path

from mygitclient.git.parsers import (
    parse_branches,
    parse_commit_files,
    parse_commit_log,
    parse_status_porcelain_v2,
    parse_unified_diff,
)


def test_parse_branches_includes_tracking_and_remote_refs() -> None:
    snapshot = parse_branches(
        Path("repository"),
        b"refs/heads/main\x00main\x001234\x00origin/main\x00[ahead 2, behind 1]"
        b"\x00*\x1e\nrefs/remotes/origin/topic\x00origin/topic\x005678\x00\x00\x00 \x1e\n",
    )

    assert len(snapshot.branches) == 2
    main, remote = snapshot.branches
    assert main.current
    assert main.upstream == "origin/main"
    assert (main.ahead, main.behind) == (2, 1)
    assert remote.remote
    assert remote.name == "origin/topic"


def test_parse_commit_files_supports_renames_and_regular_changes() -> None:
    files = parse_commit_files(
        b"M\x00changed.txt\x00R100\x00old name.txt\x00new name.txt\x00D\x00deleted.txt\x00"
    )

    assert [(file.status, file.path, file.original_path) for file in files] == [
        ("M", "changed.txt", None),
        ("R100", "new name.txt", "old name.txt"),
        ("D", "deleted.txt", None),
    ]


def test_parse_commit_log_preserves_commit_metadata() -> None:
    output = (
        b"\x1e0123456789\x00parent-one parent-two\x00Ada Lovelace\x00ada@example.com\x00"
        b"2026-07-16T12:30:00+03:00\x00Merge feature\n"
        b"\x1eabcdef0123\x00\x00Linus\x00linus@example.com\x00"
        b"2026-07-15T09:00:00+03:00\x00Initial commit"
    )

    commits = parse_commit_log(output)

    assert len(commits) == 2
    assert commits[0].oid == "0123456789"
    assert commits[0].parent_oids == ("parent-one", "parent-two")
    assert commits[0].subject == "Merge feature"
    assert commits[1].parent_oids == ()


def test_parse_unified_diff_classifies_lines() -> None:
    output = (
        b"diff --git a/example.txt b/example.txt\n"
        b"--- a/example.txt\n"
        b"+++ b/example.txt\n"
        b"@@ -1 +1 @@\n"
        b"-before\n"
        b"+after\n"
    )

    diff = parse_unified_diff(output, "example.txt", staged=False)

    assert diff.path == "example.txt"
    assert [line.kind for line in diff.lines] == [
        "header",
        "header",
        "header",
        "hunk",
        "deletion",
        "addition",
    ]
    assert diff.text.endswith("-before\n+after")
    assert len(diff.hunks) == 1
    assert diff.hunks[0].old_start == 1
    assert diff.hunks[0].new_start == 1
    assert diff.lines[4].old_line == 1
    assert diff.lines[4].new_line is None
    assert diff.lines[5].old_line is None
    assert diff.lines[5].new_line == 1
    assert diff.display_text.endswith("1   │ -before\n  1 │ +after")
    changed_row = diff.side_by_side_rows[-1]
    assert changed_row.old is not None
    assert changed_row.new is not None
    assert changed_row.old.text == "-before"
    assert changed_row.new.text == "+after"
    patch = diff.patch_for_hunk(0)
    assert patch.startswith(b"diff --git a/example.txt b/example.txt\n")
    assert patch.endswith(b"-before\n+after\n")
    selected_patch = diff.patch_for_lines({4, 5})
    assert b"@@ -1,1 +1,1 @@\n" in selected_patch
    assert selected_patch.endswith(b"-before\n+after\n")


def test_parse_unified_diff_tracks_context_and_multiple_hunks() -> None:
    output = (
        b"@@ -3,2 +3,2 @@\n"
        b" unchanged\n"
        b"-old\n"
        b"+new\n"
        b"@@ -10,0 +11,2 @@\n"
        b"+first\n"
        b"+second\n"
    )

    diff = parse_unified_diff(output, "example.txt", staged=True)

    assert len(diff.hunks) == 2
    assert [(line.old_line, line.new_line) for line in diff.hunks[0].lines] == [
        (3, 3),
        (4, None),
        (None, 4),
    ]
    assert [(line.old_line, line.new_line) for line in diff.hunks[1].lines] == [
        (None, 11),
        (None, 12),
    ]


def test_parse_binary_and_truncate_large_diff() -> None:
    binary = parse_unified_diff(
        b"diff --git a/image.png b/image.png\nBinary files a/image.png and b/image.png differ\n",
        "image.png",
        staged=False,
    )
    large = parse_unified_diff(b"metadata\n" * 100, "large.txt", staged=False, max_bytes=40)

    assert binary.binary
    assert not binary.truncated
    assert large.truncated
    assert large.text.endswith("Diff truncated because it exceeds the 2 MB display limit.")


def test_parse_branch_and_file_records() -> None:
    output = (
        b"# branch.oid abc123\0"
        b"# branch.head main\0"
        b"# branch.upstream origin/main\0"
        b"# branch.ab +2 -1\0"
        b"1 M. N... 100644 100644 100644 abc def staged.txt\0"
        b"1 .M N... 100644 100644 100644 abc def working tree.txt\0"
        b"? untracked.txt\0"
        b"! ignored.log\0"
    )

    status = parse_status_porcelain_v2(output)

    assert status.branch.head == "main"
    assert status.branch.upstream == "origin/main"
    assert status.branch.ahead == 2
    assert status.branch.behind == 1
    assert [file.path for file in status.files] == [
        "staged.txt",
        "working tree.txt",
        "untracked.txt",
    ]
    assert status.files[0].is_staged
    assert status.files[1].has_worktree_change
    assert status.ignored_count == 1


def test_parse_rename_record_with_nul_separated_original_path() -> None:
    output = b"2 R. N... 100644 100644 100644 abc def R100 new name.txt\0old name.txt\0"

    status = parse_status_porcelain_v2(output)

    assert status.files[0].path == "new name.txt"
    assert status.files[0].original_path == "old name.txt"
