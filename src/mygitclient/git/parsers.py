from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path

from mygitclient.git.errors import GitParseError
from mygitclient.git.models import (
    BranchesSnapshot,
    BranchInfo,
    BranchStatus,
    CommitFileChange,
    CommitSummary,
    DiffHunk,
    DiffLine,
    DiffLineKind,
    FileStatus,
    RepositoryStatus,
    StashesSnapshot,
    StashInfo,
    TagInfo,
    TagsSnapshot,
    UnifiedDiff,
)

_AHEAD = re.compile(r"ahead (\d+)")
_BEHIND = re.compile(r"behind (\d+)")


def parse_branches(repository: Path, output: bytes) -> BranchesSnapshot:
    branches: list[BranchInfo] = []
    for raw_record in output.split(b"\x1e"):
        raw_record = raw_record.strip(b"\r\n")
        if not raw_record:
            continue
        fields = raw_record.split(b"\x00")
        if len(fields) != 6:
            raise GitParseError("Malformed branch record")
        full_name, name, oid, upstream, tracking, head = (
            field.decode("utf-8", errors="surrogateescape") for field in fields
        )
        remote = full_name.startswith("refs/remotes/")
        if remote and full_name.endswith("/HEAD"):
            continue
        ahead_match = _AHEAD.search(tracking)
        behind_match = _BEHIND.search(tracking)
        branches.append(
            BranchInfo(
                full_name=full_name,
                name=name,
                oid=oid,
                remote=remote,
                current=head == "*",
                upstream=upstream or None,
                ahead=int(ahead_match.group(1)) if ahead_match else 0,
                behind=int(behind_match.group(1)) if behind_match else 0,
                upstream_gone="gone" in tracking,
            )
        )
    return BranchesSnapshot(repository, tuple(branches))


def parse_tags(repository: Path, output: bytes) -> TagsSnapshot:
    tags: list[TagInfo] = []
    for raw_record in output.split(b"\x1e"):
        raw_record = raw_record.strip(b"\r\n")
        if not raw_record:
            continue
        fields = raw_record.split(b"\x00")
        if len(fields) != 5:
            raise GitParseError("Malformed tag record")
        name, object_oid, object_type, peeled_oid, subject = (
            field.decode("utf-8", errors="surrogateescape") for field in fields
        )
        annotated = object_type == "tag"
        tags.append(
            TagInfo(
                name=name,
                object_oid=object_oid,
                commit_oid=peeled_oid or object_oid,
                annotated=annotated,
                subject=subject,
            )
        )
    return TagsSnapshot(repository, tuple(tags))


def parse_stashes(repository: Path, output: bytes) -> StashesSnapshot:
    stashes: list[StashInfo] = []
    for raw_record in output.split(b"\x1e"):
        raw_record = raw_record.strip(b"\r\n")
        if not raw_record:
            continue
        fields = raw_record.split(b"\x00")
        if len(fields) != 3:
            raise GitParseError("Malformed stash record")
        ref, oid, subject = (
            field.decode("utf-8", errors="surrogateescape") for field in fields
        )
        stashes.append(StashInfo(ref, oid, subject))
    return StashesSnapshot(repository, tuple(stashes))


def parse_commit_files(output: bytes) -> tuple[CommitFileChange, ...]:
    fields = output.rstrip(b"\x00").split(b"\x00") if output else []
    changes: list[CommitFileChange] = []
    index = 0
    while index < len(fields):
        status = fields[index].decode("ascii", errors="replace")
        index += 1
        renamed = status.startswith(("R", "C"))
        required = 2 if renamed else 1
        if index + required > len(fields):
            raise GitParseError("Malformed commit file list")
        paths = [
            fields[index + offset].decode("utf-8", errors="surrogateescape")
            for offset in range(required)
        ]
        index += required
        changes.append(
            CommitFileChange(
                status=status,
                path=paths[-1],
                original_path=paths[0] if renamed else None,
            )
        )
    return tuple(changes)


def parse_commit_log(output: bytes) -> tuple[CommitSummary, ...]:
    """Parse NUL-delimited fields and record-separated commits from ``git log``."""
    commits: list[CommitSummary] = []
    for raw_record in output.split(b"\x1e"):
        raw_record = raw_record.strip(b"\r\n")
        if not raw_record:
            continue
        fields = raw_record.split(b"\x00")
        if len(fields) != 6:
            raise GitParseError("Malformed commit history record")
        oid, parents, name, email, authored_at, subject = (
            value.decode("utf-8", errors="surrogateescape") for value in fields
        )
        commits.append(
            CommitSummary(
                oid=oid,
                parent_oids=tuple(parents.split()),
                author_name=name,
                author_email=email,
                authored_at=authored_at,
                subject=subject,
            )
        )
    return tuple(commits)

