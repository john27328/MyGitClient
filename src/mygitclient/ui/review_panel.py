from __future__ import annotations

from PySide6.QtCore import QDateTime, QSignalBlocker, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from mygitclient.git.models import CommitFileChange, CommitSummary
from mygitclient.workspace.reviews import ReviewSession


class ReviewPanel(QWidget):
    """The local self-review navigator; Git orchestration remains in MainWindow."""

    start_requested = Signal()
    delete_requested = Signal(object)
    session_selected = Signal(object)
    file_selected = Signal(object)
    mark_file_requested = Signal()
    boundary_selected = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("reviewPanel")
        self._session: ReviewSession | None = None
        self._files: tuple[CommitFileChange, ...] = ()
        self._states: dict[str, tuple[int, int]] = {}
        self._expanded_groups = {"Needs review", "Reviewed"}

        self.start_button = QPushButton("Start review")
        self.start_button.setObjectName("startReviewButton")
        self.start_button.clicked.connect(self.start_requested)
        self.delete_button = QPushButton("Delete")
        self.delete_button.setObjectName("deleteReviewButton")
        self.delete_button.setEnabled(False)
        self.delete_button.clicked.connect(self._delete_current)

        sessions_header = QHBoxLayout()
        sessions_header.addWidget(self.start_button, 1)
        sessions_header.addWidget(self.delete_button)
        self.sessions = QTreeWidget()
        self.sessions.setObjectName("reviewSessionsTree")
        self.sessions.setHeaderLabels(["Started reviews"])
        self.sessions.setRootIsDecorated(False)
        self.sessions.currentItemChanged.connect(self._session_changed)

        sessions_container = QWidget()
        sessions_layout = QVBoxLayout(sessions_container)
        sessions_layout.setContentsMargins(0, 0, 0, 0)
        sessions_layout.addLayout(sessions_header)
        sessions_layout.addWidget(self.sessions, 1)

        self.context = QLabel("Mark each file reviewed. Any later change returns it to review.")
        self.context.setObjectName("reviewContextLabel")
        self.context.setWordWrap(True)
        self.context.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self.boundary_label = QLabel("Start reviewing from:")
        self.boundary_label.setObjectName("reviewBoundaryLabel")
        self.boundary_combo = QComboBox()
        self.boundary_combo.setObjectName("reviewBoundaryCombo")
        self.boundary_combo.currentIndexChanged.connect(self._boundary_changed)
        self.boundary_label.hide()
        self.boundary_combo.hide()
        boundary_layout = QHBoxLayout()
        boundary_layout.setContentsMargins(0, 0, 0, 0)
        boundary_layout.addWidget(self.boundary_label)
        boundary_layout.addWidget(self.boundary_combo, 1)

        self.files = QTreeWidget()
        self.files.setObjectName("reviewFilesTree")
        self.files.setHeaderLabels(["Review state", "File"])
        self.files.setColumnWidth(0, 150)
        self.files.setRootIsDecorated(True)
        self.files.currentItemChanged.connect(self._file_changed)
        self.files.itemExpanded.connect(self._group_expanded)
        self.files.itemCollapsed.connect(self._group_collapsed)

        self.mark_file_button = QPushButton("Mark file reviewed")
        self.mark_file_button.setObjectName("markReviewFileButton")
        self.mark_file_button.setEnabled(False)
        self.mark_file_button.clicked.connect(self.mark_file_requested)

        files_container = QWidget()
        files_layout = QVBoxLayout(files_container)
        files_layout.setContentsMargins(0, 0, 0, 0)
        files_layout.addWidget(self.context)
        files_layout.addLayout(boundary_layout)
        files_layout.addWidget(self.files, 1)
        files_layout.addWidget(self.mark_file_button)

        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.splitter.setObjectName("reviewSplitter")
        self.splitter.addWidget(sessions_container)
        self.splitter.addWidget(files_container)
        self.splitter.setStretchFactor(0, 2)
        self.splitter.setStretchFactor(1, 3)
        self.splitter.setSizes([190, 470])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.splitter)

    @property
    def selected_session(self) -> ReviewSession | None:
        return self._session

    @property
    def selected_file(self) -> CommitFileChange | None:
        item = self.files.currentItem()
        if item is None:
            return None
        value = item.data(0, Qt.ItemDataRole.UserRole)
        return value if isinstance(value, CommitFileChange) else None

    def show_sessions(self, sessions: tuple[ReviewSession, ...]) -> None:
        selected_key = self._session.key if self._session is not None else ""
        self.sessions.clear()
        selected_item: QTreeWidgetItem | None = None
        for session in sessions:
            timestamp = QDateTime.fromString(session.start_at, Qt.DateFormat.ISODate)
            started = (
                timestamp.toLocalTime().toString("dd.MM.yyyy HH:mm")
                if timestamp.isValid()
                else ""
            )
            details = " · ".join(
                part for part in (session.branch, session.displayed_start_oid[:8], started) if part
            )
            item = QTreeWidgetItem([details])
            item.setData(0, Qt.ItemDataRole.UserRole, session)
            item.setToolTip(
                0, f"From {session.displayed_start_oid[:8]} · {started} · {session.base_subject}"
            )
            self.sessions.addTopLevelItem(item)
            if session.key == selected_key:
                selected_item = item
        if selected_item is not None:
            self.sessions.setCurrentItem(selected_item)

    def select_session(self, session: ReviewSession) -> None:
        for index in range(self.sessions.topLevelItemCount()):
            item = self.sessions.topLevelItem(index)
            if item is not None and item.data(0, Qt.ItemDataRole.UserRole) == session:
                self.sessions.setCurrentItem(item)
                return

    def show_files(self, session: ReviewSession, files: tuple[CommitFileChange, ...]) -> None:
        if self._session != session:
            return
        self._files = files
        paths = {change.path for change in files}
        self._states = {path: state for path, state in self._states.items() if path in paths}
        self._render_files()

    def update_file_state(self, path: str, total: int, checked: int) -> None:
        self._states[path] = (total, checked)
        self._render_files()

    def set_mark_file_enabled(self, enabled: bool) -> None:
        self.mark_file_button.setEnabled(enabled)

    def show_boundaries(
        self, commits: tuple[CommitSummary, ...], selected_oid: str
    ) -> None:
        blocker = QSignalBlocker(self.boundary_combo)
        self.boundary_combo.clear()
        for commit in commits:
            timestamp = QDateTime.fromString(commit.authored_at, Qt.DateFormat.ISODate)
            label = f"{timestamp.toLocalTime().toString('dd.MM.yyyy HH:mm')} · {commit.subject}"
            self.boundary_combo.addItem(label, commit)
        selected_index = next(
            (index for index, commit in enumerate(commits) if commit.oid == selected_oid),
            0,
        )
        self.boundary_combo.setCurrentIndex(selected_index)
        del blocker
        visible = bool(commits)
        self.boundary_label.setVisible(visible)
        self.boundary_combo.setVisible(visible)

    def clear_boundaries(self) -> None:
        blocker = QSignalBlocker(self.boundary_combo)
        self.boundary_combo.clear()
        del blocker
        self.boundary_label.hide()
        self.boundary_combo.hide()

    @Slot(QTreeWidgetItem, QTreeWidgetItem)
    def _session_changed(
        self, current: QTreeWidgetItem | None, _previous: QTreeWidgetItem | None
    ) -> None:
        value = current.data(0, Qt.ItemDataRole.UserRole) if current is not None else None
        self._session = value if isinstance(value, ReviewSession) else None
        self.delete_button.setEnabled(self._session is not None)
        self._files = ()
        self._states.clear()
        self.files.clear()
        self.mark_file_button.setEnabled(False)
        if self._session is not None:
            self.context.setText(
                f"{self._session.branch} from {self._session.displayed_start_oid[:8]} · "
                f"{self._session.base_subject}"
            )
            self.session_selected.emit(self._session)
        else:
            self.clear_boundaries()
            self.context.setText(
                "Mark each file reviewed. Any later change returns it to review."
            )

    @Slot(QTreeWidgetItem, QTreeWidgetItem)
    def _file_changed(
        self, current: QTreeWidgetItem | None, _previous: QTreeWidgetItem | None
    ) -> None:
        value = current.data(0, Qt.ItemDataRole.UserRole) if current is not None else None
        if isinstance(value, CommitFileChange):
            self.file_selected.emit(value)

    @Slot(int)
    def _boundary_changed(self, index: int) -> None:
        value = self.boundary_combo.itemData(index)
        if isinstance(value, CommitSummary):
            self.boundary_selected.emit(value)

    @Slot()
    def _delete_current(self) -> None:
        if self._session is not None:
            self.delete_requested.emit(self._session)

    @Slot(QTreeWidgetItem)
    def _group_expanded(self, item: QTreeWidgetItem) -> None:
        if item.parent() is None:
            self._expanded_groups.add(item.text(0))

    @Slot(QTreeWidgetItem)
    def _group_collapsed(self, item: QTreeWidgetItem) -> None:
        if item.parent() is None:
            self._expanded_groups.discard(item.text(0))

    def _render_files(self) -> None:
        selected_path = self.selected_file.path if self.selected_file is not None else ""
        self.files.clear()
        pending: list[CommitFileChange] = []
        reviewed: list[CommitFileChange] = []
        for change in self._files:
            total, checked = self._states.get(change.path, (0, 0))
            (reviewed if total > 0 and total == checked else pending).append(change)
        for _title, values in (("Needs review", pending), ("Reviewed", reviewed)):
            group = QTreeWidgetItem([_title, str(len(values))])
            group.setFirstColumnSpanned(True)
            self.files.addTopLevelItem(group)
            group.setExpanded(_title in self._expanded_groups)
            for change in values:
                total, checked = self._states.get(change.path, (0, 0))
                state = f"✓ {checked}/{total}" if total else "Needs review"
                item = QTreeWidgetItem([state, change.path])
                item.setData(0, Qt.ItemDataRole.UserRole, change)
                item.setToolTip(1, change.original_path or change.path)
                group.addChild(item)
                if change.path == selected_path:
                    self.files.setCurrentItem(item)
