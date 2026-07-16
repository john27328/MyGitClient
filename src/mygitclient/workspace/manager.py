from __future__ import annotations

from pathlib import Path
from typing import cast

from PySide6.QtCore import QSettings

_RECENT_KEY = "workspace/recentRepositories"
_MAX_RECENT_REPOSITORIES = 12


def find_repository_root(path: Path) -> Path | None:
    """Find the nearest non-bare Git working tree containing path."""
    candidate = path.expanduser().resolve()
    if candidate.is_file():
        candidate = candidate.parent
    for directory in (candidate, *candidate.parents):
        if (directory / ".git").exists():
            return directory
    return None


class WorkspaceManager:
    def __init__(self, settings: QSettings) -> None:
        self._settings = settings

    def recent_repositories(self) -> tuple[Path, ...]:
        value: object = self._settings.value(_RECENT_KEY, [])
        if isinstance(value, str):
            candidates: list[str] = [value]
        elif isinstance(value, list):
            items = cast(list[object], value)
            candidates = [item for item in items if isinstance(item, str)]
        else:
            candidates = []
        repositories = tuple(
            Path(item) for item in candidates if _is_repository_directory(Path(item))
        )
        if len(repositories) != len(candidates):
            self._settings.setValue(_RECENT_KEY, [str(path) for path in repositories])
        return repositories

    def remember(self, repository: Path) -> None:
        normalized = repository.resolve()
        recent = [path for path in self.recent_repositories() if path != normalized]
        recent.insert(0, normalized)
        self._settings.setValue(
            _RECENT_KEY,
            [str(path) for path in recent[:_MAX_RECENT_REPOSITORIES]],
        )

    def forget(self, repository: Path) -> None:
        normalized = repository.resolve()
        recent = [path for path in self.recent_repositories() if path != normalized]
        self._settings.setValue(_RECENT_KEY, [str(path) for path in recent])


def _is_repository_directory(path: Path) -> bool:
    return path.is_dir() and (path / ".git").exists()
