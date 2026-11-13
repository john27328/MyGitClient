from __future__ import annotations

import subprocess
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QMenu,
    QMessageBox,
    QWidget,
)
from pytest import MonkeyPatch
from pytestqt.qtbot import QtBot

from mygitclient.git.models import BranchInfo, CommitPage, CommitSummary
from mygitclient.git.service import GitService
from mygitclient.theme import Theme
from mygitclient.ui.commit_message_dialog import CommitMessageDialog
from mygitclient.ui.history_panel import HistoryPanel, is_commit_chain
from mygitclient.ui.interactive_rebase import InteractiveRebaseDialog
from mygitclient.ui.main_window import MainWindow
from mygitclient.ui.refs_panel import RefsPanel


def _commit(oid: str, subject: str, *parents: str) -> CommitSummary:
    return CommitSummary(
        oid=oid,
        parent_oids=parents,
        author_name="Test Author",
        author_email="author@example.invalid",
        authored_at="2026-07-17T10:30:00+03:00",
        subject=subject,
    )


FIRST = _commit("1" * 40, "first", "0" * 40)
SECOND = _commit("2" * 40, "second", "1" * 40)
THIRD = _commit("3" * 40, "third", "2" * 40)


def test_commit_chain_needs_adjacent_commits_oldest_first() -> None:
    assert is_commit_chain((FIRST, SECOND, THIRD))
    assert not is_commit_chain((FIRST, THIRD))
    assert not is_commit_chain((SECOND, FIRST))
    assert not is_commit_chain((FIRST,))


def _menu_choice(
    panel: HistoryPanel, rows: tuple[int, ...], label: str
) -> dict[str, bool]:
    panel.tree.clearSelection()
    for row in rows:
        item = panel.tree.topLevelItem(row)
        assert item is not None
        item.setSelected(True)
    states: dict[str, bool] = {}

    def choose() -> None:
        popup = QApplication.activePopupWidget()
        if not isinstance(popup, QMenu):
            return
        try:
            for action in popup.actions():
                if action.text().startswith(("Drop", "Squash")):
                    states[action.text()] = action.isEnabled()
            action = next(a for a in popup.actions() if a.text().startswith(label))
            if action.isEnabled():
                popup.setActiveAction(action)
                QTest.keyClick(popup, Qt.Key.Key_Return)
        finally:
            popup.close()

    item = panel.tree.topLevelItem(rows[0])
    assert item is not None
    QTimer.singleShot(0, choose)
    panel.tree.customContextMenuRequested.emit(panel.tree.visualItemRect(item).center())
    return states


def test_history_menu_drops_and_squashes_selected_commits(qtbot: QtBot) -> None:
    panel = HistoryPanel()
    qtbot.addWidget(panel)
    panel.resize(900, 400)
    panel.show()
    panel.show_page(CommitPage(Path("repository"), (THIRD, SECOND, FIRST), 0, False))
    dropped: list[object] = []
    squashed: list[object] = []
    panel.drop_commits_requested.connect(dropped.append)
    panel.squash_commits_requested.connect(squashed.append)

    adjacent = _menu_choice(panel, (0, 1), "Squash")
    apart = _menu_choice(panel, (0, 2), "Squash")
    _menu_choice(panel, (0, 2), "Drop")

    assert adjacent == {"Drop 2 commits…": True, "Squash 2 commits…": True}
    assert apart == {"Drop 2 commits…": True, "Squash 2 commits…": False}
    assert squashed == [(SECOND, THIRD)]
    assert dropped == [(FIRST, THIRD)]


def test_history_menu_squashes_a_commit_into_the_previous_one(qtbot: QtBot) -> None:
    panel = HistoryPanel()
    qtbot.addWidget(panel)
    panel.resize(900, 400)
    panel.show()
    panel.show_page(CommitPage(Path("repository"), (THIRD, SECOND, FIRST), 0, False))
    squashed: list[object] = []
    rebased: list[object] = []
    panel.squash_commits_requested.connect(squashed.append)
    panel.interactive_rebase_from_requested.connect(rebased.append)

    middle = _menu_choice(panel, (1,), "Squash into previous")
    # FIRST's parent is not loaded, so there is nothing to squash it into.
    oldest = _menu_choice(panel, (2,), "Squash into previous")
    _menu_choice(panel, (1,), "Interactive rebase from here")

    assert middle["Squash into previous commit…"]
    assert not oldest["Squash into previous commit…"]
    assert squashed == [(FIRST, SECOND)]
    assert rebased == [SECOND]


