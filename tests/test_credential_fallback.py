from pathlib import Path

from pytest import MonkeyPatch
from pytestqt.qtbot import QtBot

from mygitclient.git.clone_service import CloneService
from mygitclient.git.errors import is_credential_failure
from mygitclient.git.models import GitCommand, GitResult
from mygitclient.git.runner import GitRunner
from mygitclient.git.service import GitService

_TOKEN = "stored-github-token"
_URL = "https://github.com/example/project.git"


def _capture_commands(
    monkeypatch: MonkeyPatch,
) -> tuple[list[GitRunner], list[GitCommand]]:
    """Stop Git from actually running and record what each runner was asked to do."""
    runners: list[GitRunner] = []
    commands: list[GitCommand] = []

    def capture(
        self: GitRunner, command: GitCommand, input_data: bytes | None = None
    ) -> None:
        runners.append(self)
        commands.append(command)

    monkeypatch.setattr(GitRunner, "run", capture)
    return runners, commands


def _has_token_header(command: GitCommand) -> bool:
    return any("extraheader" in argument for argument in command.arguments)


def test_credential_failure_covers_github_not_found_and_auth_wording() -> None:
    assert is_credential_failure("remote: Repository not found.")
    assert is_credential_failure("fatal: Authentication failed for 'https://github.com/x'")
    assert is_credential_failure(
        "fatal: could not read Username for 'https://github.com': terminal prompts disabled"
    )
    assert is_credential_failure("remote: Invalid username or password.")


def test_credential_failure_covers_a_push_refused_for_the_wrong_account() -> None:
    # A public repository fetches fine for anyone, so only the push is refused.
    assert is_credential_failure(
        "remote: Permission to owner/project.git denied to other-account.\n"
        "fatal: unable to access 'https://github.com/owner/project.git/': "
        "The requested URL returned error: 403"
    )


def test_unrelated_failures_are_not_credential_failures() -> None:
    assert not is_credential_failure("fatal: could not resolve host: github.com")
    assert not is_credential_failure("error: failed to push some refs (non-fast-forward)")
    assert not is_credential_failure("CONFLICT (content): Merge conflict in a.txt")
    assert not is_credential_failure("error: unable to unlink old file: Permission denied")


def test_clone_does_not_send_the_stored_token_on_the_first_attempt(
    qtbot: QtBot, tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    _, commands = _capture_commands(monkeypatch)
    service = CloneService()

    assert service.clone(_URL, tmp_path / "clone", token=_TOKEN)

    assert len(commands) == 1
    assert not _has_token_header(commands[0])
    assert commands[0].arguments[0] == "clone"


def test_clone_retries_with_the_stored_token_after_a_credential_failure(
    qtbot: QtBot, tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    runners, commands = _capture_commands(monkeypatch)
    service = CloneService()
    failures: list[str] = []
    service.failed.connect(failures.append)
    service.clone(_URL, tmp_path / "clone", token=_TOKEN)

    runners[0].completed.emit(
        GitResult(commands[0], 128, b"", b"remote: Repository not found.")
    )

    assert len(commands) == 2
    assert _has_token_header(commands[1])
    assert commands[1].arguments[-1] == commands[0].arguments[-1]
    assert failures == []


def test_clone_reports_a_second_credential_failure_instead_of_looping(
    qtbot: QtBot, tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    runners, commands = _capture_commands(monkeypatch)
    service = CloneService()
    failures: list[str] = []
    service.failed.connect(failures.append)
    service.clone(_URL, tmp_path / "clone", token=_TOKEN)
    runners[0].completed.emit(
        GitResult(commands[0], 128, b"", b"remote: Repository not found.")
    )

    runners[1].completed.emit(
        GitResult(commands[1], 128, b"", b"remote: Repository not found.")
    )

    assert len(commands) == 2
    assert len(failures) == 1


def test_clone_does_not_retry_when_the_failure_is_unrelated_to_credentials(
    qtbot: QtBot, tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    runners, commands = _capture_commands(monkeypatch)
    service = CloneService()
    failures: list[str] = []
    service.failed.connect(failures.append)
    service.clone(_URL, tmp_path / "clone", token=_TOKEN)

    runners[0].completed.emit(
        GitResult(commands[0], 128, b"", b"fatal: could not resolve host: github.com")
    )

    assert len(commands) == 1
    assert len(failures) == 1


def test_fetch_pull_and_push_do_not_send_the_stored_token_on_the_first_attempt(
    qtbot: QtBot, tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    _, commands = _capture_commands(monkeypatch)
    # The operation queue runs one command at a time, so each request needs its own
    # service to be dispatched immediately rather than left pending behind the others.
    GitService().request_fetch(tmp_path, token=_TOKEN)
    GitService().request_pull(tmp_path, rebase=False, autostash=False, token=_TOKEN)
    GitService().request_push(tmp_path, branch="main", set_upstream=False, token=_TOKEN)
    GitService().request_reset_to_upstream(tmp_path, token=_TOKEN)

    assert [command.arguments[0] for command in commands] == [
        "fetch",
        "pull",
        "push",
        "fetch",
    ]
    assert not any(_has_token_header(command) for command in commands)


def test_fetch_retries_with_the_stored_token_after_a_credential_failure(
    qtbot: QtBot, tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    runners, commands = _capture_commands(monkeypatch)
    service = GitService()
    failures: list[str] = []
    service.operation_failed.connect(failures.append)
    service.request_fetch(tmp_path, token=_TOKEN)

    runners[0].completed.emit(
        GitResult(commands[0], 128, b"", b"fatal: Authentication failed for 'x'")
    )

    qtbot.waitUntil(lambda: len(commands) == 2, timeout=2000)
    assert _has_token_header(commands[1])
    assert "fetch" in commands[1].arguments
    assert failures == []


def test_reset_to_upstream_retries_its_fetch_with_the_stored_token(
    qtbot: QtBot, tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    runners, commands = _capture_commands(monkeypatch)
    service = GitService()
    failures: list[str] = []
    service.operation_failed.connect(failures.append)
    service.request_reset_to_upstream(tmp_path, token=_TOKEN)

    runners[0].completed.emit(
        GitResult(commands[0], 128, b"", b"remote: Repository not found.")
    )

    qtbot.waitUntil(lambda: len(commands) == 2, timeout=2000)
    assert _has_token_header(commands[1])
    assert "fetch" in commands[1].arguments
    assert failures == []


def test_fetch_without_a_stored_token_reports_the_failure(
    qtbot: QtBot, tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    runners, commands = _capture_commands(monkeypatch)
    service = GitService()
    failures: list[str] = []
    service.operation_failed.connect(failures.append)
    service.request_fetch(tmp_path)

    runners[0].completed.emit(
        GitResult(commands[0], 128, b"", b"fatal: Authentication failed for 'x'")
    )

    assert len(commands) == 1
    assert len(failures) == 1
