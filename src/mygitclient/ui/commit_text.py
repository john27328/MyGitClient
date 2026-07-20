from __future__ import annotations

from pathlib import PurePosixPath
from typing import Final

MAX_DETAILED_FILES: Final = 20
MAX_SUMMARY_GROUPS: Final = 12
MAX_FOLDER_LABEL_LENGTH: Final = 160


def generated_commit_text(changes: list[tuple[str, str]]) -> tuple[str, str]:
    if not changes:
        return "", ""
    if len(changes) == 1:
        action, path = changes[0]
        message = f"{action} {path}"
    else:
        actions = {action for action, _path in changes}
        action = actions.pop() if len(actions) == 1 else "Update"
        message = f"{action} {len(changes)} files"

    if len(changes) <= MAX_DETAILED_FILES:
        description = "\n".join(f"- {action} {path}" for action, path in changes)
        return message, description

    groups: dict[tuple[str, str], int] = {}
    for action, path in changes:
        parent = str(PurePosixPath(path).parent)
        folder = "repository root" if parent == "." else f"{parent}/"
        groups[(action, folder)] = groups.get((action, folder), 0) + 1

    lines: list[str] = []
    represented = 0
    for (action, folder), count in list(groups.items())[:MAX_SUMMARY_GROUPS]:
        label = _ellipsize(folder, MAX_FOLDER_LABEL_LENGTH)
        noun = "file" if count == 1 else "files"
        lines.append(f"- {action} {label} ({count} {noun})")
        represented += count
    remaining = len(changes) - represented
    if remaining:
        lines.append(f"- … and {remaining} more files")
    return message, "\n".join(lines)


def _ellipsize(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return f"{value[: limit - 1]}…"
