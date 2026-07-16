from __future__ import annotations

from dataclasses import dataclass, field
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
class UnifiedDiff:
    path: str
    staged: bool
    lines: tuple[DiffLine, ...] = ()
    hunks: tuple[DiffHunk, ...] = ()

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
