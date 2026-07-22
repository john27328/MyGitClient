from __future__ import annotations

import subprocess
from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QToolBar,
    QToolButton,
    QTreeWidget,
    QWidget,
)
from pytest import MonkeyPatch
from pytestqt.qtbot import QtBot

from mygitclient.git.models import (
    BranchesSnapshot,
    BranchInfo,
    BranchStatus,
    RepositoryStatus,
)
from mygitclient.git.service import GitService
from mygitclient.theme import Theme
from mygitclient.ui.main_window import MainWindow, push_requires_rewrite, sync_action_labels
from mygitclient.ui.refs_panel import RefsPanel


def test_main_window_is_created(qapp: QApplication) -> None:
    settings = QSettings(QSettings.Format.IniFormat, QSettings.Scope.UserScope, "test", "app")
    settings.clear()
    window = MainWindow(settings, Theme.SYSTEM)

    assert window.windowTitle() == "MyGitClient"
    assert window.centralWidget() is not None
    tabs = window.findChild(QTabWidget, "workspaceTabs")
    assert tabs is not None
    assert tabs.count() == 2
    assert not window.windowIcon().isNull()
    toolbar = window.findChild(QToolBar, "repositoryToolbar")
    refresh_action = window.findChild(QAction, "refreshAction")
    fetch_action = window.findChild(QAction, "fetchAction")
    push_action = window.findChild(QAction, "pushAction")
    pull_action = window.findChild(QAction, "pullAction")
    pull_button = window.findChild(QToolButton, "pullButton")
    pull_rebase = window.findChild(QAction, "pullRebaseAction")
    pull_autostash = window.findChild(QAction, "pullAutostashAction")
    font_sizes = window.findChild(QAction, "fontSizesAction")
    assert toolbar is not None
    assert refresh_action is not None
    assert fetch_action is not None
    assert push_action is not None
    assert pull_action is not None
    assert pull_button is not None
    assert pull_rebase is not None
    assert pull_autostash is not None
    assert font_sizes is not None
    assert not fetch_action.icon().isNull()
    assert not push_action.icon().isNull()
    assert not pull_action.icon().isNull()
    assert pull_button.popupMode() is QToolButton.ToolButtonPopupMode.MenuButtonPopup
    assert not pull_rebase.icon().isNull()
    assert not pull_autostash.icon().isNull()
    pull_rebase.trigger()
    pull_autostash.trigger()
    assert pull_action.text() == "Pull · Rebase · Stash"

    pull_label, push_label = sync_action_labels(
        RepositoryStatus(
            branch=BranchStatus(
                head="feature", upstream="origin/feature", ahead=3, behind=2
            )
        ),
        rebase=True,
        autostash=True,
    )
    assert pull_label == "Pull ↓2 · Rebase · Stash"
    assert push_label == "Push ⚠ ↑3"
    assert push_requires_rewrite(
        RepositoryStatus(
            branch=BranchStatus(
                head="feature", upstream="origin/feature", ahead=3, behind=2
            )
        )
    )
    assert not push_requires_rewrite(
        RepositoryStatus(
            branch=BranchStatus(
                head="feature", upstream="origin/feature", ahead=3, behind=0
            )
        )
    )
    assert not refresh_action.icon().isNull()

    window.close()


def test_force_push_menu_confirmation_starts_force_with_lease(
    qapp: QApplication, monkeypatch: MonkeyPatch
) -> None:
    requested: list[bool] = []

    def confirm(*_args: object, **_kwargs: object) -> QMessageBox.StandardButton:
        return QMessageBox.StandardButton.Yes

    def record_push(_window: MainWindow, *, force_with_lease: bool) -> None:
        requested.append(force_with_lease)

    monkeypatch.setattr(QMessageBox, "warning", confirm)
    monkeypatch.setattr(MainWindow, "_start_push", record_push)
    settings = QSettings(QSettings.Format.IniFormat, QSettings.Scope.UserScope, "test", "push")
    settings.clear()
    window = MainWindow(settings, Theme.SYSTEM)
    force_push = window.findChild(QAction, "forcePushAction")
    assert force_push is not None

    force_push.trigger()

    assert requested == [True]
    window.close()


