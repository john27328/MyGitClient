from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


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

