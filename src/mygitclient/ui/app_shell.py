from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings, Qt, Slot
from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtWidgets import (
    QFileDialog,
    QMainWindow,
    QMenu,
    QMessageBox,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
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
        controller.hide()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        for toolbar in controller.findChildren(
            QToolBar, options=Qt.FindChildOption.FindDirectChildrenOnly
        ):
            controller.removeToolBar(toolbar)
            toolbar.setParent(self)
            layout.addWidget(toolbar)
        central = controller.takeCentralWidget()
        layout.addWidget(central, 1)

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
        self._closing = False

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
            session.shutdown()
            session.deleteLater()
        self._workspace.save_open_repositories(list(self._sessions))
        self._refresh_home()

    @Slot(int)
    def _current_tab_changed(self, index: int) -> None:
        widget = self.tabs.widget(index)
        repository = next(
            (path for path, session in self._sessions.items() if session is widget),
            None,
        )
        self.setWindowTitle(
            "MyGitClient" if repository is None else f"{repository.name} — MyGitClient"
        )

        self._rebuild_menu_bar()

    def _rebuild_menu_bar(self) -> None:
        if not hasattr(self, "_file_menu"):
            return
        menu_bar = self.menuBar()
        menu_bar.clear()
        menu_bar.addMenu(self._file_menu)
        current = self.tabs.currentWidget()
        if not isinstance(current, RepositorySessionTab):
            return
        for action in current.controller.menuBar().actions():
            if action.text().replace("&", "") != "File":
                menu_bar.addAction(action)

    def _refresh_home(self) -> None:
        self.home.set_recent(self._workspace.recent_repositories())
        self.home.set_workspaces(self._workspace.named_workspaces())

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
