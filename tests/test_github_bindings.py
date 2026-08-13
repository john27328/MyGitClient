from pathlib import Path

from PySide6.QtCore import QSettings

from mygitclient.github import GitHubRepositoryBindingStore


def test_repository_profile_bindings_are_saved_and_removed(tmp_path: Path) -> None:
    settings = QSettings(str(tmp_path / "bindings.ini"), QSettings.Format.IniFormat)
    store = GitHubRepositoryBindingStore(settings)
    repository = tmp_path / "repository"

    store.bind(repository, "Work")
    assert GitHubRepositoryBindingStore(settings).profile_label(repository) == "Work"

    store.remove_profile("Work")
    assert store.profile_label(repository) is None
