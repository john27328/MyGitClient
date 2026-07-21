from __future__ import annotations

from typing import cast

from PySide6.QtCore import QDateTime, QModelIndex, QPersistentModelIndex, Qt, Signal, Slot
from PySide6.QtGui import QColor, QKeySequence, QPainter, QShortcut
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
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
    RefComparisonSnapshot,
)
from mygitclient.ui.commit_graph import GRAPH_ROLE, CommitGraphDelegate, CommitGraphRow
from mygitclient.ui.refs_panel import RefsPanel

FILTER_HIGHLIGHT_ROLE = int(Qt.ItemDataRole.UserRole) + 3


class FilterHighlightDelegate(QStyledItemDelegate):
    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        query = index.data(FILTER_HIGHLIGHT_ROLE)
        if not isinstance(query, str) or not query:
            super().paint(painter, option, index)
            return
        styled = QStyleOptionViewItem(option)
        self.initStyleOption(styled, index)
        text = styled.text
        start = text.casefold().find(query.casefold())
        if start < 0:
            super().paint(painter, option, index)
            return
        styled.text = ""
        style = styled.widget.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, styled, painter, styled.widget)
        text_rect = style.subElementRect(
            QStyle.SubElement.SE_ItemViewItemText, styled, styled.widget
        )
        metrics = styled.fontMetrics
        baseline = (
            text_rect.top()
            + (text_rect.height() + metrics.ascent() - metrics.descent()) // 2
        )
        before = text[:start]
        match = text[start : start + len(query)]
        x = text_rect.left()
        match_x = x + metrics.horizontalAdvance(before)
        match_width = metrics.horizontalAdvance(match)
        painter.save()
        painter.setClipRect(text_rect)
        painter.fillRect(
            match_x, text_rect.top(), match_width, text_rect.height(), QColor(255, 210, 70, 150)
        )
        painter.setFont(styled.font)
        painter.setPen(styled.palette.color(styled.palette.ColorRole.Text))
        painter.drawText(x, baseline, text)
        painter.restore()


class HistoryPanel(QWidget):
    load_more_requested = Signal()
    commit_selected = Signal(object)
    file_selected = Signal(object, object)
    comparison_file_selected = Signal(str, str, object)

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
        for column in (1, 2, 4):
            self.tree.setItemDelegateForColumn(column, FilterHighlightDelegate(self.tree))
        self.tree.currentItemChanged.connect(self._commit_changed)

        self.filter_edit = QLineEdit()
        self.filter_edit.setObjectName("historyFilterEdit")
        self.filter_edit.setPlaceholderText("Filter history…")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.textChanged.connect(self._apply_filter)
        self.filter_count = QLabel("0 commits")
        self.filter_count.setObjectName("historyFilterCount")
        clear_shortcut = QShortcut(QKeySequence.StandardKey.Cancel, self.filter_edit)
        clear_shortcut.activated.connect(self.filter_edit.clear)

        self.load_more_button = QPushButton("Load more")
        self.load_more_button.setObjectName("historyLoadMoreButton")
        self.load_more_button.clicked.connect(self.load_more_requested)
        self.load_more_button.hide()

        history_list = QWidget()
        history_layout = QVBoxLayout(history_list)
        history_layout.setContentsMargins(0, 0, 0, 0)
        filter_layout = QHBoxLayout()
        filter_layout.addWidget(self.filter_edit, 1)
        filter_layout.addWidget(self.filter_count)
        history_layout.addLayout(filter_layout)
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
        self._comparison_refs: tuple[str, str] | None = None
        details_layout = QVBoxLayout(self.details)
        details_layout.setContentsMargins(8, 0, 0, 0)
        details_layout.addWidget(self.details_label)
        details_layout.addWidget(self.files, 1)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setObjectName("historySplitter")
        self.refs_panel = RefsPanel()
        self.splitter.addWidget(self.refs_panel)
        self.splitter.addWidget(history_list)
        self.splitter.addWidget(self.details)
        self.splitter.setSizes([240, 700, 360])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.splitter)

    @property
    def commit_count(self) -> int:
        return self.tree.topLevelItemCount()

    def reset(self) -> None:
        self.refs_panel.reset()
        self.clear_commits()

    def clear_commits(self) -> None:
        self.filter_edit.clear()
        self.tree.clear()
        self.files.clear()
        self.details_label.setText("Select a commit to view its details.")
        self._comparison_refs = None
        self.load_more_button.hide()
        self._update_filter_count()

    def set_loading(self, loading: bool) -> None:
        self.load_more_button.setEnabled(not loading)

    def show_page(self, page: CommitPage) -> None:
        if page.offset == 0:
            self.tree.clear()
        for commit in page.commits:
            self._append_commit(commit)
        self._render_graph()
        self._apply_filter(self.filter_edit.text())
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

    def show_comparison(self, snapshot: RefComparisonSnapshot) -> None:
        self._comparison_refs = (snapshot.base_ref, snapshot.compare_ref)
        self.tree.clearSelection()
        self.files.clear()
        self.details_label.setText(
            f"Comparing {snapshot.base_ref} → {snapshot.compare_ref}\n\n"
            f"{len(snapshot.files)} changed file(s). Select a file to view its diff."
        )
        for change in snapshot.files:
            item = QTreeWidgetItem([change.status, change.path])
            item.setData(0, Qt.ItemDataRole.UserRole, change)
            if change.original_path is not None:
                item.setToolTip(1, f"Renamed from {change.original_path}")
            self.files.addTopLevelItem(item)
        self.files.resizeColumnToContents(0)

    def clear_comparison(self) -> None:
        self._comparison_refs = None
        self.files.clear()
        self.details_label.setText("Select a commit to view its details.")

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
        self._comparison_refs = None
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
        if current is None:
            return
        change = current.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(change, CommitFileChange):
            return
        if self._comparison_refs is not None:
            base_ref, compare_ref = self._comparison_refs
            self.comparison_file_selected.emit(base_ref, compare_ref, change)
            return
        commit = self.selected_commit
        if commit is not None:
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

    @Slot(str)
    def _apply_filter(self, text: str) -> None:
        query = text.strip().casefold()
        self.tree.setColumnHidden(0, bool(query))
        for row in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(row)
            if item is None:
                continue
            commit = item.data(0, Qt.ItemDataRole.UserRole)
            if not isinstance(commit, CommitSummary):
                continue
            searchable = " ".join(
                (commit.subject, commit.author_name, commit.author_email, commit.oid)
            ).casefold()
            item.setHidden(bool(query) and query not in searchable)
            for column in (1, 2, 4):
                visible_text = item.text(column)
                highlighted = query if query and query in visible_text.casefold() else None
                item.setData(column, FILTER_HIGHLIGHT_ROLE, highlighted)
        self._update_filter_count()

    def _update_filter_count(self) -> None:
        total = self.tree.topLevelItemCount()
        visible = 0
        for row in range(total):
            item = self.tree.topLevelItem(row)
            if item is not None and not item.isHidden():
                visible += 1
        self.filter_count.setText(
            f"{visible} of {total} commits" if visible != total else f"{total} commits"
        )

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