def test_branch_delete_requires_confirmation_and_preserves_force_choice(
    qapp: QApplication, monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    requested: list[bool] = []

    def confirm(*_args: object, **_kwargs: object) -> QMessageBox.StandardButton:
        return QMessageBox.StandardButton.Yes

    def record_delete(
        _service: GitService,
        _repository: Path,
        _branch: BranchInfo,
        *,
        force: bool = False,
    ) -> None:
        requested.append(force)

    monkeypatch.setattr(QMessageBox, "question", confirm)
    monkeypatch.setattr(GitService, "request_delete_branch", record_delete)
    subprocess.run(["git", "init", "--initial-branch=main"], cwd=tmp_path, check=True)
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    window = MainWindow(settings, Theme.SYSTEM)
    window.open_repository(tmp_path)
    branch = BranchInfo(
        "refs/heads/old-feature",
        "old-feature",
        "1" * 40,
        False,
        upstream="origin/old-feature",
        upstream_gone=True,
    )
    panel = window.findChild(RefsPanel)
    assert panel is not None
    panel.show_branches(BranchesSnapshot(tmp_path, (branch,)))
    local_root = panel.tree.topLevelItem(0)
    assert local_root is not None
    branch_item = local_root.child(0)
    assert branch_item is not None
    panel.tree.setCurrentItem(branch_item)

    panel.delete_action.trigger()
    panel.setEnabled(True)
    panel.force_delete_action.trigger()

    assert requested == [False, True]
    window.close()


def test_recent_repository_is_displayed(qapp: QApplication, tmp_path: Path) -> None:
    repository = tmp_path / "project"
    repository.mkdir()
    (repository / ".git").mkdir()
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    settings.setValue("workspace/recentRepositories", [str(repository)])

    window = MainWindow(settings, Theme.SYSTEM)
    repositories = window.findChild(QTreeWidget, "repositoriesTree")
    repositories_panel = window.findChild(QWidget, "repositoriesPanel")
    recent_button = window.findChild(QToolButton, "recentRepositoriesButton")

    assert repositories is not None
    assert repositories_panel is not None
    assert recent_button is not None
    item = repositories.topLevelItem(0)
    assert item is not None
    assert item.text(0) == "project"
    assert repositories_panel.isHidden()
    assert recent_button.menu() is not None
    menu_tree = window.findChild(QTreeWidget, "repositoryMenuTree")
    assert menu_tree is not None
    menu_item = menu_tree.topLevelItem(0)
    assert menu_item is not None
    assert menu_item.text(0) == "project"
    window.close()


def test_early_workspace_tab_signal_is_ignored_during_window_construction(
    qapp: QApplication, tmp_path: Path
) -> None:
    class EarlySignalWindow(MainWindow):
        def _build_ui(self) -> None:
            self._workspace_tab_changed(0)
            super()._build_ui()

    settings = QSettings(str(tmp_path / "early-tab.ini"), QSettings.Format.IniFormat)
    window = EarlySignalWindow(settings, Theme.SYSTEM)

    window.close()


def test_commit_history_is_loaded_asynchronously(
    qapp: QApplication, qtbot: QtBot, tmp_path: Path
) -> None:
    repository = tmp_path / "history"
    repository.mkdir()
    subprocess.run(["git", "init", "--initial-branch=main"], cwd=repository, check=True)
    tracked = repository / "tracked.txt"
    for message in ("First commit", "Second commit"):
        tracked.write_text(f"{message}\n", encoding="utf-8")
        subprocess.run(["git", "add", "tracked.txt"], cwd=repository, check=True)
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=History Test",
                "-c",
                "user.email=history@example.invalid",
                "commit",
                "-m",
                message,
            ],
            cwd=repository,
            check=True,
            capture_output=True,
        )
    settings = QSettings(str(tmp_path / "history.ini"), QSettings.Format.IniFormat)
    window = MainWindow(settings, Theme.SYSTEM)
    history = window.findChild(QTreeWidget, "historyTree")
    load_more = window.findChild(QPushButton, "historyLoadMoreButton")
    tabs = window.findChild(QTabWidget, "workspaceTabs")
    diff_container = window.findChild(QWidget, "diffContainer")
    assert history is not None
    assert load_more is not None
    assert tabs is not None
    assert diff_container is not None

    window.open_repository(repository)
    qtbot.waitUntil(lambda: history.topLevelItemCount() == 2, timeout=5000)

    first = history.topLevelItem(0)
    second = history.topLevelItem(1)
    assert first is not None
    assert second is not None
    assert first.text(1) == "[main] Second commit"
    assert first.text(2) == "History Test"
    assert len(first.text(4)) == 8
    assert second.text(1) == "First commit"
    assert not load_more.isVisible()
    tabs.setCurrentIndex(1)
    assert diff_container.isHidden()
    tabs.setCurrentIndex(0)
    assert not diff_container.isHidden()
    window.close()


