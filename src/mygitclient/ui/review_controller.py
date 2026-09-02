from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QDateTime, QObject, QSettings, Qt, Signal, Slot
from PySide6.QtWidgets import QInputDialog, QMessageBox, QStackedWidget, QTabWidget, QWidget

from mygitclient.git.models import (
    BranchInfo,
    CommitFileChange,
    CommitSummary,
    RefComparisonDiffSnapshot,
    RefComparisonSnapshot,
    ReviewCommitSnapshot,
    UnifiedDiff,
)
from mygitclient.git.service import GitService
from mygitclient.ui.diff_view import DiffView
from mygitclient.ui.review_panel import ReviewPanel
from mygitclient.workspace.reviews import ReviewSession, ReviewStore, review_file_fingerprint


def review_commit_choice_label(commit: CommitSummary) -> str:
    """Return the unambiguous label used to choose a review boundary."""

    timestamp = QDateTime.fromString(commit.authored_at, Qt.DateFormat.ISODate)
    display_time = timestamp.toLocalTime().toString("dd.MM.yyyy HH:mm")
    return f"{commit.oid[:8]} · {display_time} · {commit.subject}"


class ReviewController(QObject):
    """Coordinates the local self-review feature independently from MainWindow."""

    status_changed = Signal(str)

    def __init__(
        self,
        settings: QSettings,
        git: GitService,
        panel: ReviewPanel,
        diff_view: DiffView,
        diff_container: QStackedWidget,
        tabs: QTabWidget,
        *,
        review_tab: int,
        context_lines: Callable[[], int],
        ignore_whitespace: Callable[[], bool],
        parent_widget: QWidget,
    ) -> None:
        super().__init__(parent_widget)
        self._store = ReviewStore(settings)
        self._git = git
        self._panel = panel
        self._diff_view = diff_view
        self._diff_container = diff_container
        self._tabs = tabs
        self._review_tab = review_tab
        self._context_lines = context_lines
        self._ignore_whitespace = ignore_whitespace
        self._parent_widget = parent_widget
        self._repository: Path | None = None
        self._branches: tuple[BranchInfo, ...] = ()
        self._start_branch = ""
        self._start_target = ""
        self._review_boundaries: dict[str, tuple[CommitSummary, ...]] = {}
        self._active: ReviewSession | None = None
        self._diff: UnifiedDiff | None = None
        panel.start_requested.connect(self.start)
        panel.delete_requested.connect(self.delete)
        panel.session_selected.connect(self.select_session)
        panel.file_selected.connect(self.select_file)
        panel.mark_file_requested.connect(self.mark_file)
        panel.boundary_selected.connect(self.select_boundary)

    def activate_repository(self, repository: Path) -> None:
        self._repository = repository.resolve()
        self._branches = ()
        self._active = None
        self._diff = None
        self._review_boundaries.clear()
        self._panel.show_sessions(self._store.sessions(self._repository))

    def set_branches(self, branches: tuple[BranchInfo, ...]) -> None:
        self._branches = branches

    def refresh(self) -> None:
        if self._active is not None and self._tabs.currentIndex() == self._review_tab:
            self._git.request_ref_comparison(
                self._active.repository,
                self._active.base_oid,
                self._active.branch,
                merge_base=False,
            )

    def update_selection_actions(self) -> bool:
        if self._tabs.currentIndex() != self._review_tab:
            return False
        self._panel.set_mark_file_enabled(self._active is not None and self._diff is not None)
        return True

    def handle_stage_requested(self) -> bool:
        if self._tabs.currentIndex() != self._review_tab:
            return False
        self.mark_file()
        return True

    @Slot()
    def start(self) -> None:
        repository = self._repository
        branches = tuple(branch for branch in self._branches if not branch.remote)
        if repository is None:
            return
        if not branches:
            QMessageBox.information(
                self._parent_widget, "Start review", "Branches are still loading."
            )
            return
        names = [branch.full_name for branch in branches]
        current = next((index for index, branch in enumerate(branches) if branch.current), 0)
        branch, accepted = QInputDialog.getItem(
            self._parent_widget, "Start review", "Branch to review:", names, current, False
        )
        if not accepted or not branch:
            return
        targets = [name for name in names if name != branch]
        if not targets:
            QMessageBox.information(
                self._parent_widget,
                "Start review",
                "Create or fetch another branch to use as the target.",
            )
            return
        preferred = next(
            (
                index
                for index, name in enumerate(targets)
                if name.rsplit("/", 1)[-1] in {"main", "master"}
            ),
            0,
        )
        target, accepted = QInputDialog.getItem(
            self._parent_widget, "Start review", "Target branch:", targets, preferred, False
        )
        if not accepted or not target:
            return
        self._start_branch, self._start_target = branch, target
        self.status_changed.emit(f"Reading commits in {branch} that are not in {target}…")
        self._git.request_review_commits(repository, branch, target)

    @Slot(object)
    def handle_review_commits(self, value: object) -> None:
        if not isinstance(value, ReviewCommitSnapshot):
            return
        if (value.repository, value.branch, value.target_branch) != (
            self._repository,
            self._start_branch,
            self._start_target,
        ):
            return
        if not value.commits:
            QMessageBox.information(
                self._parent_widget, "Start review", "The selected branch has no commits."
            )
            return
        boundaries = tuple(reversed(value.commits))
        commit = boundaries[0]
        base = commit.parent_oids[0] if commit.parent_oids else GitService.EMPTY_TREE
        session = ReviewSession(
            value.repository, value.branch, base, commit.subject, commit.oid, commit.authored_at
        )
        self._review_boundaries[session.key] = boundaries
        self._store.save(session)
        self._panel.show_sessions(self._store.sessions(value.repository))
        self._panel.select_session(session)
        self._tabs.setCurrentIndex(self._review_tab)

    @Slot(object)
    def delete(self, value: object) -> None:
        if not isinstance(value, ReviewSession):
            return
        answer = QMessageBox.question(
            self._parent_widget,
            "Delete review",
            f"Delete local review of {value.branch}? Git branches and commits will not change.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._store.delete(value)
        if self._active == value:
            self._active, self._diff = None, None
            self._diff_view.reset()
        if self._repository is not None:
            self._panel.show_sessions(self._store.sessions(self._repository))

    @Slot(object)
    def select_session(self, value: object) -> None:
        if not isinstance(value, ReviewSession) or value.repository != self._repository:
            return
        self._active, self._diff = value, None
        boundaries = self._review_boundaries.get(value.key)
        if boundaries is None:
            self._panel.clear_boundaries()
        else:
            self._panel.show_boundaries(boundaries, value.start_oid)
        self._git.request_ref_comparison(
            value.repository, value.base_oid, value.branch, merge_base=False
        )

    @Slot(object)
    def select_file(self, value: object) -> None:
        if self._active is None or not isinstance(value, CommitFileChange):
            return
        self._git.request_ref_comparison_diff(
            self._active.repository,
            self._active.base_oid,
            self._active.branch,
            value.path,
            ignore_whitespace=self._ignore_whitespace(),
            context_lines=self._context_lines(),
            merge_base=False,
        )

    @Slot(object)
    def select_boundary(self, value: object) -> None:
        active = self._active
        if active is None or not isinstance(value, CommitSummary) or value.oid == active.start_oid:
            return
        boundaries = self._review_boundaries.get(active.key)
        if boundaries is None or all(commit.oid != value.oid for commit in boundaries):
            return
        base = value.parent_oids[0] if value.parent_oids else GitService.EMPTY_TREE
        session = ReviewSession(
            active.repository,
            active.branch,
            base,
            value.subject,
            value.oid,
            value.authored_at,
        )
        self._review_boundaries[session.key] = boundaries
        self._store.save(session)
        self._panel.show_sessions(self._store.sessions(active.repository))
        self._panel.select_session(session)

    @Slot(object)
    def handle_comparison(self, value: object) -> bool:
        if not isinstance(value, RefComparisonSnapshot) or self._active is None:
            return False
        if (value.repository, value.base_ref, value.compare_ref) != (
            self._active.repository,
            self._active.base_oid,
            self._active.branch,
        ):
            return False
        self._panel.show_files(self._active, value.files)
        self.status_changed.emit(f"{len(value.files)} file(s) need review")
        return True

    @Slot(object)
    def handle_comparison_diff(self, value: object) -> bool:
        if not isinstance(value, RefComparisonDiffSnapshot) or self._active is None:
            return False
        if (value.repository, value.base_ref, value.compare_ref) != (
            self._active.repository,
            self._active.base_oid,
            self._active.branch,
        ):
            return False
        if self._tabs.currentIndex() != self._review_tab:
            return True
        self._diff = value.diff
        reviewed = self._store.reviewed_file(self._active, value.diff.path)
        self._panel.update_file_state(
            value.diff.path,
            1,
            1 if reviewed == review_file_fingerprint(value.diff) else 0,
        )
        self._diff_container.setCurrentWidget(self._diff_view)
        self._diff_view.display_diff(
            value.diff,
            selection_key=(
                self._active.repository,
                f"review:{self._active.key}:{value.diff.path}",
                False,
            ),
            preserve_scroll=False,
            whole_file_staged=False,
            interactive=False,
        )
        self._panel.set_mark_file_enabled(True)
        return True

    @Slot()
    def mark_file(self) -> None:
        if self._active is None or self._diff is None:
            return
        self._store.set_reviewed_file(
            self._active, self._diff.path, review_file_fingerprint(self._diff)
        )
        self._panel.update_file_state(self._diff.path, 1, 1)
        self.status_changed.emit("File marked reviewed")
