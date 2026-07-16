from __future__ import annotations

from mygitclient.git.parsers import parse_status_porcelain_v2, parse_unified_diff


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
