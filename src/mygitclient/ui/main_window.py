from __future__ import annotations

import sys
from pathlib import Path
from time import monotonic
from typing import cast

from PySide6.QtCore import (
    QByteArray,
    QElapsedTimer,
    QProcess,
    QSettings,
    QSignalBlocker,
    Qt,
    QTimer,
    QUrl,
    Signal,
    Slot,
)
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QCloseEvent,
    QDesktopServices,
    QFontDatabase,
    QKeySequence,
    QShortcut,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressDialog,
    QPushButton,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QToolBar,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from mygitclient import __version__
from mygitclient.git.conflicts import conflict_marker_lines
from mygitclient.git.models import (
    AmendDiffSnapshot,
    AmendPreview,
    BranchesSnapshot,
    BranchInfo,
    BranchPointSnapshot,
    CherryPickPreviewSnapshot,
    CommitDiffSnapshot,
    CommitFileChange,
    CommitFilesSnapshot,
    CommitPage,
    CommitSummary,
    ConflictVersionsSnapshot,
    DiffSnapshot,
    FileStatus,
    MergePreviewSnapshot,
    RebasePreviewSnapshot,
    RefComparisonDiffSnapshot,
    RefComparisonSnapshot,
    ReflogSnapshot,
    RepositoryOperation,
    RepositoryOperationSnapshot,
    RepositoryStatus,
    RepositoryStatusSnapshot,
    RevertPreviewSnapshot,
    StashesSnapshot,
    StashInfo,
    TagInfo,
    TagsSnapshot,
    UnifiedDiff,
)
from mygitclient.git.operation_queue import OperationQueueSnapshot, QueuedOperation
from mygitclient.git.runner import GitRunner
from mygitclient.git.service import GitService
from mygitclient.resources import load_icon
from mygitclient.theme import Theme
from mygitclient.ui.changes_panel import ChangesPanel
from mygitclient.ui.commit_text import generated_commit_text
from mygitclient.ui.conflict_editor import ConflictEditor
from mygitclient.ui.diff_view import DiffView
from mygitclient.ui.history_panel import HistoryPanel
from mygitclient.ui.home_panel import HomePanel
from mygitclient.ui.interactive_rebase import InteractiveRebaseDialog
from mygitclient.ui.operation_output import OperationOutputDialog
from mygitclient.ui.repositories_panel import RepositoriesPanel
from mygitclient.updates import (
    UpdateChecker,
    UpdateDownloader,
    UpdateInfo,
    launch_updater,
    portable_install_directory,
)
from mygitclient.workspace import (
    LinkedRepositoriesSnapshot,
    LinkedRepository,
    WorkspaceDiscoveryService,
    WorkspaceManager,
    find_repository_root,
)


