from __future__ import annotations

import hashlib
from typing import cast

from PySide6.QtCore import (
    QByteArray,
    QDateTime,
    QModelIndex,
    QPersistentModelIndex,
    QPoint,
    QSettings,
    Qt,
    Signal,
    Slot,
)
from PySide6.QtGui import QBrush, QColor, QKeySequence, QPainter, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QColorDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
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
    BranchesSnapshot,
    BranchPointSnapshot,
    CommitFileChange,
    CommitFilesSnapshot,
    CommitPage,
    CommitSummary,
    RefComparisonSnapshot,
    TagsSnapshot,
)
from mygitclient.ui.commit_graph import GRAPH_ROLE, CommitGraphDelegate, CommitGraphRow
from mygitclient.ui.refs_panel import RefsPanel

FILTER_HIGHLIGHT_ROLE = int(Qt.ItemDataRole.UserRole) + 3
BADGES_ROLE = int(Qt.ItemDataRole.UserRole) + 4


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


class RefBadgesDelegate(QStyledItemDelegate):
    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        styled = QStyleOptionViewItem(option)
        self.initStyleOption(styled, index)
        raw_badges = index.data(BADGES_ROLE)
        styled.text = ""
        style = styled.widget.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, styled, painter, styled.widget)
        if not isinstance(raw_badges, tuple):
            return
        badges = cast(tuple[object, ...], raw_badges)
        dark = styled.palette.base().color().lightness() < 128
        colors = {
            "local": ("#204f7a", "#d8ebff") if dark else ("#d8ebff", "#174f7a"),
            "remote": ("#49336f", "#eadcff") if dark else ("#eadcff", "#57358a"),
            "tag": ("#655019", "#ffedaa") if dark else ("#fff0b8", "#6d5200"),
            "fork": ("#653f18", "#ffd8a8") if dark else ("#ffe1bd", "#79420d"),
        }
        metrics = styled.fontMetrics
        x = styled.rect.left() + 4
        height = min(styled.rect.height() - 4, metrics.height() + 4)
        y = styled.rect.top() + (styled.rect.height() - height) // 2
        painter.save()
        painter.setClipRect(styled.rect)
        for raw_badge in badges:
            if not isinstance(raw_badge, tuple):
                continue
            badge = cast(tuple[object, ...], raw_badge)
            if len(badge) != 2:
                continue
            kind, label = badge
            if not isinstance(kind, str) or not isinstance(label, str):
                continue
            width = metrics.horizontalAdvance(label) + 14
            background, foreground = colors.get(kind, colors["local"])
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(background))
            painter.drawRoundedRect(x, y, width, height, 5, 5)
            painter.setPen(QColor(foreground))
            painter.drawText(x + 7, y, width - 14, height, Qt.AlignmentFlag.AlignCenter, label)
            x += width + 4
        painter.restore()


