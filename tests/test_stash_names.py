from __future__ import annotations

import subprocess
from pathlib import Path

from PySide6.QtCore import QPoint, QSettings, Qt
from PySide6.QtGui import QAction
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QTreeWidget, QWidget
from pytest import MonkeyPatch, fixture, mark, raises
from pytestqt.qtbot import QtBot

from mygitclient.git.models import (
    BranchesSnapshot,
    BranchInfo,
    FileStatus,
    GitCommand,
    GitResult,
    StashesSnapshot,
    StashInfo,
)
from mygitclient.git.parsers import parse_stashes
from mygitclient.git.runner import GitRunner
from mygitclient.git.service import GitService
from mygitclient.git.stashes import DEFAULT_STASH_MESSAGE, renamed_stash_commit
from mygitclient.theme import Theme
from mygitclient.ui.main_window import MainWindow
from mygitclient.ui.refs_panel import RefsPanel
from mygitclient.ui.stash_name_dialog import StashNameDialog


def _git(repository: Path, *arguments: str) -> bytes:
    return subprocess.check_output(
        ["git", "-C", str(repository), "-c", "user.name=Stash Test",
         "-c", "user.email=stash@example.invalid", *arguments],
        stderr=subprocess.PIPE,
    )


@fixture
def repository(tmp_path: Path, monkeypatch: MonkeyPatch) -> Path:
    # The application commands also need an identity, independent of global Git config.
    for role in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{role}_NAME", "Stash Test")
        monkeypatch.setenv(f"GIT_{role}_EMAIL", "stash@example.invalid")
    _git(tmp_path, "init", "--initial-branch=main")
    (tmp_path / "tracked.txt").write_text("base\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "base")
    return tmp_path


def _stashes(repository: Path) -> StashesSnapshot:
    return parse_stashes(
        repository, _git(repository, "stash", "list", "--format=%gd%x00%H%x00%gs%x1e")
    )


@mark.parametrize("name", [DEFAULT_STASH_MESSAGE, "Работа над фильтром"])
def test_stash_creation_uses_the_requested_name(
    qtbot: QtBot, repository: Path, name: str
) -> None:
    tracked = repository / "tracked.txt"
    tracked.write_text("changed\n", encoding="utf-8")
    service = GitService()
    with qtbot.waitSignal(service.mutation_ready, timeout=5000):
        service.request_stash_files(
            repository, (FileStatus("tracked.txt", ".", "M"),), message=name
        )
    assert tracked.read_text(encoding="utf-8") == "base\n"
    assert _stashes(repository).stashes[0].subject == f"On main: {name}"


@mark.parametrize("index", [0, 1, 2])
def test_rename_preserves_stash_trees_parents_and_other_entries(
    qtbot: QtBot, repository: Path, index: int
) -> None:
    for number in range(3):
        (repository / "tracked.txt").write_text(f"staged {number}\n", encoding="utf-8")
        _git(repository, "add", "tracked.txt")
        (repository / "tracked.txt").write_text(f"unstaged {number}\n", encoding="utf-8")
        (repository / f"new-{number}.txt").write_text("untracked\n", encoding="utf-8")
        _git(repository, "stash", "push", "-u", "-m", f"original {number}")
    before = _stashes(repository).stashes
    target = before[index]
    service = GitService()
    with qtbot.waitSignal(service.mutation_ready, timeout=5000):
        service.request_rename_stash(repository, target, "Новое имя")
    after = _stashes(repository).stashes
    assert len(after) == 3
    assert after[0].subject == "Новое имя"
    assert after[0].oid != target.oid
    assert [stash.oid for stash in after[1:]] == [
        stash.oid for position, stash in enumerate(before) if position != index
    ]
    old_header = _git(repository, "cat-file", "commit", target.oid).partition(b"\n\n")[0]
    new_header = _git(repository, "cat-file", "commit", after[0].oid).partition(b"\n\n")[0]
    assert new_header == old_header
    assert _git(repository, "status", "--porcelain") == b""
    _git(repository, "stash", "apply", "--index", after[0].ref)
    number = 2 - index
    assert (repository / "tracked.txt").read_text(encoding="utf-8") == f"unstaged {number}\n"
    assert _git(repository, "show", ":tracked.txt") == f"staged {number}\n".encode()
    assert (repository / f"new-{number}.txt").read_text(encoding="utf-8") == "untracked\n"


@mark.parametrize("change_after_store", [False, True])
def test_rename_keeps_all_stashes_if_the_list_changes(
    qtbot: QtBot, monkeypatch: MonkeyPatch, repository: Path, change_after_store: bool
) -> None:
    (repository / "tracked.txt").write_text("changed\n", encoding="utf-8")
    _git(repository, "stash", "push", "-m", "original")
    original = _stashes(repository).stashes[0]
    saved_run = GitRunner.run

    def intercept_run(
        runner: GitRunner, command: GitCommand, input_data: bytes | None = None
    ) -> None:
        if command.arguments[:2] == ("rev-parse", "--revs-only"):
            (repository / "tracked.txt").write_text("outside change\n", encoding="utf-8")
            _git(repository, "stash", "push", "-m", "external")
        saved_run(runner, command, input_data)

    if change_after_store:
        monkeypatch.setattr(GitRunner, "run", intercept_run)
    else:
        (repository / "tracked.txt").write_text("outside change\n", encoding="utf-8")
        _git(repository, "stash", "push", "-m", "external")
    service = GitService()
    with qtbot.waitSignal(service.operation_failed, timeout=5000):
        service.request_rename_stash(repository, original, "new name")
    stashes = _stashes(repository).stashes
    assert original.oid in {stash.oid for stash in stashes}
    assert any("external" in stash.subject for stash in stashes)
    assert len(stashes) == (3 if change_after_store else 2)
    if change_after_store:
        assert any(stash.subject == "new name" for stash in stashes)
    qtbot.waitUntil(lambda: not service.findChildren(GitRunner), timeout=5000)


def test_stash_name_dialog_uses_a_placeholder_and_accepts_enter(qtbot: QtBot) -> None:
    parent = QWidget()
    qtbot.addWidget(parent)
    dialog = StashNameDialog(parent)
    dialog.show()
    assert dialog.name_edit.text() == ""
    assert dialog.name_edit.placeholderText() == DEFAULT_STASH_MESSAGE
    QTest.keyClick(dialog.name_edit, Qt.Key.Key_Return)
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.stash_name == DEFAULT_STASH_MESSAGE


@mark.parametrize("name", [None, "", "My saved work"])
def test_manual_stash_prompts_before_changing_files(
    qtbot: QtBot, monkeypatch: MonkeyPatch, repository: Path, name: str | None
) -> None:
    tracked = repository / "tracked.txt"
    tracked.write_text("changed\n", encoding="utf-8")
    settings = QSettings(str(repository / "../ui.ini"), QSettings.Format.IniFormat)
    settings.setValue("changes/presentationMode", "split")
    window = MainWindow(settings, Theme.SYSTEM)
    qtbot.addWidget(window)
    window.open_repository(repository)
    tree = window.findChild(QTreeWidget, "unstagedChangesTree")
    action = window.findChild(QAction, "stashSelectedAction")
    service = window.findChild(GitService)
    assert tree is not None and action is not None and service is not None
    qtbot.waitUntil(lambda: tree.topLevelItemCount() == 1, timeout=5000)
    item = tree.topLevelItem(0)
    assert item is not None
    tree.setCurrentItem(item)
    prompted: list[bool] = []

    def respond(dialog: StashNameDialog) -> QDialog.DialogCode:
        prompted.append(True)
        assert tracked.read_text(encoding="utf-8") == "changed\n"
        assert dialog.name_edit.text() == ""
        assert dialog.name_edit.placeholderText() == DEFAULT_STASH_MESSAGE
        if name is None:
            return QDialog.DialogCode.Rejected
        dialog.name_edit.setText(name)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(StashNameDialog, "exec", respond)
    assert action.isEnabled()
    if name is None:
        action.trigger()
        assert _stashes(repository).stashes == ()
        assert tracked.read_text(encoding="utf-8") == "changed\n"
        assert tree.isEnabled()
    else:
        with qtbot.waitSignal(service.mutation_ready, timeout=5000):
            action.trigger()
        expected_name = name or DEFAULT_STASH_MESSAGE
        assert _stashes(repository).stashes[0].subject == f"On main: {expected_name}"
    assert prompted == [True]
    window.close()


@mark.parametrize("accepted", [False, True])
def test_context_menu_rename_prompts_and_updates_the_stash(
    qtbot: QtBot, monkeypatch: MonkeyPatch, repository: Path, accepted: bool
) -> None:
    (repository / "tracked.txt").write_text("changed\n", encoding="utf-8")
    _git(repository, "stash", "push", "-m", "old name")
    settings = QSettings(str(repository / "../rename.ini"), QSettings.Format.IniFormat)
    window = MainWindow(settings, Theme.SYSTEM)
    qtbot.addWidget(window)
    window.open_repository(repository)
    panel = window.findChild(RefsPanel)
    service = window.findChild(GitService)
    assert panel is not None and service is not None

    def stash_is_listed() -> bool:
        root = panel.tree.topLevelItem(3)
        return root is not None and root.childCount() == 1

    qtbot.waitUntil(stash_is_listed, timeout=5000)
    root = panel.tree.topLevelItem(3)
    assert root is not None
    item = root.child(0)
    assert item is not None
    panel.tree.setCurrentItem(item)

    def respond(dialog: StashNameDialog) -> QDialog.DialogCode:
        assert dialog.name_edit.text() == "On main: old name"
        dialog.name_edit.setText("renamed work")
        return QDialog.DialogCode.Accepted if accepted else QDialog.DialogCode.Rejected

    monkeypatch.setattr(StashNameDialog, "exec", respond)
    if accepted:
        with qtbot.waitSignal(service.mutation_ready, timeout=5000):
            panel.rename_stash_action.trigger()
    else:
        panel.rename_stash_action.trigger()
    assert _stashes(repository).stashes[0].subject == (
        "renamed work" if accepted else "On main: old name"
    )
    qtbot.waitUntil(panel.isEnabled, timeout=5000)
    window.close()


def test_rename_is_offered_in_the_stash_context_menu_only(
    qtbot: QtBot, monkeypatch: MonkeyPatch
) -> None:
    panel = RefsPanel()
    qtbot.addWidget(panel)
    panel.show_branches(BranchesSnapshot(
        Path("repository"), (BranchInfo("refs/heads/main", "main", "1" * 40, False),)
    ))
    panel.show_stashes(StashesSnapshot(
        Path("repository"), (StashInfo("stash@{0}", "2" * 40, "saved work"),)
    ))
    panel.show()
    offered: list[bool] = []

    def inspect_menu(_position: QPoint) -> None:
        offered.append(panel.rename_stash_action.isVisible())

    monkeypatch.setattr(panel.context_menu, "exec", inspect_menu)
    for index in (3, 0):
        root = panel.tree.topLevelItem(index)
        assert root is not None
        item = root.child(0)
        assert item is not None
        panel.tree.scrollToItem(item)
        panel.tree.customContextMenuRequested.emit(panel.tree.visualItemRect(item).center())
    assert offered == [True, False]


@mark.parametrize("phase", ["store", "verify-copy", "drop-original"])
@mark.parametrize("outcome", ["failure", "cancelled", "start-error"])
def test_failed_rename_never_loses_the_original_stash(
    qtbot: QtBot, monkeypatch: MonkeyPatch, repository: Path, phase: str, outcome: str
) -> None:
    (repository / "tracked.txt").write_text("changed\n", encoding="utf-8")
    _git(repository, "stash", "push", "-m", "original")
    original = _stashes(repository).stashes[0]
    saved_run = GitRunner.run
    prefixes = {
        "store": ("stash", "store"), "verify-copy": ("rev-parse", "--revs-only"),
        "drop-original": ("stash", "drop"),
    }

    def intercept_run(
        runner: GitRunner, command: GitCommand, input_data: bytes | None = None
    ) -> None:
        if command.arguments[:2] != prefixes[phase]:
            saved_run(runner, command, input_data)
        elif outcome == "start-error":
            runner.failed_to_start.emit("Could not start Git")
        else:
            runner.completed.emit(GitResult(
                command, 1, b"", b"Simulated failure", cancelled=outcome == "cancelled"
            ))

    monkeypatch.setattr(GitRunner, "run", intercept_run)
    service = GitService()
    with qtbot.waitSignal(service.operation_failed, timeout=5000):
        service.request_rename_stash(repository, original, "new name")
    after = _stashes(repository).stashes
    assert original.oid in {stash.oid for stash in after}
    assert len(after) == (1 if phase == "store" else 2)
    qtbot.waitUntil(lambda: not service.findChildren(GitRunner), timeout=5000)


def test_stash_name_dialog_can_be_cancelled(qtbot: QtBot) -> None:
    parent = QWidget()
    qtbot.addWidget(parent)
    dialog = StashNameDialog(parent, current_name="Old name")
    dialog.show()
    assert dialog.name_edit.text() == "Old name"
    dialog.name_edit.setText("New name")
    buttons = dialog.findChild(QDialogButtonBox)
    assert buttons is not None
    buttons.button(QDialogButtonBox.StandardButton.Cancel).click()
    assert dialog.result() == QDialog.DialogCode.Rejected


def test_renamed_commit_keeps_raw_headers_and_removes_invalid_signature() -> None:
    header = (
        b"tree " + b"1" * 40 + b"\nparent " + b"2" * 40 + b"\nparent " + b"3" * 40
        + b"\nauthor Name \xff <test@example.invalid> 1000 +0000"
        + b"\ncommitter Name <test@example.invalid> 1000 +0000"
    )
    content = header + b"\ngpgsig signature\n continuation\n\nOld name\n"
    assert renamed_stash_commit(content, "Новое") == header + "\n\nНовое\n".encode()
    assert renamed_stash_commit(header + b"\n\nOld name\n\nDetails\xff\n", "New name") == (
        header + b"\n\nNew name\n\nDetails\xff\n"
    )


@mark.parametrize("message", ["", "  ", "one\ntwo", "bad\0name", "bad\tname"])
def test_invalid_stash_names_are_rejected(repository: Path, message: str) -> None:
    service = GitService()
    with raises(ValueError):
        service.request_stash_files(repository, (), message=message)
    with raises(ValueError):
        service.request_rename_stash(repository, StashInfo("stash@{0}", "1" * 40, "old"), message)
