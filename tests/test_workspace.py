from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings

from mygitclient.workspace import (
    WorkspaceManager,
    discover_linked_repositories,
    find_repository_root,
)


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
    (first / ".git").mkdir()
    (second / ".git").mkdir()
    workspace = WorkspaceManager(settings)

    workspace.remember(first)
    workspace.remember(second)
    workspace.remember(first)

    assert workspace.recent_repositories() == (first, second)


def test_missing_recent_repository_is_removed_from_settings(tmp_path: Path) -> None:
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    repository = tmp_path / "deleted"
    settings.setValue("workspace/recentRepositories", [str(repository)])
    workspace = WorkspaceManager(settings)

    assert workspace.recent_repositories() == ()
    assert settings.value("workspace/recentRepositories") == []


def test_open_and_named_workspaces_are_persisted(tmp_path: Path) -> None:
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    first = tmp_path / "first"
    second = tmp_path / "second"
    for repository in (first, second):
        repository.mkdir()
        (repository / ".git").mkdir()
    workspace = WorkspaceManager(settings)

    workspace.save_open_repositories([first, second])
    workspace.set_last_repository(second)
    workspace.save_named_workspace("Daily", [first, second])

    assert workspace.open_repositories() == (first, second)
    assert workspace.last_repository() == second
    assert workspace.named_workspaces() == ("Daily",)
    assert workspace.load_named_workspace("Daily") == (first, second)


def test_discover_nested_submodule_and_worktree(tmp_path: Path) -> None:
    repository = tmp_path / "main"
    repository.mkdir()
    git_directory = repository / ".git"
    git_directory.mkdir()
    nested = repository / "nested"
    nested.mkdir()
    (nested / ".git").mkdir()
    submodule = repository / "vendor" / "library"
    submodule.mkdir(parents=True)
    (submodule / ".git").write_text("gitdir: elsewhere\n", encoding="utf-8")
    (repository / ".gitmodules").write_text(
        '[submodule "library"]\n\tpath = vendor/library\n\turl = ../library\n',
        encoding="utf-8",
    )
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / ".git").write_text("gitdir: elsewhere\n", encoding="utf-8")
    metadata = git_directory / "worktrees" / "linked"
    metadata.mkdir(parents=True)
    (metadata / "gitdir").write_text(str(worktree / ".git"), encoding="utf-8")

    linked = discover_linked_repositories(repository)

    assert {(item.path, item.kind) for item in linked} == {
        (nested, "nested"),
        (submodule, "submodule"),
        (worktree, "worktree"),
    }
