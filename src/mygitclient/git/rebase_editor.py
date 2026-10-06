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
    if mode == "amend":
        message = state / f"message-{target.name}.txt"
        return subprocess.run(
            ["git", "commit", "--amend", "-F", str(message)], check=False
        ).returncode
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
