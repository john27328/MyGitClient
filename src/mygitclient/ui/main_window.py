from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QByteArray, QSettings, Qt, Slot
from PySide6.QtGui import QAction, QActionGroup, QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
)

from mygitclient.git.models import RepositoryStatus
from mygitclient.git.service import GitService
from mygitclient.theme import Theme, apply_theme
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
        self._changes.hide()

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._repositories)
        splitter.addWidget(self._welcome)
        splitter.addWidget(self._changes)
        splitter.setSizes([280, 900])
        self.setCentralWidget(splitter)
        self._status_label = QLabel("Ready")
        self._status_label.setObjectName("statusLabel")
        self.statusBar().addWidget(self._status_label)

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        open_action = QAction("&Open Repository…", self)
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self._choose_repository)
        file_menu.addAction(open_action)
        file_menu.addSeparator()
        exit_action = QAction("E&xit", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

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
        self._git.operation_failed.connect(self._show_git_error)
        self._repositories.itemActivated.connect(self._open_recent_item)

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
            self.open_repository(Path(value))

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
        self._welcome.hide()
        self._changes.show()
        self._git.request_status(repository)

    @Slot(object)
    def _show_status(self, value: object) -> None:
        if not isinstance(value, RepositoryStatus):
            return
        self._changes.clear()
        for file in value.files:
            item = QTreeWidgetItem(
                [file.path, _status_label(file.index_status), _status_label(file.worktree_status)]
            )
            if file.original_path is not None:
                item.setToolTip(0, f"Renamed from {file.original_path}")
            self._changes.addTopLevelItem(item)
        self._changes.resizeColumnToContents(0)

        branch = value.branch.head or "detached HEAD"
        repository_name = self._repository.name if self._repository is not None else "Repository"
        change_count = len(value.files)
        self.setWindowTitle(f"{repository_name} — {branch} — MyGitClient")
        self._status_label.setText(f"{branch} · {change_count} changed file(s)")

    @Slot(str)
    def _show_git_error(self, message: str) -> None:
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

    def _restore_window_state(self) -> None:
        geometry = self._settings.value("window/geometry")
        state = self._settings.value("window/state")
        if isinstance(geometry, QByteArray):
            self.restoreGeometry(geometry)
        if isinstance(state, QByteArray):
            self.restoreState(state)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        self._settings.setValue("window/geometry", self.saveGeometry())
        self._settings.setValue("window/state", self.saveState())
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
