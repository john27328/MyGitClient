from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher
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
    cancelled: bool = False

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
class BranchInfo:
    full_name: str
    name: str
    oid: str
    remote: bool
    current: bool = False
    upstream: str | None = None
    ahead: int = 0
    behind: int = 0
    upstream_gone: bool = False


@dataclass(frozen=True, slots=True)
class BranchesSnapshot:
    repository: Path
    branches: tuple[BranchInfo, ...]


@dataclass(frozen=True, slots=True)
class TagInfo:
    name: str
    object_oid: str
    commit_oid: str
    annotated: bool
    subject: str = ""


@dataclass(frozen=True, slots=True)
class TagsSnapshot:
    repository: Path
    tags: tuple[TagInfo, ...]


@dataclass(frozen=True, slots=True)
class StashInfo:
    ref: str
    oid: str
    subject: str


@dataclass(frozen=True, slots=True)
class StashesSnapshot:
    repository: Path
    stashes: tuple[StashInfo, ...]


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


@dataclass(frozen=True, slots=True)
class RepositoryStatusSnapshot:
    repository: Path
    status: RepositoryStatus


@dataclass(frozen=True, slots=True)
class CommitSummary:
    oid: str
    parent_oids: tuple[str, ...]
    author_name: str
    author_email: str
    authored_at: str
    subject: str


@dataclass(frozen=True, slots=True)
class CommitPage:
    repository: Path
    commits: tuple[CommitSummary, ...]
    offset: int
    has_more: bool


@dataclass(frozen=True, slots=True)
class BranchPointSnapshot:
    repository: Path
    branch_ref: str
    base_ref: str
    commit_oid: str


@dataclass(frozen=True, slots=True)
class CommitFileChange:
    status: str
    path: str
    original_path: str | None = None


@dataclass(frozen=True, slots=True)
class CommitFilesSnapshot:
    repository: Path
    commit_oid: str
    files: tuple[CommitFileChange, ...]


@dataclass(frozen=True, slots=True)
class CommitDiffSnapshot:
    repository: Path
    commit_oid: str
    diff: UnifiedDiff


@dataclass(frozen=True, slots=True)
class RefComparisonSnapshot:
    repository: Path
    base_ref: str
    compare_ref: str
    files: tuple[CommitFileChange, ...]


@dataclass(frozen=True, slots=True)
class RefComparisonDiffSnapshot:
    repository: Path
    base_ref: str
    compare_ref: str
    diff: UnifiedDiff


@dataclass(frozen=True, slots=True)
class AmendPreview:
    repository: Path
    commit_oid: str
    parent_oid: str | None
    subject: str
    description: str
    diff: UnifiedDiff


@dataclass(frozen=True, slots=True)
class AmendDiffSnapshot:
    repository: Path
    commit_oid: str
    path: str | None
    diff: UnifiedDiff
    included_paths: frozenset[str]


@dataclass(frozen=True, slots=True)
class DiffSnapshot:
    repository: Path
    diff: UnifiedDiff


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