class HistoryPanel(QWidget):
    load_more_requested = Signal()
    commit_selected = Signal(object)
    file_selected = Signal(object, object)
    comparison_file_selected = Signal(str, str, object)
    focus_mode_changed = Signal(bool)
    cherry_pick_requested = Signal(object)
    revert_requested = Signal(object)

    def __init__(
        self,
        settings: QSettings | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self.tree = QTreeWidget()
        self.tree.setObjectName("historyTree")
        self.tree.setHeaderLabels(
            ["Graph", "Refs", "Description", "Author", "Date", "Commit"]
        )
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_commit_context_menu)
        self.tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        for column, width in enumerate((60, 230, 360, 150, 190, 90)):
            self.tree.setColumnWidth(column, width)
        for column in (4, 5):
            self.tree.setColumnHidden(column, True)
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(2, self.tree.header().ResizeMode.Stretch)
        self.tree.setItemDelegateForColumn(0, CommitGraphDelegate(self.tree))
        self.tree.setItemDelegateForColumn(1, RefBadgesDelegate(self.tree))
        for column in (2, 3, 5):
            self.tree.setItemDelegateForColumn(column, FilterHighlightDelegate(self.tree))
        self.tree.currentItemChanged.connect(self._commit_changed)

        self.filter_edit = QLineEdit()
        self.filter_edit.setObjectName("historyFilterEdit")
        self.filter_edit.setPlaceholderText("Filter history…")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.textChanged.connect(self._apply_filter)
        self.filter_count = QLabel("0 commits")
        self.filter_count.setObjectName("historyFilterCount")
        self.focus_button = QPushButton("Focus on diff")
        self.focus_button.setObjectName("historyFocusDiffButton")
        self.focus_button.setCheckable(True)
        self.focus_button.setToolTip("Hide refs and give more space to the diff")
        self.focus_button.toggled.connect(self._focus_mode_toggled)
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
        filter_layout.addWidget(self.focus_button)
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
        self._branch_labels: dict[str, list[tuple[str, str]]] = {}
        self._tag_labels: dict[str, list[tuple[str, str]]] = {}
        self._branch_point: BranchPointSnapshot | None = None
        details_layout = QVBoxLayout(self.details)
        details_layout.setContentsMargins(0, 8, 0, 0)
        details_layout.addWidget(self.details_label)
        details_layout.addWidget(self.files, 1)

        self.content_splitter = QSplitter(Qt.Orientation.Vertical)
        self.content_splitter.setObjectName("historyContentSplitter")
        self.content_splitter.addWidget(history_list)
        self.content_splitter.addWidget(self.details)
        self.content_splitter.setStretchFactor(0, 3)
        self.content_splitter.setStretchFactor(1, 2)
        self.content_splitter.setSizes([520, 280])

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setObjectName("historySplitter")
        self.refs_panel = RefsPanel()
        self.splitter.addWidget(self.refs_panel)
        self.splitter.addWidget(self.content_splitter)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([250, 620])
        self.splitter.splitterMoved.connect(self._save_splitter_states)
        self.content_splitter.splitterMoved.connect(self._save_splitter_states)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.splitter)
        self._restore_layout()

    @property
    def commit_count(self) -> int:
        return self.tree.topLevelItemCount()

    def reset(self) -> None:
        self._branch_labels.clear()
        self._tag_labels.clear()
        self._branch_point = None
        self.refs_panel.reset()
        self.clear_commits()

    def show_branches(self, snapshot: BranchesSnapshot) -> None:
        self.refs_panel.show_branches(snapshot)
        self._branch_labels = {}
        self._branch_point = None
        for branch in snapshot.branches:
            kind = "remote" if branch.remote else "local"
            self._branch_labels.setdefault(branch.oid, []).append((kind, branch.name))
        self._refresh_commit_labels()

    def show_tags(self, snapshot: TagsSnapshot) -> None:
        self.refs_panel.show_tags(snapshot)
        self._tag_labels = {}
        for tag in snapshot.tags:
            self._tag_labels.setdefault(tag.commit_oid, []).append(("tag", tag.name))
        self._refresh_commit_labels()

    def show_branch_point(self, snapshot: BranchPointSnapshot) -> None:
        self._branch_point = snapshot
        self._refresh_commit_labels()

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
        header.setSectionResizeMode(2, mode)

    @property
    def focus_mode(self) -> bool:
        return self.focus_button.isChecked()

    @Slot(bool)
    def _focus_mode_toggled(self, focused: bool) -> None:
        self.refs_panel.setVisible(not focused)
        self.focus_button.setText("Show navigation" if focused else "Focus on diff")
        if self._settings is not None:
            self._settings.setValue("history/focusDiff", focused)
        self.focus_mode_changed.emit(focused)

    @Slot(int, int)
    def _save_splitter_states(self, _position: int, _index: int) -> None:
        if self._settings is None:
            return
        if self.refs_panel.isVisible():
            self._settings.setValue("history/splitterState", self.splitter.saveState())
        self._settings.setValue(
            "history/contentSplitterState", self.content_splitter.saveState()
        )

    def _restore_layout(self) -> None:
        if self._settings is None:
            return
        splitter_state = self._settings.value("history/splitterState")
        content_state = self._settings.value("history/contentSplitterState")
        if isinstance(splitter_state, QByteArray):
            self.splitter.restoreState(splitter_state)
        if isinstance(content_state, QByteArray):
            self.content_splitter.restoreState(content_state)
        focused = self._settings.value("history/focusDiff", False)
        self.focus_button.setChecked(
            focused is True or focused == "true" or focused == 1
        )

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

    @property
    def selected_commits(self) -> tuple[CommitSummary, ...]:
        rows: list[tuple[int, CommitSummary]] = []
        for item in self.tree.selectedItems():
            value = item.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(value, CommitSummary):
                rows.append((self.tree.indexOfTopLevelItem(item), value))
        rows.sort(key=lambda entry: entry[0], reverse=True)
        return tuple(commit for _row, commit in rows)

    @Slot(QPoint)
    def _show_commit_context_menu(self, position: QPoint) -> None:
        item = self.tree.itemAt(position)
        if item is not None and not item.isSelected():
            self.tree.clearSelection()
            self.tree.setCurrentItem(item)
            item.setSelected(True)
        commits = self.selected_commits
        if not commits:
            return
        menu = QMenu(self.tree)
        label = (
            "Cherry-pick commit…"
            if len(commits) == 1
            else f"Cherry-pick {len(commits)} commits…"
        )
        action = menu.addAction(label)
        action.setObjectName("historyCherryPickAction")
        action.setEnabled(all(len(commit.parent_oids) <= 1 for commit in commits))
        revert_label = (
            "Revert commit…"
            if len(commits) == 1
            else f"Revert {len(commits)} commits…"
        )
        revert_action = menu.addAction(revert_label)
        revert_action.setObjectName("historyRevertAction")
        revert_action.setEnabled(
            all(len(commit.parent_oids) <= 1 for commit in commits)
        )
        menu.addSeparator()
        author = commits[0]
        author_menu = menu.addMenu(f"Author: {author.author_name}")
        color_action = author_menu.addAction("Set color...")
        color_action.setObjectName("historySetAuthorColorAction")
        clear_color_action = author_menu.addAction("Clear color")
        clear_color_action.setObjectName("historyClearAuthorColorAction")
        clear_color_action.setEnabled(self._author_color(author) is not None)
        chosen = menu.exec(self.tree.viewport().mapToGlobal(position))
        if chosen is action:
            self.cherry_pick_requested.emit(commits)
        elif chosen is revert_action:
            self.revert_requested.emit(tuple(reversed(commits)))
        elif chosen is color_action:
            initial = self._author_color(author) or self.palette().highlight().color()
            color = QColorDialog.getColor(
                initial, self, f"Color for {author.author_name}"
            )
            if color.isValid():
                self._set_author_color(author, color)
        elif chosen is clear_color_action:
            self._set_author_color(author, None)

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
            ["", "", commit.subject, commit.author_name, display_date, commit.oid[:8]]
        )
        item.setData(0, Qt.ItemDataRole.UserRole, commit)
        item.setToolTip(2, commit.subject)
        item.setToolTip(3, f"{commit.author_name} <{commit.author_email}>")
        item.setToolTip(5, commit.oid)
        self.tree.addTopLevelItem(item)
        self._decorate_commit_item(item, commit)

    def _refresh_commit_labels(self) -> None:
        for row in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(row)
            if item is None:
                continue
            commit = item.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(commit, CommitSummary):
                self._decorate_commit_item(item, commit)
        self._apply_filter(self.filter_edit.text())

    def _decorate_commit_item(self, item: QTreeWidgetItem, commit: CommitSummary) -> None:
        badges = list(self._branch_labels.get(commit.oid, ()))
        badges.extend(self._tag_labels.get(commit.oid, ()))
        point = self._branch_point
        if point is not None and point.commit_oid == commit.oid:
            base = point.base_ref.removeprefix("refs/heads/")
            badges.append(("fork", f"from {base}"))
        item.setText(1, " · ".join(label for _kind, label in badges))
        item.setData(1, BADGES_ROLE, tuple(badges))
        item.setText(2, commit.subject)
        item.setToolTip(1, "\n".join(label for _kind, label in badges))
        color = self._author_color(commit)
        item.setForeground(3, QBrush(color) if color is not None else QBrush())

    @staticmethod
    def _author_identity(commit: CommitSummary) -> str:
        return (commit.author_email.strip() or commit.author_name.strip()).casefold()

    def _author_color_key(self, commit: CommitSummary) -> str:
        identity = self._author_identity(commit).encode("utf-8", errors="surrogateescape")
        digest = hashlib.sha256(identity).hexdigest()
        return f"history/authorColors/{digest}"

    def _author_color(self, commit: CommitSummary) -> QColor | None:
        if self._settings is None:
            return None
        value = self._settings.value(self._author_color_key(commit))
        if not isinstance(value, str):
            return None
        color = QColor(value)
        return color if color.isValid() else None

    def _set_author_color(self, commit: CommitSummary, color: QColor | None) -> None:
        if self._settings is None:
            return
        key = self._author_color_key(commit)
        if color is None:
            self._settings.remove(key)
        else:
            self._settings.setValue(key, color.name(QColor.NameFormat.HexRgb))
        self._refresh_commit_labels()

    @Slot(str)
    def _apply_filter(self, text: str) -> None:
        query = text.strip().casefold()
        self.tree.setColumnHidden(0, bool(query))
        self.tree.setColumnHidden(1, bool(query))
        for row in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(row)
            if item is None:
                continue
            commit = item.data(0, Qt.ItemDataRole.UserRole)
            if not isinstance(commit, CommitSummary):
                continue
            searchable = " ".join(
                (item.text(1), commit.subject, commit.author_name, commit.author_email, commit.oid)
            ).casefold()
            item.setHidden(bool(query) and query not in searchable)
            for column in (2, 3, 5):
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
