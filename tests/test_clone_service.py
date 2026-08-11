import subprocess
from pathlib import Path

from pytestqt.qtbot import QtBot

from mygitclient.git.clone_service import (
    CloneService,
    is_valid_clone_folder_name,
    suggested_clone_name,
)


def test_suggested_clone_name_supports_https_and_ssh() -> None:
    assert suggested_clone_name("https://github.com/example/project.git") == "project"
    assert suggested_clone_name("git@github.com:example/project.git") == "project"


def test_clone_folder_name_must_be_a_single_path_component() -> None:
    assert is_valid_clone_folder_name("project")
    assert not is_valid_clone_folder_name("")
    assert not is_valid_clone_folder_name("..")
    assert not is_valid_clone_folder_name("parent/project")
    assert not is_valid_clone_folder_name("parent\\project")


def test_clone_service_clones_repository(qtbot: QtBot, tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    subprocess.run(
        ["git", "init", "--initial-branch=main"],
        cwd=source,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=MyGitClient Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "--allow-empty",
            "-m",
            "initial",
        ],
        cwd=source,
        check=True,
        capture_output=True,
    )
    target = tmp_path / "clone"
    service = CloneService()
    completed: list[object] = []
    service.completed.connect(completed.append)

    with qtbot.waitSignal(service.completed, timeout=5000):
        assert service.clone(source.as_uri(), target)

    assert completed == [target]
    assert (target / ".git").is_dir()