def pair_changed_lines(
    deleted: list[DiffLine], added: list[DiffLine]
) -> tuple[SideBySideRow, ...]:
    if not deleted:
        return tuple(SideBySideRow(None, line) for line in added)
    if not added:
        return tuple(SideBySideRow(line, None) for line in deleted)
    if len(deleted) * len(added) > 4096:
        count = max(len(deleted), len(added))
        return tuple(
            SideBySideRow(
                deleted[index] if index < len(deleted) else None,
                added[index] if index < len(added) else None,
            )
            for index in range(count)
        )

    scores = [[0.0] * (len(added) + 1) for _ in range(len(deleted) + 1)]
    choices = [[""] * (len(added) + 1) for _ in range(len(deleted) + 1)]
    for old_index in range(1, len(deleted) + 1):
        choices[old_index][0] = "old"
    for new_index in range(1, len(added) + 1):
        choices[0][new_index] = "new"
    for old_index, old_line in enumerate(deleted, start=1):
        old_text = old_line.text[1:].strip()
        for new_index, new_line in enumerate(added, start=1):
            new_text = new_line.text[1:].strip()
            similarity = SequenceMatcher(
                None, old_text, new_text, autojunk=False
            ).ratio()
            best = scores[old_index - 1][new_index]
            choice = "old"
            if scores[old_index][new_index - 1] > best:
                best = scores[old_index][new_index - 1]
                choice = "new"
            paired = scores[old_index - 1][new_index - 1] + similarity
            if similarity >= 0.55 and paired > best:
                best = paired
                choice = "pair"
            scores[old_index][new_index] = best
            choices[old_index][new_index] = choice

    rows: list[SideBySideRow] = []
    old_index = len(deleted)
    new_index = len(added)
    while old_index or new_index:
        choice = choices[old_index][new_index]
        if choice == "pair":
            rows.append(SideBySideRow(deleted[old_index - 1], added[new_index - 1]))
            old_index -= 1
            new_index -= 1
        elif choice == "old":
            rows.append(SideBySideRow(deleted[old_index - 1], None))
            old_index -= 1
        else:
            rows.append(SideBySideRow(None, added[new_index - 1]))
            new_index -= 1
    rows.reverse()
    longest_side = max(len(deleted), len(added))
    if longest_side >= 8 and len(rows) > longest_side * 1.35:
        return tuple(
            SideBySideRow(
                deleted[index] if index < len(deleted) else None,
                added[index] if index < len(added) else None,
            )
            for index in range(longest_side)
        )
    compacted: list[SideBySideRow] = []
    index = 0
    while index < len(rows):
        current = rows[index]
        following = rows[index + 1] if index + 1 < len(rows) else None
        if (
            following is not None
            and current.old is None
            and current.new is not None
            and following.old is not None
            and following.new is None
        ):
            compacted.append(SideBySideRow(following.old, current.new))
            index += 2
            continue
        if (
            following is not None
            and current.old is not None
            and current.new is None
            and following.old is None
            and following.new is not None
        ):
            compacted.append(SideBySideRow(current.old, following.new))
            index += 2
            continue
        compacted.append(current)
        index += 1
    return tuple(compacted)


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
            rows.extend(pair_changed_lines(deleted, added))
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

    def patch_for_lines(self, selected_lines: set[int]) -> bytes:
        header = [line.text for line in self.lines if line.kind == "header"]
        patch_lines = list(header)
        index = 0
        hunk_index = -1
        while index < len(self.lines):
            line = self.lines[index]
            if line.kind != "hunk":
                index += 1
                continue
            hunk_index += 1
            hunk = self.hunks[hunk_index]
            index += 1
            body: list[str] = []
            old_count = 0
            new_count = 0
            has_selection = False
            while index < len(self.lines) and self.lines[index].kind != "hunk":
                body_line = self.lines[index]
                if body_line.kind == "addition":
                    if index in selected_lines:
                        body.append(body_line.text)
                        new_count += 1
                        has_selection = True
                elif body_line.kind == "deletion":
                    old_count += 1
                    if index in selected_lines:
                        body.append(body_line.text)
                        has_selection = True
                    else:
                        body.append(f" {body_line.text[1:]}")
                        new_count += 1
                else:
                    body.append(body_line.text)
                    if body_line.kind == "context":
                        old_count += 1
                        new_count += 1
                index += 1
            if has_selection:
                suffix = hunk.header.split("@@", 2)[-1]
                patch_lines.append(
                    f"@@ -{hunk.old_start},{old_count} +{hunk.new_start},{new_count} @@{suffix}"
                )
                patch_lines.extend(body)
        if len(patch_lines) == len(header):
            raise ValueError("No changed lines were selected")
        return ("\n".join(patch_lines) + "\n").encode("utf-8", errors="surrogateescape")
