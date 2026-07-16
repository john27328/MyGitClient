from __future__ import annotations

import shutil
from pathlib import Path

from mygitclient.git.errors import GitNotFoundError


def find_git_executable() -> Path:
    executable = shutil.which("git")
    if executable is None:
        raise GitNotFoundError(
            "Git is not installed or is not available on PATH. Install Git and restart the app."
        )
    return Path(executable).resolve()

