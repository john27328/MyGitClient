from __future__ import annotations

import json

from PySide6.QtCore import QByteArray, QIODevice, QObject, QTimer
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from pytest import MonkeyPatch, fixture, mark, raises

from mygitclient.git.models import GitCommand, GitResult
from mygitclient.git.runner import GitRunner
from mygitclient.github.browser_flow import SignInResult
from mygitclient.github.credential_flow import GitHubCredentialFlow, parse_github_credential


class _Reply(QNetworkReply):
    def __init__(self, parent: QObject) -> None:
        super().__init__(parent)
        self._data = b""
        self.aborted = False
        self.open(QIODevice.OpenModeFlag.ReadOnly)

    def readData(self, maxlen: int) -> bytes:  # noqa: N802
        chunk, self._data = self._data[:maxlen], self._data[maxlen:]
        return chunk

    def bytesAvailable(self) -> int:  # noqa: N802
        return len(self._data) + super().bytesAvailable()

    def abort(self) -> None:
        self.aborted = True
        self.finished.emit()

    def finish(self, payload: dict[str, object]) -> None:
        self._data = json.dumps(payload).encode()
        self.setFinished(True)
        self.finished.emit()


class _Network(QNetworkAccessManager):
    def __init__(self) -> None:
        super().__init__()
        self.requests: list[QNetworkRequest] = []
        self.replies: list[_Reply] = []

    def get(
        self, request: QNetworkRequest,
        data: QIODevice | QByteArray | bytes | bytearray | memoryview | None = None,
    ) -> QNetworkReply:
        self.requests.append(request)
        reply = _Reply(self)
        self.replies.append(reply)
        return reply


@fixture
def commands(monkeypatch: MonkeyPatch) -> list[tuple[GitRunner, GitCommand, bytes | None]]:
    captured: list[tuple[GitRunner, GitCommand, bytes | None]] = []

    def capture(runner: GitRunner, command: GitCommand, input_data: bytes | None = None) -> None:
        captured.append((runner, command, input_data))

    monkeypatch.setattr(GitRunner, "run", capture)
    return captured


def _complete(
    command: tuple[GitRunner, GitCommand, bytes | None], *,
    exit_code: int = 0, stdout: bytes = b"", stderr: bytes = b"",
) -> None:
    runner, request, _input = command
    runner.completed.emit(GitResult(request, exit_code, stdout, stderr))


def test_browser_sign_in_verifies_the_account_before_completing(
    commands: list[tuple[GitRunner, GitCommand, bytes | None]],
) -> None:
    network = _Network()
    flow = GitHubCredentialFlow(network=network)
    results: list[object] = []
    flow.completed.connect(results.append)
    flow.start("octocat")
    assert commands[0][1].arguments == ("credential-manager", "--version")
    assert flow.is_running
    _complete(commands[0])
    _, request, data = commands[1]
    assert request.arguments == ("credential-manager", "get")
    assert data == b"protocol=https\nhost=github.com\nusername=octocat\n\n"
    environment = dict(request.environment)
    assert environment["GCM_GITHUB_AUTHMODES"] == "browser"
    assert environment["GCM_CREDENTIAL_STORE"] == "none"
    assert environment["GCM_TRACE_SECRETS"] == "0"
    _complete(commands[1], stdout=b"username=octocat\npassword=test-token\n\n")
    assert results == []
    assert network.requests[0].url().toString() == "https://api.github.com/user"
    assert network.requests[0].rawHeader("Authorization").data() == b"Bearer test-token"
    network.replies[0].finish({"login": "octocat"})
    assert results == [SignInResult("octocat", "test-token")]
    assert not flow.is_running


def test_legacy_credential_manager_is_supported(
    commands: list[tuple[GitRunner, GitCommand, bytes | None]],
) -> None:
    flow = GitHubCredentialFlow()
    flow.start()
    _complete(commands[0], exit_code=1)
    assert commands[1][1].arguments == ("credential-manager-core", "--version")
    _complete(commands[1])
    assert commands[2][1].arguments == ("credential-manager-core", "get")
    flow.cancel()


