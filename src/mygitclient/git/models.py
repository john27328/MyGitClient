from __future__ import annotations

from dataclasses import dataclass, field
from itertools import zip_longest
from pathlib import Path
from typing import Literal


@dataclass(frozen=True, slots=True)
class GitCommand:
    arguments: tuple[str, ...]
    working_directory: Path | None = None
    operation: str = "git command"


@dataclass(frozen=True, slots=True)
class GitResult:
    command: GitCommand
    exit_code: int
    stdout: bytes
    stderr: bytes

    @property
    def succeeded(self) -> bool:
        return self.exit_code == 0

    @property
    def error_text(self) -> str:
        return self.stderr.decode("utf-8", errors="replace").strip()


@dataclass(frozen=True, slots=True)
class BranchStatus:
    head: str | None = None
    oid: str | None = None
    upstream: str | None = None
    ahead: int = 0
    behind: int = 0


@dataclass(frozen=True, slots=True)
class FileStatus:
    path: str
    index_status: str
    worktree_status: str
    original_path: str | None = None
    submodule: str = "N..."
    unmerged: bool = False

    @property
    def is_staged(self) -> bool:
        return self.index_status not in {".", "?", "!"}

    @property
    def has_worktree_change(self) -> bool:
        return self.worktree_status not in {".", "!"}


@dataclass(frozen=True, slots=True)
class RepositoryStatus:
    branch: BranchStatus = field(default_factory=BranchStatus)
    files: tuple[FileStatus, ...] = ()
    ignored_count: int = 0


DiffLineKind = Literal["header", "hunk", "addition", "deletion", "context", "metadata"]


@dataclass(frozen=True, slots=True)
class DiffLine:
    text: str
    kind: DiffLineKind
    old_line: int | None = None
    new_line: int | None = None


@dataclass(frozen=True, slots=True)
class DiffHunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    header: str
    lines: tuple[DiffLine, ...] = ()


@dataclass(frozen=True, slots=True)
class SideBySideRow:
    old: DiffLine | None
    new: DiffLine | None


@dataclass(frozen=True, slots=True)
class UnifiedDiff:
    path: str
    staged: bool
    lines: tuple[DiffLine, ...] = ()
    hunks: tuple[DiffHunk, ...] = ()
    binary: bool = False
    truncated: bool = False

    @property
    def text(self) -> str:
        return "\n".join(line.text for line in self.lines)

    @property
    def display_text(self) -> str:
        old_width = max(
            (len(str(line.old_line)) for line in self.lines if line.old_line), default=1
        )
        new_width = max(
            (len(str(line.new_line)) for line in self.lines if line.new_line), default=1
        )
        rendered: list[str] = []
        for line in self.lines:
            old_number = str(line.old_line) if line.old_line is not None else ""
            new_number = str(line.new_line) if line.new_line is not None else ""
            rendered.append(
                f"{old_number:>{old_width}} {new_number:>{new_width}} │ {line.text}"
            )
        return "\n".join(rendered)

    @property
    def side_by_side_rows(self) -> tuple[SideBySideRow, ...]:
        rows: list[SideBySideRow] = []
        index = 0
        while index < len(self.lines):
            line = self.lines[index]
            if line.kind == "addition":
                rows.append(SideBySideRow(None, line))
                index += 1
                continue
            if line.kind != "deletion":
                rows.append(SideBySideRow(line, line))
                index += 1
                continue
            deleted: list[DiffLine] = []
            added: list[DiffLine] = []
            while index < len(self.lines) and self.lines[index].kind == "deletion":
                deleted.append(self.lines[index])
                index += 1
            while index < len(self.lines) and self.lines[index].kind == "addition":
                added.append(self.lines[index])
                index += 1
            rows.extend(SideBySideRow(old, new) for old, new in zip_longest(deleted, added))
        return tuple(rows)

    def hunk_index_for_line(self, line_index: int) -> int | None:
        hunk_index: int | None = None
        current = -1
        for index, line in enumerate(self.lines):
            if line.kind == "hunk":
                current += 1
                hunk_index = current
            if index == line_index:
                return hunk_index
        return None

    def patch_for_hunk(self, hunk_index: int) -> bytes:
        if hunk_index < 0 or hunk_index >= len(self.hunks):
            raise IndexError("Diff hunk index is out of range")
        header = [line.text for line in self.lines if line.kind == "header"]
        hunk = self.hunks[hunk_index]
        patch_lines = [*header, hunk.header, *(line.text for line in hunk.lines)]
        return ("\n".join(patch_lines) + "\n").encode("utf-8", errors="surrogateescape")
