from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

_MARKER_PREFIXES = (b"<<<<<<< ", b"=======", b">>>>>>> ")
ConflictChoice = Literal["current", "incoming", "both"]


@dataclass(frozen=True, slots=True)
class ConflictBlock:
    start: int
    separator: int
    end: int
    current_label: str
    incoming_label: str
    current: tuple[str, ...]
    incoming: tuple[str, ...]


def parse_conflict_blocks(text: str) -> tuple[ConflictBlock, ...]:
    """Parse ordinary, non-nested conflict markers from worktree text."""
    lines = text.splitlines(keepends=True)
    blocks: list[ConflictBlock] = []
    start: int | None = None
    separator: int | None = None
    current_label = ""
    for index, line in enumerate(lines):
        stripped = line.rstrip("\r\n")
        if start is None:
            if stripped.startswith("<<<<<<< "):
                start = index
                separator = None
                current_label = stripped.removeprefix("<<<<<<< ").strip()
            continue
        if separator is None:
            if stripped == "=======":
                separator = index
            elif stripped.startswith("<<<<<<< "):
                start = index
                current_label = stripped.removeprefix("<<<<<<< ").strip()
            continue
        if stripped.startswith(">>>>>>> "):
            blocks.append(
                ConflictBlock(
                    start=start,
                    separator=separator,
                    end=index,
                    current_label=current_label,
                    incoming_label=stripped.removeprefix(">>>>>>> ").strip(),
                    current=tuple(lines[start + 1 : separator]),
                    incoming=tuple(lines[separator + 1 : index]),
                )
            )
            start = None
            separator = None
            current_label = ""
    return tuple(blocks)


def resolve_conflict_block(
    text: str, block_index: int, choice: ConflictChoice
) -> str:
    """Replace one parsed conflict with the selected side(s)."""
    blocks = parse_conflict_blocks(text)
    if not 0 <= block_index < len(blocks):
        raise IndexError(f"Conflict block index out of range: {block_index}")
    block = blocks[block_index]
    selected = block.current if choice == "current" else block.incoming
    if choice == "both":
        selected = block.current + block.incoming
    lines = text.splitlines(keepends=True)
    return "".join(lines[: block.start] + list(selected) + lines[block.end + 1 :])


def conflict_marker_lines(path: Path, *, limit: int = 20) -> tuple[int, ...]:
    """Return likely unresolved Git conflict-marker line numbers."""
    markers: list[int] = []
    try:
        with path.open("rb") as stream:
            for number, line in enumerate(stream, start=1):
                if line.rstrip(b"\r\n").startswith(_MARKER_PREFIXES):
                    markers.append(number)
                    if len(markers) >= limit:
                        break
    except OSError:
        return ()
    return tuple(markers)
