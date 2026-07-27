from __future__ import annotations

from pathlib import Path

_MARKER_PREFIXES = (b"<<<<<<< ", b"=======", b">>>>>>> ")


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
