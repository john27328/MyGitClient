from __future__ import annotations

from mygitclient.git.models import UnifiedDiff
from mygitclient.git.parsers import parse_unified_diff
from mygitclient.ui.diff_selection import DiffSelection


def _diff() -> UnifiedDiff:
    return parse_unified_diff(
        b"diff --git a/file.txt b/file.txt\n"
        b"--- a/file.txt\n"
        b"+++ b/file.txt\n"
        b"@@ -1,2 +1,2 @@\n"
        b"-before\n"
        b"+after\n"
        b" context\n",
        "file.txt",
        staged=False,
    )


def test_hunk_toggle_selects_all_changed_lines() -> None:
    diff = _diff()
    selection = DiffSelection()

    assert selection.marker(diff, 3) == "□"
    assert selection.toggle(diff, 3, extend=False)

    assert selection.selected_lines == {4, 5}
    assert selection.marker(diff, 3) == "■"
    assert selection.marker(diff, 4) == "✓"


def test_range_toggle_selects_only_changed_lines() -> None:
    diff = _diff()
    selection = DiffSelection()

    assert selection.toggle(diff, 4, extend=False)
    assert selection.toggle(diff, 5, extend=True)

    assert selection.selected_lines == {4, 5}


def test_whole_file_selection_is_distinct_from_partial_selection() -> None:
    diff = _diff()
    selection = DiffSelection()

    selection.select_whole_file(diff)

    assert selection.selected_lines == {4, 5}
    assert selection.whole_file
    selection.clear()
    assert not selection.selected_lines
    assert not selection.whole_file


def test_selection_restores_only_when_hunk_content_is_unchanged() -> None:
    original = _diff()
    selection = DiffSelection()
    assert selection.toggle(original, 4, extend=False)
    fingerprints = selection.fingerprints(original)
    shifted = parse_unified_diff(
        b"diff --git a/file.txt b/file.txt\n"
        b"index 1111111..2222222 100644\n"
        b"--- a/file.txt\n"
        b"+++ b/file.txt\n"
        b"@@ -10,2 +10,2 @@\n"
        b"-before\n"
        b"+after\n"
        b" context\n",
        "file.txt",
        staged=False,
    )

    selection.restore(shifted, fingerprints)

    assert selection.selected_lines == {5}

    changed = parse_unified_diff(
        b"diff --git a/file.txt b/file.txt\n"
        b"--- a/file.txt\n"
        b"+++ b/file.txt\n"
        b"@@ -1,2 +1,2 @@\n"
        b"-different\n"
        b"+after\n"
        b" context\n",
        "file.txt",
        staged=False,
    )
    selection.restore(changed, fingerprints)
    assert selection.selected_lines == set()