def test_deleted_recent_repository_is_removed_when_selected(
    qapp: QApplication, tmp_path: Path
) -> None:
    repository = tmp_path / "project"
    repository.mkdir()
    (repository / ".git").mkdir()
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    settings.setValue("workspace/recentRepositories", [str(repository)])
    window = MainWindow(settings, Theme.SYSTEM)
    repositories = window.findChild(QTreeWidget, "repositoriesTree")
    assert repositories is not None
    item = repositories.topLevelItem(0)
    assert item is not None

    (repository / ".git").rmdir()
    repository.rmdir()
    item_activated = repositories.itemActivated
    item_activated.emit(item, 0)

    placeholder = repositories.topLevelItem(0)
    assert placeholder is not None
    assert placeholder.text(0) == "No recent repositories"
    assert settings.value("workspace/recentRepositories") == []
    window.close()


def test_recent_repository_can_be_removed_with_context_action(
    qapp: QApplication, tmp_path: Path
) -> None:
    repository = tmp_path / "project"
    repository.mkdir()
    (repository / ".git").mkdir()
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    settings.setValue("workspace/recentRepositories", [str(repository)])
    window = MainWindow(settings, Theme.SYSTEM)
    repositories = window.findChild(QTreeWidget, "repositoriesTree")
    remove_action = window.findChild(QAction, "removeRecentAction")
    assert repositories is not None
    assert remove_action is not None
    item = repositories.topLevelItem(0)
    assert item is not None

    repositories.setCurrentItem(item)
    remove_action.trigger()

    placeholder = repositories.topLevelItem(0)
    assert placeholder is not None
    assert placeholder.text(0) == "No recent repositories"
    assert settings.value("workspace/recentRepositories") == []
    window.close()


def test_open_repositories_are_restored_and_switchable(
    qapp: QApplication, qtbot: QtBot, tmp_path: Path
) -> None:
    repositories = [tmp_path / "first", tmp_path / "second"]
    for repository in repositories:
        repository.mkdir()
        subprocess.run(
            ["git", "init", "--initial-branch=main"],
            cwd=repository,
            check=True,
            capture_output=True,
        )
    settings = QSettings(str(tmp_path / "session.ini"), QSettings.Format.IniFormat)
    settings.setValue("workspace/openRepositories", [str(path) for path in repositories])
    settings.setValue("workspace/lastRepository", str(repositories[1]))

    window = MainWindow(settings, Theme.SYSTEM)
    switcher = window.findChild(QComboBox, "repositorySwitcher")
    workspace_tabs = window.findChild(QTabWidget, "workspaceTabs")
    diff_container = window.findChild(QWidget, "diffContainer")
    assert switcher is not None
    assert workspace_tabs is not None
    assert diff_container is not None
    assert switcher.count() == 2
    qtbot.waitUntil(lambda: window.windowTitle().startswith("second —"), timeout=5000)

    workspace_tabs.setCurrentIndex(1)
    switcher.setCurrentIndex(0)
    qtbot.waitUntil(lambda: window.windowTitle().startswith("first —"), timeout=5000)
    assert switcher.currentText() == "first"
    assert diff_container.isHidden()
    assert workspace_tabs.currentIndex() == 1
    assert settings.value("workspace/lastRepository") == str(repositories[0])
    window.close()


