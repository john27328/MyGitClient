from pathlib import Path

import pytest
from PySide6.QtCore import QSettings

from mygitclient.github import GitHubProfile, GitHubProfileStore


def test_github_profiles_round_trip_without_secrets(tmp_path: Path) -> None:
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    store = GitHubProfileStore(settings)
    profile = GitHubProfile(
        "Work",
        "octocat-work",
        "ssh",
        "Octo Cat",
        "octo@example.invalid",
    )

    store.save(profile)

    assert store.profiles() == (profile,)
    serialized = settings.value("github/profiles")
    assert isinstance(serialized, str)
    assert "token" not in serialized.casefold()


def test_github_profile_store_updates_and_removes_profile(tmp_path: Path) -> None:
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    store = GitHubProfileStore(settings)
    store.save(GitHubProfile("Personal", "old-login"))

    store.save(GitHubProfile("Home", "new-login", "ssh"), previous_label="Personal")
    assert store.profiles() == (GitHubProfile("Home", "new-login", "ssh"),)

    store.remove("Home")
    assert store.profiles() == ()


def test_github_profile_rejects_invalid_values() -> None:
    with pytest.raises(ValueError):
        GitHubProfile("", "login")
    with pytest.raises(ValueError):
        GitHubProfile("Work", "login", "password")
