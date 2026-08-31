from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication
from pytest import MonkeyPatch

from mygitclient.ui.github_sign_in_dialog import GitHubSignInDialog


def test_sign_in_needs_both_the_client_id_and_secret(qapp: QApplication) -> None:
    dialog = GitHubSignInDialog()

    assert not dialog.browser_button.isEnabled()

    dialog.client_id.setText("client-id")
    assert not dialog.browser_button.isEnabled()

    dialog.client_secret.setText("client-secret")
    assert dialog.browser_button.isEnabled()

    dialog.client_id.setText("")
    assert not dialog.browser_button.isEnabled()

    dialog.close()


def test_remembered_credentials_are_prefilled_and_ready_to_use(qapp: QApplication) -> None:
    dialog = GitHubSignInDialog(
        client_id="existing-client-id", client_secret="remembered-secret"
    )

    assert dialog.client_id.text() == "existing-client-id"
    assert dialog.client_secret.text() == "remembered-secret"
    assert dialog.browser_button.isEnabled()

    dialog.close()


def test_a_client_id_alone_is_not_enough_to_sign_in(qapp: QApplication) -> None:
    dialog = GitHubSignInDialog(client_id="existing-client-id")

    assert not dialog.browser_button.isEnabled()

    dialog.close()


def test_show_browser_pending_opens_the_url_and_locks_inputs(
    qapp: QApplication, monkeypatch: MonkeyPatch
) -> None:
    opened: list[str] = []

    def fake_open_url(url: QUrl) -> None:
        opened.append(url.toString())

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

    dialog.browser_button.click()

    assert received == [("client-id", "client-secret")]

    dialog.close()
