from __future__ import annotations

from PySide6.QtCore import QByteArray, QSettings, Qt
from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QMainWindow,
    QPlainTextEdit,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
)

from mygitclient.theme import Theme, apply_theme


class MainWindow(QMainWindow):
    def __init__(self, settings: QSettings, theme: Theme) -> None:
        super().__init__()
        self._settings = settings
        self._theme = theme
        self.setWindowTitle("MyGitClient")
        self.resize(1180, 760)
        self._build_ui()
        self._build_menu()
        self._restore_window_state()

    def _build_ui(self) -> None:
        repositories = QTreeWidget()
        repositories.setHeaderLabel("Repositories")
        QTreeWidgetItem(repositories, ["Open a repository to get started"])

        welcome = QPlainTextEdit()
        welcome.setReadOnly(True)
        welcome.setPlainText(
            "Welcome to MyGitClient\n\n"
            "The Git repository workspace will appear here in the next milestone."
        )

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(repositories)
        splitter.addWidget(welcome)
        splitter.setSizes([280, 900])
        self.setCentralWidget(splitter)
        self.statusBar().addWidget(QLabel("Ready"))

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        exit_action = QAction("E&xit", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        view_menu = self.menuBar().addMenu("&View")
        theme_menu = view_menu.addMenu("Theme")
        for theme in Theme:
            action = QAction(theme.value.title(), self)
            action.setCheckable(True)
            action.setChecked(theme is self._theme)
            action.triggered.connect(lambda checked=False, value=theme: self._set_theme(value))
            theme_menu.addAction(action)

    def _set_theme(self, theme: Theme) -> None:
        self._theme = theme
        self._settings.setValue("appearance/theme", theme.value)
        app = QApplication.instance()
        if isinstance(app, QApplication):
            apply_theme(app, theme)
        theme_names = {item.value for item in Theme}
        for action in self.menuBar().findChildren(QAction):
            if action.parent() is not None and action.text().lower() in theme_names:
                action.setChecked(action.text().lower() == theme.value)

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
