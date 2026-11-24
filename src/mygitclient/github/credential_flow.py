from __future__ import annotations

from PySide6.QtCore import QByteArray, QObject, QTimer, QUrl, Signal, Slot
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply

from mygitclient.git.errors import GitNotFoundError
from mygitclient.git.models import GitCommand, GitResult
from mygitclient.git.runner import GitRunner
from mygitclient.github.browser_flow import SignInResult
from mygitclient.github.oauth_http import OAuthHttpError, json_request, reply_payload

_HELPERS = ("credential-manager", "credential-manager-core")
_TIMEOUT_MS = 5 * 60 * 1000
_ENVIRONMENT = (
    ("GCM_INTERACTIVE", "true"),
    ("GCM_GUI_PROMPT", "true"),
    ("GCM_GITHUB_AUTHMODES", "browser"),
    # Always authorize the account chosen in the browser. MyGitClient's own
    # credential store saves the result; existing Git credentials stay untouched.
    ("GCM_CREDENTIAL_STORE", "none"),
    ("GCM_TRACE", "0"),
    ("GCM_TRACE_SECRETS", "0"),
)


def parse_github_credential(output: bytes) -> str:
    fields: dict[bytes, bytes] = {}
    for line in output.splitlines():
        key, separator, value = line.partition(b"=")
        if not separator:
            continue
        if key in fields:
            raise ValueError("Git Credential Manager returned an invalid sign-in response.")
        fields[key] = value
    if (
        fields.get(b"protocol", b"https") != b"https"
        or fields.get(b"host", b"github.com") != b"github.com"
    ):
        raise ValueError("Git Credential Manager returned credentials for a different server.")
    try:
        token = fields.get(b"password", b"").decode("ascii")
    except UnicodeDecodeError as error:
        raise ValueError("Git Credential Manager returned an invalid sign-in response.") from error
    if not token or any(not 33 <= ord(character) <= 126 for character in token):
        raise ValueError("Git Credential Manager did not return a GitHub access token.")
    return token


class GitHubCredentialFlow(QObject):
    """Browser sign-in through the user's installed Git Credential Manager."""

    completed = Signal(object)
    failed = Signal(str)
    status_changed = Signal(str)

    def __init__(
        self, parent: QObject | None = None, *, network: QNetworkAccessManager | None = None
    ) -> None:
        super().__init__(parent)
        self._network = network or QNetworkAccessManager(self)
        self._runner: GitRunner | None = None
        self._reply: QNetworkReply | None = None
        self._helper_index = 0
        self._phase = ""
        self._login_hint = ""
        self._token = ""
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._timed_out)

    @property
    def is_running(self) -> bool:
        return self._runner is not None or self._reply is not None

    def start(self, login_hint: str = "") -> None:
        self.cancel()
        self._login_hint = login_hint.strip()
        if any(character in self._login_hint for character in "\r\n\0"):
            self.failed.emit("Enter a valid GitHub account name.")
            return
        self._helper_index = 0
        self._timer.start(_TIMEOUT_MS)
        self.status_changed.emit("Opening your browser to sign in to GitHub…")
        self._run_helper(probe=True)

    def _run_helper(self, *, probe: bool) -> None:
        self._phase = "probe" if probe else "authorize"
        try:
            runner = GitRunner(parent=self)
        except GitNotFoundError as error:
            self._fail(str(error))
            return
        self._runner = runner
        runner.completed.connect(self._command_completed)
        runner.failed_to_start.connect(self._start_failed)
        data = b"protocol=https\nhost=github.com\n"
        if self._login_hint:
            data += f"username={self._login_hint}\n".encode()
        command = GitCommand(
            (_HELPERS[self._helper_index], "--version" if probe else "get"),
            operation="connect GitHub account",
            environment=_ENVIRONMENT,
        )
        runner.run(command, None if probe else data + b"\n")

    @Slot(object)
    def _command_completed(self, result: object) -> None:
        runner = self.sender()
        if runner is not self._runner or not isinstance(runner, GitRunner):
            return
        self._runner = None
        runner.deleteLater()
        if not isinstance(result, GitResult):
            self._fail("Git Credential Manager returned an unexpected response.")
            return
        if result.cancelled:
            self.cancel()
            return
        if self._phase == "probe":
            if result.succeeded:
                self.status_changed.emit("Confirm access in your browser. Waiting for GitHub…")
                self._run_helper(probe=False)
            elif self._helper_index + 1 < len(_HELPERS):
                self._helper_index += 1
                self._run_helper(probe=True)
            else:
                self._fail(
                    "Git Credential Manager was not found. Install it with Git for Windows "
                    "or separately, then retry. You can also use Advanced sign-in settings."
                )
            return
        if not result.succeeded:
            # Credential-helper output can contain credentials: never echo it to
            # a dialog or a log, including on a failed or cancelled authorization.
            self._fail(
                "GitHub sign-in was not completed. Confirm access in your browser and retry."
            )
            return
        try:
            self._token = parse_github_credential(result.stdout)
        except ValueError as error:
            self._fail(str(error))
            return
        self.status_changed.emit("Finishing sign-in…")
        request = json_request(QUrl("https://api.github.com/user"))
        request.setTransferTimeout(30_000)
        request.setRawHeader(b"Authorization", QByteArray(f"Bearer {self._token}".encode("ascii")))
        reply = self._network.get(request)
        self._reply = reply
        reply.finished.connect(self._user_completed)

    @Slot()
    def _user_completed(self) -> None:
        reply = self._reply
        if reply is None or self.sender() is not reply:
            return
        self._reply = None
        try:
            payload = reply_payload(reply)
            login = payload.get("login")
            if not isinstance(login, str) or not login.strip():
                raise OAuthHttpError("GitHub did not return the authorized account name.")
        except OAuthHttpError as error:
            self._fail(str(error))
            return
        finally:
            reply.deleteLater()
        token = self._token
        self._token = ""
        self._timer.stop()
        self.completed.emit(SignInResult(login.strip(), token))

    @Slot(str)
    def _start_failed(self, _message: str) -> None:
        runner = self._runner
        if runner is None or self.sender() is not runner:
            return
        self._runner = None
        runner.deleteLater()
        self._fail("Could not start Git. Check that Git is installed, then retry.")

    def cancel(self) -> None:
        self._timer.stop()
        self._token = ""
        runner, self._runner = self._runner, None
        if runner is not None:
            runner.completed.connect(runner.deleteLater)
            runner.failed_to_start.connect(runner.deleteLater)
            runner.cancel()
            if not runner.is_running:
                runner.deleteLater()
        reply, self._reply = self._reply, None
        if reply is not None:
            reply.abort()
            reply.deleteLater()

    def shutdown(self) -> None:
        runner, self._runner = self._runner, None
        if runner is not None:
            runner.shutdown()
            runner.deleteLater()
        self.cancel()

    def _timed_out(self) -> None:
        self._fail(
            "GitHub sign-in timed out. Try again when you are ready to confirm in the browser."
        )

    def _fail(self, message: str) -> None:
        self.cancel()
        self.failed.emit(message)
