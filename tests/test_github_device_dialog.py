from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication
from pytest import MonkeyPatch

from mygitclient.github.device_flow import DeviceAuthorization
from mygitclient.ui.github_device_dialog import GitHubDeviceDialog


def test_buttons_require_both_fields_before_enabling(qapp: QApplication) -> None:
    dialog = GitHubDeviceDialog()

    assert not dialog.request_button.isEnabled()
    assert not dialog.browser_button.isEnabled()

    dialog.client_id.setText("client-id")
    assert dialog.request_button.isEnabled()
    assert not dialog.browser_button.isEnabled()

    dialog.client_secret.setText("client-secret")
    assert dialog.browser_button.isEnabled()

    dialog.client_id.setText("")
    assert not dialog.request_button.isEnabled()
    assert not dialog.browser_button.isEnabled()

    dialog.close()


def test_prefilling_client_id_enables_code_request_button(qapp: QApplication) -> None:
    dialog = GitHubDeviceDialog(client_id="existing-client-id")

    assert dialog.request_button.isEnabled()
    assert not dialog.browser_button.isEnabled()

    dialog.close()


def test_a_remembered_client_secret_is_prefilled_and_enables_browser_sign_in(
    qapp: QApplication,
) -> None:
    dialog = GitHubDeviceDialog(
        client_id="existing-client-id", client_secret="remembered-secret"
    )

    assert dialog.client_secret.text() == "remembered-secret"
    assert dialog.browser_button.isEnabled()
    assert dialog.request_button.isEnabled()

    dialog.close()


def test_show_authorization_locks_inputs_and_fills_code(qapp: QApplication) -> None:
    dialog = GitHubDeviceDialog(client_id="client-id")

    dialog.show_authorization(
        DeviceAuthorization("device-code", "ABCD-1234", "https://github.com/login/device", 900, 5)
    )

    assert dialog.code.text() == "ABCD-1234"
    assert dialog.copy_button.isEnabled()
    assert dialog.open_button.isEnabled()
    assert not dialog.client_id.isEnabled()
    assert not dialog.request_button.isEnabled()
    assert not dialog.browser_button.isEnabled()

    dialog.close()


def test_show_browser_pending_locks_inputs(qapp: QApplication, monkeypatch: MonkeyPatch) -> None:
    opened: list[str] = []

    def fake_open_url(url: QUrl) -> None:
        opened.append(url.toString())

    monkeypatch.setattr(
        "mygitclient.ui.github_device_dialog.QDesktopServices.openUrl", fake_open_url
    )
    dialog = GitHubDeviceDialog(client_id="client-id")
    dialog.client_secret.setText("client-secret")

    dialog.show_browser_pending("https://github.com/login/oauth/authorize?client_id=client-id")

    assert opened == ["https://github.com/login/oauth/authorize?client_id=client-id"]
    assert not dialog.client_id.isEnabled()
    assert not dialog.client_secret.isEnabled()
    assert not dialog.browser_button.isEnabled()
    assert not dialog.request_button.isEnabled()

    dialog.close()


def test_show_error_unlocks_inputs_and_recomputes_button_state(qapp: QApplication) -> None:
    dialog = GitHubDeviceDialog(client_id="client-id")
    dialog.client_secret.setText("client-secret")
    dialog.show_authorization(
        DeviceAuthorization("device-code", "ABCD-1234", "https://github.com/login/device", 900, 5)
    )

    dialog.show_error("The GitHub authorization code expired. Start sign-in again.")

    assert dialog.status.text() == "The GitHub authorization code expired. Start sign-in again."
    assert dialog.client_id.isEnabled()
    assert dialog.client_secret.isEnabled()
    assert dialog.request_button.isEnabled()
    assert dialog.browser_button.isEnabled()

    dialog.close()


def test_request_browser_sign_in_emits_client_id_and_secret(qapp: QApplication) -> None:
    dialog = GitHubDeviceDialog()
    dialog.client_id.setText(" client-id ")
    dialog.client_secret.setText(" client-secret ")
    received: list[tuple[str, str]] = []

    def record(cid: str, secret: str) -> None:
        received.append((cid, secret))

    dialog.browser_start_requested.connect(record)

    dialog.browser_button.click()

    assert received == [("client-id", "client-secret")]

    dialog.close()
