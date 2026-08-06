from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _replace(path: Path, text: str) -> None:
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def main() -> int:
    if len(sys.argv) < 3:
        return 2
    mode, target = sys.argv[1], Path(sys.argv[2])
    state = Path(os.environ["MYGITCLIENT_REBASE_STATE"])
    if mode == "sequence":
        _replace(target, (state / "todo").read_text(encoding="utf-8"))
        return 0
    if mode == "amend":
        message = state / f"message-{target.name}.txt"
        return subprocess.run(
            ["git", "commit", "--amend", "-F", str(message)], check=False
        ).returncode
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
