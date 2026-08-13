from pathlib import Path

from pytestqt.qtbot import QtBot

from mygitclient.github import GitHubProfile
from mygitclient.ui.home_panel import HomePanel


def test_home_panel_opens_recent_repository(qtbot: QtBot, tmp_path: Path) -> None:
    panel = HomePanel()
    qtbot.addWidget(panel)
    repository = tmp_path / "example"
    requested: list[Path] = []
    panel.open_repository_requested.connect(requested.append)
    panel.set_recent((repository,))

    item = panel.recent_tree.topLevelItem(0)
    assert item is not None
    panel.recent_tree.itemDoubleClicked.emit(item, 0)

    assert requested == [repository]


def test_home_panel_shows_github_remote_and_emits_profile_binding(
    qtbot: QtBot, tmp_path: Path
) -> None:
    panel = HomePanel()
    qtbot.addWidget(panel)
    repository = tmp_path / "repository"
    profile = GitHubProfile("Work", "octocat")
    panel.set_recent((repository,))
    panel.set_github_profiles((profile,))
    panel.set_recent_github(repository, "octocat/repository", "Work")
    item = panel.recent_tree.topLevelItem(0)
    assert item is not None
    assert item.text(2) == "octocat/repository · Work"

    requested: list[tuple[object, object]] = []
    def record_binding(path: object, label: object) -> None:
        requested.append((path, label))

    panel.bind_github_profile_requested.connect(record_binding)
    panel.recent_tree.setCurrentItem(item)
    action = next(
        action for action in panel.github_binding_menu.actions() if action.text() == "Work"
    )
    action.trigger()
    assert requested == [(repository, "Work")]


def test_home_panel_removes_selected_recent_repository(
    qtbot: QtBot, tmp_path: Path
) -> None:
    panel = HomePanel()
    qtbot.addWidget(panel)
    repository = tmp_path / "example"
    requested: list[Path] = []
    panel.remove_recent_repository_requested.connect(requested.append)
    panel.set_recent((repository,))

    item = panel.recent_tree.topLevelItem(0)
    assert item is not None
    panel.recent_tree.setCurrentItem(item)
    assert panel.remove_recent_action.isEnabled()
    panel.remove_recent_action.trigger()

    assert requested == [repository]


def test_home_panel_opens_named_workspace(qtbot: QtBot) -> None:
    panel = HomePanel()
    qtbot.addWidget(panel)
    requested: list[str] = []
    panel.open_workspace_requested.connect(requested.append)
    panel.set_workspaces(("Work", "Personal"))

    item = panel.workspace_tree.topLevelItem(1)
    assert item is not None
    panel.workspace_tree.itemDoubleClicked.emit(item, 0)

    assert requested == ["Personal"]


def test_home_panel_requests_clone_from_url(qtbot: QtBot) -> None:
    panel = HomePanel()
    qtbot.addWidget(panel)
    requested: list[str] = []
    panel.clone_repository_requested.connect(requested.append)

    panel.clone_url.setText("https://github.com/example/project.git")
    panel.clone_button.click()

    assert requested == ["https://github.com/example/project.git"]


def test_home_panel_shows_and_edits_github_profile(qtbot: QtBot) -> None:
    panel = HomePanel()
    qtbot.addWidget(panel)
    profile = GitHubProfile("Work", "octocat", "ssh", "Octo", "octo@example.invalid")
    requested: list[object] = []
    panel.edit_github_profile_requested.connect(requested.append)

    panel.set_github_profiles((profile,), frozenset({"octocat"}))
    item = panel.github_tree.topLevelItem(0)
    assert item is not None
    panel.github_tree.setCurrentItem(item)
    panel.edit_github_button.click()

    assert item.text(2) == "Token saved"
    assert item.text(3) == "SSH"
    assert requested == [profile]


def test_home_panel_add_account_starts_connection_flow(qtbot: QtBot) -> None:
    panel = HomePanel()
    qtbot.addWidget(panel)
    requested: list[bool] = []
    panel.add_github_profile_requested.connect(lambda: requested.append(True))

    panel.add_github_button.click()

    assert panel.add_github_button.text() == "Connect GitHub account…"
    assert requested == [True]


def test_connected_github_profile_does_not_offer_reconnect(qtbot: QtBot) -> None:
    panel = HomePanel()
    qtbot.addWidget(panel)
    profile = GitHubProfile("octocat", "octocat")
    panel.set_github_profiles((profile,), frozenset({"octocat"}))
    item = panel.github_tree.topLevelItem(0)
    assert item is not None

    panel.github_tree.setCurrentItem(item)

    assert not panel.connect_github_button.isEnabled()
    assert panel.remove_github_token_button.isEnabled()
    assert panel.browse_github_button.isEnabled()


def test_connected_github_profile_opens_repository_browser(qtbot: QtBot) -> None:
    panel = HomePanel()
    qtbot.addWidget(panel)
    profile = GitHubProfile("Personal", "octocat")
    requested: list[object] = []
    panel.browse_github_requested.connect(requested.append)
    panel.set_github_profiles((profile,), frozenset({"octocat"}))
    item = panel.github_tree.topLevelItem(0)
    assert item is not None
    panel.github_tree.setCurrentItem(item)

    panel.browse_github_button.click()

    assert requested == [profile]