def _repository(path: Path) -> Path:
    path.mkdir()

    def git(*arguments: str) -> None:
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=MyGitClient Test",
                "-c",
                "user.email=test@example.invalid",
                *arguments,
            ],
            cwd=path,
            check=True,
            capture_output=True,
        )

    git("init", "--initial-branch=main")
    # Replays run through QProcess and need a committer identity as well as the
    # explicit identity used to create the fixture's original commits.
    git("config", "user.name", "MyGitClient Test")
    git("config", "user.email", "test@example.invalid")
    for name in ("base", "first", "second", "third"):
        (path / f"{name}.txt").write_text(f"{name}\n", encoding="utf-8")
        git("add", f"{name}.txt")
        git("commit", "-m", name)
    return path


def _subjects(repository: Path) -> list[str]:
    return subprocess.check_output(
        ["git", "log", "--format=%s"], cwd=repository, text=True
    ).splitlines()


def _loaded_commits(qtbot: QtBot, window: MainWindow) -> tuple[CommitSummary, ...]:
    history = window.findChild(HistoryPanel)
    assert history is not None
    qtbot.waitUntil(lambda: history.commit_count == 4, timeout=5000)
    commits: list[CommitSummary] = []
    for row in range(history.tree.topLevelItemCount()):
        item = history.tree.topLevelItem(row)
        assert item is not None
        value = item.data(0, Qt.ItemDataRole.UserRole)
        assert isinstance(value, CommitSummary)
        commits.append(value)
    return tuple(reversed(commits))


def _close_rebase_report(monkeypatch: MonkeyPatch) -> None:
    def no_report(_box: QMessageBox) -> int:
        return int(QMessageBox.StandardButton.Close.value)

    def unexpected_error(_parent: QWidget | None, title: str, message: str) -> None:
        raise AssertionError(f"Unexpected Git error in {title}: {message}")

    monkeypatch.setattr(QMessageBox, "exec", no_report)
    monkeypatch.setattr(QMessageBox, "critical", unexpected_error)