def test_fetch_all_queues_every_open_repository(
    qapp: QApplication, monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    repositories = [tmp_path / "first", tmp_path / "second"]
    for repository in repositories:
        repository.mkdir()
        subprocess.run(
            ["git", "init", "--initial-branch=main"],
            cwd=repository,
            check=True,
            capture_output=True,
        )
    settings = QSettings(str(tmp_path / "fetch-all.ini"), QSettings.Format.IniFormat)
    settings.setValue("workspace/openRepositories", [str(path) for path in repositories])
    settings.setValue("workspace/lastRepository", str(repositories[0]))
    window = MainWindow(settings, Theme.SYSTEM)
    fetch_all = window.findChild(QAction, "fetchAllAction")
    service = window.findChild(GitService)
    assert fetch_all is not None
    assert service is not None
    requested: list[Path] = []
    monkeypatch.setattr(service, "request_fetch", requested.append)

    fetch_all.trigger()

    assert requested == repositories
    window.close()


def test_linked_repository_stays_nested_and_is_selected_in_switcher(
    qapp: QApplication, qtbot: QtBot, tmp_path: Path
) -> None:
    parent = tmp_path / "parent"
    child = parent / "child"
    child.mkdir(parents=True)
    for repository in (parent, child):
        subprocess.run(
            ["git", "init", "--initial-branch=main"],
            cwd=repository,
            check=True,
            capture_output=True,
        )
    settings = QSettings(str(tmp_path / "linked.ini"), QSettings.Format.IniFormat)
    window = MainWindow(settings, Theme.SYSTEM)
    repositories = window.findChild(QTreeWidget, "repositoriesTree")
    switcher = window.findChild(QComboBox, "repositorySwitcher")
    assert repositories is not None
    assert switcher is not None
    window.show()
    window.open_repository(parent)

    def linked_item() -> object:
        root = repositories.topLevelItem(0)
        return root.child(0) if root is not None and root.childCount() else None

    qtbot.waitUntil(lambda: linked_item() is not None, timeout=5000)
    root = repositories.topLevelItem(0)
    assert root is not None
    child_item = root.child(0)
    assert child_item is not None
    repositories.itemActivated.emit(child_item, 0)
    qtbot.waitUntil(lambda: switcher.currentText() == "child", timeout=5000)

    assert repositories.topLevelItemCount() == 1
    assert root.childCount() == 1
    assert settings.value("workspace/recentRepositories") == [str(parent.resolve())]
    window.close()


def test_invalid_theme_falls_back_to_system() -> None:
    assert Theme.from_value("unknown") is Theme.SYSTEM


def test_selected_commit_shows_details_files_and_diff(
    qapp: QApplication, qtbot: QtBot, tmp_path: Path
) -> None:
    repository = tmp_path / "history-details"
    repository.mkdir()
    subprocess.run(
        ["git", "init", "--initial-branch=main"],
        cwd=repository,
        check=True,
        capture_output=True,
    )
    tracked = repository / "tracked.txt"
    tracked.write_text("before\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=repository, check=True)
    identity = [
        "-c",
        "user.name=MyGitClient Test",
        "-c",
        "user.email=test@example.invalid",
    ]
    subprocess.run(
        ["git", *identity, "commit", "-m", "initial"],
        cwd=repository,
        check=True,
        capture_output=True,
    )
    tracked.write_text("after\n", encoding="utf-8")
    subprocess.run(
        ["git", *identity, "commit", "-am", "Update tracked file"],
        cwd=repository,
        check=True,
        capture_output=True,
    )
    settings = QSettings(str(tmp_path / "history-details.ini"), QSettings.Format.IniFormat)
    window = MainWindow(settings, Theme.SYSTEM)
    tabs = window.findChild(QTabWidget, "workspaceTabs")
    history = window.findChild(QTreeWidget, "historyTree")
    details = window.findChild(QLabel, "commitDetailsLabel")
    files = window.findChild(QTreeWidget, "commitFilesTree")
    diff = window.findChild(QPlainTextEdit, "diffPanel")
    diff_container = window.findChild(QWidget, "diffContainer")
    assert tabs is not None
    assert history is not None
    assert details is not None
    assert files is not None
    assert diff is not None
    assert diff_container is not None
    window.resize(1400, 800)
    window.show()
    window.open_repository(repository)
    tabs.setCurrentIndex(1)
    qtbot.waitUntil(lambda: history.topLevelItemCount() == 2, timeout=5000)
    commit_item = history.topLevelItem(0)
    assert commit_item is not None

    history.setCurrentItem(commit_item)
    qtbot.waitUntil(lambda: files.topLevelItemCount() == 1, timeout=5000)
    assert "Update tracked file" in details.text()
    file_item = files.topLevelItem(0)
    assert file_item is not None
    assert file_item.text(1) == "tracked.txt"

    files.setCurrentItem(file_item)
    qtbot.waitUntil(lambda: "+after" in diff.toPlainText(), timeout=5000)
    assert "-before" in diff.toPlainText()
    assert not diff_container.isHidden()
    assert tabs.currentIndex() == 1
    window.close()


def test_branches_tab_can_checkout_and_create_branch(
    qapp: QApplication, qtbot: QtBot, tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    repository = tmp_path / "branches"
    repository.mkdir()
    subprocess.run(
        ["git", "init", "--initial-branch=main"],
        cwd=repository,
        check=True,
        capture_output=True,
    )
    tracked = repository / "tracked.txt"
    tracked.write_text("content\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=repository, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=MyGitClient Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-m",
            "initial",
        ],
        cwd=repository,
        check=True,
        capture_output=True,
    )
    subprocess.run(["git", "branch", "feature"], cwd=repository, check=True)
    settings = QSettings(str(tmp_path / "branches.ini"), QSettings.Format.IniFormat)
    window = MainWindow(settings, Theme.SYSTEM)
    tabs = window.findChild(QTabWidget, "workspaceTabs")
    refs_panel = window.findChild(RefsPanel)
    branches = window.findChild(QTreeWidget, "refsTree")
    stage_all = window.findChild(QCheckBox, "stageAllCheckBox")
    assert tabs is not None
    assert branches is not None
    assert refs_panel is not None
    assert stage_all is not None
    window.show()
    window.open_repository(repository)
    tabs.setCurrentIndex(1)

    def local_branch_count() -> int:
        root = branches.topLevelItem(0)
        return root.childCount() if root is not None else 0

    qtbot.waitUntil(lambda: local_branch_count() == 2, timeout=5000)
    window.open_repository(repository)
    assert tabs.currentIndex() == 1
    assert not stage_all.isVisible()
    qtbot.waitUntil(lambda: local_branch_count() == 2, timeout=5000)
    local = branches.topLevelItem(0)
    assert local is not None
    feature = None
    for index in range(local.childCount()):
        child = local.child(index)
        if child.text(0) == "feature":
            feature = child
            break
    assert feature is not None
    branches.setCurrentItem(feature)
    refs_panel.checkout_action.trigger()
    qtbot.waitUntil(lambda: window.windowTitle().startswith("branches — feature —"), timeout=5000)

    def branch_name_dialog(*_args: object) -> tuple[str, bool]:
        return "new-branch", True

    monkeypatch.setattr(QInputDialog, "getText", branch_name_dialog)
    refs_panel.create_branch_action.trigger()
    qtbot.waitUntil(
        lambda: window.windowTitle().startswith("branches — new-branch —"), timeout=5000
    )
    window.close()


def test_theme_actions_are_exclusive_and_persisted(qapp: QApplication, tmp_path: Path) -> None:
    settings = QSettings(str(tmp_path / "theme.ini"), QSettings.Format.IniFormat)
    window = MainWindow(settings, Theme.SYSTEM)
    system_action = window.findChild(QAction, "themeAction_system")
    dark_action = window.findChild(QAction, "themeAction_dark")
    diff_panel = window.findChild(QPlainTextEdit, "diffPanel")
    initial_base = qapp.palette().base().color()

    assert system_action is not None
    assert dark_action is not None
    assert diff_panel is not None
    dark_action.trigger()

    assert dark_action.isChecked()
    assert not system_action.isChecked()
    assert settings.value("appearance/theme") == Theme.DARK.value
    assert qapp.palette().base().color().lightness() < 128
    assert diff_panel.palette().base().color().lightness() < 128
    assert qapp.palette().highlight().color().name() == "#2f80ed"
    assert "checkbox-checked.svg" in qapp.styleSheet()
    assert "checkbox-partial.svg" in qapp.styleSheet()

    system_action.trigger()
    assert system_action.isChecked()
    assert not dark_action.isChecked()
    assert qapp.styleSheet() == ""
    assert qapp.palette().base().color() == initial_base
    assert diff_panel.palette().base().color() == initial_base
    window.close()
