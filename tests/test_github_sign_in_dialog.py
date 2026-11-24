from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication
from pytest import MonkeyPatch

from mygitclient.ui.github_sign_in_dialog import GitHubSignInDialog


def test_sign_in_needs_both_the_client_id_and_secret(qapp: QApplication) -> None:
    dialog = GitHubSignInDialog()

    assert dialog.browser_button.isEnabled()
    assert not dialog.oauth_button.isEnabled()
    assert dialog.advanced.isHidden()

    dialog.client_id.setText("client-id")
    assert not dialog.oauth_button.isEnabled()

    dialog.client_secret.setText("client-secret")
    assert dialog.oauth_button.isEnabled()

    dialog.client_id.setText("")
    assert not dialog.oauth_button.isEnabled()

    dialog.close()


def test_remembered_credentials_are_prefilled_and_ready_to_use(qapp: QApplication) -> None:
    dialog = GitHubSignInDialog(
        client_id="existing-client-id", client_secret="remembered-secret"
    )

    assert dialog.client_id.text() == "existing-client-id"
    assert dialog.client_secret.text() == "remembered-secret"
    assert dialog.browser_button.isEnabled()
    assert dialog.oauth_button.isEnabled()

    dialog.close()


def test_a_client_id_alone_is_not_enough_to_sign_in(qapp: QApplication) -> None:
    dialog = GitHubSignInDialog(client_id="existing-client-id")

    assert dialog.browser_button.isEnabled()
    assert not dialog.oauth_button.isEnabled()

    dialog.close()


def test_show_browser_pending_opens_the_url_and_locks_inputs(
    qapp: QApplication, monkeypatch: MonkeyPatch
) -> None:
    opened: list[str] = []

    def fake_open_url(url: QUrl) -> bool:
        opened.append(url.toString())
        return True

    monkeypatch.setattr(
        "mygitclient.ui.github_sign_in_dialog.QDesktopServices.openUrl", fake_open_url
    )
    dialog = GitHubSignInDialog(client_id="client-id", client_secret="client-secret")

    dialog.show_browser_pending("https://github.com/login/oauth/authorize?client_id=client-id")

    assert opened == ["https://github.com/login/oauth/authorize?client_id=client-id"]
    assert not dialog.client_id.isEnabled()
    assert not dialog.client_secret.isEnabled()
    assert not dialog.browser_button.isEnabled()

    dialog.close()


def test_show_error_unlocks_inputs_and_recomputes_button_state(
    qapp: QApplication, monkeypatch: MonkeyPatch
) -> None:
    def fake_open_url(_: QUrl) -> bool:
        return True

    monkeypatch.setattr(
        "mygitclient.ui.github_sign_in_dialog.QDesktopServices.openUrl", fake_open_url
    )
    dialog = GitHubSignInDialog(client_id="client-id", client_secret="client-secret")
    dialog.show_browser_pending("https://github.com/login/oauth/authorize")

    dialog.show_error("GitHub authorization was denied.")

    assert dialog.status.text() == "GitHub authorization was denied."
    assert dialog.client_id.isEnabled()
    assert dialog.client_secret.isEnabled()
    assert dialog.browser_button.isEnabled()

    dialog.close()


def test_sign_in_emits_trimmed_credentials(qapp: QApplication) -> None:
    dialog = GitHubSignInDialog()
    dialog.client_id.setText(" client-id ")
    dialog.client_secret.setText(" client-secret ")
    received: list[tuple[str, str]] = []

    def record(client_id: str, secret: str) -> None:
        received.append((client_id, secret))

    dialog.browser_start_requested.connect(record)

    dialog.oauth_button.click()

    assert received == [("client-id", "client-secret")]

    dialog.close()


def test_primary_sign_in_does_not_need_app_credentials(qapp: QApplication) -> None:
    dialog = GitHubSignInDialog()
    requested: list[bool] = []
    dialog.credential_start_requested.connect(lambda: requested.append(True))
    dialog.browser_button.click()
    assert requested == [True]
    assert dialog.client_id.text() == ""
    assert dialog.client_secret.text() == ""
    assert dialog.advanced.isHidden()
    dialog.advanced_toggle.click()
    assert not dialog.advanced.isHidden()
    dialog.close()


def test_native_sign_in_progress_can_be_cancelled(qapp: QApplication) -> None:
    dialog = GitHubSignInDialog()
    cancelled: list[bool] = []
    dialog.cancelled.connect(lambda: cancelled.append(True))
    dialog.show_pending("Confirm in the browser")
    assert not dialog.browser_button.isEnabled()
    assert not dialog.progress.isHidden()
    assert not dialog.advanced_toggle.isEnabled()
    dialog.reject()
    assert cancelled == [True]


def test_browser_failure_allows_retry(qapp: QApplication, monkeypatch: MonkeyPatch) -> None:
    def cannot_open(_url: QUrl) -> bool:
        return False

    monkeypatch.setattr(
        "mygitclient.ui.github_sign_in_dialog.QDesktopServices.openUrl", cannot_open
    )
    dialog = GitHubSignInDialog(client_id="id", client_secret="secret")
    assert not dialog.show_browser_pending("https://github.com/login/oauth/authorize")
    assert dialog.browser_button.isEnabled()
    assert dialog.oauth_button.isEnabled()
    assert dialog.progress.isHidden()
    assert "Could not open your browser" in dialog.status.text()
    dialog.close()