def test_main_window_drops_commits_after_confirmation(
    qapp: QApplication, qtbot: QtBot, tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    repository = _repository(tmp_path / "drop")
    window = MainWindow(
        QSettings(str(tmp_path / "drop.ini"), QSettings.Format.IniFormat), Theme.SYSTEM
    )
    window.show()
    window.open_repository(repository)
    _base, first, _second, third = _loaded_commits(qtbot, window)
    history = window.findChild(HistoryPanel)
    assert history is not None
    questions: list[str] = []
    answers = [QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Yes]

    def confirm(_parent: QWidget, _title: str, text: str, *_args: object) -> object:
        questions.append(text)
        return answers.pop(0)

    monkeypatch.setattr(QMessageBox, "warning", confirm)
    _close_rebase_report(monkeypatch)

    history.drop_commits_requested.emit((first, third))
    assert _subjects(repository) == ["third", "second", "first", "base"]
    history.drop_commits_requested.emit((first, third))

    qtbot.waitUntil(lambda: _subjects(repository) == ["second", "base"], timeout=15000)
    assert "Remove these 2 commits from main?" in questions[0]
    assert "third" in questions[0] and "first" in questions[0]
    window.close()


def test_main_window_squashes_commits_with_an_edited_message(
    qapp: QApplication, qtbot: QtBot, tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    repository = _repository(tmp_path / "squash")
    window = MainWindow(
        QSettings(str(tmp_path / "squash.ini"), QSettings.Format.IniFormat), Theme.SYSTEM
    )
    window.show()
    window.open_repository(repository)
    _base, first, second, _third = _loaded_commits(qtbot, window)
    history = window.findChild(HistoryPanel)
    assert history is not None
    prefilled: list[tuple[str, str]] = []

    def edit_message(dialog: CommitMessageDialog) -> int:
        prefilled.append((dialog.subject, dialog.description))
        dialog.subject_edit.setText("first and second")
        dialog.description_edit.setPlainText("")
        return int(QDialog.DialogCode.Accepted.value)

    def approve(*_args: object) -> object:
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(CommitMessageDialog, "exec", edit_message)
    monkeypatch.setattr(QMessageBox, "question", approve)
    _close_rebase_report(monkeypatch)

    history.squash_commits_requested.emit((first, second))

    qtbot.waitUntil(
        lambda: _subjects(repository) == ["third", "first and second", "base"], timeout=15000
    )
    assert prefilled == [("first", "second")]
    window.close()


def test_main_window_runs_an_interactive_rebase_from_a_history_commit(
    qapp: QApplication, qtbot: QtBot, tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    repository = _repository(tmp_path / "interactive")
    window = MainWindow(
        QSettings(str(tmp_path / "interactive.ini"), QSettings.Format.IniFormat), Theme.SYSTEM
    )
    window.show()
    window.open_repository(repository)
    _base, _first, second, _third = _loaded_commits(qtbot, window)
    history = window.findChild(HistoryPanel)
    assert history is not None
    listed: list[list[str]] = []

    def drop_newest(dialog: InteractiveRebaseDialog) -> int:
        rows = [dialog.tree.topLevelItem(row) for row in range(dialog.tree.topLevelItemCount())]
        listed.append([item.text(2) for item in rows if item is not None])
        newest = rows[-1]
        assert newest is not None
        combo = dialog.tree.itemWidget(newest, 0)
        assert isinstance(combo, QComboBox)
        combo.setCurrentText("drop")
        return int(QDialog.DialogCode.Accepted.value)

    monkeypatch.setattr(InteractiveRebaseDialog, "exec", drop_newest)
    _close_rebase_report(monkeypatch)

    history.interactive_rebase_from_requested.emit(second)

    qtbot.waitUntil(lambda: _subjects(repository) == ["second", "first", "base"], timeout=15000)
    assert listed == [["second", "third"]]
    window.close()


def test_rebase_range_refuses_a_commit_from_another_branch(
    qtbot: QtBot, tmp_path: Path
) -> None:
    repository = _repository(tmp_path / "range")

    def git(*arguments: str) -> None:
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=MyGitClient Test",
                "-c",
                "user.email=test@example.invalid",
                *arguments,
            ],
            cwd=repository,
            check=True,
            capture_output=True,
        )

    git("switch", "-c", "other")
    git("commit", "--allow-empty", "-m", "elsewhere")
    oid = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repository, text=True
    ).strip()
    parent = subprocess.check_output(
        ["git", "rev-parse", "HEAD~1"], cwd=repository, text=True
    ).strip()
    git("switch", "main")
    git("commit", "--allow-empty", "-m", "main work")
    service = GitService()
    errors: list[str] = []
    service.operation_failed.connect(errors.append)

    with qtbot.waitSignal(service.operation_failed, timeout=15000):
        service.request_rebase_range(repository, _commit(oid, "elsewhere", parent))

    assert errors == ["The selected commit is not part of the current branch."]


def test_rebasing_a_branch_without_own_commits_moves_it_to_the_target(
    qapp: QApplication, qtbot: QtBot, tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    repository = _repository(tmp_path / "behind")
    subprocess.run(
        ["git", "switch", "-c", "topic", "HEAD~2"], cwd=repository, check=True, capture_output=True
    )
    main_oid = subprocess.check_output(
        ["git", "rev-parse", "main"], cwd=repository, text=True
    ).strip()
    target = BranchInfo("refs/heads/main", "main", main_oid, remote=False)
    window = MainWindow(
        QSettings(str(tmp_path / "behind.ini"), QSettings.Format.IniFormat), Theme.SYSTEM
    )
    refs = window.findChild(RefsPanel)
    assert refs is not None
    questions: list[str] = []
    notices: list[str] = []

    def approve(_parent: QWidget, _title: str, text: str, *_args: object) -> object:
        questions.append(text)
        return QMessageBox.StandardButton.Yes

    def notice(_parent: QWidget, _title: str, text: str, *_args: object) -> object:
        notices.append(text)
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "question", approve)
    monkeypatch.setattr(QMessageBox, "information", notice)
    window.show()
    window.open_repository(repository)
    qtbot.waitUntil(lambda: window.windowTitle().startswith("behind — topic —"), timeout=5000)

    refs.rebase_requested.emit(target)

    def head() -> str:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=repository, text=True
        ).strip()

    qtbot.waitUntil(lambda: head() == main_oid, timeout=15000)
    assert questions and "has no commits of its own" in questions[0]
    branch = subprocess.check_output(
        ["git", "branch", "--show-current"], cwd=repository, text=True
    ).strip()
    assert branch == "topic"

    qtbot.waitUntil(lambda: refs.isEnabled(), timeout=5000)
    refs.rebase_requested.emit(target)
    qtbot.waitUntil(lambda: bool(notices), timeout=5000)
    assert notices == ["topic already points at main."]
    window.close()
