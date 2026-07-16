from __future__ import annotations

from dataclasses import replace

from mygitclient.git.errors import GitParseError
from mygitclient.git.models import BranchStatus, FileStatus, RepositoryStatus


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

