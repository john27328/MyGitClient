from __future__ import annotations

from pathlib import Path
from typing import cast

from PySide6.QtCore import QByteArray, QSettings, QSignalBlocker, Qt, QTimer, Slot
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QCloseEvent,
)
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QSplitter,
    QTabWidget,
    QToolBar,
    QToolButton,
    QTreeWidgetItem,
)

from mygitclient.git.models import (
    AmendDiffSnapshot,
    AmendPreview,
    BranchesSnapshot,
    BranchInfo,
    CommitDiffSnapshot,
    CommitFileChange,
    CommitFilesSnapshot,
    CommitPage,
    CommitSummary,
    DiffSnapshot,
    FileStatus,
    RepositoryStatus,
    RepositoryStatusSnapshot,
    UnifiedDiff,
)
from mygitclient.git.runner import GitRunner
from mygitclient.git.service import GitService
from mygitclient.resources import load_icon
from mygitclient.theme import Theme, apply_theme
from mygitclient.ui.branches_panel import BranchesPanel
from mygitclient.ui.changes_panel import ChangesPanel
from mygitclient.ui.diff_view import DiffView
from mygitclient.ui.history_panel import HistoryPanel
from mygitclient.ui.repositories_panel import RepositoriesPanel
from mygitclient.workspace import (
    LinkedRepositoriesSnapshot,
    WorkspaceDiscoveryService,
    WorkspaceManager,
    find_repository_root,
)