_HUNK_HEADER = re.compile(
    r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(?: .*)?$"
)


def parse_unified_diff(
    output: bytes, path: str, *, staged: bool, max_bytes: int = 2_000_000
) -> UnifiedDiff:
    """Decode unified diff output and classify its lines for presentation."""
    binary = b"Binary files " in output or b"GIT binary patch" in output
    truncated = len(output) > max_bytes
    if truncated:
        output = output[:max_bytes]
        boundary = output.rfind(b"\n")
        if boundary >= 0:
            output = output[: boundary + 1]
        output += b"Diff truncated because it exceeds the 2 MB display limit.\n"
    text = output.decode("utf-8", errors="replace")
    lines: list[DiffLine] = []
    hunks: list[DiffHunk] = []
    hunk_lines: list[DiffLine] = []
    hunk_values: tuple[int, int, int, int, str] | None = None
    old_line: int | None = None
    new_line: int | None = None

    for text_line in text.splitlines():
        kind = _diff_line_kind(text_line)
        if kind == "hunk":
            if hunk_values is not None:
                hunks.append(_make_hunk(hunk_values, hunk_lines))
            match = _HUNK_HEADER.match(text_line)
            if match is None:
                raise GitParseError(f"Malformed diff hunk header: {text_line!r}")
            old_start = int(match.group(1))
            old_count = int(match.group(2) or "1")
            new_start = int(match.group(3))
            new_count = int(match.group(4) or "1")
            hunk_values = (old_start, old_count, new_start, new_count, text_line)
            hunk_lines = []
            old_line = old_start
            new_line = new_start
            diff_line = DiffLine(text_line, kind)
        elif kind == "deletion" and hunk_values is not None:
            diff_line = DiffLine(text_line, kind, old_line=old_line)
            old_line = _next_line(old_line)
        elif kind == "addition" and hunk_values is not None:
            diff_line = DiffLine(text_line, kind, new_line=new_line)
            new_line = _next_line(new_line)
        elif kind == "context" and hunk_values is not None:
            diff_line = DiffLine(text_line, kind, old_line=old_line, new_line=new_line)
            old_line = _next_line(old_line)
            new_line = _next_line(new_line)
        else:
            diff_line = DiffLine(text_line, kind)
        lines.append(diff_line)
        if hunk_values is not None and kind != "hunk":
            hunk_lines.append(diff_line)

    if hunk_values is not None:
        hunks.append(_make_hunk(hunk_values, hunk_lines))
    return UnifiedDiff(
        path=path,
        staged=staged,
        lines=tuple(lines),
        hunks=tuple(hunks),
        binary=binary,
        truncated=truncated,
    )


def parse_amend_preview(
    output: bytes, path: str = "HEAD"
) -> tuple[str, str | None, str, UnifiedDiff]:
    message_bytes, separator, remainder = output.partition(b"\x00")
    parent_bytes, parent_separator, diff_bytes = remainder.partition(b"\x00")
    if not separator or not parent_separator:
        raise GitParseError("Malformed amend preview: missing metadata separator")
    message = message_bytes.decode("utf-8", errors="replace").strip("\r\n")
    subject, newline, description = message.partition("\n")
    parent_text = parent_bytes.decode("ascii", errors="replace").strip()
    parent_oid = parent_text.split()[0] if parent_text else None
    diff = parse_unified_diff(diff_bytes.lstrip(b"\r\n"), path, staged=True)
    return subject, parent_oid, description.strip("\r\n") if newline else "", diff


def diff_paths(diff: UnifiedDiff) -> frozenset[str]:
    paths: set[str] = set()
    old_path: str | None = None
    for line in diff.lines:
        if line.text.startswith("--- "):
            old_path = _diff_header_path(line.text[4:], "a/")
        elif line.text.startswith("+++ "):
            new_path = _diff_header_path(line.text[4:], "b/")
            path = new_path if new_path != "/dev/null" else old_path
            if path is not None and path != "/dev/null":
                paths.add(path)
    return frozenset(paths)


def _diff_header_path(value: str, prefix: str) -> str:
    path = value.split("\t", 1)[0]
    if len(path) >= 2 and path.startswith('"') and path.endswith('"'):
        path = _decode_git_quoted_path(path[1:-1])
    return path.removeprefix(prefix)


_GIT_PATH_ESCAPES = {
    "a": b"\a",
    "b": b"\b",
    "t": b"\t",
    "n": b"\n",
    "v": b"\v",
    "f": b"\f",
    "r": b"\r",
    "\\": b"\\",
    '"': b'"',
}


