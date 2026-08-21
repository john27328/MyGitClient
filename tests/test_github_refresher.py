from PySide6.QtWidgets import QApplication

from mygitclient.github import GitHubTokenRefresher


def test_refresh_needs_every_credential(qapp: QApplication) -> None:
    refresher = GitHubTokenRefresher()

    assert not refresher.refresh("", "renewal", "client-id", "secret")
    assert not refresher.refresh("octocat", "", "client-id", "secret")
    assert not refresher.refresh("octocat", "renewal", "", "secret")
    assert not refresher.refresh("octocat", "renewal", "client-id", "  ")


def test_refresh_starts_when_all_credentials_are_present(qapp: QApplication) -> None:
    refresher = GitHubTokenRefresher()

    assert refresher.refresh("octocat", "renewal", "client-id", "secret")
