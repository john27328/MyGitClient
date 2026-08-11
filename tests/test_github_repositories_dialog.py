from __future__ import annotations

from pytestqt.qtbot import QtBot

from mygitclient.github import GitHubProfile, GitHubRepository
from mygitclient.ui.github_repositories_dialog import GitHubRepositoriesDialog


def _repositories() -> tuple[GitHubRepository, ...]:
    return (
        GitHubRepository(
            "octocat/alpha",
            "octocat",
            False,
            "https://github.com/octocat/alpha.git",
            "git@github.com:octocat/alpha.git",
            "2026-08-11T10:20:30Z",
        ),
        GitHubRepository(
            "work/beta",
            "work",
            True,
            "https://github.com/work/beta.git",
            "git@github.com:work/beta.git",
            "2026-08-10T08:00:00Z",
        ),
    )


def test_repository_dialog_filters_and_requests_https_clone(qtbot: QtBot) -> None:
    dialog = GitHubRepositoriesDialog(GitHubProfile("Personal", "octocat"))
    qtbot.addWidget(dialog)
    requested: list[str] = []
    dialog.clone_requested.connect(requested.append)
    dialog.show_repositories(_repositories())

    dialog.search.setText("beta")
    item = dialog.tree.topLevelItem(0)
    assert item is not None
    assert dialog.tree.topLevelItemCount() == 1
    assert item.text(0) == "work/beta"
    assert item.text(1) == "Private"
    dialog.tree.setCurrentItem(item)
    dialog.clone_button.click()

    assert requested == ["https://github.com/work/beta.git"]


def test_repository_dialog_uses_profile_ssh_transport(qtbot: QtBot) -> None:
    profile = GitHubProfile("Work", "octocat", "ssh")
    dialog = GitHubRepositoriesDialog(profile)
    qtbot.addWidget(dialog)
    requested: list[str] = []
    dialog.clone_requested.connect(requested.append)
    dialog.show_repositories(_repositories())
    item = dialog.tree.topLevelItem(0)
    assert item is not None
    dialog.tree.setCurrentItem(item)

    dialog.tree.itemDoubleClicked.emit(item, 0)

    assert requested == ["git@github.com:octocat/alpha.git"]
