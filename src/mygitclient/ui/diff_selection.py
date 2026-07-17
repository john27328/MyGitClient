from __future__ import annotations

from dataclasses import dataclass, field

from mygitclient.git.models import UnifiedDiff


@dataclass(slots=True)
class DiffSelection:
    """Tracks selectable changed lines independently from diff widgets."""

    selected_lines: set[int] = field(default_factory=lambda: set[int]())
    last_line: int | None = None
    whole_file: bool = False

    def clear(self) -> None:
        self.selected_lines.clear()
        self.last_line = None
        self.whole_file = False

    def select_whole_file(self, diff: UnifiedDiff) -> None:
        self.selected_lines = {
            index
            for index, line in enumerate(diff.lines)
            if line.kind in {"addition", "deletion"}
        }
        self.last_line = None
        self.whole_file = bool(self.selected_lines)

    def toggle(self, diff: UnifiedDiff, line_index: int, *, extend: bool) -> bool:
        if line_index < 0 or line_index >= len(diff.lines):
            return False
        self.whole_file = False
        line = diff.lines[line_index]
        if line.kind == "hunk":
            selectable = self._changed_lines_in_hunk(diff, line_index)
        elif line.kind in {"addition", "deletion"}:
            selectable = {line_index}
            if extend and self.last_line is not None:
                start, end = sorted((self.last_line, line_index))
                selectable = {
                    index
                    for index in range(start, end + 1)
                    if diff.lines[index].kind in {"addition", "deletion"}
                }
        else:
            return False
        if selectable and selectable.issubset(self.selected_lines):
            self.selected_lines.difference_update(selectable)
        else:
            self.selected_lines.update(selectable)
        self.last_line = line_index
        return bool(selectable)

    def marker(self, diff: UnifiedDiff, line_index: int) -> str:
        line = diff.lines[line_index]
        if line.kind in {"addition", "deletion"}:
            return "✓" if line_index in self.selected_lines else "□"
        if line.kind != "hunk":
            return " "
        hunk_lines = self._changed_lines_in_hunk(diff, line_index)
        selected_count = len(hunk_lines & self.selected_lines)
        if hunk_lines and selected_count == len(hunk_lines):
            return "■"
        if selected_count:
            return "◩"
        return "□"

    @staticmethod
    def _changed_lines_in_hunk(diff: UnifiedDiff, line_index: int) -> set[int]:
        hunk_index = diff.hunk_index_for_line(line_index)
        return {
            index
            for index, line in enumerate(diff.lines)
            if diff.hunk_index_for_line(index) == hunk_index
            and line.kind in {"addition", "deletion"}
        }
