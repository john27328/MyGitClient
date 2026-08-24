from __future__ import annotations

from PySide6.QtCore import QByteArray, QSettings, Qt, Signal, Slot
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
    RefComparisonSnapshot,
    StashFilesSnapshot,
    StashInfo,
)

_CONTEXT_LABEL_STYLE = (
    "QLabel { padding: 4px 6px; background: palette(alternate-base); "
    "border-bottom: 1px solid palette(midlight); }"
)


class DiffStudyPanel(QWidget):
    """Commit and file navigator for the dedicated diff-reading tab.

    Deliberately narrower than :class:`~mygitclient.ui.history_panel.HistoryPanel`: a flat
    subject list rather than the commit graph, so the diff beside it gets the width.
    Like the history panel it never talks to Git — orchestration stays in the main window.
    """

    load_more_requested = Signal()
    commit_selected = Signal(object)
    file_selected = Signal(object, object)
    comparison_file_selected = Signal(str, str, object)
    stash_file_selected = Signal(object, object)

    def __init__(
        self,
        settings: QSettings | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("diffStudyPanel")
        self._settings = settings
        self._comparison_refs: tuple[str, str] | None = None
        self._selected_stash: StashInfo | None = None

        self.context_label = QLabel("Select a commit to study its diff.")
        self.context_label.setObjectName("diffStudyContextLabel")
        self.context_label.setWordWrap(True)
        self.context_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.context_label.setStyleSheet(_CONTEXT_LABEL_STYLE)

        self.commits = QTreeWidget()
        self.commits.setObjectName("diffStudyCommitsTree")
        self.commits.setHeaderLabels(["Description"])
        self.commits.setRootIsDecorated(False)
        self.commits.setUniformRowHeights(True)
        self.commits.header().setStretchLastSection(True)
        self.commits.currentItemChanged.connect(self._commit_changed)

        self.load_more_button = QPushButton("Load more")
        self.load_more_button.setObjectName("diffStudyLoadMoreButton")
        self.load_more_button.clicked.connect(self.load_more_requested)
        self.load_more_button.hide()

        commits_container = QWidget()
        commits_layout = QVBoxLayout(commits_container)
        commits_layout.setContentsMargins(0, 0, 0, 0)
        commits_layout.setSpacing(0)
        commits_layout.addWidget(self.commits, 1)
        commits_layout.addWidget(self.load_more_button)

        self.files = QTreeWidget()
        self.files.setObjectName("diffStudyFilesTree")
        self.files.setHeaderLabels(["Status", "File"])
        self.files.setColumnWidth(0, 60)
        self.files.setRootIsDecorated(False)
        self.files.currentItemChanged.connect(self._file_changed)

        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.splitter.setObjectName("diffStudySplitter")
        self.splitter.addWidget(commits_container)
        self.splitter.addWidget(self.files)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 2)
        self.splitter.setSizes([440, 260])
        self.splitter.splitterMoved.connect(self._save_splitter_state)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.context_label)
        layout.addWidget(self.splitter, 1)
        self._restore_layout()

    # -- Commits ------------------------------------------------------------

    @property
    def selected_commit(self) -> CommitSummary | None:
        item = self.commits.currentItem()
        if item is None:
            return None
        value = item.data(0, Qt.ItemDataRole.UserRole)
        return value if isinstance(value, CommitSummary) else None

    @property
    def commit_count(self) -> int:
        return self.commits.topLevelItemCount()

    def show_page(self, page: CommitPage) -> None:
        if page.offset == 0:
            self.commits.clear()
        for commit in page.commits:
            item = QTreeWidgetItem([commit.subject])
            item.setData(0, Qt.ItemDataRole.UserRole, commit)
            item.setToolTip(0, f"{commit.oid[:8]} · {commit.author_name}")
            self.commits.addTopLevelItem(item)
        self.load_more_button.setVisible(page.has_more)
        self.load_more_button.setEnabled(True)

    def clear_commits(self) -> None:
        self.commits.clear()
        self.files.clear()
        self._comparison_refs = None
        self._selected_stash = None
        self.context_label.setText("Select a commit to study its diff.")

    def select_commit(self, oid: str) -> bool:
        """Move the cursor onto ``oid``; returns whether that commit was listed."""

        for index in range(self.commits.topLevelItemCount()):
            item = self.commits.topLevelItem(index)
            if item is None:
                continue
            value = item.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(value, CommitSummary) and value.oid == oid:
                self.commits.setCurrentItem(item)
                self.commits.scrollToItem(item)
                return True
        return False

    # -- Files --------------------------------------------------------------

    def show_files(self, snapshot: CommitFilesSnapshot) -> None:
        commit = self.selected_commit
        if commit is None or commit.oid != snapshot.commit_oid:
            return
        self._populate(snapshot.files)

    def show_stash_files(self, snapshot: StashFilesSnapshot) -> None:
        if self._selected_stash != snapshot.stash:
            return
        self._populate(snapshot.files)

    def show_comparison(self, snapshot: RefComparisonSnapshot) -> None:
        self._comparison_refs = (snapshot.base_ref, snapshot.compare_ref)
        self._selected_stash = None
        self.commits.clearSelection()
        self.context_label.setText(
            f"{snapshot.base_ref} … {snapshot.compare_ref} · "
            f"{len(snapshot.files)} changed file(s)"
        )
        self._populate(snapshot.files)

    def show_stash(self, stash: StashInfo) -> None:
        self._selected_stash = stash
        self._comparison_refs = None
        self.commits.clearSelection()
        self.files.clear()
        self.context_label.setText(f"{stash.ref} · {stash.subject}")

    def clear_comparison(self) -> None:
        self._comparison_refs = None
        self._selected_stash = None
        self.files.clear()
        self.context_label.setText("Select a commit to study its diff.")

    def select_file(self, path: str) -> bool:
        for index in range(self.files.topLevelItemCount()):
            item = self.files.topLevelItem(index)
            if item is None:
                continue
            change = item.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(change, CommitFileChange) and change.path == path:
                self.files.setCurrentItem(item)
                self.files.scrollToItem(item)
                return True
        return False

    def select_first_file(self) -> bool:
        if self.files.topLevelItemCount() == 0:
            return False
        item = self.files.topLevelItem(0)
        if item is None:
            return False
        self.files.setCurrentItem(item)
        return True

    def _populate(self, files: tuple[CommitFileChange, ...]) -> None:
        self.files.clear()
        for change in files:
            item = QTreeWidgetItem([change.status, change.path])
            item.setData(0, Qt.ItemDataRole.UserRole, change)
            if change.original_path is not None:
                item.setToolTip(1, f"Renamed from {change.original_path}")
            self.files.addTopLevelItem(item)
        self.files.resizeColumnToContents(0)

    # -- Signals ------------------------------------------------------------

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
        self._selected_stash = None
        self.context_label.setText(f"Commit {commit.oid[:8]} · {commit.subject}")
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
        if self._selected_stash is not None:
            self.stash_file_selected.emit(self._selected_stash, change)
            return
        commit = self.selected_commit
        if commit is not None:
            self.file_selected.emit(commit, change)

    # -- Persistence --------------------------------------------------------

    @Slot(int, int)
    def _save_splitter_state(self, _position: int, _index: int) -> None:
        if self._settings is not None:
            self._settings.setValue("diff/studySplitterState", self.splitter.saveState())

    def _restore_layout(self) -> None:
        if self._settings is None:
            return
        state = self._settings.value("diff/studySplitterState")
        if isinstance(state, QByteArray):
            self.splitter.restoreState(state)
