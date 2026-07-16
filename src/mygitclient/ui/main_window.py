from __future__ import annotations

from pathlib import Path
from typing import cast

from PySide6.QtCore import QByteArray, QSettings, QSignalBlocker, Qt, Slot
from PySide6.QtGui import QAction, QActionGroup, QCloseEvent, QFont, QFontDatabase, QFontMetrics
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QSplitter,
    QStackedWidget,
    QToolBar,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from mygitclient.git.models import DiffLine, DiffLineKind, FileStatus, RepositoryStatus, UnifiedDiff
from mygitclient.git.service import GitService
from mygitclient.resources import load_icon
from mygitclient.theme import Theme, apply_theme
from mygitclient.ui.diff_highlighter import DiffHighlighter
from mygitclient.workspace import WorkspaceManager, find_repository_root


class MainWindow(QMainWindow):
    def __init__(self, settings: QSettings, theme: Theme) -> None:
        super().__init__()
        self._settings = settings
        self._theme = theme
        self._workspace = WorkspaceManager(settings)
        self._git = GitService(self)
        self._repository: Path | None = None
        self.setWindowTitle("MyGitClient")
        self.setWindowIcon(load_icon("app-icon.png"))
        self.resize(1180, 760)
        self._build_ui()
        self._build_menu()
        self._connect_services()
        self._populate_recent_repositories()
        self._restore_window_state()

    def _build_ui(self) -> None:
        self._repositories = QTreeWidget()
        self._repositories.setObjectName("repositoriesTree")
        self._repositories.setHeaderLabel("Recent repositories")
        self._repositories.setMinimumWidth(180)
        self._repositories.setContextMenuPolicy(Qt.ContextMenuPolicy.ActionsContextMenu)
        self._remove_recent_action = QAction("Remove from recent list", self._repositories)
        self._remove_recent_action.setIcon(load_icon("remove.svg"))
        self._remove_recent_action.setObjectName("removeRecentAction")
        self._remove_recent_action.triggered.connect(self._remove_selected_recent)
        self._repositories.addAction(self._remove_recent_action)

        self._welcome = QPlainTextEdit()
        self._welcome.setObjectName("welcomePanel")
        self._welcome.setReadOnly(True)
        self._welcome.setPlainText(
            "Welcome to MyGitClient\n\n"
            "Open a Git repository with File → Open Repository."
        )

        self._changes = QTreeWidget()
        self._changes.setObjectName("changesTree")
        self._changes.setHeaderLabels(["File", "Index", "Working tree"])
        self._changes.setRootIsDecorated(False)
        self._changes.setMinimumWidth(280)
        self._changes.hide()

        self._diff = QPlainTextEdit()
        self._diff.setObjectName("diffPanel")
        self._diff.setReadOnly(True)
        self._diff.setPlaceholderText("Select a changed file to view its diff.")
        self._diff.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._diff.setMinimumWidth(400)
        diff_font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        diff_font.setStyleHint(QFont.StyleHint.Monospace)
        diff_font.setFixedPitch(True)
        self._diff.setFont(diff_font)
        self._diff.hide()
        self._diff_highlighter = DiffHighlighter(self._diff)

        self._diff_gutter = QPlainTextEdit()
        self._diff_gutter.setObjectName("diffGutter")
        self._diff_gutter.setReadOnly(True)
        self._diff_gutter.setFont(diff_font)
        self._diff_gutter.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._diff_gutter.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._diff_gutter.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._diff_gutter.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._diff_gutter.setStyleSheet(
            "QPlainTextEdit { background: palette(alternate-base); "
            "color: palette(mid); border: 0; border-right: 1px solid palette(midlight); }"
        )
        self._diff_gutter.hide()
        self._diff.verticalScrollBar().valueChanged.connect(
            self._diff_gutter.verticalScrollBar().setValue
        )
        self._diff_gutter.verticalScrollBar().valueChanged.connect(
            self._diff.verticalScrollBar().setValue
        )

        self._diff_version = QComboBox()
        self._diff_version.setObjectName("diffVersionCombo")
        self._diff_version.setToolTip("Choose which version of the selected file to compare")
        self._diff_version.currentIndexChanged.connect(self._request_selected_diff)
        self._diff_version.hide()

        self._diff_view_mode = QComboBox()
        self._diff_view_mode.setObjectName("diffViewModeCombo")
        self._diff_view_mode.addItem("Unified", "unified")
        self._diff_view_mode.addItem("Side-by-side", "side-by-side")
        saved_view = self._settings.value("diff/viewMode", "unified")
        saved_index = self._diff_view_mode.findData(saved_view)
        self._diff_view_mode.setCurrentIndex(max(saved_index, 0))
        self._diff_view_mode.currentIndexChanged.connect(self._diff_view_changed)
        self._diff_view_mode.hide()

        self._diff_container = QWidget()
        diff_layout = QVBoxLayout(self._diff_container)
        diff_layout.setContentsMargins(0, 0, 0, 0)
        diff_body = QWidget()
        diff_body_layout = QHBoxLayout(diff_body)
        diff_body_layout.setContentsMargins(0, 0, 0, 0)
        diff_body_layout.setSpacing(0)
        diff_body_layout.addWidget(self._diff_gutter)
        diff_body_layout.addWidget(self._diff, 1)

        self._side_old = self._make_side_diff_editor("sideBySideOld")
        self._side_new = self._make_side_diff_editor("sideBySideNew")
        self._side_old_highlighter = DiffHighlighter(self._side_old)
        self._side_new_highlighter = DiffHighlighter(self._side_new)
        self._side_old.verticalScrollBar().valueChanged.connect(
            self._side_new.verticalScrollBar().setValue
        )
        self._side_new.verticalScrollBar().valueChanged.connect(
            self._side_old.verticalScrollBar().setValue
        )
        side_splitter = QSplitter(Qt.Orientation.Horizontal)
        side_splitter.addWidget(self._side_old)
        side_splitter.addWidget(self._side_new)
        side_splitter.setSizes([500, 500])

        toolbar = QWidget()
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(0, 0, 0, 0)
        toolbar_layout.addWidget(self._diff_version, 1)
        toolbar_layout.addWidget(self._diff_view_mode)
        diff_layout.insertWidget(0, toolbar)

        self._diff_stack = QStackedWidget()
        self._diff_stack.addWidget(diff_body)
        self._diff_stack.addWidget(side_splitter)
        self._diff_stack.setCurrentIndex(max(saved_index, 0))
        diff_layout.addWidget(self._diff_stack)
        self._diff_container.hide()

        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.setObjectName("mainSplitter")
        self._splitter.addWidget(self._repositories)
        self._splitter.addWidget(self._welcome)
        self._splitter.addWidget(self._changes)
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

    @staticmethod
    def _make_side_diff_editor(object_name: str) -> QPlainTextEdit:
        editor = QPlainTextEdit()
        editor.setObjectName(object_name)
        editor.setReadOnly(True)
        editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setFixedPitch(True)
        editor.setFont(font)
        return editor

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
        refresh_action = QAction(load_icon("refresh.svg"), "Refresh", self)
        refresh_action.setObjectName("refreshAction")
        refresh_action.setShortcut("F5")
        refresh_action.triggered.connect(self._refresh_repository)
        toolbar.addAction(refresh_action)
        self.addToolBar(toolbar)

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
        self._git.status_ready.connect(self._show_status)
        self._git.diff_ready.connect(self._show_diff)
        self._git.mutation_ready.connect(self._staging_finished)
        self._git.operation_failed.connect(self._show_git_error)
        self._repositories.itemActivated.connect(self._open_recent_item)
        self._changes.itemSelectionChanged.connect(self._selected_file_changed)
        self._changes.itemChanged.connect(self._stage_checkbox_changed)

    def _populate_recent_repositories(self) -> None:
        self._repositories.clear()
        recent = self._workspace.recent_repositories()
        if not recent:
            placeholder = QTreeWidgetItem(["No recent repositories"])
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            self._repositories.addTopLevelItem(placeholder)
            return
        for repository in recent:
            item = QTreeWidgetItem([repository.name])
            item.setToolTip(0, str(repository))
            item.setData(0, Qt.ItemDataRole.UserRole, str(repository))
            self._repositories.addTopLevelItem(item)

    @Slot()
    def _choose_repository(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Open Git Repository")
        if selected:
            self.open_repository(Path(selected))

    @Slot(QTreeWidgetItem, int)
    def _open_recent_item(self, item: QTreeWidgetItem, _column: int) -> None:
        value = item.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(value, str):
            repository = Path(value)
            if not repository.is_dir() or not (repository / ".git").exists():
                self._workspace.forget(repository)
                self._populate_recent_repositories()
                self._status_label.setText("Removed missing repository from recent list")
                return
            self.open_repository(repository)

    @Slot()
    def _remove_selected_recent(self) -> None:
        selected_items = self._repositories.selectedItems()
        if not selected_items:
            return
        value = selected_items[0].data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(value, str):
            return
        self._workspace.forget(Path(value))
        self._populate_recent_repositories()
        self._status_label.setText("Removed repository from recent list")

    def open_repository(self, selected_path: Path) -> None:
        repository = find_repository_root(selected_path)
        if repository is None:
            QMessageBox.warning(
                self,
                "Not a Git repository",
                f"No Git repository was found in or above:\n{selected_path}",
            )
            return
        self._repository = repository
        self._workspace.remember(repository)
        self._populate_recent_repositories()
        self._status_label.setText(f"Reading {repository.name}…")
        self._changes.clear()
        self._diff.clear()
        self._diff_gutter.clear()
        self._welcome.hide()
        self._changes.show()
        self._diff_version.show()
        self._diff_view_mode.show()
        self._diff_gutter.show()
        self._diff.show()
        self._diff_container.show()
        self._restore_workspace_splitter_sizes()
        self._git.request_status(repository)

    @Slot()
    def _refresh_repository(self) -> None:
        if self._repository is None:
            return
        self._status_label.setText(f"Refreshing {self._repository.name}…")
        self._git.request_status(self._repository)

    @Slot(object)
    def _show_status(self, value: object) -> None:
        if not isinstance(value, RepositoryStatus):
            return
        blocker = QSignalBlocker(self._changes)
        self._changes.clear()
        for file in value.files:
            index_label = "" if file.index_status == "?" else _status_label(file.index_status)
            item = QTreeWidgetItem(
                [file.path, index_label, _status_label(file.worktree_status)]
            )
            if file.original_path is not None:
                item.setToolTip(0, f"Renamed from {file.original_path}")
            item.setData(0, Qt.ItemDataRole.UserRole, file)
            if not file.unmerged:
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                if file.is_staged and file.has_worktree_change:
                    item.setCheckState(0, Qt.CheckState.PartiallyChecked)
                elif file.is_staged:
                    item.setCheckState(0, Qt.CheckState.Checked)
                else:
                    item.setCheckState(0, Qt.CheckState.Unchecked)
            self._changes.addTopLevelItem(item)
        del blocker
        self._changes.resizeColumnToContents(0)

        branch = value.branch.head or "detached HEAD"
        repository_name = self._repository.name if self._repository is not None else "Repository"
        change_count = len(value.files)
        self.setWindowTitle(f"{repository_name} — {branch} — MyGitClient")
        self._status_label.setText(f"{branch} · {change_count} changed file(s)")

    @Slot(QTreeWidgetItem, int)
    def _stage_checkbox_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if column != 0 or self._repository is None:
            return
        file = item.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(file, FileStatus) or file.unmerged:
            return
        should_stage = item.checkState(0) is not Qt.CheckState.Unchecked
        self._changes.setEnabled(False)
        action = "Staging" if should_stage else "Unstaging"
        self._status_label.setText(f"{action} {file.path}…")
        self._git.request_stage(self._repository, file, staged=should_stage)

    @Slot(str)
    def _staging_finished(self, path: str) -> None:
        self._changes.setEnabled(True)
        self._status_label.setText(f"Updated staging area for {path}")
        if self._repository is not None:
            self._git.request_status(self._repository)

    @Slot()
    def _selected_file_changed(self) -> None:
        selected_items = self._changes.selectedItems()
        if not selected_items:
            return
        file = selected_items[0].data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(file, FileStatus):
            return
        self._populate_diff_versions(file)
        self._request_selected_diff()

    @Slot()
    def _request_selected_diff(self) -> None:
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
        if not isinstance(value, UnifiedDiff):
            return
        selected_items = self._changes.selectedItems()
        if not selected_items:
            return
        current = selected_items[0]
        file = current.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(file, FileStatus) or file.path != value.path:
            return
        if self._diff_version.currentData() != value.staged:
            return
        self._diff_highlighter.set_diff(value)
        self._diff.setPlainText(value.text or "No textual changes to display.")
        self._show_diff_line_numbers(value)
        self._show_side_by_side(value)
        version = "staged" if value.staged else "working tree"
        self._status_label.setText(f"Showing {version} diff for {value.path}")

    def _show_diff_line_numbers(self, diff: UnifiedDiff) -> None:
        old_width = max(
            (len(str(line.old_line)) for line in diff.lines if line.old_line is not None),
            default=1,
        )
        new_width = max(
            (len(str(line.new_line)) for line in diff.lines if line.new_line is not None),
            default=1,
        )
        numbers: list[str] = []
        for line in diff.lines:
            old_number = str(line.old_line) if line.old_line is not None else ""
            new_number = str(line.new_line) if line.new_line is not None else ""
            numbers.append(f"{old_number:>{old_width}}  {new_number:>{new_width}}")
        self._diff_gutter.setPlainText("\n".join(numbers))
        metrics = QFontMetrics(self._diff_gutter.font())
        sample = "0" * (old_width + new_width + 3)
        self._diff_gutter.setFixedWidth(metrics.horizontalAdvance(sample) + 12)

    def _show_side_by_side(self, diff: UnifiedDiff) -> None:
        old_lines: list[str] = []
        new_lines: list[str] = []
        old_kinds: list[DiffLineKind] = []
        new_kinds: list[DiffLineKind] = []
        old_width = max(
            (len(str(line.old_line)) for line in diff.lines if line.old_line is not None),
            default=1,
        )
        new_width = max(
            (len(str(line.new_line)) for line in diff.lines if line.new_line is not None),
            default=1,
        )
        for row in diff.side_by_side_rows:
            old_lines.append(self._side_line_text(row.old, old_width, old=True))
            new_lines.append(self._side_line_text(row.new, new_width, old=False))
            old_kinds.append(row.old.kind if row.old is not None else "metadata")
            new_kinds.append(row.new.kind if row.new is not None else "metadata")
        self._side_old_highlighter.set_line_kinds(tuple(old_kinds))
        self._side_new_highlighter.set_line_kinds(tuple(new_kinds))
        self._side_old.setPlainText("\n".join(old_lines))
        self._side_new.setPlainText("\n".join(new_lines))

    @staticmethod
    def _side_line_text(line: DiffLine | None, width: int, *, old: bool) -> str:
        if line is None:
            return ""
        number = line.old_line if old else line.new_line
        number_text = str(number) if number is not None else ""
        content = line.text[1:] if line.kind in {"addition", "deletion", "context"} else line.text
        return f"{number_text:>{width}}  {content}"

    @Slot(int)
    def _diff_view_changed(self, _index: int) -> None:
        mode = self._diff_view_mode.currentData()
        if not isinstance(mode, str):
            return
        self._settings.setValue("diff/viewMode", mode)
        self._diff_stack.setCurrentIndex(1 if mode == "side-by-side" else 0)

    @Slot(str)
    def _show_git_error(self, message: str) -> None:
        self._changes.setEnabled(True)
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
            self._diff_highlighter.rehighlight()
            self._side_old_highlighter.rehighlight()
            self._side_new_highlighter.rehighlight()

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
        self._settings.setValue("window/geometry", self.saveGeometry())
        self._settings.setValue("window/state", self.saveState())
        if self._repository is not None:
            self._settings.setValue("window/workspaceSplitterSizes", self._splitter.sizes())
        super().closeEvent(event)


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
