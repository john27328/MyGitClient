from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QProcess, QSettings, Qt, Slot
from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QInputDialog,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressDialog,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from mygitclient.git.clone_service import (
    CloneService,
    is_valid_clone_folder_name,
    suggested_clone_name,
)
from mygitclient.resources import load_icon
from mygitclient.theme import Theme
from mygitclient.ui.home_panel import HomePanel
from mygitclient.ui.main_window import MainWindow
from mygitclient.workspace import WorkspaceManager, find_repository_root


class RepositorySessionTab(QWidget):
    def __init__(self, controller: MainWindow) -> None:
        super().__init__()
        self.controller = controller
        self._stopped = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        controller.setParent(self)
        controller.setWindowFlags(Qt.WindowType.Widget)
        controller.menuBar().hide()
        layout.addWidget(controller)
        controller.show()

    def open_repository(self, repository: Path) -> None:
        self.controller.open_repository(repository)

    def shutdown(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        self.controller.close()


class AppShell(QMainWindow):
    def __init__(self, settings: QSettings, theme: Theme) -> None:
        super().__init__()
        self._settings = settings
        self._theme = theme
        self._workspace = WorkspaceManager(settings)
        self._sessions: dict[Path, RepositorySessionTab] = {}
        self._last_session: RepositorySessionTab | None = None
        self._menu_proxies: list[QMenu] = []
        self._closing = False
        self._clone_progress: QProgressDialog | None = None
        self._clone_service = CloneService(self)
        self._clone_service.progress.connect(self._clone_progress_changed)
        self._clone_service.completed.connect(self._clone_completed)
        self._clone_service.failed.connect(self._clone_failed)
        self._clone_service.cancelled.connect(self._clone_cancelled)

        self.setObjectName("appShell")
        self.setWindowTitle("MyGitClient")
        self.setWindowIcon(load_icon("app-icon.png"))
        self.resize(1180, 760)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("repositorySessionTabs")
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.tabCloseRequested.connect(self._close_tab)
        self.tabs.currentChanged.connect(self._current_tab_changed)
        self.setCentralWidget(self.tabs)

        self.home = HomePanel()
        self.home.choose_repository_requested.connect(self._choose_repository)
        self.home.open_repository_requested.connect(self._open_home_repository)
        self.home.open_workspace_requested.connect(self._open_workspace)
        self.home.clone_repository_requested.connect(self._clone_repository)
        self.tabs.addTab(self.home, "Home")
        self.tabs.tabBar().setTabButton(0, self.tabs.tabBar().ButtonPosition.RightSide, None)

        self._file_menu = QMenu("&File", self)
        open_action = QAction(load_icon("open.svg"), "&Open Repository…", self)
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self._choose_repository)
        self._file_menu.addAction(open_action)
        self._file_menu.addSeparator()
        exit_action = self._file_menu.addAction("E&xit")
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        self._rebuild_menu_bar()

        self._refresh_home()

    @Slot()
    def _choose_repository(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Open Git Repository")
        if selected:
            self.open_repository(Path(selected))

    @Slot(object)
    def _open_home_repository(self, value: object) -> None:
        if isinstance(value, Path):
            self.open_repository(value)

    @Slot(str)
    def _open_workspace(self, name: str) -> None:
        for repository in self._workspace.load_named_workspace(name):
            self.open_repository(repository)

    @Slot(str)
    def _clone_repository(self, url: str) -> None:
        if self._clone_service.is_running:
            QMessageBox.information(self, "Clone in progress", "A repository is already cloning.")
            return
        parent = QFileDialog.getExistingDirectory(self, "Select clone parent directory")
        if not parent:
            return
        name, accepted = QInputDialog.getText(
            self,
            "Clone repository",
            "Folder name:",
            text=suggested_clone_name(url),
        )
        name = name.strip()
        if not accepted:
            return
        if not is_valid_clone_folder_name(name):
            QMessageBox.warning(
                self,
                "Invalid folder name",
                "Enter a single folder name without path separators, '.' or '..'.",
            )
            return
        target = (Path(parent) / name).resolve()
        if target.exists():
            QMessageBox.warning(
                self,
                "Clone destination exists",
                f"Choose a new folder name. This path already exists:\n{target}",
            )
            return
        progress = QProgressDialog("Starting clone…", "Cancel", 0, 0, self)
        progress.setObjectName("cloneRepositoryProgress")
        progress.setWindowTitle("Cloning repository")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.canceled.connect(self._clone_service.cancel)
        self._clone_progress = progress
        progress.show()
        if not self._clone_service.clone(url, target):
            self._close_clone_progress()

    @Slot(str)
    def _clone_progress_changed(self, message: str) -> None:
        if self._clone_progress is not None:
            self._clone_progress.setLabelText(message)

    @Slot(object)
    def _clone_completed(self, value: object) -> None:
        self._close_clone_progress()
        if not isinstance(value, Path):
            return
        self.home.clone_url.clear()
        self.open_repository(value)

    @Slot(str)
    def _clone_failed(self, message: str) -> None:
        self._close_clone_progress()
        QMessageBox.warning(self, "Clone failed", message)

    @Slot()
    def _clone_cancelled(self) -> None:
        self._close_clone_progress()

    def _close_clone_progress(self) -> None:
        if self._clone_progress is not None:
            self._clone_progress.close()
            self._clone_progress.deleteLater()
            self._clone_progress = None

    def open_repository(self, selected_path: Path) -> None:
        repository = find_repository_root(selected_path)
        if repository is None:
            QMessageBox.warning(
                self,
                "Not a Git repository",
                f"No Git repository was found in or above:\n{selected_path}",
            )
            return
        repository = repository.resolve()
        existing = self._sessions.get(repository)
        if existing is not None:
            self.tabs.setCurrentWidget(existing)
            return

        controller = MainWindow(self._settings, self._theme, session_mode=True)
        controller.repository_tab_requested.connect(self._open_session_repository)
        controller.restart_requested.connect(self._restart_application)
        controller.open_repository(repository)
        session = RepositorySessionTab(controller)
        self._sessions[repository] = session
        index = self.tabs.addTab(session, repository.name)
        self.tabs.setTabToolTip(index, str(repository))
        self.tabs.setCurrentIndex(index)

        repositories = list(self._sessions)
        self._workspace.save_open_repositories(repositories)
        self._workspace.remember(repository)
        self._workspace.set_last_repository(repository)
        self._refresh_home()

    @Slot(object, bool)
    def _open_session_repository(self, value: object, remember: bool) -> None:
        del remember
        if isinstance(value, Path):
            self.open_repository(value)

    @Slot(int)
    def _close_tab(self, index: int) -> None:
        if index <= 0:
            return
        widget = self.tabs.widget(index)
        repository = next(
            (path for path, session in self._sessions.items() if session is widget),
            None,
        )
        self.tabs.removeTab(index)
        if repository is not None:
            session = self._sessions.pop(repository)
            if self._last_session is session:
                self._last_session = next(iter(self._sessions.values()), None)
            session.shutdown()
            session.deleteLater()
        self._workspace.save_open_repositories(list(self._sessions))
        self._refresh_home()
        self._rebuild_menu_bar()

    @Slot(int)
    def _current_tab_changed(self, index: int) -> None:
        widget = self.tabs.widget(index)
        repository = next(
            (path for path, session in self._sessions.items() if session is widget),
            None,
        )
        if isinstance(widget, RepositorySessionTab):
            self._last_session = widget
        self.setWindowTitle(
            "MyGitClient" if repository is None else f"{repository.name} — MyGitClient"
        )

        self._rebuild_menu_bar()

    def _rebuild_menu_bar(self) -> None:
        if not hasattr(self, "_file_menu"):
            return
        menu_bar = self.menuBar()
        menu_bar.clear()
        for menu in self._menu_proxies:
            menu.deleteLater()
        self._menu_proxies.clear()
        menu_bar.addMenu(self._file_menu)
        current = self.tabs.currentWidget()
        source = current if isinstance(current, RepositorySessionTab) else self._last_session
        if source is None:
            return
        for action in source.controller.menuBar().actions():
            source_menu = action.menu()
            if action.text().replace("&", "") == "File" or not isinstance(
                source_menu, QMenu
            ):
                continue
            proxy = QMenu(source_menu.title(), self)
            proxy.addActions(source_menu.actions())
            self._menu_proxies.append(proxy)
            menu_bar.addMenu(proxy)

    def _refresh_home(self) -> None:
        self.home.set_recent(self._workspace.recent_repositories())
        self.home.set_workspaces(self._workspace.named_workspaces())

    @Slot()
    def _restart_application(self) -> None:
        if getattr(sys, "frozen", False):
            program = sys.executable
            arguments = sys.argv[1:]
        else:
            program = sys.executable
            arguments = ["-m", "mygitclient", *sys.argv[1:]]
        started, _process_id = QProcess.startDetached(program, arguments, str(Path.cwd()))
        if not started:
            QMessageBox.warning(
                self,
                "Restart failed",
                "The theme was saved, but MyGitClient could not restart automatically.",
            )
            return
        app = QApplication.instance()
        if isinstance(app, QApplication):
            app.quit()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self._closing:
            super().closeEvent(event)
            return
        self._closing = True
        repositories = list(self._sessions)
        for session in tuple(self._sessions.values()):
            session.shutdown()
        self._sessions.clear()
        self._workspace.save_open_repositories(repositories)
        super().closeEvent(event)
