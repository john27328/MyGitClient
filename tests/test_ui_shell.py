from __future__ import annotations

import subprocess
from pathlib import Path

from PySide6.QtCore import QSettings, Qt
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
    CommitFileChange,
    CommitSummary,
    RepositoryOperation,
    RepositoryOperationSnapshot,
    RepositoryStatus,
)
from mygitclient.git.runner import GitRunner
from mygitclient.git.service import GitService
from mygitclient.github import GitHubProfile, GitHubTokenStore
from mygitclient.theme import Theme
from mygitclient.ui.history_panel import HistoryPanel
from mygitclient.ui.main_window import MainWindow, push_requires_rewrite, sync_action_labels
from mygitclient.ui.refs_panel import RefsPanel


class _MemoryTokenBackend:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.values.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.values[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        self.values.pop((service, username), None)


class _TestMainWindow(MainWindow):
    def configure_github_token(self, repository: Path, profile: GitHubProfile, token: str) -> None:
        self._github_profiles.save(profile)
        self._github_tokens = GitHubTokenStore(_MemoryTokenBackend())
        self._github_tokens.save(profile.login, token)
        self._repository = repository

    def github_token(self) -> str | None:
        return self._resolve_github_token()

    def configure_review_start(
        self, repository: Path, branches: tuple[BranchInfo, ...]
    ) -> None:
        self._review_controller.activate_repository(repository)
        self._review_controller.set_branches(branches)

    @property
    def git_service(self) -> GitService:
        return self._git

    def start_review(self) -> None:
        self._review_controller.start()


def test_main_window_is_created(qapp: QApplication) -> None:
    settings = QSettings(QSettings.Format.IniFormat, QSettings.Scope.UserScope, "test", "app")
    settings.clear()
    window = MainWindow(settings, Theme.SYSTEM)

    assert window.windowTitle() == "MyGitClient"
    assert window.centralWidget() is not None
    tabs = window.findChild(QTabWidget, "workspaceTabs")
    assert tabs is not None
    assert tabs.count() == 4
    assert not window.windowIcon().isNull()
    toolbar = window.findChild(QToolBar, "repositoryToolbar")
    refresh_action = window.findChild(QAction, "refreshAction")
    fetch_action = window.findChild(QAction, "fetchAction")
    push_action = window.findChild(QAction, "pushAction")
    pull_action = window.findChild(QAction, "pullAction")
    open_github = window.findChild(QAction, "openGitHubRepositoryAction")
    open_pull_request = window.findChild(QAction, "openPullRequestAction")
    pull_button = window.findChild(QToolButton, "pullButton")
    pull_rebase = window.findChild(QAction, "pullRebaseAction")
    pull_autostash = window.findChild(QAction, "pullAutostashAction")
    fetch_submodules = window.findChild(QAction, "fetchSubmodulesAction")
    pull_submodules = window.findChild(QAction, "pullSubmodulesAction")
    reset_to_upstream = window.findChild(QAction, "resetToUpstreamAction")
    push_submodules = window.findChild(QAction, "pushSubmodulesAction")
    font_sizes = window.findChild(QAction, "fontSizesAction")
    assert toolbar is not None
    assert refresh_action is not None
    assert fetch_action is not None
    assert push_action is not None
    assert pull_action is not None
    assert open_github is not None
    assert open_pull_request is not None
    assert not open_github.isVisible()
    assert not open_pull_request.isVisible()
    window.set_github_repository("octocat/project")
    assert open_github.isVisible()
    assert open_github.isEnabled()
    assert open_pull_request.isVisible()
    assert pull_button is not None
    assert pull_rebase is not None
    assert pull_autostash is not None
    assert fetch_submodules is not None
    assert pull_submodules is not None
    assert reset_to_upstream is not None
    assert reset_to_upstream.text() == "Reset to upstream…"
    assert push_submodules is not None

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


def test_start_review_asks_for_source_and_target_branch(
    qapp: QApplication, monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    settings = QSettings(str(tmp_path / "review-start.ini"), QSettings.Format.IniFormat)
    window = _TestMainWindow(settings, Theme.SYSTEM)
    window.configure_review_start(
        tmp_path,
        (
        BranchInfo("refs/heads/develop", "develop", "a" * 40, False, current=True),
        BranchInfo("refs/heads/master", "master", "b" * 40, False),
        ),
    )
    choices = iter((("refs/heads/develop", True), ("refs/heads/master", True)))
    monkeypatch.setattr(QInputDialog, "getItem", staticmethod(lambda *_args: next(choices)))
    captured: list[tuple[Path, str, str]] = []
    def capture_request(repository: Path, branch: str, target: str) -> GitRunner:
        captured.append((repository, branch, target))
        return GitRunner()

    monkeypatch.setattr(window.git_service, "request_review_commits", capture_request)

    window.start_review()

    assert captured == [(tmp_path, "refs/heads/develop", "refs/heads/master")]


def test_saved_github_token_is_resolved_only_for_https_remote(tmp_path: Path) -> None:
    settings = QSettings(str(tmp_path / "github-token.ini"), QSettings.Format.IniFormat)
    window = _TestMainWindow(settings, Theme.SYSTEM)
    profile = GitHubProfile("Octocat", "octocat")
    window.configure_github_token(tmp_path, profile, "saved-token")

    window.set_github_repository(
        "octocat/private-repository", "https://github.com/octocat/private-repository.git"
    )
    assert window.github_token() == "saved-token"

    window.set_github_repository(
        "octocat/private-repository", "git@github.com:octocat/private-repository.git"
    )
    assert window.github_token() is None
    window.close()


def test_git_error_burst_opens_only_one_dialog(
    qapp: QApplication, tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    settings = QSettings(str(tmp_path / "errors.ini"), QSettings.Format.IniFormat)
    window = MainWindow(settings, Theme.SYSTEM)
    messages: list[str] = []

    def show_error(_parent: QWidget, _title: str, message: str) -> None:
        messages.append(message)

    monkeypatch.setattr(QMessageBox, "critical", show_error)
    service = window.findChild(GitService)
    assert service is not None
    service.operation_failed.emit("first failure")
    service.operation_failed.emit("second failure from the same request burst")

    assert messages == ["first failure"]
    window.close()


def test_repository_operation_banner_restores(
    qapp: QApplication, tmp_path: Path
) -> None:
    settings = QSettings(
        QSettings.Format.IniFormat, QSettings.Scope.UserScope, "test", "operation-banner"
    )
    settings.clear()
    window = MainWindow(settings, Theme.SYSTEM)
    window.__dict__["_repository"] = tmp_path
    service = window.findChild(GitService)
    assert service is not None
    service.repository_operation_ready.emit(
        RepositoryOperationSnapshot(
            tmp_path,
            RepositoryOperation("rebase", 2, 5, "current commit", ("next one", "next two")),
        )
    )
    banner = window.findChild(QWidget, "repositoryOperationBanner")
    label = window.findChild(QLabel, "repositoryOperationLabel")
    continue_button = window.findChild(
        QPushButton, "repositoryOperationContinueButton"
    )
    skip_button = window.findChild(QPushButton, "repositoryOperationSkipButton")
    assert banner is not None and not banner.isHidden()
    assert label is not None and "step 2 of 5" in label.text()
    assert "current commit" in label.text() and "2 remaining" in label.text()
    assert "next one" in label.toolTip()
    assert continue_button is not None
    assert skip_button is not None and not skip_button.isHidden()

    service.repository_operation_ready.emit(RepositoryOperationSnapshot(tmp_path, None))
    assert banner.isHidden()
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
    window.__dict__["_repository"] = tmp_path
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


def test_remote_branch_delete_requires_confirmation(
    qapp: QApplication, monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    requested: list[str] = []

    def confirm(*_args: object, **_kwargs: object) -> QMessageBox.StandardButton:
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", confirm)

    def record_delete(
        _service: GitService, _repository: Path, branch: BranchInfo
    ) -> None:
        requested.append(branch.name)

    monkeypatch.setattr(GitService, "request_delete_remote_branch", record_delete)
    subprocess.run(["git", "init", "--initial-branch=main"], cwd=tmp_path, check=True)
    settings = QSettings(str(tmp_path / "remote-delete.ini"), QSettings.Format.IniFormat)
    window = MainWindow(settings, Theme.SYSTEM)
    window.__dict__["_repository"] = tmp_path
    branch = BranchInfo(
        "refs/remotes/origin/feature", "origin/feature", "1" * 40, True
    )
    panel = window.findChild(RefsPanel)
    assert panel is not None
    panel.show_branches(BranchesSnapshot(tmp_path, (branch,)))
    remotes = panel.tree.topLevelItem(1)
    assert remotes is not None
    origin = remotes.child(0)
    assert origin is not None
    remote_item = origin.child(0)
    assert remote_item is not None
    panel.tree.setCurrentItem(remote_item)

    panel.remote_delete_action.trigger()

    assert requested == ["origin/feature"]
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

    assert repositories is not None
    assert repositories_panel is not None
    item = repositories.topLevelItem(0)
    assert item is not None
    assert item.text(0) == "project"
    assert repositories_panel.isHidden()
    assert window.findChild(QToolButton, "recentRepositoriesButton") is None
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
    assert first.text(1) == "main"
    assert first.text(2) == "Second commit"
    assert first.text(3) == "History Test"
    assert len(first.text(5)) == 8
    assert second.text(2) == "First commit"
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


def test_open_repositories_are_restored_on_home_without_activation(
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
    home = window.findChild(QWidget, "homePanel")
    recent = window.findChild(QTreeWidget, "homeRecentRepositories")
    diff_container = window.findChild(QWidget, "diffContainer")
    assert switcher is not None
    assert home is not None
    assert recent is not None
    assert diff_container is not None
    assert switcher.count() == 2
    assert recent.topLevelItemCount() == 0
    assert window.windowTitle() == "MyGitClient"
    assert home.isVisibleTo(window)
    assert diff_container.isHidden()
    assert settings.value("workspace/lastRepository") == str(repositories[1])
    window.close()


def test_fetch_submodules_option_is_saved_and_used_for_current_repository(
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
    fetch_submodules = window.findChild(QAction, "fetchSubmodulesAction")
    fetch = window.findChild(QAction, "fetchAction")
    service = window.findChild(GitService)
    assert fetch_submodules is not None
    assert fetch is not None
    assert service is not None
    requested: list[tuple[Path, bool]] = []

    def record_fetch(
        repository: Path, *, recurse_submodules: bool = False, token: str | None = None
    ) -> None:
        requested.append((repository, recurse_submodules))

    monkeypatch.setattr(service, "request_fetch", record_fetch)
    window.open_repository(repositories[0])

    fetch_submodules.trigger()
    fetch.trigger()

    assert requested == [(repositories[0], True)]
    assert settings.value("sync/fetchSubmodules") is True
    assert window.findChild(QAction, "fetchAllAction") is None
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

    # A single click only expands an inline diff in place; the shared diff pane stays
    # hidden and the History tab stays active.
    files.setCurrentItem(file_item)
    file_item.setExpanded(True)

    def inline_diff_text() -> str:
        child = file_item.child(0)
        if child is None:
            return ""
        widget = files.itemWidget(child, 0)
        return widget.toPlainText() if isinstance(widget, QPlainTextEdit) else ""

    qtbot.waitUntil(lambda: "+after" in inline_diff_text(), timeout=5000)
    assert "-before" in inline_diff_text()
    assert diff_container.isHidden()
    assert tabs.currentIndex() == 1

    # Double-clicking the file opens the Diff tab on this commit and file, using the
    # shared diff pane.
    files.itemDoubleClicked.emit(file_item, 1)
    assert tabs.currentIndex() == 2
    qtbot.waitUntil(lambda: "+after" in diff.toPlainText(), timeout=5000)
    assert "-before" in diff.toPlainText()
    assert not diff_container.isHidden()
    window.close()


def test_repository_switch_ignores_stale_history_selection(
    qapp: QApplication, qtbot: QtBot, tmp_path: Path
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    identity = [
        "-c",
        "user.name=MyGitClient Test",
        "-c",
        "user.email=test@example.invalid",
    ]
    for repository in (first, second):
        repository.mkdir()
        subprocess.run(
            ["git", "init", "--initial-branch=main"],
            cwd=repository,
            check=True,
            capture_output=True,
        )
        (repository / "tracked.txt").write_text(
            f"{repository.name}\n", encoding="utf-8"
        )
        subprocess.run(["git", "add", "tracked.txt"], cwd=repository, check=True)
        subprocess.run(
            ["git", *identity, "commit", "-m", f"Initial {repository.name}"],
            cwd=repository,
            check=True,
            capture_output=True,
        )
    old_oid = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=first,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    commit = CommitSummary(
        old_oid,
        (),
        "MyGitClient Test",
        "test@example.invalid",
        "2026-07-25T12:00:00+00:00",
        "Old repository commit",
    )
    change = CommitFileChange("M", "old.txt")
    settings = QSettings(str(tmp_path / "stale-history.ini"), QSettings.Format.IniFormat)
    window = MainWindow(settings, Theme.SYSTEM)
    qtbot.addWidget(window)
    history = window.findChild(HistoryPanel)
    service = window.findChild(GitService)
    assert history is not None and service is not None
    errors: list[str] = []
    service.operation_failed.connect(errors.append)

    window.open_repository(first)
    qtbot.waitUntil(lambda: history.commit_count == 1, timeout=5000)
    window.open_repository(second)
    history.commit_selected.emit(commit)
    history.file_selected.emit(commit, change)
    qtbot.wait(500)

    assert errors == []


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
        assert child is not None
        value = child.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(value, BranchInfo) and value.name == "feature":
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


def test_external_checkout_is_detected_by_poll_and_refresh(
    qtbot: QtBot, tmp_path: Path
) -> None:
    repository = tmp_path / "external-checkout"
    repository.mkdir()
    subprocess.run(
        ["git", "init", "--initial-branch=main"],
        cwd=repository,
        check=True,
        capture_output=True,
    )
    (repository / "tracked.txt").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repository, check=True)
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
    settings = QSettings(str(tmp_path / "external.ini"), QSettings.Format.IniFormat)
    window = MainWindow(settings, Theme.SYSTEM)
    qtbot.addWidget(window)
    window.show()
    window.open_repository(repository)
    qtbot.waitUntil(lambda: "main" in window.windowTitle(), timeout=5000)

    subprocess.run(["git", "switch", "feature"], cwd=repository, check=True)
    qtbot.waitUntil(lambda: "feature" in window.windowTitle(), timeout=5000)

    subprocess.run(["git", "switch", "main"], cwd=repository, check=True)
    refresh = window.findChild(QAction, "refreshAction")
    assert refresh is not None
    refresh.trigger()
    qtbot.waitUntil(lambda: "main" in window.windowTitle(), timeout=5000)
    window.close()


def test_theme_actions_are_exclusive_persisted_and_request_restart(
    qtbot: QtBot, tmp_path: Path
) -> None:
    settings = QSettings(str(tmp_path / "theme.ini"), QSettings.Format.IniFormat)
    window = MainWindow(settings, Theme.SYSTEM)
    qtbot.addWidget(window)
    system_action = window.findChild(QAction, "themeAction_system")
    dark_action = window.findChild(QAction, "themeAction_dark")

    assert system_action is not None
    assert dark_action is not None
    with qtbot.waitSignal(window.restart_requested):
        dark_action.trigger()

    assert dark_action.isChecked()
    assert not system_action.isChecked()
    assert settings.value("appearance/theme") == Theme.DARK.value

    with qtbot.waitSignal(window.restart_requested):
        system_action.trigger()
    assert system_action.isChecked()
    assert not dark_action.isChecked()
    assert settings.value("appearance/theme") == Theme.SYSTEM.value
    window.close()
