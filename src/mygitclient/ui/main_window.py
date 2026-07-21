from __future__ import annotations

from pathlib import Path
from typing import cast

from PySide6.QtCore import (
    QByteArray,
    QElapsedTimer,
    QSettings,
    QSignalBlocker,
    Qt,
    QTimer,
    QUrl,
    Slot,
)
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QCloseEvent,
    QDesktopServices,
    QFontDatabase,
)
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressDialog,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QToolBar,
    QToolButton,
    QTreeWidgetItem,
)

from mygitclient import __version__
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
    RefComparisonDiffSnapshot,
    RefComparisonSnapshot,
    RepositoryStatus,
    RepositoryStatusSnapshot,
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
from mygitclient.theme import Theme, apply_theme
from mygitclient.ui.changes_panel import ChangesPanel
from mygitclient.ui.commit_text import generated_commit_text
from mygitclient.ui.diff_view import DiffView
from mygitclient.ui.history_panel import HistoryPanel
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
    def __init__(self, settings: QSettings, theme: Theme) -> None:
        super().__init__()
        self._settings = settings
        self._theme = theme
        self._apply_saved_ui_font()
        self._workspace = WorkspaceManager(settings)
        self._workspace_discovery = WorkspaceDiscoveryService(self)
        self._update_checker = UpdateChecker(self)
        self._update_downloader = UpdateDownloader(self)
        self._update_progress: QProgressDialog | None = None
        self._manual_update_check = False
        self._update_checker.update_available.connect(self._update_available)
        self._update_checker.up_to_date.connect(self._update_is_current)
        self._update_checker.failed.connect(self._update_check_failed)
        self._update_downloader.progress.connect(self._update_download_progress)
        self._update_downloader.ready.connect(self._update_downloaded)
        self._update_downloader.failed.connect(self._update_download_failed)
        self._update_downloader.cancelled.connect(self._update_download_cancelled)
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
        self._history_refs: tuple[str, ...] = ()
        self._active_queue_operation: QueuedOperation | None = None
        self._queued_operation_count = 0
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

        self._changes_panel = ChangesPanel(self._settings)
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
        self._changes_panel.folder_stage_requested.connect(self._stage_folder)
        self._changes_panel.view_mode_changed.connect(self._changes_view_mode_changed)
        self._update_commit_controls()

        self._history_panel = HistoryPanel()
        self._history_panel.load_more_requested.connect(self._load_more_history)
        self._history_panel.commit_selected.connect(self._history_commit_selected)
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
        refs_panel.create_branch_requested.connect(self._create_branch)
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
        self._git.history_ready.connect(self._show_history)
        self._git.comparison_ready.connect(self._show_ref_comparison)
        self._git.comparison_diff_ready.connect(self._show_ref_comparison_diff)
        self._git.branches_ready.connect(self._show_branches)
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
        self._changes.itemSelectionChanged.connect(self._selected_file_changed)
        self._changes.itemSelectionChanged.connect(self._update_file_actions)
        self._changes.itemChanged.connect(self._stage_checkbox_changed)

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
        self._history_refs = ()
        self._diff_view.reset()
        self._welcome.hide()
        self._workspace_tabs.show()
        self._diff_version.show()
        self._diff_view_mode.show()
        self._diff_gutter.setVisible(not self._wrap_button.isChecked())
        self._diff.show()
        self._workspace_tab_changed(self._workspace_tabs.currentIndex())
        self._status_runner = self._git.request_status(repository)
        self._history_runner = None
        self._git.request_branches(repository)
        self._git.request_tags(repository)
        self._git.request_stashes(repository)
        self._refresh_timer.start()

    @Slot(int)
    def _workspace_tab_changed(self, index: int) -> None:
        repository = getattr(self, "_repository", None)
        commit_diff_visible = getattr(self, "_commit_diff_visible", False)
        showing_history = index == 1
        show_diff = repository is not None and (not showing_history or commit_diff_visible)
        self._diff_container.setVisible(show_diff)
        if showing_history:
            if commit_diff_visible:
                self._splitter.setSizes([220, 0, 560, 840])
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

    @Slot(str, str, object)
    def _history_comparison_file_selected(
        self, base_ref: str, compare_ref: str, file_value: object
    ) -> None:
        if self._repository is None or not isinstance(file_value, CommitFileChange):
            return
        self._status_label.setText(f"Comparing {file_value.path}…")
        self._git.request_ref_comparison_diff(
            self._repository, base_ref, compare_ref, file_value.path
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
        self._diff_view.display_diff(
            value.diff,
            selection_key=None,
            preserve_scroll=False,
            whole_file_staged=False,
            interactive=False,
        )
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
        self._history_panel.refs_panel.show_branches(value)

    @Slot(object)
    def _show_tags(self, value: object) -> None:
        if not isinstance(value, TagsSnapshot) or value.repository != self._repository:
            return
        self._history_panel.refs_panel.show_tags(value)

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
        stage_all_blocker = QSignalBlocker(self._stage_all)
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
        item_to_restore = self._changes_panel.show_files(rendered_files, selected_path)
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

    @Slot(object, bool)
    def _stage_folder(self, value: object, should_stage: bool) -> None:
        if self._repository is None or not isinstance(value, tuple):
            return
        objects = cast(tuple[object, ...], value)
        files = tuple(file for file in objects if isinstance(file, FileStatus))
        if not files or len(files) != len(objects):
            return
        self._changes.setEnabled(False)
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
        if self._repository is None:
            return
        self._repository_status = None
        self._status_runner = self._git.request_status(self._repository)

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
        self._history_panel.refs_panel.setEnabled(True)
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
        self._history_panel.refs_panel.setEnabled(True)
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
