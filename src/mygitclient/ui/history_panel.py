from __future__ import annotations

from typing import cast

from PySide6.QtCore import QDateTime, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QLabel,
    QPushButton,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from mygitclient.git.models import (
    CommitFileChange,
    CommitFilesSnapshot,
    CommitPage,
    CommitSummary,
)
from mygitclient.ui.commit_graph import GRAPH_ROLE, CommitGraphDelegate, CommitGraphRow


class HistoryPanel(QWidget):
    load_more_requested = Signal()
    commit_selected = Signal(object)
    file_selected = Signal(object, object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.tree = QTreeWidget()
        self.tree.setObjectName("historyTree")
        self.tree.setHeaderLabels(["Graph", "Description", "Author", "Date", "Commit"])
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        for column, width in enumerate((60, 360, 150, 190, 90)):
            self.tree.setColumnWidth(column, width)
        self.tree.setItemDelegateForColumn(0, CommitGraphDelegate(self.tree))
        self.tree.currentItemChanged.connect(self._commit_changed)

        self.load_more_button = QPushButton("Load more")
        self.load_more_button.setObjectName("historyLoadMoreButton")
        self.load_more_button.clicked.connect(self.load_more_requested)
        self.load_more_button.hide()

        history_list = QWidget()
        history_layout = QVBoxLayout(history_list)
        history_layout.setContentsMargins(0, 0, 0, 0)
        history_layout.addWidget(self.tree)
        history_layout.addWidget(self.load_more_button)

        self.details = QWidget()
        self.details.setObjectName("commitDetailsPanel")
        self.details_label = QLabel("Select a commit to view its details.")
        self.details_label.setObjectName("commitDetailsLabel")
        self.details_label.setWordWrap(True)
        self.details_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.files = QTreeWidget()
        self.files.setObjectName("commitFilesTree")
        self.files.setHeaderLabels(["Status", "File"])
        self.files.setColumnWidth(0, 80)
        self.files.currentItemChanged.connect(self._file_changed)
        details_layout = QVBoxLayout(self.details)
        details_layout.setContentsMargins(8, 0, 0, 0)
        details_layout.addWidget(self.details_label)
        details_layout.addWidget(self.files, 1)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setObjectName("historySplitter")
        self.splitter.addWidget(history_list)
        self.splitter.addWidget(self.details)
        self.splitter.setSizes([700, 360])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.splitter)

    @property
    def commit_count(self) -> int:
        return self.tree.topLevelItemCount()

    def reset(self) -> None:
        self.tree.clear()
        self.files.clear()
        self.details_label.setText("Select a commit to view its details.")
        self.load_more_button.hide()

    def set_loading(self, loading: bool) -> None:
        self.load_more_button.setEnabled(not loading)

    def show_page(self, page: CommitPage) -> None:
        if page.offset == 0:
            self.tree.clear()
        for commit in page.commits:
            self._append_commit(commit)
        self._render_graph()
        self.load_more_button.setVisible(page.has_more)
        self.load_more_button.setEnabled(True)

    def set_expanded_layout(self, expanded: bool) -> None:
        header = self.tree.header()
        header.setStretchLastSection(False)
        mode = header.ResizeMode.Stretch if expanded else header.ResizeMode.Interactive
        header.setSectionResizeMode(1, mode)

    def show_files(self, snapshot: CommitFilesSnapshot) -> None:
        commit = self.selected_commit
        if commit is None or commit.oid != snapshot.commit_oid:
            return
        self.files.clear()
        for change in snapshot.files:
            item = QTreeWidgetItem([change.status, change.path])
            item.setData(0, Qt.ItemDataRole.UserRole, change)
            if change.original_path is not None:
                item.setToolTip(1, f"Renamed from {change.original_path}")
            self.files.addTopLevelItem(item)
        self.files.resizeColumnToContents(0)

    @property
    def selected_commit(self) -> CommitSummary | None:
        item = cast(QTreeWidgetItem | None, self.tree.currentItem())
        if item is None:
            return None
        value = item.data(0, Qt.ItemDataRole.UserRole)
        return value if isinstance(value, CommitSummary) else None

    @Slot(QTreeWidgetItem, QTreeWidgetItem)
    def _commit_changed(
        self, current: QTreeWidgetItem | None, _previous: QTreeWidgetItem | None
    ) -> None:
        if current is None:
            return
        commit = current.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(commit, CommitSummary):
            return
        parents = ", ".join(parent[:8] for parent in commit.parent_oids) or "None (root)"
        self.details_label.setText(
            f"{commit.subject}\n\n"
            f"Commit: {commit.oid}\n"
            f"Author: {commit.author_name} <{commit.author_email}>\n"
            f"Date: {commit.authored_at}\n"
            f"Parents: {parents}"
        )
        self.files.clear()
        self.commit_selected.emit(commit)

    @Slot(QTreeWidgetItem, QTreeWidgetItem)
    def _file_changed(
        self, current: QTreeWidgetItem | None, _previous: QTreeWidgetItem | None
    ) -> None:
        commit = self.selected_commit
        if current is None or commit is None:
            return
        change = current.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(change, CommitFileChange):
            self.file_selected.emit(commit, change)

    def _append_commit(self, commit: CommitSummary) -> None:
        authored_at = QDateTime.fromString(commit.authored_at, Qt.DateFormat.ISODate)
        display_date = (
            authored_at.toLocalTime().toString("dd.MM.yyyy HH:mm")
            if authored_at.isValid()
            else commit.authored_at
        )
        item = QTreeWidgetItem(
            ["", commit.subject, commit.author_name, display_date, commit.oid[:8]]
        )
        item.setData(0, Qt.ItemDataRole.UserRole, commit)
        item.setToolTip(1, commit.subject)
        item.setToolTip(2, f"{commit.author_name} <{commit.author_email}>")
        item.setToolTip(4, commit.oid)
        self.tree.addTopLevelItem(item)

    def _render_graph(self) -> None:
        lanes: list[str] = []
        widest = 1
        for row in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(row)
            if item is None:
                continue
            commit = item.data(0, Qt.ItemDataRole.UserRole)
            if not isinstance(commit, CommitSummary):
                continue
            try:
                lane = lanes.index(commit.oid)
            except ValueError:
                lane = 0
                lanes.insert(0, commit.oid)
            before = tuple(lanes)
            lanes.pop(lane)
            for parent in reversed(commit.parent_oids):
                if parent not in lanes:
                    lanes.insert(lane, parent)
            parent_lanes = tuple(lanes.index(parent) for parent in commit.parent_oids)
            item.setData(
                0, GRAPH_ROLE, CommitGraphRow(before, tuple(lanes), lane, parent_lanes)
            )
            widest = max(widest, len(before), len(lanes))
        width = max(60, widest * CommitGraphDelegate.lane_width + 16)
        self.tree.setColumnWidth(0, width)
