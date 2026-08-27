from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, QSettings, Signal, Slot
from PySide6.QtWidgets import QInputDialog, QMessageBox, QStackedWidget, QTabWidget, QWidget

from mygitclient.git.models import (
    BranchInfo,
    CommitFileChange,
    RefComparisonDiffSnapshot,
    RefComparisonSnapshot,
    ReviewCommitSnapshot,
    UnifiedDiff,
)
from mygitclient.git.service import GitService
from mygitclient.ui.diff_view import DiffView
from mygitclient.ui.review_panel import ReviewPanel
from mygitclient.workspace.reviews import ReviewSession, ReviewStore, hunk_fingerprint


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
        self._active: ReviewSession | None = None
        self._diff: UnifiedDiff | None = None
        panel.start_requested.connect(self.start)
        panel.delete_requested.connect(self.delete)
        panel.session_selected.connect(self.select_session)
        panel.file_selected.connect(self.select_file)
        panel.mark_selected_requested.connect(self.mark_selected_hunks)

    def activate_repository(self, repository: Path) -> None:
        self._repository = repository.resolve()
        self._branches = ()
        self._active = None
        self._diff = None
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
        self._panel.set_mark_selected_enabled(bool(self._diff_view.selected_line_indexes))
        return True

    def handle_stage_requested(self) -> bool:
        if self._tabs.currentIndex() != self._review_tab:
            return False
        self.mark_selected_hunks()
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
        choices = [f"{commit.oid[:8]} · {commit.subject}" for commit in value.commits]
        if not choices:
            QMessageBox.information(
                self._parent_widget, "Start review", "The selected branch has no commits."
            )
            return
        choice, accepted = QInputDialog.getItem(
            self._parent_widget,
            "Start review",
            "Show changes from commit:",
            choices,
            min(1, len(choices) - 1),
            False,
        )
        if not accepted:
            return
        commit = value.commits[choices.index(choice)]
        base = commit.parent_oids[0] if commit.parent_oids else GitService.EMPTY_TREE
        session = ReviewSession(value.repository, value.branch, base, commit.subject, commit.oid)
        self._store.save(session)
        self._panel.show_sessions(self._store.sessions(value.repository))
        self._panel.select_session(session)

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
        checked = self._store.checked_hunks(self._active, value.diff.path)
        fingerprints = {hunk_fingerprint(value.diff.path, hunk) for hunk in value.diff.hunks}
        self._panel.update_file_state(
            value.diff.path, len(fingerprints), len(checked & fingerprints)
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
            interactive=True,
        )
        self._panel.set_mark_selected_enabled(False)
        return True

    @Slot()
    def mark_selected_hunks(self) -> None:
        if self._active is None or self._diff is None:
            return
        indexes = {
            self._diff.hunk_index_for_line(line) for line in self._diff_view.selected_line_indexes
        }
        fingerprints = {
            hunk_fingerprint(self._diff.path, self._diff.hunks[index])
            for index in indexes
            if index is not None
        }
        if not fingerprints:
            return
        checked = set(self._store.checked_hunks(self._active, self._diff.path)) | fingerprints
        self._store.set_checked_hunks(self._active, self._diff.path, checked)
        self._diff_view.clear_selection()
        all_fingerprints = {hunk_fingerprint(self._diff.path, hunk) for hunk in self._diff.hunks}
        self._panel.update_file_state(
            self._diff.path, len(all_fingerprints), len(checked & all_fingerprints)
        )
        self.status_changed.emit("Selected blocks marked reviewed")
