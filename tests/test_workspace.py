from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings

from mygitclient.workspace import WorkspaceManager, find_repository_root


def test_find_repository_root_from_nested_directory(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    nested = repository / "src" / "package"
    nested.mkdir(parents=True)
    (repository / ".git").mkdir()

    assert find_repository_root(nested) == repository


def test_recent_repositories_are_deduplicated_and_ordered(tmp_path: Path) -> None:
    settings_file = tmp_path / "settings.ini"
    settings = QSettings(str(settings_file), QSettings.Format.IniFormat)
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    workspace = WorkspaceManager(settings)

    workspace.remember(first)
    workspace.remember(second)
    workspace.remember(first)

    assert workspace.recent_repositories() == (first, second)

