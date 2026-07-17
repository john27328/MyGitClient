from __future__ import annotations

from PySide6.QtCore import QDateTime, Qt, Signal
from PySide6.QtWidgets import QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from mygitclient.git.models import CommitPage, CommitSummary
from mygitclient.ui.commit_graph import GRAPH_ROLE, CommitGraphDelegate, CommitGraphRow


class HistoryPanel(QWidget):
    load_more_requested = Signal()

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

        self.load_more_button = QPushButton("Load more")
        self.load_more_button.setObjectName("historyLoadMoreButton")
        self.load_more_button.clicked.connect(self.load_more_requested)
        self.load_more_button.hide()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.tree)
        layout.addWidget(self.load_more_button)

    @property
    def commit_count(self) -> int:
        return self.tree.topLevelItemCount()

    def reset(self) -> None:
        self.tree.clear()
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
