from __future__ import annotations

import configparser
import os
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from PySide6.QtCore import QSettings

_RECENT_KEY = "workspace/recentRepositories"
_OPEN_KEY = "workspace/openRepositories"
_LAST_KEY = "workspace/lastRepository"
_WORKSPACE_NAMES_KEY = "workspace/namedWorkspaces"
_MAX_RECENT_REPOSITORIES = 12


@dataclass(frozen=True, slots=True)
class LinkedRepository:
    path: Path
    kind: str


def discover_linked_repositories(repository: Path) -> tuple[LinkedRepository, ...]:
    root = repository.resolve()
    discovered: dict[Path, str] = {}
    gitmodules = root / ".gitmodules"
    if gitmodules.is_file():
        parser = configparser.ConfigParser()
        parser.read(gitmodules, encoding="utf-8")
        for section in parser.sections():
            path_value = parser.get(section, "path", fallback="").strip()
            path = (root / path_value).resolve()
            if path_value and _is_repository_directory(path):
                discovered[path] = "submodule"

    worktrees = root / ".git" / "worktrees"
    if worktrees.is_dir():
        for gitdir in worktrees.glob("*/gitdir"):
            try:
                linked_git = Path(
                    gitdir.read_text(encoding="utf-8", errors="surrogateescape").strip()
                )
            except OSError:
                continue
            path = linked_git.parent.resolve()
            if _is_repository_directory(path):
                discovered[path] = "worktree"

    skipped = {".git", ".venv", "node_modules", "__pycache__"}
    for current, directories, _files in os.walk(root):
        directories[:] = [name for name in directories if name not in skipped]
        current_path = Path(current)
        for name in tuple(directories):
            candidate = (current_path / name).resolve()
            if candidate != root and (candidate / ".git").exists():
                discovered.setdefault(candidate, "nested")
                directories.remove(name)
    return tuple(
        LinkedRepository(path, kind)
        for path, kind in sorted(discovered.items(), key=lambda item: str(item[0]).casefold())
    )


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

    def open_repositories(self) -> tuple[Path, ...]:
        return self._read_repository_list(_OPEN_KEY)

    def save_open_repositories(self, repositories: list[Path]) -> None:
        self._settings.setValue(_OPEN_KEY, [str(path.resolve()) for path in repositories])

    def last_repository(self) -> Path | None:
        value = self._settings.value(_LAST_KEY)
        if not isinstance(value, str):
            return None
        path = Path(value)
        return path if _is_repository_directory(path) else None

    def set_last_repository(self, repository: Path) -> None:
        self._settings.setValue(_LAST_KEY, str(repository.resolve()))

    def named_workspaces(self) -> tuple[str, ...]:
        value: object = self._settings.value(_WORKSPACE_NAMES_KEY, [])
        if isinstance(value, str):
            return (value,)
        if isinstance(value, list):
            values = cast(list[object], value)
            return tuple(item for item in values if isinstance(item, str))
        return ()

    def save_named_workspace(self, name: str, repositories: list[Path]) -> None:
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("Workspace name cannot be empty")
        names = list(self.named_workspaces())
        if clean_name not in names:
            names.append(clean_name)
            names.sort(key=str.casefold)
        self._settings.setValue(_WORKSPACE_NAMES_KEY, names)
        self._settings.setValue(
            f"workspace/named/{clean_name}",
            [str(path.resolve()) for path in repositories],
        )

    def load_named_workspace(self, name: str) -> tuple[Path, ...]:
        return self._read_repository_list(f"workspace/named/{name}")

    def _read_repository_list(self, key: str) -> tuple[Path, ...]:
        value: object = self._settings.value(key, [])
        if isinstance(value, str):
            candidates = [value]
        elif isinstance(value, list):
            items = cast(list[object], value)
            candidates = [item for item in items if isinstance(item, str)]
        else:
            candidates = []
        return tuple(Path(item) for item in candidates if _is_repository_directory(Path(item)))


def _is_repository_directory(path: Path) -> bool:
    return path.is_dir() and (path / ".git").exists()
