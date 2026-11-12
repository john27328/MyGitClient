from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _replace(path: Path, text: str) -> None:
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def _reword_first(todo: Path) -> int:
    """Turn the oldest ``pick`` of Git's own todo into a reword of the expected commit."""

    expected = os.environ.get("MYGITCLIENT_REWORD_OID", "")
    lines = todo.read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines):
        parts = line.split()
        if not parts or parts[0] != "pick":
            continue
        if len(parts) < 2 or not expected.startswith(parts[1]):
            break
        helper = Path(__file__).resolve()
        lines.insert(index + 1, f'exec "{sys.executable}" "{helper}" amend 0')
        _replace(todo, "\n".join(lines))
        return 0
    print("The selected commit is not part of the current branch.", file=sys.stderr)
    return 3


def _matching_oid(abbreviated: str, oids: list[str]) -> str | None:
    return next((oid for oid in oids if oid.startswith(abbreviated)), None)


def _rewrite(todo: Path) -> int:
    """Drop or squash the requested commits inside Git's own todo.

    ``MYGITCLIENT_DROP_OIDS`` lists commits to drop. ``MYGITCLIENT_SQUASH_OIDS`` lists
    adjacent commits to fold into the oldest of them, which then takes ``message-0.txt``.
    """

    drops = os.environ.get("MYGITCLIENT_DROP_OIDS", "").split()
    squashes = os.environ.get("MYGITCLIENT_SQUASH_OIDS", "").split()
    lines = todo.read_text(encoding="utf-8").splitlines()
    found: dict[str, int] = {}
    for index, line in enumerate(lines):
        parts = line.split()
        if len(parts) < 2 or parts[0] != "pick":
            continue
        oid = _matching_oid(parts[1], drops + squashes)
        if oid is not None:
            found[oid] = index
    if any(oid not in found for oid in drops + squashes):
        print("The selected commits are not all on the current branch.", file=sys.stderr)
        return 3
    for oid in drops:
        lines[found[oid]] = "drop" + lines[found[oid]][len("pick") :]
    if squashes:
        indexes = sorted(found[oid] for oid in squashes)
        if indexes[-1] - indexes[0] + 1 != len(indexes):
            print(
                "Only commits that directly follow each other can be squashed.",
                file=sys.stderr,
            )
            return 3
        for index in indexes[1:]:
            lines[index] = "fixup" + lines[index][len("pick") :]
        helper = Path(__file__).resolve()
        lines.insert(indexes[-1] + 1, f'exec "{sys.executable}" "{helper}" amend 0')
    _replace(todo, "\n".join(lines))
    return 0


def main() -> int:
    if len(sys.argv) < 3:
        return 2
    mode, target = sys.argv[1], Path(sys.argv[2])
    state = Path(os.environ["MYGITCLIENT_REBASE_STATE"])
    if mode == "sequence":
        _replace(target, (state / "todo").read_text(encoding="utf-8"))
        return 0
    if mode == "reword-first":
        return _reword_first(target)
    if mode == "rewrite":
        return _rewrite(target)
    if mode == "amend":
        message = state / f"message-{target.name}.txt"
        return subprocess.run(
            ["git", "commit", "--amend", "-F", str(message)], check=False
        ).returncode
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