def _decode_git_quoted_path(value: str) -> str:
    """Decode the C-style quoting used by Git for paths in textual diff headers."""
    decoded = bytearray()
    index = 0
    while index < len(value):
        character = value[index]
        if character != "\\":
            decoded.extend(character.encode("utf-8", errors="surrogateescape"))
            index += 1
            continue
        index += 1
        if index >= len(value):
            decoded.extend(b"\\")
            break
        escape = value[index]
        if escape in _GIT_PATH_ESCAPES:
            decoded.extend(_GIT_PATH_ESCAPES[escape])
            index += 1
            continue
        octal = re.match(r"[0-7]{1,3}", value[index:])
        if octal is not None:
            decoded.append(int(octal.group(), 8))
            index += len(octal.group())
            continue
        decoded.extend(escape.encode("utf-8", errors="surrogateescape"))
        index += 1
    return decoded.decode("utf-8", errors="surrogateescape")


def _next_line(value: int | None) -> int | None:
    return None if value is None else value + 1


def _make_hunk(
    values: tuple[int, int, int, int, str], lines: list[DiffLine]
) -> DiffHunk:
    old_start, old_count, new_start, new_count, header = values
    return DiffHunk(old_start, old_count, new_start, new_count, header, tuple(lines))


def _diff_line_kind(line: str) -> DiffLineKind:
    if line.startswith(("diff --git ", "index ", "--- ", "+++ ")):
        return "header"
    if line.startswith("@@"):
        return "hunk"
    if line.startswith("+"):
        return "addition"
    if line.startswith("-"):
        return "deletion"
    if line.startswith(" "):
        return "context"
    return "metadata"


def parse_status_porcelain_v2(output: bytes) -> RepositoryStatus:
    """Parse `git status --porcelain=v2 --branch -z` output."""
    branch = BranchStatus()
    files: list[FileStatus] = []
    ignored_count = 0
    records = output.split(b"\0")
    index = 0

    while index < len(records):
        raw = records[index]
        index += 1
        if not raw:
            continue
        record = raw.decode("utf-8", errors="surrogateescape")

        if record.startswith("# "):
            branch = _parse_branch_header(branch, record)
        elif record.startswith("1 "):
            files.append(_parse_ordinary(record))
        elif record.startswith("2 "):
            if index >= len(records) or not records[index]:
                raise GitParseError("Rename record does not contain its original path")
            original_path = records[index].decode("utf-8", errors="surrogateescape")
            index += 1
            files.append(_parse_renamed(record, original_path))
        elif record.startswith("u "):
            files.append(_parse_unmerged(record))
        elif record.startswith("? "):
            files.append(FileStatus(record[2:], "?", "?"))
        elif record.startswith("! "):
            ignored_count += 1
        else:
            raise GitParseError(f"Unknown porcelain v2 record: {record[:30]!r}")

    return RepositoryStatus(branch=branch, files=tuple(files), ignored_count=ignored_count)


def _parse_branch_header(branch: BranchStatus, record: str) -> BranchStatus:
    key, separator, value = record[2:].partition(" ")
    if not separator:
        raise GitParseError(f"Malformed branch header: {record!r}")
    if key == "branch.oid":
        return replace(branch, oid=None if value == "(initial)" else value)
    if key == "branch.head":
        return replace(branch, head=None if value == "(detached)" else value)
    if key == "branch.upstream":
        return replace(branch, upstream=value)
    if key == "branch.ab":
        parts = value.split()
        if len(parts) != 2:
            raise GitParseError(f"Malformed ahead/behind header: {record!r}")
        return replace(branch, ahead=int(parts[0][1:]), behind=int(parts[1][1:]))
    return branch


def _parse_ordinary(record: str) -> FileStatus:
    parts = record.split(" ", 8)
    if len(parts) != 9:
        raise GitParseError(f"Malformed ordinary status record: {record!r}")
    return _file_status(parts[1], parts[2], parts[8])


def _parse_renamed(record: str, original_path: str) -> FileStatus:
    parts = record.split(" ", 9)
    if len(parts) != 10:
        raise GitParseError(f"Malformed rename status record: {record!r}")
    status = _file_status(parts[1], parts[2], parts[9])
    return replace(status, original_path=original_path)


def _parse_unmerged(record: str) -> FileStatus:
    parts = record.split(" ", 10)
    if len(parts) != 11:
        raise GitParseError(f"Malformed unmerged status record: {record!r}")
    status = _file_status(parts[1], parts[2], parts[10])
    return replace(status, unmerged=True)


def _file_status(xy: str, submodule: str, path: str) -> FileStatus:
    if len(xy) != 2:
        raise GitParseError(f"Invalid XY status: {xy!r}")
    return FileStatus(path, xy[0], xy[1], submodule=submodule)