class MainWindow(QMainWindow):
    repository_tab_requested = Signal(object, bool)
    restart_requested = Signal()

    def __init__(
        self, settings: QSettings, theme: Theme, *, session_mode: bool = False
    ) -> None:
        super().__init__()
        self._settings = settings
        self._theme = theme
        self._session_mode = session_mode
        self._apply_saved_ui_font()
        self._workspace = WorkspaceManager(settings)
        self._workspace_discovery = WorkspaceDiscoveryService(self)
        self._update_checker = UpdateChecker(self)
        self._update_downloader = UpdateDownloader(self)
        self._update_progress: QProgressDialog | None = None
        self._manual_update_check = False
        self._git_error_dialog_open = False
        self._last_git_error_at = 0.0
        self._update_checker.update_available.connect(self._update_available)
        self._update_checker.up_to_date.connect(self._update_is_current)
        self._update_checker.failed.connect(self._update_check_failed)
        self._update_downloader.progress.connect(self._update_download_progress)
        self._update_downloader.ready.connect(self._update_downloaded)
        self._update_downloader.failed.connect(self._update_download_failed)
        self._update_downloader.cancelled.connect(self._update_download_cancelled)
        self._git = GitService(self)
        self._repository: Path | None = None
        self._repository_activation = 0
        self._open_repositories: list[Path] = []
        self._repository_status: RepositoryStatus | None = None
        self._repository_operation: RepositoryOperation | None = None
        self._interactive_rebase_pending = False
        self._rewrite_recovery_head = ""
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
        self._history_repository: Path | None = None
        self._history_refs: tuple[str, ...] = ()
        self._active_queue_operation: QueuedOperation | None = None
        self._queued_operation_count = 0
        self._refresh_all_after_queue = False
        self._clear_change_selection_after_mutation = False
        self._queue_elapsed = QElapsedTimer()
        self._known_queue_operations: dict[int, QueuedOperation] = {}
        self._operation_output_dialogs: dict[int, OperationOutputDialog] = {}
        self._queue_duration_timer = QTimer(self)
        self._queue_duration_timer.setInterval(1000)
        self._queue_duration_timer.timeout.connect(self._update_queue_duration)
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
        if not self._session_mode:
            self._restore_open_repositories()

    def _build_ui(self) -> None:
        self._repositories_panel = RepositoriesPanel()
        self._repositories = self._repositories_panel.tree

        self._welcome = HomePanel()
        self._welcome.choose_repository_requested.connect(self._choose_repository)
        self._welcome.open_repository_requested.connect(self._open_home_repository)
        self._welcome.open_workspace_requested.connect(self._open_named_workspace)

        self._changes_panel = ChangesPanel(self._settings)
        self._changes_container = self._changes_panel
        self._changes = self._changes_panel.tree
        self._open_file_action = self._changes_panel.open_action
        self._open_file_with_action = self._changes_panel.open_with_action
        self._reveal_file_action = self._changes_panel.reveal_action
        self._use_ours_action = self._changes_panel.use_ours_action
        self._use_theirs_action = self._changes_panel.use_theirs_action
        self._conflict_actions_separator = (
            self._changes_panel.conflict_actions_separator
        )
        self._discard_action = self._changes_panel.discard_action
        self._stash_action = self._changes_panel.stash_action
        self._ignore_action = self._changes_panel.ignore_action
        self._stage_all = self._changes_panel.stage_all
        self._commit_message = self._changes_panel.commit_message
        self._commit_description = self._changes_panel.commit_description
        self._amend = self._changes_panel.amend
        self._commit_button = self._changes_panel.commit_button
        self._commit_error = self._changes_panel.commit_error

        self._open_file_action.triggered.connect(self._open_selected_file)
        self._open_file_with_action.triggered.connect(self._open_selected_file_with)
        self._reveal_file_action.triggered.connect(self._reveal_selected_file)
        self._use_ours_action.triggered.connect(
            lambda: self._use_selected_conflict_side("ours")
        )
        self._use_theirs_action.triggered.connect(
            lambda: self._use_selected_conflict_side("theirs")
        )
        self._ignore_action.triggered.connect(self._ignore_selected_file)
        self._commit_message.textChanged.connect(self._update_commit_controls)
        self._amend.toggled.connect(self._amend_toggled)
        self._commit_button.clicked.connect(self._create_commit)
        self._changes_panel.stage_requested.connect(self._stage_checked_changes)
        self._changes_panel.unstage_requested.connect(self._unstage_checked_changes)
        self._changes_panel.stash_requested.connect(self._stash_checked_changes)
        self._changes_panel.discard_requested.connect(self._discard_checked_changes)
        self._changes_panel.view_mode_changed.connect(self._changes_view_mode_changed)
        self._changes_panel.presentation_mode_changed.connect(
            self._changes_view_mode_changed
        )
        self._update_commit_controls()

        self._history_panel = HistoryPanel(self._settings)
        self._history_panel.load_more_requested.connect(self._load_more_history)
        self._history_panel.commit_selected.connect(self._history_commit_selected)
        self._history_panel.cherry_pick_requested.connect(
            self._preview_cherry_pick
        )
        self._history_panel.revert_requested.connect(self._preview_revert)
        self._history_panel.focus_mode_changed.connect(self._history_focus_mode_changed)
        self._history_panel.file_selected.connect(self._history_file_selected)
        self._history_panel.comparison_file_selected.connect(
            self._history_comparison_file_selected
        )
        refs_panel = self._history_panel.refs_panel
        refs_panel.refs_selected.connect(self._history_refs_selected)
        refs_panel.checkout_requested.connect(self._checkout_branch)
        refs_panel.rename_requested.connect(self._rename_branch)
        refs_panel.delete_requested.connect(self._delete_branch)
        refs_panel.force_delete_requested.connect(self._force_delete_branch)
        refs_panel.remote_delete_requested.connect(self._delete_remote_branch)
        refs_panel.cleanup_gone_requested.connect(self._cleanup_gone_branches)
        refs_panel.rebase_requested.connect(self._preview_rebase)
        refs_panel.interactive_rebase_requested.connect(self._preview_interactive_rebase)
        refs_panel.merge_requested.connect(self._preview_merge)
        refs_panel.create_branch_requested.connect(self._create_branch)
        refs_panel.create_branch_from_requested.connect(self._create_branch_from)
        refs_panel.publish_branch_requested.connect(self._publish_branch)
        refs_panel.create_tag_requested.connect(self._create_tag)
        refs_panel.delete_tag_requested.connect(self._delete_tag)
        refs_panel.push_tag_requested.connect(self._push_tag)
        refs_panel.stash_apply_requested.connect(self._apply_stash)
        refs_panel.stash_pop_requested.connect(self._pop_stash)
        refs_panel.stash_drop_requested.connect(self._drop_stash)
        refs_panel.repository_requested.connect(self._open_linked_repository)

        self._workspace_tabs = QTabWidget()
        self._workspace_tabs.setObjectName("workspaceTabs")
        self._workspace_tabs.addTab(self._changes_container, "Changes")
        self._workspace_tabs.addTab(self._history_panel, "History")
        self._workspace_tabs.setMinimumWidth(360)
        self._workspace_tabs.currentChanged.connect(self._workspace_tab_changed)
        self._operation_banner = QFrame()
        self._operation_banner.setObjectName("repositoryOperationBanner")
        operation_layout = QHBoxLayout(self._operation_banner)
        operation_layout.setContentsMargins(8, 4, 8, 4)
        self._operation_label = QLabel()
        self._operation_label.setObjectName("repositoryOperationLabel")
        operation_layout.addWidget(self._operation_label, 1)
        self._operation_continue = QPushButton("Continue")
        self._operation_continue.setObjectName("repositoryOperationContinueButton")
        self._operation_skip = QPushButton("Skip")
        self._operation_skip.setObjectName("repositoryOperationSkipButton")
        self._operation_abort = QPushButton("Abort…")
        self._operation_abort.setObjectName("repositoryOperationAbortButton")
        operation_layout.addWidget(self._operation_continue)
        operation_layout.addWidget(self._operation_skip)
        operation_layout.addWidget(self._operation_abort)
        self._operation_continue.clicked.connect(
            lambda: self._run_repository_operation_action("continue")
        )
        self._operation_skip.clicked.connect(
            lambda: self._run_repository_operation_action("skip")
        )
        self._operation_abort.clicked.connect(
            lambda: self._run_repository_operation_action("abort")
        )
        self._operation_banner.hide()

        self._workspace_container = QWidget()
        workspace_layout = QVBoxLayout(self._workspace_container)
        workspace_layout.setContentsMargins(0, 0, 0, 0)
        workspace_layout.setSpacing(0)
        workspace_layout.addWidget(self._operation_banner)
        workspace_layout.addWidget(self._workspace_tabs, 1)
        self._workspace_container.hide()

        self._diff_view = DiffView(self._settings)
        self._diff_view.setObjectName("diffView")
        self._diff_view.set_auto_apply_hunks(False)
        self._conflict_editor = ConflictEditor()
        self._conflict_editor.save_requested.connect(self._save_conflict_result)
        self._conflict_editor.mergetool_requested.connect(self._launch_mergetool)
        self._conflict_editor.binary_choice_requested.connect(
            self._use_selected_conflict_side
        )
        self._diff_container = QStackedWidget()
        self._diff_container.setObjectName("diffContainer")
        self._diff_container.addWidget(self._diff_view)
        self._diff_container.addWidget(self._conflict_editor)
        self._diff = self._diff_view.diff
        self._diff_gutter = self._diff_view.gutter
        self._diff_version = self._diff_view.version_combo
        self._diff_view_mode = self._diff_view.view_mode_combo
        self._wrap_button = self._diff_view.wrap_button
        self._whitespace_button = self._diff_view.whitespace_button
        self._ignore_whitespace_button = self._diff_view.ignore_whitespace_button

        self._diff_version.currentIndexChanged.connect(self._request_selected_diff)
        self._diff_view_mode.currentIndexChanged.connect(self._diff_view_changed)
        self._diff_view.selection_changed.connect(self._update_selection_actions)
        self._diff_view.context_requested.connect(self._diff_context_changed)
        self._diff_view.close_requested.connect(self._close_history_diff)
        self._diff_view.stage_requested.connect(self._stage_checked_changes)
        self._diff_view.stash_requested.connect(self._stash_checked_changes)
        self._diff_view.unstage_requested.connect(self._unstage_checked_changes)
        self._diff_view.discard_requested.connect(self._discard_checked_changes)
        self._close_diff_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        self._close_diff_shortcut.setObjectName("closeHistoryDiffShortcut")
        self._close_diff_shortcut.activated.connect(self._close_history_diff)
        self._diff_context_lines = 3
        self._wrap_button.setChecked(self._read_bool_setting("diff/wrapLines"))
        self._wrap_button.toggled.connect(self._diff_wrap_changed)
        self._whitespace_button.setChecked(
            self._read_bool_setting("diff/showWhitespace")
        )
        self._whitespace_button.toggled.connect(self._diff_whitespace_changed)
        self._ignore_whitespace_button.setChecked(
            self._read_bool_setting("diff/ignoreWhitespace")
        )
        self._ignore_whitespace_button.toggled.connect(
            self._diff_ignore_whitespace_changed
        )
        self._apply_diff_wrap(self._wrap_button.isChecked())
        self._apply_diff_whitespace(self._whitespace_button.isChecked())

        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.setObjectName("mainSplitter")
        self._splitter.addWidget(self._repositories_panel)
        self._splitter.addWidget(self._welcome)
        self._splitter.addWidget(self._workspace_container)
        self._splitter.addWidget(self._diff_container)
        self._splitter.setStretchFactor(0, 0)
        self._splitter.setStretchFactor(1, 1)
        self._splitter.setStretchFactor(2, 0)
        self._splitter.setStretchFactor(3, 1)
        self._splitter.splitterMoved.connect(self._main_splitter_moved)
        self._repositories_panel.hide()
        self._splitter.setSizes([0, 920, 0, 0])
        self.setCentralWidget(self._splitter)
        self._status_label = QLabel("Ready")
        self._status_label.setObjectName("statusLabel")
        self.statusBar().addWidget(self._status_label)
        QTimer.singleShot(2500, self._automatic_update_check)

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
        toolbar.addWidget(self._repositories_panel.recent_button)
        self._repository_switcher = self._repositories_panel.switcher
        refresh_action = QAction(load_icon("refresh.svg"), "Refresh", self)
        refresh_action.setObjectName("refreshAction")
        refresh_action.setShortcut("F5")
        refresh_action.setToolTip("Fully reload repository state (F5)")
        refresh_action.triggered.connect(self._refresh_repository)
        toolbar.addAction(refresh_action)
        self._fetch_action = QAction(load_icon("fetch.svg"), "Fetch", self)
        self._fetch_action.setObjectName("fetchAction")
        self._fetch_action.triggered.connect(self._fetch_repository)
        fetch_menu = QMenu(self)
        self._fetch_all_action = fetch_menu.addAction(
            load_icon("fetch.svg"), "Fetch all open repositories"
        )
        self._fetch_all_action.setObjectName("fetchAllAction")
        self._fetch_all_action.triggered.connect(self._fetch_all_repositories)
        self._fetch_button = QToolButton()
        self._fetch_button.setObjectName("fetchButton")
        self._fetch_button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self._fetch_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._fetch_button.setDefaultAction(self._fetch_action)
        self._fetch_button.setMenu(fetch_menu)
        toolbar.addWidget(self._fetch_button)
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
        self._operation_queue_menu = QMenu(self)
        self._cancel_action.setMenu(self._operation_queue_menu)
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
        view_menu.addSeparator()
        font_sizes = QAction("Font Sizes…", self)
        font_sizes.setObjectName("fontSizesAction")
        font_sizes.triggered.connect(self._configure_font_sizes)
        view_menu.addAction(font_sizes)

        help_menu = self.menuBar().addMenu("&Help")
        check_updates = QAction("Check for Updates…", self)
        check_updates.setObjectName("checkUpdatesAction")
        check_updates.triggered.connect(self._manual_update_check_requested)
        help_menu.addAction(check_updates)
        about_action = QAction("About MyGitClient", self)
        about_action.setObjectName("aboutAction")
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    @Slot()
    def _automatic_update_check(self) -> None:
        self._manual_update_check = False
        self._update_checker.check()

    @Slot()
    def _manual_update_check_requested(self) -> None:
        self._manual_update_check = True
        self._status_label.setText("Checking for updates…")
        self._update_checker.check()

    @Slot(object)
    def _update_available(self, value: object) -> None:
        if not isinstance(value, UpdateInfo):
            return
        self._manual_update_check = False
        install_directory = portable_install_directory()
        can_install = (
            install_directory is not None
            and value.archive_url is not None
            and value.checksum_url is not None
        )
        if not can_install:
            answer = QMessageBox.question(
                self,
                "Update available",
                f"MyGitClient {value.version} is available.\n\n"
                f"You are using {__version__}. Open the download page?",
            )
            if answer == QMessageBox.StandardButton.Yes:
                QDesktopServices.openUrl(QUrl(value.page_url))
            return
        answer = QMessageBox.question(
            self,
            "Update available",
            f"MyGitClient {value.version} is available.\n\n"
            "Download it, install it, and restart MyGitClient?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        progress = QProgressDialog("Downloading update…", "Cancel", 0, 0, self)
        progress.setObjectName("updateDownloadProgress")
        progress.setWindowTitle("Updating MyGitClient")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.canceled.connect(self._update_downloader.cancel)
        self._update_progress = progress
        progress.show()
        self._update_downloader.download(value)

    @Slot(int, int)
    def _update_download_progress(self, received: int, total: int) -> None:
        progress = self._update_progress
        if progress is None:
            return
        if total <= 0:
            progress.setRange(0, 0)
        else:
            progress.setRange(0, total)
            progress.setValue(received)
        progress.setLabelText(f"Downloading update… {received / 1024 / 1024:.1f} MB")

    @Slot(object)
    def _update_downloaded(self, value: object) -> None:
        self._close_update_progress()
        if not isinstance(value, Path):
            return
        install_directory = portable_install_directory()
        if install_directory is None:
            QMessageBox.warning(self, "Update failed", "This installation is not portable.")
            return
        if not launch_updater(value, install_directory):
            QMessageBox.warning(self, "Update failed", "Could not start the update installer.")
            return
        application = QApplication.instance()
        if application is not None:
            application.quit()

    @Slot(str)
    def _update_download_failed(self, message: str) -> None:
        self._close_update_progress()
        QMessageBox.warning(self, "Update failed", message)

    @Slot()
    def _update_download_cancelled(self) -> None:
        self._close_update_progress()
        self._status_label.setText("Update cancelled")

    def _close_update_progress(self) -> None:
        if self._update_progress is not None:
            self._update_progress.close()
            self._update_progress.deleteLater()
            self._update_progress = None

    @Slot()
    def _update_is_current(self) -> None:
        if self._manual_update_check:
            QMessageBox.information(
                self,
                "No updates",
                f"MyGitClient {__version__} is the latest version.",
            )
        self._manual_update_check = False

    @Slot(str)
    def _update_check_failed(self, message: str) -> None:
        if self._manual_update_check:
            QMessageBox.warning(self, "Update check failed", message)
        self._manual_update_check = False

    @Slot()
    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            "About MyGitClient",
            f"MyGitClient {__version__}\n\nA focused desktop Git client.",
        )

    def _connect_services(self) -> None:
        self._git.amend_diff_ready.connect(self._show_amend_diff)
        self._git.amend_preview_ready.connect(self._show_amend_preview)
        self._git.status_ready.connect(self._show_status)
        self._git.repository_operation_ready.connect(self._show_repository_operation)
        self._git.history_ready.connect(self._show_history)
        self._git.comparison_ready.connect(self._show_ref_comparison)
        self._git.comparison_diff_ready.connect(self._show_ref_comparison_diff)
        self._git.branches_ready.connect(self._show_branches)
        self._git.branch_point_ready.connect(self._show_branch_point)
        self._git.cherry_pick_preview_ready.connect(self._show_cherry_pick_preview)
        self._git.revert_preview_ready.connect(self._show_revert_preview)
        self._git.rebase_preview_ready.connect(self._show_rebase_preview)
        self._git.merge_preview_ready.connect(self._show_merge_preview)
        self._git.reflog_ready.connect(self._show_reflog)
        self._git.conflict_versions_ready.connect(self._show_conflict_versions)
        self._git.tags_ready.connect(self._show_tags)
        self._git.stashes_ready.connect(self._show_stashes)
        self._git.commit_files_ready.connect(self._show_commit_files)
        self._git.commit_diff_ready.connect(self._show_commit_diff)
        self._git.diff_ready.connect(self._show_diff)
        self._git.mutation_ready.connect(self._mutation_finished)
        self._git.operation_cancelled.connect(self._operation_cancelled)
        self._git.operation_failed.connect(self._show_git_error)
        self._git.queue_changed.connect(self._show_operation_queue)
        self._workspace_discovery.linked_repositories_ready.connect(
            self._linked_repositories_ready
        )
        self._workspace_discovery.operation_failed.connect(self._show_git_error)
        self._repositories_panel.repository_activated.connect(self._open_recent_repository)
        self._repositories_panel.remove_requested.connect(self._remove_recent_repository)
        self._repositories_panel.switch_requested.connect(self._repository_selected)
        for tree in self._changes_panel.all_trees:
            tree.itemSelectionChanged.connect(self._selected_file_changed)
            tree.focused.connect(self._selected_file_changed)
            tree.itemSelectionChanged.connect(self._update_file_actions)

    def _apply_saved_ui_font(self) -> None:
        app = QApplication.instance()
        if not isinstance(app, QApplication):
            return
        default_size = QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont).pointSize()
        value = self._settings.value("appearance/fontSize", default_size)
        try:
            point_size = int(value) if isinstance(value, (int, str)) else default_size
        except ValueError:
            point_size = default_size
        font = app.font()
        font.setPointSize(max(7, min(24, point_size)))
        app.setFont(font)

    @Slot()
    def _configure_font_sizes(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Font Sizes")
        form = QFormLayout(dialog)
        interface_size = QSpinBox(dialog)
        interface_size.setObjectName("interfaceFontSizeSpinBox")
        interface_size.setRange(7, 24)
        app = QApplication.instance()
        current_ui_size = app.font().pointSize() if isinstance(app, QApplication) else 10
        interface_size.setValue(current_ui_size)
        diff_size = QSpinBox(dialog)
        diff_size.setObjectName("diffFontSizeSpinBox")
        diff_size.setRange(7, 32)
        diff_size.setValue(self._diff.font().pointSize())
        form.addRow("Interface:", interface_size)
        form.addRow("Diff:", diff_size)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=dialog,
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._settings.setValue("appearance/fontSize", interface_size.value())
        self._settings.setValue("diff/fontSize", diff_size.value())
        if isinstance(app, QApplication):
            font = app.font()
            font.setPointSize(interface_size.value())
            app.setFont(font)
        self._diff_view.set_font_size(diff_size.value())

    def _populate_recent_repositories(self) -> None:
        repositories = self._workspace.recent_repositories()
        self._repositories_panel.set_recent(repositories)
        self._welcome.set_recent(repositories)

    @Slot()
    def _choose_repository(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Open Git Repository")
        if selected:
            self.open_repository(Path(selected))

    @Slot(object)
    def _open_home_repository(self, value: object) -> None:
        if isinstance(value, Path):
            self.open_repository(value)

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
        if (
            self._session_mode
            and self._repository is not None
            and repository != self._repository
        ):
            self.repository_tab_requested.emit(repository, remember)
            return
        if repository not in self._open_repositories:
            self._open_repositories.append(repository)
            self._workspace.save_open_repositories(self._open_repositories)
            self._populate_repository_switcher()
        self._activate_repository(repository, remember=remember)

    def _activate_repository(self, repository: Path, *, remember: bool = False) -> None:
        self._refresh_timer.stop()
        self._repository_activation += 1
        activation = self._repository_activation
        if repository != self._repository:
            self._changes_panel.clear_checked_files()
        if repository not in self._open_repositories:
            self._open_repositories.append(repository)
            self._workspace.save_open_repositories(self._open_repositories)
            self._populate_repository_switcher()
        self._repository = repository
        self._repository_status = None
        self._repository_operation = None
        self._operation_banner.hide()
        self._commit_diff_visible = False
        self._workspace.set_last_repository(repository)
        self._repositories_panel.select_repository(repository)
        if remember:
            self._workspace.remember(repository)
            self._populate_recent_repositories()
        self._show_linked_repositories(repository)
        self._status_label.setText(f"Reading {repository.name}…")
        self._changes.clear()
        self._history_repository = None
        self._history_panel.reset()
        self._history_refs = ()
        self._diff_view.reset()
        self._conflict_editor.clear()
        self._diff_container.setCurrentWidget(self._diff_view)
        self._welcome.hide()
        self._workspace_tabs.show()
        self._workspace_container.show()
        self._diff_view.refresh_version_selector()
        self._diff_view_mode.show()
        self._diff_gutter.setVisible(not self._wrap_button.isChecked())
        self._diff.show()
        self._workspace_tab_changed(self._workspace_tabs.currentIndex())
        QTimer.singleShot(
            0,
            lambda: self._request_activated_repository(repository, activation),
        )

    def _request_activated_repository(
        self, repository: Path, activation: int
    ) -> None:
        if repository != self._repository or activation != self._repository_activation:
            return
        self._status_runner = self._git.request_status(repository)
        self._history_runner = None
        self._git.request_branches(repository)
        self._git.request_tags(repository)
        self._git.request_stashes(repository)
        self._refresh_timer.start()

    @Slot(int)
    def _workspace_tab_changed(self, index: int) -> None:
        diff_container = cast(QWidget | None, getattr(self, "_diff_container", None))
        if diff_container is None:
            return
        repository = getattr(self, "_repository", None)
        commit_diff_visible = getattr(self, "_commit_diff_visible", False)
        showing_history = index == 1
        show_diff = repository is not None and (not showing_history or commit_diff_visible)
        diff_container.setVisible(show_diff)
        if showing_history:
            if commit_diff_visible:
                self._apply_history_splitter_sizes()
                self._history_panel.set_expanded_layout(False)
            else:
                available = max(
                    self._splitter.width() - self._repositories_panel.minimumWidth(), 600
                )
                self._splitter.setSizes([220, 0, available, 0])
                self._history_panel.set_expanded_layout(True)
        elif repository is not None:
            self._commit_diff_visible = False
            self._history_panel.set_expanded_layout(False)
            self._restore_workspace_splitter_sizes()

    @Slot(bool)
    def _history_focus_mode_changed(self, _focused: bool) -> None:
        if (
            self._workspace_tabs.currentIndex() == 1
            and self._commit_diff_visible
        ):
            self._apply_history_splitter_sizes()

    def _apply_history_splitter_sizes(self) -> None:
        key = (
            "history/focusMainSplitterSizes"
            if self._history_panel.focus_mode
            else "history/mainSplitterSizes"
        )
        saved: object = self._settings.value(key)
        if isinstance(saved, list):
            items = cast(list[object], saved)
            sizes = [item for item in items if isinstance(item, int)]
            if len(items) == 4 and len(sizes) == 4:
                sizes[0] = 0
                sizes[1] = 0
                self._splitter.setSizes(sizes)
                return
        available = max(self._splitter.width(), 900)
        history_width = 390 if self._history_panel.focus_mode else 650
        diff_width = max(available - history_width, 500)
        self._splitter.setSizes([0, 0, history_width, diff_width])

    @Slot(int, int)
    def _main_splitter_moved(self, _position: int, _index: int) -> None:
        if (
            self._workspace_tabs.currentIndex() != 1
            or not self._commit_diff_visible
        ):
            return
        key = (
            "history/focusMainSplitterSizes"
            if self._history_panel.focus_mode
            else "history/mainSplitterSizes"
        )
        self._settings.setValue(key, self._splitter.sizes())

    @Slot()
    def _load_more_history(self) -> None:
        if self._repository is None:
            return
        if self._history_runner is not None and self._history_runner.is_running:
            return
        self._history_panel.set_loading(True)
        self._status_label.setText("Loading more commits…")
        self._history_runner = self._git.request_history(
            self._repository,
            offset=self._history_panel.commit_count,
            refs=self._history_refs,
        )

    @Slot(object)
    def _history_refs_selected(self, value: object) -> None:
        if self._repository is None or not isinstance(value, tuple):
            return
        selected_refs: list[str] = []
        for ref in cast(tuple[object, ...], value):
            if not isinstance(ref, str) or not ref:
                return
            selected_refs.append(ref)
        refs = tuple(selected_refs)
        if not refs or len(refs) > 2:
            return
        if refs == self._history_refs:
            return
        self._history_refs = refs
        self._history_panel.clear_commits()
        self._history_panel.set_loading(True)
        self._status_label.setText(f"Loading history for {' + '.join(refs)}…")
        self._history_runner = self._git.request_history(
            self._repository, refs=self._history_refs
        )
        if len(refs) == 2:
            self._status_label.setText(f"Comparing {refs[0]} with {refs[1]}…")
            self._git.request_ref_comparison(self._repository, refs[0], refs[1])
        else:
            self._history_panel.clear_comparison()

    @Slot(object)
    def _show_history(self, value: object) -> None:
        if not isinstance(value, CommitPage):
            return
        if self._repository is None or value.repository != self._repository:
            return
        self._history_runner = None
        self._history_repository = value.repository
        self._history_panel.show_page(value)
        count = self._history_panel.commit_count
        self._status_label.setText(f"Loaded {count} commits")

    @Slot(object)
    def _history_commit_selected(self, value: object) -> None:
        if (
            self._repository is None
            or self._history_repository != self._repository
            or not isinstance(value, CommitSummary)
        ):
            return
        self._commit_diff_visible = False
        self._diff_view.reset()
        self._workspace_tab_changed(self._workspace_tabs.currentIndex())
        self._status_label.setText(f"Reading files for {value.oid[:8]}…")
        self._git.request_commit_files(self._repository, value.oid)

    @Slot(object)
    def _preview_cherry_pick(self, value: object) -> None:
        if (
            self._repository is None
            or not isinstance(value, tuple)
            or not value
        ):
            return
        raw_commits = cast(tuple[object, ...], value)
        if not all(isinstance(commit, CommitSummary) for commit in raw_commits):
            return
        commits = cast(tuple[CommitSummary, ...], raw_commits)
        if any(len(commit.parent_oids) > 1 for commit in commits):
            QMessageBox.warning(
                self,
                "Cherry-pick unavailable",
                "Merge commits need a mainline parent and cannot be cherry-picked "
                "from this action.",
            )
            return
        self._status_label.setText(
            f"Preparing cherry-pick of {len(commits)} commit(s)…"
        )
        self._git.request_cherry_pick_preview(self._repository, commits)

    @Slot(object)
    def _show_cherry_pick_preview(self, value: object) -> None:
        if (
            not isinstance(value, CherryPickPreviewSnapshot)
            or value.repository != self._repository
        ):
            return
        dirty = bool(self._repository_status and self._repository_status.files)
        dialog = QDialog(self)
        dialog.setObjectName("cherryPickPreviewDialog")
        dialog.setWindowTitle("Cherry-pick commits")
        layout = QVBoxLayout(dialog)
        summary = QLabel(
            f"Apply {len(value.commits)} commit(s) to the current branch?"
        )
        summary.setWordWrap(True)
        layout.addWidget(summary)
        preview = QPlainTextEdit()
        preview.setObjectName("cherryPickPreviewEdit")
        preview.setReadOnly(True)
        commit_lines = [
            f"{commit.oid[:8]}  {commit.subject}" for commit in value.commits
        ]
        file_lines = [f"  {path}" for path in value.files]
        preview.setPlainText(
            "Commits (oldest first):\n"
            + "\n".join(commit_lines)
            + "\n\nChanged files:\n"
            + ("\n".join(file_lines) if file_lines else "  No changed files")
        )
        layout.addWidget(preview, 1)
        autostash = QCheckBox("Stash local changes and restore them afterwards")
        autostash.setObjectName("cherryPickAutostashCheckBox")
        autostash.setChecked(dirty)
        autostash.setVisible(dirty)
        layout.addWidget(autostash)
        if dirty:
            warning = QLabel(
                "The working tree contains local changes. Auto-stash is required "
                "to start this cherry-pick safely."
            )
            warning.setWordWrap(True)
            layout.addWidget(warning)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel,
            parent=dialog,
        )
        ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok_button.setText("Cherry-pick")
        if dirty:
            ok_button.setEnabled(autostash.isChecked())
            autostash.toggled.connect(ok_button.setEnabled)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.resize(680, 460)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            self._status_label.setText("Cherry-pick cancelled")
            return
        self._status_label.setText(
            f"Queueing cherry-pick of {len(value.commits)} commit(s)…"
        )
        self._git.request_cherry_pick(
            value.repository,
            value.commits,
            autostash=dirty and autostash.isChecked(),
        )

    @Slot(object)
    def _preview_revert(self, value: object) -> None:
        if (
            self._repository is None
            or not isinstance(value, tuple)
            or not value
        ):
            return
        raw_commits = cast(tuple[object, ...], value)
        if not all(isinstance(commit, CommitSummary) for commit in raw_commits):
            return
        commits = cast(tuple[CommitSummary, ...], raw_commits)
        if any(len(commit.parent_oids) > 1 for commit in commits):
            QMessageBox.warning(
                self,
                "Revert unavailable",
                "Merge commits need a mainline parent and cannot be reverted "
                "from this action.",
            )
            return
        if self._repository_status and self._repository_status.files:
            QMessageBox.warning(
                self,
                "Clean working tree required",
                "Commit, stash, or discard local changes before reverting commits.",
            )
            return
        self._status_label.setText(
            f"Preparing revert of {len(commits)} commit(s)…"
        )
        self._git.request_revert_preview(self._repository, commits)

    @Slot(object)
    def _show_revert_preview(self, value: object) -> None:
        if (
            not isinstance(value, RevertPreviewSnapshot)
            or value.repository != self._repository
        ):
            return
        dialog = QDialog(self)
        dialog.setObjectName("revertPreviewDialog")
        dialog.setWindowTitle("Revert commits")
        layout = QVBoxLayout(dialog)
        summary = QLabel(
            f"Create {len(value.commits)} reverse commit(s)? "
            "The commits will be reverted newest first."
        )
        summary.setWordWrap(True)
        layout.addWidget(summary)
        preview = QPlainTextEdit()
        preview.setObjectName("revertPreviewEdit")
        preview.setReadOnly(True)
        commit_lines = [
            f"{commit.oid[:8]}  {commit.subject}" for commit in value.commits
        ]
        file_lines = [f"  {path}" for path in value.files]
        preview.setPlainText(
            "Commits (revert order):\n"
            + "\n".join(commit_lines)
            + "\n\nChanged files:\n"
            + ("\n".join(file_lines) if file_lines else "  No changed files")
            + "\n\nChanges below will be reversed:\n\n"
            + value.diff.text
        )
        layout.addWidget(preview, 1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel,
            parent=dialog,
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Revert")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.resize(760, 560)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            self._status_label.setText("Revert cancelled")
            return
        self._status_label.setText(
            f"Queueing revert of {len(value.commits)} commit(s)…"
        )
        self._git.request_revert(value.repository, value.commits)

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
            or self._history_repository != self._repository
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
            ignore_whitespace=self._ignore_whitespace_button.isChecked(),
            context_lines=self._diff_context_lines,
        )

    @Slot(str, str, object)
    def _history_comparison_file_selected(
        self, base_ref: str, compare_ref: str, file_value: object
    ) -> None:
        if (
            self._repository is None
            or self._history_repository != self._repository
            or not isinstance(file_value, CommitFileChange)
        ):
            return
        self._status_label.setText(f"Comparing {file_value.path}…")
        self._git.request_ref_comparison_diff(
            self._repository,
            base_ref,
            compare_ref,
            file_value.path,
            ignore_whitespace=self._ignore_whitespace_button.isChecked(),
            context_lines=self._diff_context_lines,
        )

    @Slot(object)
    def _show_ref_comparison(self, value: object) -> None:
        if (
            not isinstance(value, RefComparisonSnapshot)
            or value.repository != self._repository
            or self._history_refs != (value.base_ref, value.compare_ref)
        ):
            return
        self._history_panel.show_comparison(value)
        self._status_label.setText(
            f"{len(value.files)} file(s) differ between the selected refs"
        )

    @Slot(object)
    def _show_ref_comparison_diff(self, value: object) -> None:
        if (
            not isinstance(value, RefComparisonDiffSnapshot)
            or value.repository != self._repository
            or self._history_refs != (value.base_ref, value.compare_ref)
            or self._workspace_tabs.currentIndex() != 1
        ):
            return
        blocker = QSignalBlocker(self._diff_version)
        self._diff_version.clear()
        self._diff_version.addItem(
            f"{value.base_ref}…{value.compare_ref}", None
        )
        del blocker
        self._diff_view.refresh_version_selector()
        self._diff_container.setCurrentWidget(self._diff_view)
        self._diff_view.display_diff(
            value.diff,
            selection_key=None,
            preserve_scroll=False,
            whole_file_staged=False,
            interactive=False,
        )
        self._diff_view.set_close_available(True)
        self._diff_container.show()
        self._commit_diff_visible = True
        self._workspace_tab_changed(self._workspace_tabs.currentIndex())
        self._status_label.setText(f"Showing comparison diff for {value.diff.path}")

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
        self._diff_view.refresh_version_selector()
        self._diff_container.setCurrentWidget(self._diff_view)
        self._diff_view.display_diff(
            value.diff,
            selection_key=None,
            preserve_scroll=False,
            whole_file_staged=False,
            interactive=False,
        )
        self._diff_view.set_close_available(True)
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
        self._history_panel.show_branches(value)
        current = next((branch for branch in value.branches if branch.current), None)
        if current is None:
            return
        local = [branch for branch in value.branches if not branch.remote]
        base = next(
            (branch for branch in local if branch.name == "main"),
            next((branch for branch in local if branch.name == "master"), None),
        )
        if base is not None and base.full_name != current.full_name:
            self._git.request_branch_point(
                value.repository, current.full_name, base.full_name
            )

    @Slot(object)
    def _show_branch_point(self, value: object) -> None:
        if not isinstance(value, BranchPointSnapshot) or value.repository != self._repository:
            return
        self._history_panel.show_branch_point(value)

    @Slot(object)
    def _show_tags(self, value: object) -> None:
        if not isinstance(value, TagsSnapshot) or value.repository != self._repository:
            return
        self._history_panel.show_tags(value)

    @Slot(object)
    def _show_stashes(self, value: object) -> None:
        if not isinstance(value, StashesSnapshot) or value.repository != self._repository:
            return
        self._history_panel.refs_panel.show_stashes(value)

    @Slot()
    def _create_tag(self) -> None:
        repository = self._repository
        if repository is None:
            return
        name, accepted = QInputDialog.getText(self, "New tag", "Tag name:")
        name = name.strip()
        if not accepted or not name:
            return
        commit = self._history_panel.selected_commit
        target = commit.oid if commit is not None else "HEAD"
        message, accepted = QInputDialog.getMultiLineText(
            self,
            "Tag type and message",
            "Optional annotation (leave empty for a lightweight tag):",
        )
        if not accepted:
            return
        self._history_panel.refs_panel.setEnabled(False)
        self._status_label.setText(f"Creating tag {name} at {target[:8]}…")
        self._git.request_create_tag(repository, name, target, message.strip())

    @Slot(object)
    def _delete_tag(self, value: object) -> None:
        if self._repository is None or not isinstance(value, TagInfo):
            return
        answer = QMessageBox.question(
            self,
            "Delete tag",
            f"Delete local tag '{value.name}'?\n\nThis does not delete the remote tag.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._history_panel.refs_panel.setEnabled(False)
        self._git.request_delete_tag(self._repository, value.name)

    @Slot(object)
    def _push_tag(self, value: object) -> None:
        if self._repository is None or not isinstance(value, TagInfo):
            return
        self._history_panel.refs_panel.setEnabled(False)
        self._status_label.setText(f"Pushing tag {value.name}…")
        self._git.request_push_tag(self._repository, value.name)

    @Slot(object)
    def _apply_stash(self, value: object) -> None:
        self._run_stash_action(value, action="apply", confirm=False)

    @Slot(object)
    def _pop_stash(self, value: object) -> None:
        self._run_stash_action(value, action="pop", confirm=True)

    @Slot(object)
    def _drop_stash(self, value: object) -> None:
        self._run_stash_action(value, action="drop", confirm=True)

    def _run_stash_action(
        self, value: object, *, action: str, confirm: bool
    ) -> None:
        if self._repository is None or not isinstance(value, StashInfo):
            return
        if confirm:
            detail = (
                f"{action.title()} {value.ref}?\n\n{value.subject}\n\n"
                + (
                    "The stash will be removed after its changes are applied."
                    if action == "pop"
                    else "This permanently removes the stash without applying it."
                )
            )
            answer = QMessageBox.question(self, f"{action.title()} stash", detail)
            if answer != QMessageBox.StandardButton.Yes:
                return
        self._history_panel.refs_panel.setEnabled(False)
        self._status_label.setText(f"{action.title()}ing {value.ref}…")
        self._git.request_stash_action(self._repository, value, action=action)

    @Slot(object)
    def _checkout_branch(self, value: object) -> None:
        if self._repository is None or not isinstance(value, BranchInfo):
            return
        self._history_panel.refs_panel.setEnabled(False)
        self._status_label.setText(f"Checking out {value.name}…")
        self._git.request_checkout(
            self._repository,
            value,
            autostash=self._history_panel.refs_panel.autostash.isChecked(),
        )

    @Slot()
    def _create_branch(self) -> None:
        if self._repository is None:
            return
        name, accepted = QInputDialog.getText(self, "New branch", "Branch name:")
        name = name.strip()
        if not accepted or not name:
            return
        self._history_panel.refs_panel.setEnabled(False)
        self._status_label.setText(f"Creating branch {name}…")
        self._git.request_create_branch(self._repository, name)

    @Slot(object)
    def _create_branch_from(self, value: object) -> None:
        if self._repository is None or not isinstance(value, BranchInfo):
            return
        suggested = value.name.rpartition("/")[2]
        name, accepted = QInputDialog.getText(
            self,
            "New branch from ref",
            f"New branch name (start at {value.name}):",
            text=suggested,
        )
        name = name.strip()
        if not accepted or not name:
            return
        self._history_panel.refs_panel.setEnabled(False)
        self._status_label.setText(f"Creating branch {name} from {value.name}…")
        self._git.request_create_branch_from(self._repository, name, value)

    @Slot(object)
    def _publish_branch(self, value: object) -> None:
        if (
            self._repository is None
            or not isinstance(value, BranchInfo)
            or value.remote
            or value.upstream is not None
        ):
            return
        self._history_panel.refs_panel.setEnabled(False)
        self._status_label.setText(f"Publishing {value.name} to origin…")
        self._set_network_busy("Push")
        self._git.request_push(
            self._repository,
            branch=value.name,
            set_upstream=True,
        )

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
        self._history_panel.refs_panel.setEnabled(False)
        self._git.request_rename_branch(self._repository, value, name)

    @Slot(object)
    def _delete_branch(self, value: object) -> None:
        self._confirm_delete_branch(value, force=False)

    @Slot(object)
    def _force_delete_branch(self, value: object) -> None:
        self._confirm_delete_branch(value, force=True)

    @Slot(object)
    def _delete_remote_branch(self, value: object) -> None:
        if (
            self._repository is None
            or not isinstance(value, BranchInfo)
            or not value.remote
        ):
            return
        detail = (
            f"Delete remote branch '{value.name}'?\n\n"
            "This removes the branch from the remote for every collaborator. "
            "Any matching local branch is kept."
        )
        answer = QMessageBox.question(self, "Delete remote branch", detail)
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._history_panel.refs_panel.setEnabled(False)
        self._status_label.setText(f"Deleting remote branch {value.name}…")
        self._git.request_delete_remote_branch(self._repository, value)

    @Slot(object)
    def _cleanup_gone_branches(self, value: object) -> None:
        if self._repository is None or not isinstance(value, tuple):
            return
        items = cast(tuple[object, ...], value)
        branches = tuple(
            branch
            for branch in items
            if isinstance(branch, BranchInfo)
            and branch.upstream_gone
            and not branch.remote
            and not branch.current
        )
        if not branches:
            return

        dialog = QDialog(self)
        dialog.setObjectName("cleanupGoneBranchesDialog")
        dialog.setWindowTitle("Clean up gone branches")
        layout = QVBoxLayout(dialog)
        label = QLabel(
            "These local branches track remote branches that disappeared after fetch. "
            "Select branches to delete. Safe deletion remains the default."
        )
        label.setWordWrap(True)
        layout.addWidget(label)
        tree = QTreeWidget()
        tree.setObjectName("cleanupGoneBranchesTree")
        tree.setHeaderLabels(["Delete", "Branch", "Former upstream"])
        tree.setRootIsDecorated(False)
        for branch in branches:
            item = QTreeWidgetItem(["", branch.name, branch.upstream or ""])
            item.setData(0, Qt.ItemDataRole.UserRole, branch)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(0, Qt.CheckState.Checked)
            tree.addTopLevelItem(item)
        tree.resizeColumnToContents(0)
        tree.resizeColumnToContents(1)
        layout.addWidget(tree)
        force = QCheckBox("Force delete selected branches that are not fully merged")
        force.setObjectName("cleanupGoneBranchesForceCheckBox")
        force.setToolTip("Uses git branch -D. Commits unique to a branch can be lost.")
        layout.addWidget(force)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel,
            parent=dialog,
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Delete selected")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.resize(620, 360)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            self._status_label.setText("Branch cleanup cancelled")
            return
        selected: list[BranchInfo] = []
        for index in range(tree.topLevelItemCount()):
            item = tree.topLevelItem(index)
            if item is None or item.checkState(0) is not Qt.CheckState.Checked:
                continue
            branch = item.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(branch, BranchInfo):
                selected.append(branch)
        if not selected:
            self._status_label.setText("No branches selected for cleanup")
            return
        if force.isChecked():
            confirmed = QMessageBox.warning(
                self,
                "Force delete branches?",
                "Force deletion can discard commits unique to the selected branches.\n\n"
                + "\n".join(branch.name for branch in selected),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if confirmed != QMessageBox.StandardButton.Yes:
                self._status_label.setText("Force branch cleanup cancelled")
                return
        self._status_label.setText(f"Queueing deletion of {len(selected)} branch(es)…")
        for branch in selected:
            self._git.request_delete_branch(
                self._repository, branch, force=force.isChecked()
            )

    @Slot(object)
    def _preview_rebase(self, value: object) -> None:
        status = self._repository_status
        if (
            self._repository is None
            or status is None
            or not isinstance(value, BranchInfo)
            or value.current
        ):
            return
        current_branch = status.branch.head
        if current_branch is None or current_branch in {"(detached)", "HEAD"}:
            QMessageBox.warning(
                self,
                "Rebase unavailable",
                "Check out a local branch before starting a rebase.",
            )
            return
        self._history_panel.refs_panel.setEnabled(False)
        self._interactive_rebase_pending = False
        self._status_label.setText(
            f"Preparing rebase of {current_branch} onto {value.name}…"
        )
        self._git.request_rebase_preview(self._repository, value)

    @Slot(object)
    def _preview_interactive_rebase(self, value: object) -> None:
        self._interactive_rebase_pending = True
        self._preview_rebase(value)
        self._interactive_rebase_pending = True

    @Slot(object)
    def _preview_merge(self, value: object) -> None:
        if self._repository is None or not isinstance(value, BranchInfo) or value.current:
            return
        self._history_panel.refs_panel.setEnabled(False)
        self._status_label.setText(f"Preparing merge from {value.name}вЂ¦")
        self._git.request_merge_preview(self._repository, value)

    @Slot(object)
    def _show_merge_preview(self, value: object) -> None:
        self._history_panel.refs_panel.setEnabled(True)
        if not isinstance(value, MergePreviewSnapshot) or value.repository != self._repository:
            return
        status = self._repository_status
        if status is None:
            return
        dialog = QDialog(self)
        dialog.setObjectName("mergePreviewDialog")
        dialog.setWindowTitle("Merge branch")
        layout = QVBoxLayout(dialog)
        summary = QLabel(
            f"Merge {value.target.name} into {status.branch.head or 'HEAD'}?\n"
            f"{len(value.commits)} incoming commit(s), {len(value.files)} changed file(s)"
        )
        summary.setWordWrap(True)
        layout.addWidget(summary)
        preview = QPlainTextEdit()
        preview.setObjectName("mergePreviewEdit")
        preview.setReadOnly(True)
        preview.setPlainText(
            "Incoming commits:\n"
            + ("\n".join(f"{commit.oid[:8]}  {commit.subject}" for commit in value.commits)
               or "  No incoming commits")
            + "\n\nChanged files:\n"
            + ("\n".join(f"  {path}" for path in value.files) or "  No changed files")
        )
        layout.addWidget(preview, 1)
        dirty = bool(status.files)
        autostash = QCheckBox("Stash local changes and restore them after merge")
        autostash.setChecked(dirty)
        autostash.setVisible(dirty)
        layout.addWidget(autostash)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=dialog,
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Merge")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.resize(700, 500)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            self._status_label.setText("Merge cancelled")
            return
        self._history_panel.refs_panel.setEnabled(False)
        self._status_label.setText(f"Merging {value.target.name}вЂ¦")
        self._git.request_merge(value.repository, value.target, autostash=dirty)

    @Slot(object)
    def _show_reflog(self, value: object) -> None:
        if not isinstance(value, ReflogSnapshot) or value.repository != self._repository:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Reflog")
        layout = QVBoxLayout(dialog)
        edit = QPlainTextEdit()
        edit.setObjectName("reflogEdit")
        edit.setReadOnly(True)
        edit.setPlainText("\n".join(value.entries) or "Reflog is empty.")
        layout.addWidget(edit)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.resize(900, 520)
        dialog.exec()

    @Slot(object)
    def _show_rebase_preview(self, value: object) -> None:
        self._history_panel.refs_panel.setEnabled(True)
        if (
            not isinstance(value, RebasePreviewSnapshot)
            or value.repository != self._repository
        ):
            return
        status = self._repository_status
        if status is None or status.branch.head is None:
            return
        if not value.commits:
            QMessageBox.information(
                self,
                "Nothing to rebase",
                f"The current branch has no commits to replay onto {value.target.name}.",
            )
            self._status_label.setText("Nothing to rebase")
            return
        dirty = bool(status.files)
        self._rewrite_recovery_head = value.head_oid
        if self._interactive_rebase_pending:
            self._interactive_rebase_pending = False
            editor = InteractiveRebaseDialog(value.commits, self)
            if editor.exec() != QDialog.DialogCode.Accepted:
                self._status_label.setText("Interactive rebase cancelled")
                return
            if dirty:
                answer = QMessageBox.question(
                    self,
                    "Stash local changes?",
                    "The working tree is dirty. Stash and restore its changes automatically?",
                )
                if answer != QMessageBox.StandardButton.Yes:
                    self._status_label.setText("Interactive rebase cancelled")
                    return
            self._history_panel.refs_panel.setEnabled(False)
            self._status_label.setText(f"Interactively rebasing onto {value.target.name}вЂ¦")
            self._git.request_interactive_rebase(
                value.repository,
                value.target,
                value.base_oid,
                editor.items(),
                autostash=dirty,
            )
            return
        dialog = QDialog(self)
        dialog.setObjectName("rebasePreviewDialog")
        dialog.setWindowTitle("Rebase branch")
        layout = QVBoxLayout(dialog)
        summary = QLabel(
            f"Rebase {status.branch.head} onto {value.target.name}?\n"
            f"Base: {value.base_oid[:8]} · {len(value.commits)} commit(s) to replay"
        )
        summary.setWordWrap(True)
        layout.addWidget(summary)
        recovery = QLabel(f"Recovery point: {value.head_oid}")
        recovery.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(recovery)
        preview = QPlainTextEdit()
        preview.setObjectName("rebasePreviewEdit")
        preview.setReadOnly(True)
        preview.setPlainText(
            "Commits (replay order):\n"
            + "\n".join(
                f"{commit.oid[:8]}  {commit.subject}" for commit in value.commits
            )
            + "\n\nChanged files:\n"
            + (
                "\n".join(f"  {path}" for path in value.files)
                if value.files
                else "  No changed files"
            )
        )
        layout.addWidget(preview, 1)
        autostash = QCheckBox("Stash local changes and restore them after rebase")
        autostash.setObjectName("rebaseAutostashCheckBox")
        autostash.setChecked(dirty)
        autostash.setVisible(dirty)
        layout.addWidget(autostash)
        if dirty:
            warning = QLabel(
                "The working tree contains local changes. Auto-stash is required "
                "to start this rebase safely."
            )
            warning.setWordWrap(True)
            layout.addWidget(warning)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel,
            parent=dialog,
        )
        ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok_button.setText("Rebase")
        if dirty:
            ok_button.setEnabled(autostash.isChecked())
            autostash.toggled.connect(ok_button.setEnabled)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.resize(700, 500)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            self._status_label.setText("Rebase cancelled")
            return
        self._history_panel.refs_panel.setEnabled(False)
        self._status_label.setText(f"Rebasing onto {value.target.name}…")
        self._git.request_rebase(
            value.repository,
            value.target,
            autostash=dirty and autostash.isChecked(),
        )

    def _confirm_delete_branch(self, value: object, *, force: bool) -> None:
        if self._repository is None or not isinstance(value, BranchInfo):
            return
        if force:
            tracking = (
                "Its upstream branch no longer exists.\n\n"
                if value.upstream_gone
                else ""
            )
            detail = tracking + (
                f"Force-delete local branch '{value.name}'?\n\n"
                "Commits that are not reachable from another branch may become difficult "
                "to recover. The remote branch will not be deleted."
            )
        else:
            detail = (
                f"Safely delete local branch '{value.name}'?\n\n"
                "Git will refuse if the branch contains commits that have not been merged. "
                "Use Force delete from the branch context menu only if that is intentional."
            )
        answer = QMessageBox.question(
            self, "Force delete branch" if force else "Delete branch", detail
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._history_panel.refs_panel.setEnabled(False)
        self._git.request_delete_branch(self._repository, value, force=force)

    def _show_linked_repositories(self, repository: Path) -> None:
        self._workspace_discovery.request_linked_repositories(repository)

    @Slot(object)
    def _linked_repositories_ready(self, value: object) -> None:
        if not isinstance(value, LinkedRepositoriesSnapshot):
            return
        self._repositories_panel.set_linked(value.repository, value.repositories)
        if value.repository == self._repository:
            self._history_panel.refs_panel.show_linked_repositories(value.repositories)

    @Slot(object)
    def _open_linked_repository(self, value: object) -> None:
        if isinstance(value, LinkedRepository) and value.path.is_dir():
            self.open_repository(value.path, remember=False)

    def _populate_repository_switcher(self) -> None:
        self._repositories_panel.set_open(self._open_repositories, self._repository)
        for repository in self._open_repositories:
            if repository != self._repository and repository.is_dir():
                self._git.request_status(repository)

    @Slot(object)
    def _repository_selected(self, value: object) -> None:
        if isinstance(value, Path) and value != self._repository and value.is_dir():
            self.open_repository(value, remember=False)

    def _restore_open_repositories(self) -> None:
        self._open_repositories = list(self._workspace.open_repositories())
        last = self._workspace.last_repository()
        if last is not None and last not in self._open_repositories:
            self._open_repositories.append(last)
        self._populate_repository_switcher()
        self._welcome.show()
        self._workspace_container.hide()
        self._diff_container.hide()

    @Slot()
    def _save_workspace(self) -> None:
        name, accepted = QInputDialog.getText(self, "Save Workspace", "Workspace name:")
        if not accepted or not name.strip():
            return
        self._workspace.save_named_workspace(name, self._open_repositories)
        self._populate_workspace_menu()

    def _populate_workspace_menu(self) -> None:
        self._load_workspace_menu.clear()
        names = self._workspace.named_workspaces()
        self._welcome.set_workspaces(names)
        for name in names:
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
        self._open_named_workspace(name)

    @Slot(str)
    def _open_named_workspace(self, name: str) -> None:
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
        self._repository_status = None
        self._diff_view.reset()
        self._git.request_branches(self._repository)
        self._git.request_tags(self._repository)
        self._git.request_stashes(self._repository)
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
    def _fetch_all_repositories(self) -> None:
        repositories = [path for path in self._open_repositories if path.is_dir()]
        if not repositories:
            return
        self._refresh_all_after_queue = True
        self._status_label.setText(f"Queueing fetch for {len(repositories)} repositories…")
        for repository in repositories:
            self._git.request_fetch(repository)

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
        if operation is not None:
            self._status_label.setText(f"Queueing {operation.lower()}…")

    @Slot()
    def _poll_repository(self) -> None:
        if self._repository is None:
            return
        if self._status_runner is not None and self._status_runner.is_running:
            return
        self._status_runner = self._git.request_status(self._repository)

    @Slot(object)
    def _show_operation_queue(self, value: object) -> None:
        if not isinstance(value, OperationQueueSnapshot):
            return
        operations = (() if value.active is None else (value.active,)) + value.pending
        previous_id = (
            self._active_queue_operation.operation_id
            if self._active_queue_operation is not None
            else None
        )
        self._active_queue_operation = value.active
        self._queued_operation_count = len(value.pending)
        if value.active is None:
            self._queue_duration_timer.stop()
            self._queue_elapsed.invalidate()
        elif value.active.operation_id != previous_id:
            self._queue_elapsed.start()
            self._queue_duration_timer.start()
        self._operation_queue_menu.clear()
        for index, operation in enumerate(operations):
            self._known_queue_operations[operation.operation_id] = operation
            prefix = (
                "Running"
                if index == 0 and value.active is not None
                else "Queued"
            )
            operation_menu = self._operation_queue_menu.addMenu(
                load_icon(_queue_operation_icon(operation.operation)),
                f"{prefix}: {operation.operation} — {operation.repository.name}",
            )
            preview = operation_menu.addAction(operation.output_preview)
            preview.setEnabled(False)
            output_action = operation_menu.addAction("Show output…")
            output_action.setData(operation.operation_id)
            output_action.triggered.connect(self._show_queue_output)
            cancel_action = operation_menu.addAction(
                "Cancel operation"
                if index == 0 and value.active is not None
                else "Remove from queue"
            )
            cancel_action.setIcon(load_icon("cancel.svg"))
            cancel_action.setData(operation.operation_id)
            cancel_action.triggered.connect(self._cancel_queue_action)
            dialog = self._operation_output_dialogs.get(operation.operation_id)
            if dialog is not None:
                dialog.update_output(operation.output_preview, operation.output)
        self._cancel_action.setEnabled(bool(operations))
        if not operations and self._refresh_all_after_queue:
            self._refresh_all_after_queue = False
            for repository in self._open_repositories:
                if repository.is_dir():
                    self._git.request_status(repository)
        self._update_queue_duration()

    @Slot()
    def _update_queue_duration(self) -> None:
        operation = self._active_queue_operation
        if operation is None or not self._queue_elapsed.isValid():
            self._cancel_action.setText("Queue")
            return
        duration = format_operation_duration(self._queue_elapsed.elapsed())
        total = self._queued_operation_count + 1
        self._cancel_action.setText(f"Queue {total} · {duration}")
        self._status_label.setText(
            f"{operation.operation.title()} · {duration} · "
            f"{self._queued_operation_count} queued"
        )

    @Slot()
    def _cancel_queue_action(self) -> None:
        action = self.sender()
        if not isinstance(action, QAction):
            return
        operation_id = action.data()
        if isinstance(operation_id, int):
            self._git.cancel_operation(operation_id)

    @Slot()
    def _show_queue_output(self) -> None:
        action = self.sender()
        if not isinstance(action, QAction):
            return
        operation_id = action.data()
        if not isinstance(operation_id, int):
            return
        operation = self._known_queue_operations.get(operation_id)
        if operation is None:
            return
        dialog = self._operation_output_dialogs.get(operation_id)
        if dialog is None:
            dialog = OperationOutputDialog(
                f"{operation.operation.title()} — {operation.repository.name}", self
            )
            dialog.setProperty("operationId", operation_id)
            dialog.finished.connect(self._operation_output_closed)
            self._operation_output_dialogs[operation_id] = dialog
        dialog.update_output(operation.output_preview, operation.output)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    @Slot(int)
    def _operation_output_closed(self, _result: int) -> None:
        dialog = self.sender()
        if not isinstance(dialog, OperationOutputDialog):
            return
        operation_id = dialog.property("operationId")
        if isinstance(operation_id, int):
            self._operation_output_dialogs.pop(operation_id, None)

    @Slot()
    def _operation_cancelled(self) -> None:
        self._set_network_busy(None)
        self._status_runner = None
        self._history_runner = None
        self._set_changes_trees_enabled(True)
        self._changes_container.setEnabled(True)
        self._conflict_editor.setEnabled(True)
        self._operation_banner.setEnabled(True)
        self._status_label.setText("Operation cancelled")

    @Slot(object)
    def _show_repository_operation(self, value: object) -> None:
        if not isinstance(value, RepositoryOperationSnapshot):
            return
        if self._repository is None or value.repository != self._repository:
            return
        self._repository_operation = value.operation
        operation = value.operation
        if operation is None:
            self._operation_banner.hide()
            return
        name = {
            "merge": "Merge",
            "rebase": "Rebase",
            "cherry-pick": "Cherry-pick",
            "revert": "Revert",
        }[operation.kind]
        progress = ""
        if operation.current_step is not None and operation.total_steps is not None:
            progress = f" · step {operation.current_step} of {operation.total_steps}"
        current = f" · {operation.current_subject}" if operation.current_subject else ""
        queued = f" · {len(operation.remaining)} remaining" if operation.remaining else ""
        self._operation_label.setText(
            f"{name} in progress{progress}{current}{queued}. "
            "Resolve conflicts, then continue."
        )
        self._operation_label.setToolTip(
            "Remaining commits:\n" + "\n".join(operation.remaining)
            if operation.remaining
            else ""
        )
        self._operation_skip.setVisible(operation.kind != "merge")
        self._operation_banner.setEnabled(True)
        self._operation_banner.show()

    def _run_repository_operation_action(self, action: str) -> None:
        repository = self._repository
        operation = self._repository_operation
        if repository is None or operation is None:
            return
        if action == "abort":
            answer = QMessageBox.question(
                self,
                f"Abort {operation.kind}?",
                f"Abort the current {operation.kind} and restore its previous state?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self._operation_banner.setEnabled(False)
        self._status_label.setText(f"{action.title()}ing {operation.kind}…")
        self._git.request_repository_operation_action(
            repository, kind=operation.kind, action=action
        )

    @Slot(object)
    def _show_status(self, value: object) -> None:
        if not isinstance(value, RepositoryStatusSnapshot):
            return
        branch = value.status.branch
        self._repositories_panel.set_sync_status(
            value.repository, ahead=branch.ahead, behind=branch.behind
        )
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
        active_tree = self._changes_panel.active_tree()
        selected_items = active_tree.selectedItems()
        if selected_items:
            selected_file = selected_items[0].data(0, Qt.ItemDataRole.UserRole)
            if isinstance(selected_file, FileStatus):
                selected_path = selected_file.path
        previous_head = (
            self._repository_status.branch.head
            if self._repository_status is not None
            else None
        )
        self._repository_status = status_value
        if previous_head is not None and previous_head != status_value.branch.head:
            self._diff_view.reset()
            self._history_panel.clear_commits()
            self._git.request_branches(value.repository)
            self._git.request_tags(value.repository)
        self._update_sync_indicators()
        changed_paths = {file.path for file in status_value.files}
        self._diff_view.retain_changed_paths(value.repository, changed_paths)
        files_to_show = list(status_value.files)
        if self._amend.isChecked():
            visible_paths = {file.path for file in files_to_show}
            for change in self._amend_commit_files:
                if change.path not in visible_paths:
                    files_to_show.append(FileStatus(change.path, ".", "."))
        rendered_files = [
            (file, self._file_check_state(value.repository, file))
            for file in files_to_show
        ]
        item_to_restore = self._changes_panel.show_files(
            rendered_files,
            selected_path,
            amend=self._amend.isChecked(),
        )
        selection_restored = False
        if item_to_restore is not None:
            self._changes_panel.active_tree().setCurrentItem(item_to_restore)
            selection_restored = True
        elif self._changes_panel.split_mode and selected_path is not None:
            opposite_tree = (
                self._changes_panel.staged_tree
                if active_tree is self._changes_panel.unstaged_tree
                else self._changes_panel.unstaged_tree
            )
            opposite_item = self._changes_panel.find_file_item(
                opposite_tree, selected_path
            )
            if opposite_item is not None:
                self._changes_panel.set_active_tree(opposite_tree)
                opposite_tree.setFocus()
                opposite_tree.setCurrentItem(opposite_item)
                selection_restored = True
        if (
            not selection_restored
            and not self._amend.isChecked()
            and self._diff_view.current_diff is not None
            and self._diff_view.current_diff.path not in changed_paths
        ):
            self._diff_view.reset()
        for tree in self._changes_panel.all_trees:
            tree.resizeColumnToContents(0)
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
        message, description = generated_commit_text(changes)

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

    def _file_check_state(self, repository: Path, file: FileStatus) -> Qt.CheckState:
        if file.unmerged:
            return Qt.CheckState.Unchecked
        has_saved_selection = self._diff_view.has_saved_selection(repository, file.path)
        if self._amend.isChecked():
            included = file.path in self._amend_included_paths
            if included and file.has_worktree_change:
                return Qt.CheckState.PartiallyChecked
            return Qt.CheckState.Checked if included else Qt.CheckState.Unchecked
        if has_saved_selection or (file.is_staged and file.has_worktree_change):
            return Qt.CheckState.PartiallyChecked
        return Qt.CheckState.Checked if file.is_staged else Qt.CheckState.Unchecked

    def _set_changes_trees_enabled(self, enabled: bool) -> None:
        for tree in self._changes_panel.all_trees:
            tree.setEnabled(enabled)

    @Slot(object, bool)
    def _stage_folder(self, value: object, should_stage: bool) -> None:
        if self._repository is None or not isinstance(value, tuple):
            return
        objects = cast(tuple[object, ...], value)
        files = tuple(file for file in objects if isinstance(file, FileStatus))
        if not files or len(files) != len(objects):
            return
        self._set_changes_trees_enabled(False)
        action = "Staging" if should_stage else "Unstaging"
        self._status_label.setText(f"{action} {len(files)} files…")
        status = self._repository_status
        self._git.request_stage_files(
            self._repository,
            files,
            staged=should_stage,
            has_head=status is not None and status.branch.oid is not None,
        )

    @Slot(str)
    def _changes_view_mode_changed(self, _mode: str) -> None:
        self._diff_view.set_auto_apply_hunks(False)
        if self._repository is None:
            return
        self._repository_status = None
        self._status_runner = self._git.request_status(self._repository)

    @Slot(QTreeWidgetItem, int)
    def _stage_checkbox_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if column != 0 or self._repository is None:
            return
        file = item.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(file, FileStatus):
            return
        sender = self.sender()
        if self._changes_panel.split_mode and sender is self._changes_panel.unstaged_tree:
            should_stage = True
        elif self._changes_panel.split_mode and sender is self._changes_panel.staged_tree:
            should_stage = False
        else:
            should_stage = item.checkState(0) != Qt.CheckState.Unchecked
        if file.unmerged and not should_stage:
            return
        if file.unmerged:
            path = self._selected_file_path(file)
            markers = conflict_marker_lines(path) if path is not None else ()
            if markers:
                line_list = ", ".join(str(line) for line in markers[:8])
                answer = QMessageBox.warning(
                    self,
                    "Conflict markers remain",
                    f"{file.path} still contains conflict markers on line(s) {line_list}.\n\n"
                    "Mark this file as resolved anyway?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                    QMessageBox.StandardButton.Cancel,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    tree = sender if isinstance(sender, QTreeWidget) else self._changes
                    blocker = QSignalBlocker(tree)
                    item.setCheckState(0, Qt.CheckState.Unchecked)
                    del blocker
                    return
        self._set_changes_trees_enabled(False)
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
        if self._clear_change_selection_after_mutation:
            self._clear_change_selection_after_mutation = False
            self._changes_panel.clear_checked_files()
            self._diff_view.clear_selection()
        if path in {"fetch", "pull", "push"}:
            self._set_network_busy(None)
        self._set_changes_trees_enabled(True)
        self._changes_container.setEnabled(True)
        self._conflict_editor.setEnabled(True)
        self._history_panel.refs_panel.setEnabled(True)
        self._operation_banner.setEnabled(True)
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
        elif path == "tags:changed":
            self._status_label.setText("Tags updated")
        elif path == "stashes:changed":
            self._status_label.setText("Stashes updated")
        elif path == "pull":
            self._status_label.setText("Pull completed")
        elif path == "fetch":
            self._status_label.setText("Fetch completed")
        elif path == "push":
            self._status_label.setText("Push completed")
        elif path == "cherry-pick":
            self._status_label.setText("Cherry-pick completed")
        elif path == "rebase":
            self._status_label.setText("Rebase completed")
            if self._rewrite_recovery_head:
                box = QMessageBox(self)
                box.setWindowTitle("Rebase completed")
                box.setText("The branch history was rewritten successfully.")
                box.setInformativeText(
                    "Previous HEAD (also available through reflog):\n"
                    + self._rewrite_recovery_head
                )
                copy_button = box.addButton("Copy previous HEAD", QMessageBox.ButtonRole.ActionRole)
                history_button = box.addButton("Open reflog", QMessageBox.ButtonRole.ActionRole)
                box.addButton(QMessageBox.StandardButton.Close)
                box.exec()
                if box.clickedButton() is copy_button:
                    QApplication.clipboard().setText(self._rewrite_recovery_head)
                elif box.clickedButton() is history_button and self._repository is not None:
                    self._git.request_reflog(self._repository)
                self._rewrite_recovery_head = ""
        elif path == "revert":
            self._status_label.setText("Revert completed")
        elif path == "merge":
            self._status_label.setText("Merge completed")
        elif path == "mergetool":
            self._status_label.setText("External merge tool completed")
        elif path == "repository-operation:changed":
            self._status_label.setText("Repository operation updated")
        elif path == "stash":
            self._status_label.setText("Selected changes stashed")
        else:
            self._status_label.setText(f"Updated staging area for {path}")
        if self._repository is not None:
            history_changed = path in {
                "commit",
                "fetch",
                "pull",
                "push",
                "cherry-pick",
                "revert",
                "rebase",
                "merge",
                "repository-operation:changed",
            }
            branch_changed = path.startswith("branch:") or path.startswith("branches:")
            if history_changed and self._history_refs:
                self._history_panel.clear_commits()
                self._history_panel.set_loading(True)
                self._history_runner = self._git.request_history(
                    self._repository, refs=self._history_refs
                )
            elif branch_changed:
                self._history_panel.clear_commits()
            status = self._repository_status
            if self._amend.isChecked() and status is not None and status.branch.oid:
                self._git.request_amend_diff(
                    self._repository,
                    status.branch.oid,
                    parent_oid=self._amend_parent_oid,
                )
            self._status_runner = self._git.request_status(self._repository)
            self._git.request_branches(self._repository)
            self._git.request_tags(self._repository)
            self._git.request_stashes(self._repository)

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
        self._amend_commit_files = ()
        self._amend_included_paths = frozenset()
        self._amend_parent_oid = None
        self._amend_render_pending = False
        self._amend_files_loaded = False
        self._amend_diff_loaded = False
        self._diff_view.reset()
        if repository is not None:
            self._repository_status = None
            self._status_runner = self._git.request_status(repository)
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
        self._diff_view.refresh_version_selector()
        self._diff_container.setCurrentWidget(self._diff_view)
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
        sender = self.sender()
        selected_tree = (
            sender if isinstance(sender, QTreeWidget) else self._changes_panel.active_tree()
        )
        if self._changes_panel.split_mode:
            self._changes_panel.set_active_tree(selected_tree)
            for tree in self._changes_panel.all_trees:
                if tree is not selected_tree:
                    tree.clearSelection()
        if self._amend.isChecked():
            selected_items = selected_tree.selectedItems()
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
        selected_items = selected_tree.selectedItems()
        if not selected_items:
            return
        file = selected_items[0].data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(file, FileStatus):
            return
        if file.unmerged:
            path = self._selected_file_path(file)
            if path is None:
                return
            self._conflict_editor.load_file(path, file.path)
            if self._repository is not None:
                self._git.request_conflict_versions(self._repository, file)
            self._diff_container.setCurrentWidget(self._conflict_editor)
            self._status_label.setText(f"Resolving conflicts in {file.path}")
            return
        self._diff_container.setCurrentWidget(self._diff_view)
        self._populate_diff_versions(file)
        preferred_staged = self._changes_panel.preferred_staged(selected_tree)
        if preferred_staged is not None:
            index = self._diff_version.findData(preferred_staged)
            if index >= 0:
                self._diff_version.setCurrentIndex(index)
        self._request_selected_diff()

    @Slot()
    def _update_file_actions(self) -> None:
        files = self._selected_files()
        file = files[0] if len(files) == 1 else None
        path = self._selected_file_path(file)
        self._open_file_action.setEnabled(path is not None and path.exists())
        self._open_file_with_action.setEnabled(
            path is not None and path.exists() and sys.platform == "win32"
        )
        self._reveal_file_action.setEnabled(
            path is not None and (path.exists() or path.parent.exists())
        )
        conflict_selected = file is not None and file.unmerged
        self._use_ours_action.setVisible(conflict_selected)
        self._use_theirs_action.setVisible(conflict_selected)
        self._conflict_actions_separator.setVisible(conflict_selected)
        operation = self._repository_operation
        if operation is not None and operation.kind in {"rebase", "cherry-pick"}:
            self._use_ours_action.setText("Use target branch version")
            self._use_theirs_action.setText("Use replayed commit version")
        else:
            self._use_ours_action.setText("Use current branch version")
            self._use_theirs_action.setText("Use incoming branch version")
        self._ignore_action.setEnabled(file is not None and file.index_status == "?")

    def _selected_file_path(self, file: FileStatus | None) -> Path | None:
        repository = self._repository
        if repository is None or file is None:
            return None
        repository = repository.resolve()
        path = (repository / file.path).resolve()
        return path if path.is_relative_to(repository) else None

    @Slot()
    def _open_selected_file(self) -> None:
        path = self._selected_file_path(self._selected_file())
        if path is None or not path.exists():
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
            QMessageBox.warning(self, "Open file", f"Could not open:\n{path}")

    @Slot()
    def _open_selected_file_with(self) -> None:
        path = self._selected_file_path(self._selected_file())
        if path is None or not path.exists() or sys.platform != "win32":
            return
        started, _process_id = QProcess.startDetached(
            "rundll32.exe",
            ["shell32.dll,OpenAs_RunDLL", str(path)],
            str(path.parent),
        )
        if not started:
            QMessageBox.warning(self, "Open with", f"Could not show applications for:\n{path}")

    @Slot()
    def _reveal_selected_file(self) -> None:
        path = self._selected_file_path(self._selected_file())
        if path is None:
            return
        existing_target = path if path.exists() else path.parent
        if not existing_target.exists():
            return
        folder = existing_target.parent if existing_target.is_file() else existing_target
        if sys.platform == "win32":
            arguments = (
                ["/select,", str(path)]
                if path.exists() and not path.is_dir()
                else [str(folder)]
            )
            started, _process_id = QProcess.startDetached(
                "explorer.exe",
                arguments,
                str(folder),
            )
        else:
            started = QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
        if not started:
            QMessageBox.warning(
                self,
                "Show in File Manager",
                f"Could not show:\n{path}",
            )

    def _use_selected_conflict_side(self, side: str) -> None:
        file = self._selected_file()
        repository = self._repository
        if repository is None or file is None or not file.unmerged:
            return
        if side == "delete":
            self._set_changes_trees_enabled(False)
            self._status_label.setText(f"Deleting conflicted file {file.path}…")
            self._git.request_delete_conflict(repository, file)
            return
        self._set_changes_trees_enabled(False)
        self._status_label.setText(f"Using {side} version of {file.path}…")
        self._git.request_conflict_side(repository, file, side=side)

    @Slot(object)
    def _show_conflict_versions(self, value: object) -> None:
        file = self._selected_file()
        if (
            not isinstance(value, ConflictVersionsSnapshot)
            or value.repository != self._repository
            or file is None
            or file.path != value.path
        ):
            return
        self._conflict_editor.set_versions(
            value.base, value.current, value.incoming, value.attributes
        )

    @Slot()
    def _launch_mergetool(self) -> None:
        repository = self._repository
        file = self._selected_file()
        if repository is None or file is None or not file.unmerged:
            return
        answer = QMessageBox.question(
            self,
            "Open external merge tool",
            f"Run the Git-configured merge tool for {file.path}?\n\n"
            "The application will refresh the conflict state after the tool exits.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._conflict_editor.setEnabled(False)
        self._status_label.setText(f"Running merge tool for {file.path}…")
        self._git.request_mergetool(repository, file)

    @Slot(object, str)
    def _save_conflict_result(self, value: object, content: str) -> None:
        repository = self._repository
        file = self._selected_file()
        path = self._selected_file_path(file)
        if (
            repository is None
            or file is None
            or not file.unmerged
            or not isinstance(value, Path)
            or path != value
        ):
            return
        self._set_changes_trees_enabled(False)
        self._conflict_editor.setEnabled(False)
        self._status_label.setText(f"Marking {file.path} resolved…")
        self._git.request_resolve_conflict(repository, file, content)

    def _selected_files(self) -> tuple[FileStatus, ...]:
        files: list[FileStatus] = []
        for item in self._changes_panel.active_tree().selectedItems():
            value = item.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(value, FileStatus):
                files.append(value)
        return tuple(files)

    def _checked_files(self) -> tuple[FileStatus, ...]:
        return self._changes_panel.action_files()

    @Slot()
    def _update_selection_actions(self) -> None:
        self._changes_panel.refresh_selection_controls()
        diff = self._diff_view.current_diff
        if diff is not None and self._diff_view.selected_line_indexes:
            if diff.staged:
                self._changes_panel.unstage_button.setEnabled(True)
            else:
                self._changes_panel.stage_button.setEnabled(True)
        self._diff_view.set_selection_action_states(
            stage=self._changes_panel.stage_button.isEnabled(),
            stash=self._changes_panel.stash_button.isEnabled(),
            unstage=self._changes_panel.unstage_button.isEnabled(),
            discard=self._changes_panel.discard_button.isEnabled(),
        )

    @Slot()
    def _stage_checked_changes(self) -> None:
        diff = self._diff_view.current_diff
        selected_lines = self._diff_view.selected_line_indexes
        if diff is not None and selected_lines and not diff.staged:
            self._clear_change_selection_after_mutation = True
            self._apply_diff_lines(diff, selected_lines)
            return
        self._set_checked_files_staged(True)

    @Slot()
    def _unstage_checked_changes(self) -> None:
        diff = self._diff_view.current_diff
        selected_lines = self._diff_view.selected_line_indexes
        if diff is not None and selected_lines and diff.staged:
            self._clear_change_selection_after_mutation = True
            self._apply_diff_lines(diff, selected_lines)
            return
        self._set_checked_files_staged(False)

    def _set_checked_files_staged(self, staged: bool) -> None:
        repository = self._repository
        status = self._repository_status
        checked = self._checked_files()
        if staged:
            for file in checked:
                if not file.unmerged:
                    continue
                path = self._selected_file_path(file)
                markers = conflict_marker_lines(path) if path is not None else ()
                if not markers:
                    continue
                line_list = ", ".join(str(line) for line in markers[:8])
                answer = QMessageBox.warning(
                    self,
                    "Conflict markers remain",
                    f"{file.path} still contains conflict markers on line(s) {line_list}.\n\n"
                    "Mark this file as resolved anyway?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                    QMessageBox.StandardButton.Cancel,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    return
        if (
            repository is not None
            and status is not None
            and self._amend.isChecked()
            and status.branch.oid is not None
            and checked
        ):
            self._set_changes_trees_enabled(False)
            for file in checked:
                self._git.request_amend_file(
                    repository,
                    status.branch.oid,
                    self._amend_parent_oid,
                    file.path,
                    included=staged,
                )
            return
        files = tuple(
            file
            for file in checked
            if ((file.has_worktree_change or file.unmerged) if staged else file.is_staged)
        )
        if repository is None or status is None or not files:
            return
        self._set_changes_trees_enabled(False)
        action = "Staging" if staged else "Unstaging"
        self._status_label.setText(f"{action} {len(files)} selected file(s)…")
        self._clear_change_selection_after_mutation = True
        self._git.request_stage_files(
            repository,
            files,
            staged=staged,
            has_head=status.branch.oid is not None,
        )

    @Slot()
    def _stash_checked_changes(self) -> None:
        files = tuple(file for file in self._checked_files() if file.has_worktree_change)
        repository = self._repository
        if repository is None or not files or any(file.unmerged for file in files):
            return
        self._changes_container.setEnabled(False)
        self._status_label.setText(f"Stashing {len(files)} selected file(s)…")
        self._clear_change_selection_after_mutation = True
        self._git.request_stash_files(repository, files)

    @Slot()
    def _discard_checked_changes(self) -> None:
        files = tuple(file for file in self._checked_files() if file.has_worktree_change)
        repository = self._repository
        if repository is None or not files or any(file.unmerged for file in files):
            return
        target = files[0].path if len(files) == 1 else f"{len(files)} selected files"
        answer = QMessageBox.question(
            self,
            "Discard changes",
            f"Permanently discard all unstaged changes to {target}?",
            QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Discard:
            return
        self._changes_container.setEnabled(False)
        self._status_label.setText(f"Discarding changes to {target}…")
        self._clear_change_selection_after_mutation = True
        self._git.request_discard_files(repository, files)

    def _selected_file(self) -> FileStatus | None:
        selected_items = self._changes_panel.active_tree().selectedItems()
        if not selected_items:
            return None
        value = selected_items[0].data(0, Qt.ItemDataRole.UserRole)
        return value if isinstance(value, FileStatus) else None

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
        selected_items = self._changes_panel.active_tree().selectedItems()
        repository = self._repository
        if not selected_items or repository is None:
            return
        item = selected_items[0]
        file = item.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(file, FileStatus) or file.unmerged:
            return
        staged = self._diff_version.currentData()
        if not isinstance(staged, bool):
            return
        current_diff = self._diff_view.current_diff
        replacing_visible_diff = (
            current_diff is None
            or current_diff.path != file.path
            or current_diff.staged != staged
        )
        if not silent and replacing_visible_diff:
            self._diff.setPlainText("Loading diff…")
            self._status_label.setText(f"Reading diff for {file.path}…")
        self._git.request_diff(
            repository,
            file,
            staged=staged,
            ignore_whitespace=self._ignore_whitespace_button.isChecked(),
            context_lines=self._diff_context_lines,
        )

    def _populate_diff_versions(self, file: FileStatus) -> None:
        blocker = QSignalBlocker(self._diff_version)
        self._diff_version.clear()
        if file.has_worktree_change:
            self._diff_version.addItem("Working tree", False)
        if file.is_staged:
            self._diff_version.addItem("Staged", True)
        del blocker
        self._diff_view.refresh_version_selector()

    @Slot(object)
    def _show_diff(self, value: object) -> None:
        if not isinstance(value, DiffSnapshot):
            return
        if self._amend.isChecked():
            return
        if value.repository != self._repository:
            return
        diff_value = value.diff
        selected_items = self._changes_panel.active_tree().selectedItems()
        if not selected_items:
            return
        current = selected_items[0]
        file = current.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(file, FileStatus) or file.path != diff_value.path:
            return
        if self._diff_version.currentData() != diff_value.staged:
            return
        current_diff = self._diff_view.current_diff
        preserve_view = (
            current_diff is not None
            and current_diff.path == diff_value.path
            and current_diff.staged == diff_value.staged
        )
        self._diff_container.setCurrentWidget(self._diff_view)
        self._diff_view.display_diff(
            diff_value,
            selection_key=(value.repository, diff_value.path, diff_value.staged),
            preserve_scroll=preserve_view,
            whole_file_staged=(
                diff_value.staged and not file.has_worktree_change and not file.unmerged
            ),
        )
        self._diff_view.set_close_available(False)
        version = "staged" if diff_value.staged else "working tree"
        self._status_label.setText(f"Showing {version} diff for {diff_value.path}")

    @Slot()
    def _close_history_diff(self) -> None:
        if self._workspace_tabs.currentIndex() != 1 or not self._commit_diff_visible:
            return
        self._commit_diff_visible = False
        self._diff_view.clear_display()
        self._workspace_tab_changed(self._workspace_tabs.currentIndex())
        target = self._history_panel.files
        if target.topLevelItemCount() == 0:
            target = self._history_panel.tree
        target.setFocus()
        self._status_label.setText("Closed commit diff")

    def _sync_selected_file_checkbox(self) -> None:
        if self._amend.isChecked():
            return
        active_tree = self._changes_panel.active_tree()
        selected_items = active_tree.selectedItems()
        if not selected_items:
            return
        item = selected_items[0]
        file = item.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(file, FileStatus) or file.unmerged:
            return
        if self._diff_view.has_pending_partial_selection:
            state = Qt.CheckState.PartiallyChecked
        elif self._changes_panel.split_mode:
            state = (
                Qt.CheckState.Checked
                if active_tree is self._changes_panel.staged_tree
                else Qt.CheckState.Unchecked
            )
        elif file.is_staged and file.has_worktree_change:
            state = Qt.CheckState.PartiallyChecked
        elif file.is_staged:
            state = Qt.CheckState.Checked
        else:
            state = Qt.CheckState.Unchecked
        self._changes_panel.set_file_check_state(active_tree, item, state)

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

    @Slot(bool)
    def _diff_ignore_whitespace_changed(self, enabled: bool) -> None:
        self._settings.setValue("diff/ignoreWhitespace", enabled)
        if self._workspace_tabs.currentIndex() != 1:
            self._request_diff(silent=False)
            return
        item = cast(QTreeWidgetItem | None, self._history_panel.files.currentItem())
        if item is None:
            return
        file = item.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(file, CommitFileChange):
            return
        if len(self._history_refs) == 2:
            self._history_comparison_file_selected(*self._history_refs, file)
            return
        commit = self._history_panel.selected_commit
        if commit is not None:
            self._history_file_selected(commit, file)

    @Slot(int)
    def _diff_context_changed(self, context_lines: int) -> None:
        self._diff_context_lines = context_lines
        if self._workspace_tabs.currentIndex() != 1:
            self._request_diff(silent=False)
            return
        item = cast(QTreeWidgetItem | None, self._history_panel.files.currentItem())
        if item is None:
            return
        file = item.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(file, CommitFileChange):
            return
        if len(self._history_refs) == 2:
            self._history_comparison_file_selected(*self._history_refs, file)
            return
        commit = self._history_panel.selected_commit
        if commit is not None:
            self._history_file_selected(commit, file)

    @Slot(str)
    def _show_git_error(self, message: str) -> None:
        self._clear_change_selection_after_mutation = False
        self._set_network_busy(None)
        self._status_runner = None
        self._history_runner = None
        self._set_changes_trees_enabled(True)
        self._changes_container.setEnabled(True)
        self._conflict_editor.setEnabled(True)
        self._history_panel.refs_panel.setEnabled(True)
        self._status_label.setText("Git operation failed")
        now = monotonic()
        if self._git_error_dialog_open or now - self._last_git_error_at < 1.0:
            return
        self._git_error_dialog_open = True
        self._last_git_error_at = now
        try:
            QMessageBox.critical(self, "Git error", message)
        finally:
            self._git_error_dialog_open = False
            self._last_git_error_at = monotonic()

    @Slot(QAction)
    def _theme_selected(self, action: QAction) -> None:
        theme = Theme.from_value(action.data())
        self._theme = theme
        self._settings.setValue("appearance/theme", theme.value)
        self._settings.sync()
        self.restart_requested.emit()

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
        self._refresh_timer.stop()
        self._queue_duration_timer.stop()
        self._repository_activation += 1
        self._status_runner = None
        self._git.blockSignals(True)
        self._workspace_discovery.blockSignals(True)
        self._git.shutdown()
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


def _queue_operation_icon(operation: str) -> str:
    lowered = operation.casefold()
    if "push" in lowered:
        return "push.svg"
    if "pull" in lowered:
        return "pull.svg"
    if "fetch" in lowered:
        return "fetch.svg"
    if "commit" in lowered:
        return "commit.svg"
    if "unstage" in lowered or "exclude" in lowered:
        return "unstage.svg"
    if "stage" in lowered or "include" in lowered or "apply" in lowered:
        return "stage.svg"
    if "discard" in lowered or "delete" in lowered:
        return "remove.svg"
    if "checkout" in lowered or "branch" in lowered:
        return "open.svg"
    if "stash" in lowered:
        return "autostash.svg"
    return "refresh.svg"


def format_operation_duration(milliseconds: int) -> str:
    seconds = max(0, milliseconds // 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def _commit_change_label(file: FileStatus) -> str:
    return {
        "A": "Add",
        "D": "Delete",
        "R": "Rename",
        "C": "Copy",
        "T": "Change type of",
    }.get(file.index_status, "Update")
