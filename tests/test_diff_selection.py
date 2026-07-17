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