class MainWindow(QMainWindow):
    def __init__(self, settings: QSettings, theme: Theme) -> None:
        super().__init__()
        self._settings = settings
        self._theme = theme
        self._workspace = WorkspaceManager(settings)
        self._workspace_discovery = WorkspaceDiscoveryService(self)
        self._git = GitService(self)
        self._repository: Path | None = None
        self._open_repositories: list[Path] = []
        self._repository_status: RepositoryStatus | None = None
        self._commit_diff_visible = False
        self._generated_commit_message = ""
        self._generated_commit_description = ""
        self._pre_amend_message = ""
        self._pre_amend_description = ""
        self._amend_commit_files: tuple[CommitFileChange, ...] = ()
        self._amend_included_paths: frozenset[str] = frozenset()
        self._amend_parent_oid: str | None = None
        self._amend_render_pending = False
        self._amend_files_loaded = False
        self._amend_diff_loaded = False
        self._status_runner: GitRunner | None = None
        self._history_runner: GitRunner | None = None
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(1500)
        self._refresh_timer.timeout.connect(self._poll_repository)
        self.setWindowTitle("MyGitClient")
        self.setWindowIcon(load_icon("app-icon.png"))
        self.resize(1180, 760)
        self._build_ui()
        self._build_menu()
        self._connect_services()
        self._populate_recent_repositories()
        self._restore_window_state()
        self._restore_open_repositories()

    def _build_ui(self) -> None:
        self._repositories_panel = RepositoriesPanel()
        self._repositories = self._repositories_panel.tree

        self._welcome = QPlainTextEdit()
        self._welcome.setObjectName("welcomePanel")
        self._welcome.setReadOnly(True)
        self._welcome.setPlainText(
            "Welcome to MyGitClient\n\n"
            "Open a Git repository with File → Open Repository."
        )

        self._changes_panel = ChangesPanel()
        self._changes_container = self._changes_panel
        self._changes = self._changes_panel.tree
        self._discard_action = self._changes_panel.discard_action
        self._stash_action = self._changes_panel.stash_action
        self._ignore_action = self._changes_panel.ignore_action
        self._stage_all = self._changes_panel.stage_all
        self._commit_message = self._changes_panel.commit_message
        self._commit_description = self._changes_panel.commit_description
        self._amend = self._changes_panel.amend
        self._commit_button = self._changes_panel.commit_button
        self._commit_error = self._changes_panel.commit_error

        self._discard_action.triggered.connect(self._discard_selected_file)
        self._stash_action.triggered.connect(self._stash_selected_files)
        self._ignore_action.triggered.connect(self._ignore_selected_file)
        self._stage_all.stateChanged.connect(self._stage_all_changed)
        self._commit_message.textChanged.connect(self._update_commit_controls)
        self._amend.toggled.connect(self._amend_toggled)
        self._commit_button.clicked.connect(self._create_commit)
        self._update_commit_controls()

        self._history_panel = HistoryPanel()
        self._history_panel.load_more_requested.connect(self._load_more_history)
        self._history_panel.commit_selected.connect(self._history_commit_selected)
        self._history_panel.file_selected.connect(self._history_file_selected)

        self._branches_panel = BranchesPanel()
        self._branches_panel.checkout_requested.connect(self._checkout_branch)
        self._branches_panel.create_requested.connect(self._create_branch)
        self._branches_panel.rename_requested.connect(self._rename_branch)
        self._branches_panel.delete_requested.connect(self._delete_branch)

        self._workspace_tabs = QTabWidget()
        self._workspace_tabs.setObjectName("workspaceTabs")
        self._workspace_tabs.addTab(self._changes_container, "Changes")
        self._workspace_tabs.addTab(self._history_panel, "History")
        self._workspace_tabs.addTab(self._branches_panel, "Branches")
        self._workspace_tabs.setMinimumWidth(360)
        self._workspace_tabs.currentChanged.connect(self._workspace_tab_changed)
        self._workspace_tabs.hide()

        self._diff_view = DiffView(self._settings)
        self._diff_container = self._diff_view
        self._diff = self._diff_view.diff
        self._diff_gutter = self._diff_view.gutter
        self._diff_version = self._diff_view.version_combo
        self._diff_view_mode = self._diff_view.view_mode_combo
        self._wrap_button = self._diff_view.wrap_button
        self._whitespace_button = self._diff_view.whitespace_button

        self._diff_version.currentIndexChanged.connect(self._request_selected_diff)
        self._diff_view_mode.currentIndexChanged.connect(self._diff_view_changed)
        self._diff_view.selection_changed.connect(self._sync_selected_file_checkbox)
        self._diff_view.lines_requested.connect(self._apply_diff_lines)
        self._diff_view.hunk_requested.connect(self._apply_diff_hunk)
        self._wrap_button.setChecked(self._read_bool_setting("diff/wrapLines"))
        self._wrap_button.toggled.connect(self._diff_wrap_changed)
        self._whitespace_button.setChecked(
            self._read_bool_setting("diff/showWhitespace")
        )
        self._whitespace_button.toggled.connect(self._diff_whitespace_changed)
        self._apply_diff_wrap(self._wrap_button.isChecked())
        self._apply_diff_whitespace(self._whitespace_button.isChecked())

        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.setObjectName("mainSplitter")
        self._splitter.addWidget(self._repositories_panel)
        self._splitter.addWidget(self._welcome)
        self._splitter.addWidget(self._workspace_tabs)
        self._splitter.addWidget(self._diff_container)
        self._splitter.setStretchFactor(0, 0)
        self._splitter.setStretchFactor(1, 1)
        self._splitter.setStretchFactor(2, 0)
        self._splitter.setStretchFactor(3, 1)
        self._splitter.setSizes([260, 920, 0, 0])
        self.setCentralWidget(self._splitter)
        self._status_label = QLabel("Ready")
        self._status_label.setObjectName("statusLabel")
        self.statusBar().addWidget(self._status_label)

    def _read_bool_setting(self, key: str) -> bool:
        value = self._settings.value(key, False)
        return value is True or value == "true" or value == 1

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        open_action = QAction("&Open Repository…", self)
        open_action.setIcon(load_icon("open.svg"))
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self._choose_repository)
        file_menu.addAction(open_action)
        file_menu.addSeparator()
        exit_action = QAction("E&xit", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        toolbar = QToolBar("Repository", self)
        toolbar.setObjectName("repositoryToolbar")
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        toolbar.addAction(open_action)
        self._repository_switcher = self._repositories_panel.switcher
        toolbar.addWidget(self._repository_switcher)
        refresh_action = QAction(load_icon("refresh.svg"), "Refresh", self)
        refresh_action.setObjectName("refreshAction")
        refresh_action.setShortcut("F5")
        refresh_action.triggered.connect(self._refresh_repository)
        toolbar.addAction(refresh_action)
        self._fetch_action = QAction(load_icon("fetch.svg"), "Fetch", self)
        self._fetch_action.setObjectName("fetchAction")
        self._fetch_action.triggered.connect(self._fetch_repository)
        toolbar.addAction(self._fetch_action)
        self._pull_action = QAction(load_icon("pull.svg"), "Pull", self)
        self._pull_action.setObjectName("pullAction")
        self._pull_action.triggered.connect(self._pull_repository)
        pull_menu = QMenu(self)
        self._pull_merge_action = pull_menu.addAction(load_icon("pull-merge.svg"), "Merge")
        self._pull_merge_action.setObjectName("pullMergeAction")
        self._pull_merge_action.setCheckable(True)
        self._pull_rebase_action = pull_menu.addAction(
            load_icon("pull-rebase.svg"), "Rebase"
        )
        self._pull_rebase_action.setObjectName("pullRebaseAction")
        self._pull_rebase_action.setCheckable(True)
        pull_strategy_group = QActionGroup(self)
        pull_strategy_group.setExclusive(True)
        pull_strategy_group.addAction(self._pull_merge_action)
        pull_strategy_group.addAction(self._pull_rebase_action)
        self._pull_rebase_action.setChecked(
            self._read_bool_setting("sync/pullRebase")
        )
        self._pull_merge_action.setChecked(not self._pull_rebase_action.isChecked())
        pull_menu.addSeparator()
        self._pull_autostash_action = pull_menu.addAction(
            load_icon("autostash.svg"), "Auto-stash local changes"
        )
        self._pull_autostash_action.setObjectName("pullAutostashAction")
        self._pull_autostash_action.setCheckable(True)
        self._pull_autostash_action.setChecked(
            self._read_bool_setting("sync/pullAutostash")
        )
        for option in (
            self._pull_merge_action,
            self._pull_rebase_action,
            self._pull_autostash_action,
        ):
            option.triggered.connect(self._pull_options_changed)
        self._pull_button = QToolButton()
        self._pull_button.setObjectName("pullButton")
        self._pull_button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self._pull_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._pull_button.setDefaultAction(self._pull_action)
        self._pull_button.setMenu(pull_menu)
        toolbar.addWidget(self._pull_button)
        self._update_pull_button()
        self._push_action = QAction(load_icon("push.svg"), "Push", self)
        self._push_action.setObjectName("pushAction")
        self._push_action.triggered.connect(self._push_repository)
        push_menu = QMenu(self)
        self._force_push_action = push_menu.addAction(
            load_icon("force-push.svg"), "Force push with lease…"
        )
        self._force_push_action.setObjectName("forcePushAction")
        self._force_push_action.triggered.connect(self._force_push_repository)
        self._push_button = QToolButton()
        self._push_button.setObjectName("pushButton")
        self._push_button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self._push_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._push_button.setDefaultAction(self._push_action)
        self._push_button.setMenu(push_menu)
        toolbar.addWidget(self._push_button)
        self._update_sync_indicators()
        self._cancel_action = QAction(load_icon("cancel.svg"), "Cancel", self)
        self._cancel_action.setObjectName("cancelOperationsAction")
        self._cancel_action.triggered.connect(self._cancel_operations)
        self._cancel_action.setEnabled(False)
        toolbar.addAction(self._cancel_action)
        self.addToolBar(toolbar)

        workspace_menu = self.menuBar().addMenu("&Workspace")
        save_workspace = QAction("Save Workspace…", self)
        save_workspace.triggered.connect(self._save_workspace)
        workspace_menu.addAction(save_workspace)
        self._load_workspace_menu = workspace_menu.addMenu("Open Workspace")
        self._populate_workspace_menu()

        view_menu = self.menuBar().addMenu("&View")
        theme_menu = view_menu.addMenu("Theme")
        self._theme_actions = QActionGroup(self)
        self._theme_actions.setExclusive(True)
        for theme in Theme:
            action = QAction(theme.value.title(), self)
            action.setObjectName(f"themeAction_{theme.value}")
            action.setCheckable(True)
            action.setChecked(theme is self._theme)
            action.setData(theme.value)
            self._theme_actions.addAction(action)
            theme_menu.addAction(action)
        self._theme_actions.triggered.connect(self._theme_selected)

    def _connect_services(self) -> None:
        self._git.amend_diff_ready.connect(self._show_amend_diff)
        self._git.amend_preview_ready.connect(self._show_amend_preview)
        self._git.status_ready.connect(self._show_status)
        self._git.history_ready.connect(self._show_history)
        self._git.branches_ready.connect(self._show_branches)
        self._git.commit_files_ready.connect(self._show_commit_files)
        self._git.commit_diff_ready.connect(self._show_commit_diff)
        self._git.diff_ready.connect(self._show_diff)
        self._git.mutation_ready.connect(self._mutation_finished)
        self._git.operation_cancelled.connect(self._operation_cancelled)
        self._git.operation_failed.connect(self._show_git_error)
        self._workspace_discovery.linked_repositories_ready.connect(
            self._linked_repositories_ready
        )
        self._workspace_discovery.operation_failed.connect(self._show_git_error)
        self._repositories_panel.repository_activated.connect(self._open_recent_repository)
        self._repositories_panel.remove_requested.connect(self._remove_recent_repository)
        self._repositories_panel.switch_requested.connect(self._repository_selected)
        self._changes.itemSelectionChanged.connect(self._selected_file_changed)
        self._changes.itemSelectionChanged.connect(self._update_file_actions)
        self._changes.itemChanged.connect(self._stage_checkbox_changed)

    def _populate_recent_repositories(self) -> None:
        self._repositories_panel.set_recent(self._workspace.recent_repositories())

    @Slot()
    def _choose_repository(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Open Git Repository")
        if selected:
            self.open_repository(Path(selected))

    @Slot(object, bool)
    def _open_recent_repository(self, value: object, remember: bool) -> None:
        if not isinstance(value, Path):
            return
        if not value.is_dir() or not (value / ".git").exists():
            self._workspace.forget(value)
            self._populate_recent_repositories()
            self._status_label.setText("Removed missing repository from recent list")
            return
        self.open_repository(value, remember=remember)

    @Slot(object)
    def _remove_recent_repository(self, value: object) -> None:
        if not isinstance(value, Path):
            return
        self._workspace.forget(value)
        self._populate_recent_repositories()
        self._status_label.setText("Removed repository from recent list")

    def open_repository(self, selected_path: Path, *, remember: bool = True) -> None:
        repository = find_repository_root(selected_path)
        if repository is None:
            QMessageBox.warning(
                self,
                "Not a Git repository",
                f"No Git repository was found in or above:\n{selected_path}",
            )
            return
        if repository not in self._open_repositories:
            self._open_repositories.append(repository)
            self._workspace.save_open_repositories(self._open_repositories)
            self._populate_repository_switcher()
        self._activate_repository(repository, remember=remember)

    def _activate_repository(self, repository: Path, *, remember: bool = False) -> None:
        if repository not in self._open_repositories:
            self._open_repositories.append(repository)
            self._workspace.save_open_repositories(self._open_repositories)
            self._populate_repository_switcher()
        self._repository = repository
        self._repository_status = None
        self._commit_diff_visible = False
        self._workspace.set_last_repository(repository)
        self._repositories_panel.select_repository(repository)
        if remember:
            self._workspace.remember(repository)
            self._populate_recent_repositories()
        self._show_linked_repositories(repository)
        self._status_label.setText(f"Reading {repository.name}…")
        self._changes.clear()
        self._history_panel.reset()
        self._branches_panel.reset()
        self._diff_view.reset()
        self._welcome.hide()
        self._workspace_tabs.show()
        self._diff_version.show()
        self._diff_view_mode.show()
        self._diff_gutter.setVisible(not self._wrap_button.isChecked())
        self._diff.show()
        self._workspace_tab_changed(self._workspace_tabs.currentIndex())
        self._status_runner = self._git.request_status(repository)
        self._history_runner = self._git.request_history(repository)
        self._git.request_branches(repository)
        self._refresh_timer.start()

    @Slot(int)
    def _workspace_tab_changed(self, index: int) -> None:
        showing_history = index == 1
        showing_branches = index == 2
        show_diff = self._repository is not None and (
            not showing_history or self._commit_diff_visible
        ) and not showing_branches
        self._diff_container.setVisible(show_diff)
        if showing_history:
            if self._commit_diff_visible:
                self._splitter.setSizes([220, 0, 560, 840])
                self._history_panel.set_expanded_layout(False)
            else:
                available = max(
                    self._splitter.width() - self._repositories_panel.minimumWidth(), 600
                )
                self._splitter.setSizes([220, 0, available, 0])
                self._history_panel.set_expanded_layout(True)
        elif showing_branches:
            available = max(
                self._splitter.width() - self._repositories_panel.minimumWidth(), 600
            )
            self._splitter.setSizes([220, 0, available, 0])
            self._history_panel.set_expanded_layout(False)
        elif self._repository is not None:
            self._commit_diff_visible = False
            self._history_panel.set_expanded_layout(False)
            self._restore_workspace_splitter_sizes()

    @Slot()
    def _load_more_history(self) -> None:
        if self._repository is None:
            return
        if self._history_runner is not None and self._history_runner.is_running:
            return
        self._history_panel.set_loading(True)
        self._status_label.setText("Loading more commits…")
        self._history_runner = self._git.request_history(
            self._repository, offset=self._history_panel.commit_count
        )

    @Slot(object)
    def _show_history(self, value: object) -> None:
        if not isinstance(value, CommitPage):
            return
        if self._repository is None or value.repository != self._repository:
            return
        self._history_runner = None
        self._history_panel.show_page(value)
        count = self._history_panel.commit_count
        self._status_label.setText(f"Loaded {count} commits")

    @Slot(object)
    def _history_commit_selected(self, value: object) -> None:
        if self._repository is None or not isinstance(value, CommitSummary):
            return
        self._commit_diff_visible = False
        self._diff_view.reset()
        self._workspace_tab_changed(self._workspace_tabs.currentIndex())
        self._status_label.setText(f"Reading files for {value.oid[:8]}…")
        self._git.request_commit_files(self._repository, value.oid)

    @Slot(object)
    def _show_commit_files(self, value: object) -> None:
        if not isinstance(value, CommitFilesSnapshot) or value.repository != self._repository:
            return
        status = self._repository_status
        if (
            self._amend.isChecked()
            and status is not None
            and status.branch.oid == value.commit_oid
        ):
            self._amend_commit_files = value.files
            self._amend_files_loaded = True
            self._refresh_amend_tree_if_ready(value.repository)
            return
        commit = self._history_panel.selected_commit
        if commit is None or commit.oid != value.commit_oid:
            return
        self._history_panel.show_files(value)
        self._status_label.setText(
            f"{len(value.files)} file(s) changed in {value.commit_oid[:8]}"
        )

    @Slot(object, object)
    def _history_file_selected(self, commit_value: object, file_value: object) -> None:
        if (
            self._repository is None
            or not isinstance(commit_value, CommitSummary)
            or not isinstance(file_value, CommitFileChange)
        ):
            return
        self._status_label.setText(
            f"Reading {file_value.path} from {commit_value.oid[:8]}…"
        )
        self._git.request_commit_diff(
            self._repository,
            commit_value.oid,
            file_value.path,
            parent_oid=commit_value.parent_oids[0] if commit_value.parent_oids else None,
        )

    @Slot(object)
    def _show_commit_diff(self, value: object) -> None:
        if (
            not isinstance(value, CommitDiffSnapshot)
            or value.repository != self._repository
            or self._workspace_tabs.currentIndex() != 1
        ):
            return
        commit = self._history_panel.selected_commit
        if commit is None or commit.oid != value.commit_oid:
            return
        blocker = QSignalBlocker(self._diff_version)
        self._diff_version.clear()
        self._diff_version.addItem(f"Commit {value.commit_oid[:8]}", None)
        del blocker
        self._diff_view.display_diff(
            value.diff,
            selection_key=None,
            preserve_scroll=False,
            whole_file_staged=False,
            interactive=False,
        )
        self._diff_version.show()
        self._diff_view_mode.show()
        self._diff.show()
        self._diff_container.show()
        self._commit_diff_visible = True
        self._workspace_tab_changed(self._workspace_tabs.currentIndex())
        self._status_label.setText(
            f"Showing {value.diff.path} from {value.commit_oid[:8]}"
        )

    @Slot(object)
    def _show_branches(self, value: object) -> None:
        if not isinstance(value, BranchesSnapshot) or value.repository != self._repository:
            return
        self._branches_panel.show_branches(value)

    @Slot(object)
    def _checkout_branch(self, value: object) -> None:
        if self._repository is None or not isinstance(value, BranchInfo):
            return
        self._branches_panel.setEnabled(False)
        self._status_label.setText(f"Checking out {value.name}…")
        self._git.request_checkout(
            self._repository, value, autostash=self._branches_panel.autostash.isChecked()
        )

    @Slot()
    def _create_branch(self) -> None:
        if self._repository is None:
            return
        name, accepted = QInputDialog.getText(self, "New branch", "Branch name:")
        name = name.strip()
        if not accepted or not name:
            return
        self._branches_panel.setEnabled(False)
        self._status_label.setText(f"Creating branch {name}…")
        self._git.request_create_branch(self._repository, name)

    @Slot(object)
    def _rename_branch(self, value: object) -> None:
        if self._repository is None or not isinstance(value, BranchInfo):
            return
        name, accepted = QInputDialog.getText(
            self, "Rename branch", "New branch name:", text=value.name
        )
        name = name.strip()
        if not accepted or not name or name == value.name:
            return
        self._branches_panel.setEnabled(False)
        self._git.request_rename_branch(self._repository, value, name)

    @Slot(object)
    def _delete_branch(self, value: object) -> None:
        if self._repository is None or not isinstance(value, BranchInfo):
            return
        force = value.ahead > 0
        if force:
            detail = (
                f"Branch '{value.name}' is {value.ahead} commit(s) ahead of its upstream.\n\n"
                "Force-delete the local branch? Its remote branch and commits reachable "
                "from other branches will not be deleted."
            )
        else:
            detail = f"Delete local branch '{value.name}'?"
        answer = QMessageBox.question(
            self, "Force delete branch" if force else "Delete branch", detail
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._branches_panel.setEnabled(False)
        self._git.request_delete_branch(self._repository, value, force=force)

    def _show_linked_repositories(self, repository: Path) -> None:
        self._workspace_discovery.request_linked_repositories(repository)

    @Slot(object)
    def _linked_repositories_ready(self, value: object) -> None:
        if not isinstance(value, LinkedRepositoriesSnapshot):
            return
        self._repositories_panel.set_linked(value.repository, value.repositories)

    def _populate_repository_switcher(self) -> None:
        self._repositories_panel.set_open(self._open_repositories, self._repository)

    @Slot(object)
    def _repository_selected(self, value: object) -> None:
        if isinstance(value, Path) and value != self._repository and value.is_dir():
            self._activate_repository(value)

    def _restore_open_repositories(self) -> None:
        self._open_repositories = list(self._workspace.open_repositories())
        last = self._workspace.last_repository()
        if last is not None and last not in self._open_repositories:
            self._open_repositories.append(last)
        self._populate_repository_switcher()
        if last is not None:
            self._activate_repository(last)

    @Slot()
    def _save_workspace(self) -> None:
        name, accepted = QInputDialog.getText(self, "Save Workspace", "Workspace name:")
        if not accepted or not name.strip():
            return
        self._workspace.save_named_workspace(name, self._open_repositories)
        self._populate_workspace_menu()

    def _populate_workspace_menu(self) -> None:
        self._load_workspace_menu.clear()
        for name in self._workspace.named_workspaces():
            action = QAction(name, self)
            action.setData(name)
            action.triggered.connect(self._load_workspace)
            self._load_workspace_menu.addAction(action)
        self._load_workspace_menu.setEnabled(bool(self._workspace.named_workspaces()))

    @Slot()
    def _load_workspace(self) -> None:
        action = self.sender()
        if not isinstance(action, QAction):
            return
        name = action.data()
        if not isinstance(name, str):
            return
        repositories = list(self._workspace.load_named_workspace(name))
        if not repositories:
            return
        self._open_repositories = repositories
        self._workspace.save_open_repositories(repositories)
        self._populate_repository_switcher()
        self._activate_repository(repositories[0])

    @Slot()
    def _refresh_repository(self) -> None:
        if self._repository is None:
            return
        self._status_label.setText(f"Refreshing {self._repository.name}…")
        self._status_runner = self._git.request_status(self._repository)

    @Slot()
    def _pull_repository(self) -> None:
        if self._repository is None:
            return
        self._status_label.setText("Pulling changes…")
        self._set_network_busy("Pull")
        self._git.request_pull(
            self._repository,
            rebase=self._pull_rebase_action.isChecked(),
            autostash=self._pull_autostash_action.isChecked(),
        )

    @Slot()
    def _pull_options_changed(self) -> None:
        self._settings.setValue("sync/pullRebase", self._pull_rebase_action.isChecked())
        self._settings.setValue(
            "sync/pullAutostash", self._pull_autostash_action.isChecked()
        )
        self._update_pull_button()

    def _update_pull_button(self) -> None:
        rebase = self._pull_rebase_action.isChecked()
        strategy = "Rebase" if rebase else "Merge"
        self._pull_action.setIcon(
            load_icon("pull-rebase.svg" if rebase else "pull-merge.svg")
        )
        suffix = " · Stash" if self._pull_autostash_action.isChecked() else ""
        behind = (
            self._repository_status.branch.behind
            if self._repository_status is not None
            else 0
        )
        incoming = f" ↓{behind}" if behind else ""
        self._pull_action.setText(f"Pull{incoming} · {strategy}{suffix}")

    def _update_sync_indicators(self) -> None:
        self._update_pull_button()
        status = self._repository_status
        pull_text, push_text = sync_action_labels(
            status,
            rebase=self._pull_rebase_action.isChecked(),
            autostash=self._pull_autostash_action.isChecked(),
        )
        self._pull_action.setText(pull_text)
        self._push_action.setText(push_text)
        self._push_action.setIcon(
            load_icon("force-push.svg" if push_requires_rewrite(status) else "push.svg")
        )
        if status is None or status.branch.head is None:
            self._push_action.setToolTip("No checked-out branch to push")
            return
        branch = status.branch
        if branch.upstream is None:
            self._push_action.setToolTip(
                f"Publish {branch.head} to origin and configure its upstream"
            )
        elif push_requires_rewrite(status):
            self._push_action.setToolTip(
                f"A normal push to {branch.upstream} will be rejected: the branches "
                f"have diverged ({branch.ahead} ahead, {branch.behind} behind). "
                "Pull/Rebase first, or use Force push with lease from the arrow menu."
            )
        else:
            self._push_action.setToolTip(
                f"{branch.ahead} commit(s) ready to push to {branch.upstream}"
            )
        self._pull_action.setToolTip(
            f"{branch.behind} commit(s) available from {branch.upstream or 'upstream'}"
        )

    @Slot()
    def _fetch_repository(self) -> None:
        if self._repository is None:
            return
        self._status_label.setText("Fetching changes…")
        self._set_network_busy("Fetch")
        self._git.request_fetch(self._repository)

    @Slot()
    def _push_repository(self) -> None:
        if push_requires_rewrite(self._repository_status):
            QMessageBox.information(
                self,
                "Normal push unavailable",
                "The local and remote branches have diverged, so a normal push would "
                "be rejected.\n\nPull with Rebase to preserve both histories, or choose "
                "Force push with lease from the Push arrow menu to replace the remote "
                "history safely.",
            )
            return
        self._start_push(force_with_lease=False)

    @Slot()
    def _force_push_repository(self) -> None:
        answer = QMessageBox.warning(
            self,
            "Force push with lease",
            "Rewrite the remote branch only if it has not changed since the last fetch?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._start_push(force_with_lease=True)

    def _start_push(self, *, force_with_lease: bool) -> None:
        if self._repository is None or self._repository_status is None:
            return
        branch = self._repository_status.branch
        if branch.head is None:
            QMessageBox.information(self, "Cannot push", "Check out a branch before pushing.")
            return
        set_upstream = branch.upstream is None
        if set_upstream:
            answer = QMessageBox.question(
                self,
                "Publish branch",
                f"Publish '{branch.head}' to origin and set its upstream?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self._status_label.setText(f"Pushing {branch.head}…")
        self._set_network_busy("Force push" if force_with_lease else "Push")
        self._git.request_push(
            self._repository,
            branch=branch.head,
            set_upstream=set_upstream,
            force_with_lease=force_with_lease,
        )

    def _set_network_busy(self, operation: str | None) -> None:
        busy = operation is not None
        self._fetch_action.setEnabled(not busy)
        self._pull_action.setEnabled(not busy)
        self._push_action.setEnabled(not busy)
        self._force_push_action.setEnabled(not busy)
        self._cancel_action.setEnabled(busy)
        if operation is not None:
            self._cancel_action.setToolTip(f"Cancel {operation}")

    @Slot()
    def _poll_repository(self) -> None:
        if self._repository is None:
            return
        if self._status_runner is not None and self._status_runner.is_running:
            return
        self._status_runner = self._git.request_status(self._repository)

    @Slot()
    def _cancel_operations(self) -> None:
        self._git.cancel_all()
        self._workspace_discovery.cancel_all()
        self._status_label.setText("Cancelling operations…")

    @Slot()
    def _operation_cancelled(self) -> None:
        self._set_network_busy(None)
        self._status_runner = None
        self._history_runner = None
        self._changes.setEnabled(True)
        self._changes_container.setEnabled(True)
        self._status_label.setText("Operation cancelled")

    @Slot(object)
    def _show_status(self, value: object) -> None:
        if not isinstance(value, RepositoryStatusSnapshot):
            return
        if self._repository is None or value.repository != self._repository:
            return
        self._status_runner = None
        status_value = value.status
        if status_value == self._repository_status and (
            not self._amend.isChecked() or not self._amend_render_pending
        ):
            self._request_diff(silent=True)
            return
        selected_path: str | None = None
        selected_items = self._changes.selectedItems()
        if selected_items:
            selected_file = selected_items[0].data(0, Qt.ItemDataRole.UserRole)
            if isinstance(selected_file, FileStatus):
                selected_path = selected_file.path
        self._repository_status = status_value
        self._update_sync_indicators()
        changed_paths = {file.path for file in status_value.files}
        self._diff_view.retain_changed_paths(value.repository, changed_paths)
        blocker = QSignalBlocker(self._changes)
        stage_all_blocker = QSignalBlocker(self._stage_all)
        item_to_restore: QTreeWidgetItem | None = None
        self._changes.clear()
        files_to_show = list(status_value.files)
        if self._amend.isChecked():
            visible_paths = {file.path for file in files_to_show}
            for change in self._amend_commit_files:
                if change.path not in visible_paths:
                    files_to_show.append(FileStatus(change.path, ".", "."))
        for file in files_to_show:
            index_label = "" if file.index_status == "?" else _status_label(file.index_status)
            item = QTreeWidgetItem(
                [file.path, index_label, _status_label(file.worktree_status)]
            )
            if file.original_path is not None:
                item.setToolTip(0, f"Renamed from {file.original_path}")
            item.setData(0, Qt.ItemDataRole.UserRole, file)
            if not file.unmerged:
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                has_saved_selection = self._diff_view.has_saved_selection(
                    value.repository, file.path
                )
                if self._amend.isChecked():
                    included = file.path in self._amend_included_paths
                    if included and file.has_worktree_change:
                        state = Qt.CheckState.PartiallyChecked
                    elif included:
                        state = Qt.CheckState.Checked
                    else:
                        state = Qt.CheckState.Unchecked
                    item.setCheckState(0, state)
                elif has_saved_selection or (file.is_staged and file.has_worktree_change):
                    item.setCheckState(0, Qt.CheckState.PartiallyChecked)
                elif file.is_staged:
                    item.setCheckState(0, Qt.CheckState.Checked)
                else:
                    item.setCheckState(0, Qt.CheckState.Unchecked)
            self._changes.addTopLevelItem(item)
            if file.path == selected_path:
                item_to_restore = item
        del blocker
        stageable = [file for file in status_value.files if not file.unmerged]
        has_conflicts = any(file.unmerged for file in status_value.files)
        self._stage_all.setEnabled(bool(stageable) and not has_conflicts)
        if not stageable or not any(file.is_staged for file in stageable):
            self._stage_all.setCheckState(Qt.CheckState.Unchecked)
        elif all(file.is_staged and not file.has_worktree_change for file in stageable):
            self._stage_all.setCheckState(Qt.CheckState.Checked)
        else:
            self._stage_all.setCheckState(Qt.CheckState.PartiallyChecked)
        del stage_all_blocker
        if item_to_restore is not None:
            self._changes.setCurrentItem(item_to_restore)
        elif (
            not self._amend.isChecked()
            and self._diff_view.current_diff is not None
            and self._diff_view.current_diff.path not in changed_paths
        ):
            self._diff_view.reset()
        self._changes.resizeColumnToContents(0)
        self._amend_render_pending = False

        branch = status_value.branch.head or "detached HEAD"
        repository_name = self._repository.name
        change_count = len(status_value.files)
        self.setWindowTitle(f"{repository_name} — {branch} — MyGitClient")
        self._status_label.setText(f"{branch} · {change_count} changed file(s)")
        self._update_generated_commit_text(status_value)
        self._update_commit_controls()

    def _update_generated_commit_text(self, status: RepositoryStatus) -> None:
        staged = [file for file in status.files if file.is_staged]
        changes = [(_commit_change_label(file), file.path) for file in staged]
        if len(changes) == 1:
            action, path = changes[0]
            message = f"{action} {path}"
        elif changes:
            actions = {action for action, _path in changes}
            action = actions.pop() if len(actions) == 1 else "Update"
            message = f"{action} {len(changes)} files"
        else:
            message = ""
        description = "\n".join(f"- {action} {path}" for action, path in changes)

        current_message = self._commit_message.toPlainText()
        if not current_message or current_message == self._generated_commit_message:
            blocker = QSignalBlocker(self._commit_message)
            self._commit_message.setPlainText(message)
            del blocker
        current_description = self._commit_description.toPlainText()
        if not current_description or current_description == self._generated_commit_description:
            blocker = QSignalBlocker(self._commit_description)
            self._commit_description.setPlainText(description)
            del blocker
        self._generated_commit_message = message
        self._generated_commit_description = description

    @Slot(QTreeWidgetItem, int)
    def _stage_checkbox_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if column != 0 or self._repository is None:
            return
        file = item.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(file, FileStatus) or file.unmerged:
            return
        should_stage = item.checkState(0) != Qt.CheckState.Unchecked
        self._changes.setEnabled(False)
        if self._amend.isChecked() and self._repository_status is not None:
            commit_oid = self._repository_status.branch.oid
            if commit_oid is not None:
                self._git.request_amend_file(
                    self._repository,
                    commit_oid,
                    self._amend_parent_oid,
                    file.path,
                    included=should_stage,
                )
                return
        action = "Staging" if should_stage else "Unstaging"
        self._status_label.setText(f"{action} {file.path}…")
        self._git.request_stage(self._repository, file, staged=should_stage)

    @Slot(int)
    def _stage_all_changed(self, state: int) -> None:
        repository = self._repository
        status = self._repository_status
        if repository is None or status is None:
            return
        should_stage = Qt.CheckState(state) != Qt.CheckState.Unchecked
        self._changes_container.setEnabled(False)
        action = "Staging" if should_stage else "Unstaging"
        self._status_label.setText(f"{action} all changes…")
        self._git.request_stage_all(
            repository,
            staged=should_stage,
            has_head=status.branch.oid is not None,
        )

    @Slot(str)
    def _mutation_finished(self, path: str) -> None:
        if path in {"fetch", "pull", "push"}:
            self._set_network_busy(None)
        self._changes.setEnabled(True)
        self._changes_container.setEnabled(True)
        self._branches_panel.setEnabled(True)
        if path == "commit":
            self._commit_message.clear()
            self._commit_description.clear()
            self._generated_commit_message = ""
            self._generated_commit_description = ""
            self._pre_amend_message = ""
            self._pre_amend_description = ""
            self._amend.setChecked(False)
            self._status_label.setText("Commit created")
        elif path.startswith("branch:"):
            self._status_label.setText(f"Checked out {path.removeprefix('branch:')}")
        elif path == "branches:renamed":
            self._status_label.setText("Branch renamed")
        elif path == "branches:deleted":
            self._status_label.setText("Branch deleted")
        elif path == "pull":
            self._status_label.setText("Pull completed")
        elif path == "fetch":
            self._status_label.setText("Fetch completed")
        elif path == "push":
            self._status_label.setText("Push completed")
        elif path == "stash":
            self._status_label.setText("Selected changes stashed")
        else:
            self._status_label.setText(f"Updated staging area for {path}")
        if self._repository is not None:
            status = self._repository_status
            if self._amend.isChecked() and status is not None and status.branch.oid:
                self._git.request_amend_diff(
                    self._repository,
                    status.branch.oid,
                    parent_oid=self._amend_parent_oid,
                )
            self._status_runner = self._git.request_status(self._repository)
            self._git.request_branches(self._repository)

    @Slot()
    def _update_commit_controls(self) -> None:
        status = self._repository_status
        message = self._commit_message.toPlainText().strip()
        amend = self._amend.isChecked()
        has_staged = status is not None and any(file.is_staged for file in status.files)
        has_head = status is not None and status.branch.oid is not None
        allowed = bool(message) and ((amend and has_head) or (not amend and has_staged))
        self._commit_button.setEnabled(allowed)
        if not message:
            self._commit_error.setText("Enter a commit message.")
        elif amend and not has_head:
            self._commit_error.setText("There is no commit to amend.")
        elif not amend and not has_staged:
            self._commit_error.setText("Stage at least one change.")
        else:
            self._commit_error.clear()

    @Slot(bool)
    def _amend_toggled(self, checked: bool) -> None:
        self._update_commit_controls()
        repository = self._repository
        status = self._repository_status
        if checked:
            if repository is None or status is None or status.branch.oid is None:
                return
            self._pre_amend_message = self._commit_message.toPlainText()
            self._pre_amend_description = self._commit_description.toPlainText()
            self._status_label.setText("Loading the last commit for amend…")
            self._git.request_amend_preview(repository, status.branch.oid)
            self._amend_files_loaded = False
            self._amend_diff_loaded = False
            self._git.request_commit_files(repository, status.branch.oid)
            return
        message_blocker = QSignalBlocker(self._commit_message)
        description_blocker = QSignalBlocker(self._commit_description)
        self._commit_message.setPlainText(self._pre_amend_message)
        self._commit_description.setPlainText(self._pre_amend_description)
        del message_blocker, description_blocker
        self._request_selected_diff()
        self._amend_commit_files = ()
        self._amend_included_paths = frozenset()
        self._amend_parent_oid = None
        self._amend_render_pending = False
        self._amend_files_loaded = False
        self._amend_diff_loaded = False
        self._update_commit_controls()

    @Slot(object)
    def _show_amend_preview(self, value: object) -> None:
        status = self._repository_status
        if (
            not isinstance(value, AmendPreview)
            or value.repository != self._repository
            or not self._amend.isChecked()
            or status is None
            or status.branch.oid != value.commit_oid
        ):
            return
        message_blocker = QSignalBlocker(self._commit_message)
        description_blocker = QSignalBlocker(self._commit_description)
        self._commit_message.setPlainText(value.subject)
        self._commit_description.setPlainText(value.description)
        del message_blocker, description_blocker
        self._amend_parent_oid = value.parent_oid
        self._git.request_amend_diff(
            value.repository, value.commit_oid, parent_oid=value.parent_oid
        )
        self._update_commit_controls()

    @Slot(object)
    def _show_amend_diff(self, value: object) -> None:
        status = self._repository_status
        if (
            not isinstance(value, AmendDiffSnapshot)
            or value.repository != self._repository
            or not self._amend.isChecked()
            or status is None
            or status.branch.oid != value.commit_oid
        ):
            return
        if value.path is None:
            self._amend_included_paths = value.included_paths
            self._amend_diff_loaded = True
        version_blocker = QSignalBlocker(self._diff_version)
        self._diff_version.clear()
        label = f"Amend {value.commit_oid[:8]}"
        if value.path is not None:
            label = f"{label} В· {value.path}"
        self._diff_version.addItem(label, None)
        del version_blocker
        self._diff_view.display_diff(
            value.diff,
            selection_key=None,
            preserve_scroll=False,
            whole_file_staged=False,
            interactive=False,
        )
        self._status_label.setText(f"Showing commit {value.commit_oid[:8]} to amend")
        if value.path is None:
            self._refresh_amend_tree_if_ready(value.repository)

    def _refresh_amend_tree_if_ready(self, repository: Path) -> None:
        if not self._amend_files_loaded or not self._amend_diff_loaded:
            return
        self._amend_diff_loaded = False
        self._amend_render_pending = True
        self._status_runner = self._git.request_status(repository)

    @Slot()
    def _create_commit(self) -> None:
        repository = self._repository
        message = self._commit_message.toPlainText().strip()
        description = self._commit_description.toPlainText().strip()
        if repository is None or not self._commit_button.isEnabled() or not message:
            return
        self._changes_container.setEnabled(False)
        self._status_label.setText("Creating commit…")
        self._git.request_commit(
            repository, message, description, amend=self._amend.isChecked()
        )

    @Slot()
    def _selected_file_changed(self) -> None:
        if self._amend.isChecked():
            selected_items = self._changes.selectedItems()
            status = self._repository_status
            if (
                not selected_items
                or self._repository is None
                or status is None
                or status.branch.oid is None
            ):
                return
            file = selected_items[0].data(0, Qt.ItemDataRole.UserRole)
            if not isinstance(file, FileStatus):
                return
            self._diff.setPlainText("Loading amend diffвЂ¦")
            self._git.request_amend_diff(
                self._repository,
                status.branch.oid,
                parent_oid=self._amend_parent_oid,
                path=file.path,
            )
            return
        selected_items = self._changes.selectedItems()
        if not selected_items:
            return
        file = selected_items[0].data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(file, FileStatus):
            return
        self._populate_diff_versions(file)
        self._request_selected_diff()

    @Slot()
    def _update_file_actions(self) -> None:
        files = self._selected_files()
        file = files[0] if len(files) == 1 else None
        safe_files = bool(files) and all(not selected.unmerged for selected in files)
        self._discard_action.setEnabled(safe_files)
        self._stash_action.setEnabled(safe_files)
        self._ignore_action.setEnabled(file is not None and file.index_status == "?")

    def _selected_files(self) -> tuple[FileStatus, ...]:
        files: list[FileStatus] = []
        for item in self._changes.selectedItems():
            value = item.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(value, FileStatus):
                files.append(value)
        return tuple(files)

    def _selected_file(self) -> FileStatus | None:
        selected_items = self._changes.selectedItems()
        if not selected_items:
            return None
        value = selected_items[0].data(0, Qt.ItemDataRole.UserRole)
        return value if isinstance(value, FileStatus) else None

    @Slot()
    def _discard_selected_file(self) -> None:
        files = self._selected_files()
        repository = self._repository
        if repository is None or not files or any(file.unmerged for file in files):
            return
        target = files[0].path if len(files) == 1 else f"{len(files)} selected files"
        answer = QMessageBox.question(
            self,
            "Discard changes",
            f"Permanently discard all changes to {target}?",
            QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Discard:
            return
        self._changes_container.setEnabled(False)
        self._status_label.setText(f"Discarding changes to {target}…")
        for file in files:
            self._git.request_discard(repository, file)

    @Slot()
    def _stash_selected_files(self) -> None:
        files = self._selected_files()
        repository = self._repository
        if repository is None or not files or any(file.unmerged for file in files):
            return
        self._changes_container.setEnabled(False)
        self._status_label.setText(f"Stashing {len(files)} selected file(s)…")
        self._git.request_stash_files(repository, files)

    @Slot()
    def _ignore_selected_file(self) -> None:
        file = self._selected_file()
        repository = self._repository
        if file is None or repository is None or file.index_status != "?":
            return
        self._git.ignore_path(repository, file.path)

    @Slot()
    def _request_selected_diff(self) -> None:
        self._request_diff(silent=False)

    def _request_diff(self, *, silent: bool) -> None:
        selected_items = self._changes.selectedItems()
        repository = self._repository
        if not selected_items or repository is None:
            return
        item = selected_items[0]
        file = item.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(file, FileStatus):
            return
        staged = self._diff_version.currentData()
        if not isinstance(staged, bool):
            return
        if not silent:
            self._diff.setPlainText("Loading diff…")
            self._status_label.setText(f"Reading diff for {file.path}…")
        self._git.request_diff(repository, file, staged=staged)

    def _populate_diff_versions(self, file: FileStatus) -> None:
        blocker = QSignalBlocker(self._diff_version)
        self._diff_version.clear()
        if file.has_worktree_change:
            self._diff_version.addItem("Working tree", False)
        if file.is_staged:
            self._diff_version.addItem("Staged", True)
        del blocker

    @Slot(object)
    def _show_diff(self, value: object) -> None:
        if not isinstance(value, DiffSnapshot):
            return
        if self._amend.isChecked():
            return
        if value.repository != self._repository:
            return
        diff_value = value.diff
        selected_items = self._changes.selectedItems()
        if not selected_items:
            return
        current = selected_items[0]
        file = current.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(file, FileStatus) or file.path != diff_value.path:
            return
        if self._diff_version.currentData() != diff_value.staged:
            return
        preserve_selection = diff_value == self._diff_view.current_diff
        whole_file_staged = (
            diff_value.staged and file.is_staged and not file.has_worktree_change
        )
        self._diff_view.display_diff(
            diff_value,
            selection_key=(value.repository, diff_value.path, diff_value.staged),
            preserve_scroll=preserve_selection,
            whole_file_staged=whole_file_staged,
        )
        version = "staged" if diff_value.staged else "working tree"
        self._status_label.setText(f"Showing {version} diff for {diff_value.path}")

    def _sync_selected_file_checkbox(self) -> None:
        selected_items = self._changes.selectedItems()
        if not selected_items:
            return
        item = selected_items[0]
        file = item.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(file, FileStatus) or file.unmerged:
            return
        if self._diff_view.has_pending_partial_selection or (
            file.is_staged and file.has_worktree_change
        ):
            state = Qt.CheckState.PartiallyChecked
        elif file.is_staged:
            state = Qt.CheckState.Checked
        else:
            state = Qt.CheckState.Unchecked
        blocker = QSignalBlocker(self._changes)
        item.setCheckState(0, state)
        del blocker

    @Slot(object, object)
    def _apply_diff_lines(self, diff_value: object, selected_value: object) -> None:
        repository = self._repository
        if repository is None or not isinstance(diff_value, UnifiedDiff):
            return
        if not isinstance(selected_value, set):
            return
        selected_objects = cast(set[object], selected_value)
        if not all(isinstance(index, int) for index in selected_objects):
            return
        selected_lines = {index for index in selected_objects if isinstance(index, int)}
        if not selected_lines:
            return
        self._changes_container.setEnabled(False)
        action = "Unstaging" if diff_value.staged else "Staging"
        self._status_label.setText(f"{action} selected lines in {diff_value.path}…")
        self._git.request_lines(
            repository,
            diff_value,
            selected_lines,
            stage=not diff_value.staged,
        )

    @Slot(int)
    def _diff_view_changed(self, _index: int) -> None:
        mode = self._diff_view_mode.currentData()
        if not isinstance(mode, str):
            return
        self._settings.setValue("diff/viewMode", mode)
        self._diff_view.set_view_mode(mode)
    @Slot(object, int)
    def _apply_diff_hunk(self, diff_value: object, hunk_index: int) -> None:
        repository = self._repository
        if repository is None or not isinstance(diff_value, UnifiedDiff):
            return
        self._changes_container.setEnabled(False)
        action = "Unstaging" if diff_value.staged else "Staging"
        self._status_label.setText(f"{action} hunk in {diff_value.path}…")
        self._git.request_hunk(
            repository, diff_value, hunk_index, stage=not diff_value.staged
        )

    @Slot(bool)
    def _diff_wrap_changed(self, enabled: bool) -> None:
        self._settings.setValue("diff/wrapLines", enabled)
        self._apply_diff_wrap(enabled)

    def _apply_diff_wrap(self, enabled: bool) -> None:
        self._diff_view.set_wrap(enabled)

    @Slot(bool)
    def _diff_whitespace_changed(self, enabled: bool) -> None:
        self._settings.setValue("diff/showWhitespace", enabled)
        self._apply_diff_whitespace(enabled)

    def _apply_diff_whitespace(self, enabled: bool) -> None:
        self._diff_view.set_whitespace(enabled)

    @Slot(str)
    def _show_git_error(self, message: str) -> None:
        self._set_network_busy(None)
        self._status_runner = None
        self._history_runner = None
        self._changes.setEnabled(True)
        self._changes_container.setEnabled(True)
        self._branches_panel.setEnabled(True)
        self._status_label.setText("Git operation failed")
        QMessageBox.critical(self, "Git error", message)

    @Slot(QAction)
    def _theme_selected(self, action: QAction) -> None:
        theme = Theme.from_value(action.data())
        self._theme = theme
        self._settings.setValue("appearance/theme", theme.value)
        app = QApplication.instance()
        if isinstance(app, QApplication):
            apply_theme(app, theme)
            self._diff_view.rehighlight()

    def _restore_window_state(self) -> None:
        geometry = self._settings.value("window/geometry")
        state = self._settings.value("window/state")
        if isinstance(geometry, QByteArray):
            self.restoreGeometry(geometry)
        if isinstance(state, QByteArray):
            self.restoreState(state)

    def _restore_workspace_splitter_sizes(self) -> None:
        value: object = self._settings.value("window/workspaceSplitterSizes")
        if isinstance(value, list):
            items = cast(list[object], value)
            sizes = [item for item in items if isinstance(item, int)]
            if len(items) == 4 and len(sizes) == 4:
                sizes[1] = 0
                self._splitter.setSizes(sizes)
                return
        self._splitter.setSizes([240, 0, 360, 900])

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        self._workspace_discovery.shutdown()
        self._settings.setValue("window/geometry", self.saveGeometry())
        self._settings.setValue("window/state", self.saveState())
        if self._repository is not None:
            self._settings.setValue("window/workspaceSplitterSizes", self._splitter.sizes())
        super().closeEvent(event)


def sync_action_labels(
    status: RepositoryStatus | None, *, rebase: bool, autostash: bool
) -> tuple[str, str]:
    branch = status.branch if status is not None else None
    incoming = f" ↓{branch.behind}" if branch is not None and branch.behind else ""
    strategy = "Rebase" if rebase else "Merge"
    stash = " · Stash" if autostash else ""
    pull = f"Pull{incoming} · {strategy}{stash}"
    if branch is None or branch.head is None:
        push = "Push"
    elif branch.upstream is None:
        push = "Push · Publish"
    elif branch.ahead and branch.behind:
        push = f"Push ⚠ ↑{branch.ahead}"
    else:
        outgoing = f" ↑{branch.ahead}" if branch.ahead else ""
        push = f"Push{outgoing}"
    return pull, push


def push_requires_rewrite(status: RepositoryStatus | None) -> bool:
    if status is None:
        return False
    branch = status.branch
    return branch.upstream is not None and branch.ahead > 0 and branch.behind > 0


def _status_label(code: str) -> str:
    return {
        ".": "",
        "?": "Untracked",
        "!": "Ignored",
        "A": "Added",
        "M": "Modified",
        "D": "Deleted",
        "R": "Renamed",
        "C": "Copied",
        "U": "Unmerged",
        "T": "Type changed",
    }.get(code, code)


def _commit_change_label(file: FileStatus) -> str:
    return {
        "A": "Add",
        "D": "Delete",
        "R": "Rename",
        "C": "Copy",
        "T": "Change type of",
    }.get(file.index_status, "Update")