def test_missing_helper_has_an_actionable_error(
    commands: list[tuple[GitRunner, GitCommand, bytes | None]],
) -> None:
    flow = GitHubCredentialFlow()
    errors: list[str] = []
    flow.failed.connect(errors.append)
    flow.start()
    _complete(commands[0], exit_code=1)
    _complete(commands[1], exit_code=1)
    assert len(errors) == 1
    assert "Git Credential Manager was not found" in errors[0]
    assert "Advanced" in errors[0]
    assert not flow.is_running


def test_failed_helper_does_not_expose_credential_output(
    commands: list[tuple[GitRunner, GitCommand, bytes | None]],
) -> None:
    flow = GitHubCredentialFlow()
    errors: list[str] = []
    flow.failed.connect(errors.append)
    flow.start()
    _complete(commands[0])
    _complete(commands[1], exit_code=1, stderr=b"password=private-test-token")
    assert len(errors) == 1
    assert "private-test-token" not in errors[0]
    assert not flow.is_running


def test_cancelled_attempt_cannot_complete_a_new_sign_in(
    commands: list[tuple[GitRunner, GitCommand, bytes | None]],
) -> None:
    network = _Network()
    flow = GitHubCredentialFlow(network=network)
    results: list[object] = []
    flow.completed.connect(results.append)
    flow.start()
    _complete(commands[0])
    old = commands[1]
    flow.cancel()
    flow.start()
    _complete(old, stdout=b"password=stale-token\n")
    assert not network.requests
    assert flow.is_running
    _complete(commands[2])
    _complete(commands[3], stdout=b"password=fresh-token\n")
    reply = network.replies[0]
    flow.cancel()
    assert reply.aborted
    reply.finish({"login": "stale-user"})
    assert results == []
    assert not flow.is_running


@mark.parametrize("payload", [{"message": "Bad credentials"}, {"login": ""}, {"login": 123}])
def test_invalid_user_response_does_not_connect_an_account(
    commands: list[tuple[GitRunner, GitCommand, bytes | None]], payload: dict[str, object]
) -> None:
    network = _Network()
    flow = GitHubCredentialFlow(network=network)
    results: list[object] = []
    errors: list[str] = []
    flow.completed.connect(results.append)
    flow.failed.connect(errors.append)
    flow.start()
    _complete(commands[0])
    _complete(commands[1], stdout=b"password=test-token\n")
    network.replies[0].finish(payload)
    assert not results
    assert len(errors) == 1
    assert not flow.is_running


@mark.parametrize("output", [
    b"", b"username=octocat\n", b"password=\xff\n", b"password=bad token\n",
    b"password=one\npassword=two\n", b"host=example.com\npassword=token\n",
    b"protocol=http\npassword=token\n",
])
def test_invalid_credentials_are_rejected(output: bytes) -> None:
    with raises(ValueError):
        parse_github_credential(output)


def test_timeout_stops_the_attempt_and_late_results_are_ignored(
    commands: list[tuple[GitRunner, GitCommand, bytes | None]],
) -> None:
    flow = GitHubCredentialFlow()
    errors: list[str] = []
    flow.failed.connect(errors.append)
    flow.start()
    timer = flow.findChild(QTimer)
    assert timer is not None
    timer.timeout.emit()
    assert "timed out" in errors[0]
    assert not flow.is_running
    _complete(commands[0])
    assert len(commands) == 1


def test_failure_to_start_git_allows_a_new_attempt(
    commands: list[tuple[GitRunner, GitCommand, bytes | None]],
) -> None:
    flow = GitHubCredentialFlow()
    errors: list[str] = []
    flow.failed.connect(errors.append)
    flow.start()
    commands[0][0].failed_to_start.emit("Process could not start")
    assert "Could not start Git" in errors[0]
    assert not flow.is_running
    flow.start()
    assert len(commands) == 2
    flow.shutdown()
    assert not flow.is_running


def test_login_hint_cannot_inject_credential_protocol_fields(
    commands: list[tuple[GitRunner, GitCommand, bytes | None]],
) -> None:
    flow = GitHubCredentialFlow()
    errors: list[str] = []
    flow.failed.connect(errors.append)
    flow.start("octocat\nhost=example.com")
    assert errors
    assert not commands
