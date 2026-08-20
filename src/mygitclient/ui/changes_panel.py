from __future__ import annotations

from pathlib import PurePosixPath

from PySide6.QtCore import QRect, QSettings, QSignalBlocker, QSize, Qt, QTimer, Signal, Slot
from PySide6.QtGui import (
    QAction,
    QColor,
    QFocusEvent,
    QIcon,
    QMouseEvent,
    QPainter,
    QPixmap,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QStyle,
    QStyleOptionViewItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from mygitclient.git.models import FileStatus
from mygitclient.resources import load_icon

_FOLDER_ROLE = int(Qt.ItemDataRole.UserRole) + 1


class ChangesTreeWidget(QTreeWidget):
    """Keeps row selection separate from clicking a staging checkbox."""

    focused = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._checkbox_pressed = False

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        item = self.itemAt(event.position().toPoint())
        if item is not None and self.indicator_rect(item).contains(
            event.position().toPoint()
        ):
            current = item.checkState(0)
            item.setCheckState(
                0,
                Qt.CheckState.Unchecked
                if current != Qt.CheckState.Unchecked
                else Qt.CheckState.Checked,
            )
            self._checkbox_pressed = True
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._checkbox_pressed:
            self._checkbox_pressed = False
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def focusInEvent(self, event: QFocusEvent) -> None:  # noqa: N802
        super().focusInEvent(event)
        self.focused.emit()

    def indicator_rect(self, item: QTreeWidgetItem) -> QRect:
        option = QStyleOptionViewItem()
        option.initFrom(self)
        option.rect = self.visualItemRect(item)
        option.features |= QStyleOptionViewItem.ViewItemFeature.HasCheckIndicator
        return self.style().subElementRect(
            QStyle.SubElement.SE_ItemViewItemCheckIndicator,
            option,
            self,
        )


class ChangesPanel(QWidget):
    """Owns the changed-files tree and commit form widgets."""

    selection_changed = Signal()
    stage_requested = Signal()
    unstage_requested = Signal()
    stash_requested = Signal()
    discard_requested = Signal()
    view_mode_changed = Signal(str)
    presentation_mode_changed = Signal(str)
    file_activated = Signal(object)
    submodule_init_requested = Signal(object)
    submodule_update_requested = Signal(object)
    submodule_sync_requested = Signal(object)
    submodule_init_recursive_requested = Signal(object)
    submodule_update_recursive_requested = Signal(object)
    submodule_sync_recursive_requested = Signal(object)

    def __init__(self, settings: QSettings | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._selected_paths: set[str] = set()
        self._visible_files: dict[str, FileStatus] = {}
        self._submodule_sync: dict[str, tuple[int, int]] = {}
        self._submodule_checkout: dict[str, tuple[str | None, bool]] = {}
        self._amend_mode = False
        self._render_generation = 0
        self._pending_scroll_restore: tuple[int, int, int] | None = None
        self._scroll_restore_timer = QTimer(self)
        self._scroll_restore_timer.setSingleShot(True)
        self._scroll_restore_timer.timeout.connect(self._restore_scroll_position)
        self.tree = self._make_tree("changesTree", "Changes")
        self.unstaged_tree = self._make_tree("unstagedChangesTree", "Unstaged")
        self.staged_tree = self._make_tree("stagedChangesTree", "Staged")
        self._active_split_tree = self.unstaged_tree
        for tree in self.all_trees:
            tree.itemChanged.connect(self._item_changed)
            tree.itemSelectionChanged.connect(self._tree_selection_changed)
            tree.itemDoubleClicked.connect(self._item_activated)

        self.open_action = QAction("Open", self.tree)
        self.open_action.setObjectName("openChangedFileAction")
        self.open_action.setEnabled(False)
        self.open_with_action = QAction("Open with…", self.tree)
        self.open_with_action.setObjectName("openChangedFileWithAction")
        self.open_with_action.setEnabled(False)
        self.reveal_action = QAction("Show in File Manager", self.tree)
        self.reveal_action.setObjectName("revealChangedFileAction")
        self.reveal_action.setEnabled(False)
        self.file_actions_separator = QAction(self.tree)
        self.file_actions_separator.setSeparator(True)
        self.use_ours_action = QAction("Use current side", self.tree)
        self.use_ours_action.setObjectName("useOursConflictAction")
        self.use_ours_action.setVisible(False)
        self.use_theirs_action = QAction("Use incoming side", self.tree)
        self.use_theirs_action.setObjectName("useTheirsConflictAction")
        self.use_theirs_action.setVisible(False)
        self.conflict_actions_separator = QAction(self.tree)
        self.conflict_actions_separator.setSeparator(True)
        self.conflict_actions_separator.setVisible(False)
        self.submodule_init_action = QAction("Initialize submodule", self.tree)
        self.submodule_init_action.setObjectName("initializeSubmoduleAction")
        self.submodule_init_action.setVisible(False)
        self.submodule_init_action.triggered.connect(self._request_submodule_init)
        self.submodule_update_action = QAction("Update submodule", self.tree)
        self.submodule_update_action.setObjectName("updateSubmoduleAction")
        self.submodule_update_action.setVisible(False)
        self.submodule_update_action.triggered.connect(self._request_submodule_update)
        self.submodule_sync_action = QAction("Sync submodule URL", self.tree)
        self.submodule_sync_action.setObjectName("syncSubmoduleAction")
        self.submodule_sync_action.setVisible(False)
        self.submodule_sync_action.triggered.connect(self._request_submodule_sync)
        self.submodule_init_recursive_action = QAction(
            "Initialize recursively…", self.tree
        )
        self.submodule_init_recursive_action.setObjectName(
            "initializeSubmoduleRecursiveAction"
        )
        self.submodule_init_recursive_action.setVisible(False)
        self.submodule_init_recursive_action.triggered.connect(
            self._request_submodule_init_recursive
        )
        self.submodule_update_recursive_action = QAction(
            "Update recursively…", self.tree
        )
        self.submodule_update_recursive_action.setObjectName(
            "updateSubmoduleRecursiveAction"
        )
        self.submodule_update_recursive_action.setVisible(False)
        self.submodule_update_recursive_action.triggered.connect(
            self._request_submodule_update_recursive
        )
        self.submodule_sync_recursive_action = QAction("Sync recursively…", self.tree)
        self.submodule_sync_recursive_action.setObjectName(
            "syncSubmoduleRecursiveAction"
        )
        self.submodule_sync_recursive_action.setVisible(False)
        self.submodule_sync_recursive_action.triggered.connect(
            self._request_submodule_sync_recursive
        )
        self.submodule_actions_separator = QAction(self.tree)
        self.submodule_actions_separator.setSeparator(True)
        self.submodule_actions_separator.setVisible(False)
        self.stage_action = QAction("Stage", self.tree)
        self.stage_action.setObjectName("stageChangesAction")
        self.stage_action.setEnabled(False)
        self.stage_action.triggered.connect(self.stage_requested)
        self.unstage_action = QAction("Unstage", self.tree)
        self.unstage_action.setObjectName("unstageChangesAction")
        self.unstage_action.setEnabled(False)
        self.unstage_action.triggered.connect(self.unstage_requested)
        self.discard_action = QAction("Discard changes…", self.tree)
        self.discard_action.setObjectName("discardChangesAction")
        self.discard_action.setEnabled(False)
        self.discard_action.triggered.connect(self.discard_requested)
        self.ignore_action = QAction("Add to .gitignore", self.tree)
        self.ignore_action.setObjectName("ignoreFileAction")
        self.ignore_action.setEnabled(False)
        self.stash_action = QAction("Stash selected changes", self.tree)
        self.stash_action.setObjectName("stashSelectedAction")
        self.stash_action.setEnabled(False)
        self.stash_action.triggered.connect(self.stash_requested)
        for tree in self.all_trees:
            tree.addAction(self.open_action)
            tree.addAction(self.open_with_action)
            tree.addAction(self.reveal_action)
            tree.addAction(self.file_actions_separator)
            tree.addAction(self.use_ours_action)
            tree.addAction(self.use_theirs_action)
            tree.addAction(self.conflict_actions_separator)
            tree.addAction(self.submodule_init_action)
            tree.addAction(self.submodule_update_action)
            tree.addAction(self.submodule_sync_action)
            tree.addAction(self.submodule_init_recursive_action)
            tree.addAction(self.submodule_update_recursive_action)
            tree.addAction(self.submodule_sync_recursive_action)
            tree.addAction(self.submodule_actions_separator)
            tree.addAction(self.stage_action)
            tree.addAction(self.stash_action)
            tree.addAction(self.unstage_action)
            tree.addAction(self.discard_action)
            tree.addAction(self.ignore_action)

        self.stage_all = QCheckBox("Select all changes")
        self.stage_all.setObjectName("stageAllCheckBox")
        self.stage_all.setTristate(True)
        self.stage_all.stateChanged.connect(self._select_all_changed)
        self.stage_summary = QLabel("✓ 0 · ✎ 0")
        self.stage_summary.setObjectName("stageSummaryLabel")
        self.stage_summary.setToolTip(
            "Files in the Git index and all files with uncommitted changes"
        )

        self.stage_button = QPushButton("Stage")
        self.stage_button.setObjectName("stageSelectedButton")
        self.stage_button.clicked.connect(self.stage_requested)
        self.stash_button = QPushButton("Stash")
        self.stash_button.setObjectName("stashSelectedButton")
        self.stash_button.clicked.connect(self.stash_requested)
        self.unstage_button = QPushButton("Unstage")
        self.unstage_button.setObjectName("unstageSelectedButton")
        self.unstage_button.clicked.connect(self.unstage_requested)
        self.discard_button = QPushButton("Discard")
        self.discard_button.setObjectName("discardSelectedButton")
        self.discard_button.clicked.connect(self.discard_requested)

        self.view_mode = QComboBox()
        self.view_mode.setObjectName("changesViewModeCombo")
        self.view_mode.addItem("List", "list")
        self.view_mode.addItem("Tree", "tree")
        saved_mode = settings.value("changes/viewMode", "list") if settings else "list"
        index = self.view_mode.findData(saved_mode)
        self.view_mode.setCurrentIndex(max(0, index))
        self.view_mode.currentIndexChanged.connect(self._view_mode_selected)

        self.presentation_mode = QComboBox()
        self.presentation_mode.setObjectName("changesPresentationModeCombo")
        self.presentation_mode.addItem("Combined", "combined")
        self.presentation_mode.addItem("Split", "split")
        saved_presentation = (
            settings.value("changes/presentationMode", "combined")
            if settings
            else "combined"
        )
        presentation_index = self.presentation_mode.findData(saved_presentation)
        self.presentation_mode.setCurrentIndex(max(0, presentation_index))
        self.presentation_mode.currentIndexChanged.connect(
            self._presentation_mode_selected
        )

        self.commit_message = QPlainTextEdit()
        self.commit_message.setObjectName("commitMessageEdit")
        self.commit_message.setPlaceholderText("Commit message")
        self.commit_message.setMaximumHeight(90)
        self.commit_description = QPlainTextEdit()
        self.commit_description.setObjectName("commitDescriptionEdit")
        self.commit_description.setPlaceholderText("Description (optional)")
        self.commit_description.setMaximumHeight(110)

        self.amend = QCheckBox("Amend")
        self.amend.setObjectName("amendCheckBox")
        self.commit_button = QPushButton(load_icon("commit.svg"), "Commit")
        self.commit_button.setObjectName("commitButton")
        self.commit_error = QLabel()
        self.commit_error.setObjectName("commitErrorLabel")
        self.commit_error.setStyleSheet("color: palette(bright-text);")

        commit_actions = QWidget()
        commit_actions_layout = QHBoxLayout(commit_actions)
        commit_actions_layout.setContentsMargins(0, 0, 0, 0)
        commit_actions_layout.addWidget(self.amend)
        commit_actions_layout.addStretch(1)
        commit_actions_layout.addWidget(self.commit_button)

        split = QSplitter(Qt.Orientation.Vertical)
        split.setObjectName("splitChangesTrees")
        split.addWidget(self.unstaged_tree)
        split.addWidget(self.staged_tree)
        split.setSizes([350, 250])
        self.tree_stack = QStackedWidget()
        self.tree_stack.setObjectName("changesTreeStack")
        self.tree_stack.addWidget(self.tree)
        self.tree_stack.addWidget(split)
        self.tree_stack.setCurrentIndex(1 if self.split_mode else 0)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        options = QHBoxLayout()
        options.addWidget(self.stage_all)
        options.addWidget(self.stage_summary)
        options.addStretch(1)
        options.addWidget(self.presentation_mode)
        options.addWidget(self.view_mode)
        layout.addLayout(options)
        selection_actions = QHBoxLayout()
        selection_actions.addWidget(self.stage_button)
        selection_actions.addWidget(self.stash_button)
        selection_actions.addWidget(self.unstage_button)
        selection_actions.addWidget(self.discard_button)
        selection_actions.addStretch(1)
        layout.addLayout(selection_actions)
        layout.addWidget(self.tree_stack)
        layout.addWidget(self.commit_message)
        layout.addWidget(self.commit_description)
        layout.addWidget(commit_actions)
        layout.addWidget(self.commit_error)
        self._update_selection_controls()
        self.hide()

    @property
    def tree_mode(self) -> bool:
        return self.view_mode.currentData() == "tree"

    @property
    def split_mode(self) -> bool:
        return self.presentation_mode.currentData() == "split"

    @property
    def all_trees(self) -> tuple[ChangesTreeWidget, ...]:
        return (self.tree, self.unstaged_tree, self.staged_tree)

    def active_tree(self) -> ChangesTreeWidget:
        if not self.split_mode:
            return self.tree
        return self._active_split_tree

    def set_active_tree(self, tree: QTreeWidget) -> None:
        if tree is self.unstaged_tree:
            self._active_split_tree = self.unstaged_tree
        elif tree is self.staged_tree:
            self._active_split_tree = self.staged_tree

    def preferred_staged(self, tree: QTreeWidget | None = None) -> bool | None:
        selected_tree = tree or self.active_tree()
        if not self.split_mode:
            return None
        return selected_tree is self.staged_tree

    def set_file_check_state(
        self,
        tree: QTreeWidget,
        item: QTreeWidgetItem,
        state: Qt.CheckState,
    ) -> None:
        blocker = QSignalBlocker(tree)
        item.setCheckState(0, state)
        parent = item.parent()
        while parent is not None:
            self._refresh_folder_state(parent)
            parent = parent.parent()
        del blocker

    @staticmethod
    def _make_tree(object_name: str, header: str) -> ChangesTreeWidget:
        tree = ChangesTreeWidget()
        tree.setObjectName(object_name)
        tree.setHeaderLabel(header)
        tree.setRootIsDecorated(False)
        tree.setIconSize(QSize(27, 20))
        tree.setMinimumWidth(280)
        tree.setContextMenuPolicy(Qt.ContextMenuPolicy.ActionsContextMenu)
        tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        return tree

    def show_files(
        self,
        files: list[tuple[FileStatus, Qt.CheckState]],
        selected_path: str | None,
        *,
        amend: bool = False,
    ) -> QTreeWidgetItem | None:
        self._amend_mode = amend
        self._visible_files = {file.path: file for file, _state in files}
        staged_count = sum(file.is_staged and not file.unmerged for file, _state in files)
        self.stage_summary.setText(f"✓ {staged_count} · ✎ {len(files)}")
        self._selected_paths.intersection_update(self._visible_files)
        selected_files = [
            (
                file,
                Qt.CheckState.Checked
                if file.path in self._selected_paths
                else Qt.CheckState.Unchecked,
            )
            for file, _state in files
        ]
        selected = self._render_tree(
            self.tree,
            selected_files,
            selected_path,
            preserve_scroll=True,
            checkable=True,
        )
        unstaged = [
            (
                file,
                Qt.CheckState.Checked
                if file.path in self._selected_paths
                else Qt.CheckState.Unchecked,
            )
            for file, state in files
            if (amend and state is not Qt.CheckState.Checked)
            or file.has_worktree_change
            or file.unmerged
        ]
        staged = [
            (
                file,
                Qt.CheckState.Checked
                if file.path in self._selected_paths
                else Qt.CheckState.Unchecked,
            )
            for file, state in files
            if (amend and state is not Qt.CheckState.Unchecked)
            or (file.is_staged and not file.unmerged)
        ]
        unstaged_selected = self._render_tree(
            self.unstaged_tree,
            unstaged,
            selected_path,
            preserve_scroll=False,
            checkable=True,
        )
        staged_selected = self._render_tree(
            self.staged_tree,
            staged,
            selected_path,
            preserve_scroll=False,
            checkable=True,
        )
        if not self.split_mode:
            self._update_selection_controls()
            return selected
        self._update_selection_controls()
        return staged_selected if self.active_tree() is self.staged_tree else unstaged_selected

    def checked_files(self) -> tuple[FileStatus, ...]:
        return tuple(
            file
            for path, file in self._visible_files.items()
            if path in self._selected_paths
        )

    def action_files(self) -> tuple[FileStatus, ...]:
        checked = self.checked_files()
        if checked:
            return checked
        item = self.active_tree().currentItem()
        if item is None:
            return ()
        file = item.data(0, Qt.ItemDataRole.UserRole)
        return (file,) if isinstance(file, FileStatus) else ()

    @Slot()
    def _tree_selection_changed(self) -> None:
        self._update_selection_controls()
        self.selection_changed.emit()

    def clear_checked_files(self) -> None:
        self._selected_paths.clear()
        for tree in self.all_trees:
            blocker = QSignalBlocker(tree)
            self._set_all_tree_states(tree, Qt.CheckState.Unchecked)
            del blocker
        self._update_selection_controls()
        self.selection_changed.emit()

    def refresh_selection_controls(self) -> None:
        self._update_selection_controls()

    def set_submodule_sync(self, path: str, *, ahead: int, behind: int) -> None:
        self._submodule_sync[path] = (ahead, behind)
        for tree in self.all_trees:
            item = self._find_file_item(tree, path)
            if item is None:
                continue
            file = item.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(file, FileStatus):
                item.setText(0, self._file_label(file))
                item.setToolTip(0, self._file_tooltip(file))

    def set_submodule_checkout(
        self, path: str, *, checked_oid: str | None, initialized: bool
    ) -> None:
        self._submodule_checkout[path] = (checked_oid, initialized)
        for tree in self.all_trees:
            item = self._find_file_item(tree, path)
            if item is None:
                continue
            file = item.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(file, FileStatus):
                item.setText(0, self._file_label(file))
                item.setToolTip(0, self._file_tooltip(file))
        self._update_selection_controls()

    @Slot(QTreeWidgetItem, int)
    def _item_activated(self, item: QTreeWidgetItem, _column: int) -> None:
        file = item.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(file, FileStatus):
            self.file_activated.emit(file)

    def _file_label(self, file: FileStatus) -> str:
        name = PurePosixPath(file.path).name if self.tree_mode else file.path
        if file.submodule == "N...":
            return name
        ahead, behind = self._submodule_sync.get(file.path, (0, 0))
        checked_oid, initialized = self._submodule_checkout.get(file.path, (None, True))
        sync: list[str] = []
        if not initialized:
            sync.append("not initialized")
        elif checked_oid:
            expected = file.submodule_expected_oid
            if expected and expected != checked_oid:
                sync.append(f"expected {expected[:7]}")
                sync.append(f"checked out {checked_oid[:7]}")
            else:
                sync.append(f"at {checked_oid[:7]}")
        if ahead:
            sync.append(f"Push ↑{ahead}")
        if behind:
            sync.append(f"Pull ↓{behind}")
        suffix = " · ".join(("submodule", *sync))
        return f"{name}  [{suffix}]"

    def _file_tooltip(self, file: FileStatus) -> str:
        tooltip = _status_tooltip(file)
        if file.submodule == "N...":
            return tooltip
        ahead, behind = self._submodule_sync.get(file.path, (0, 0))
        details = [tooltip, "Git submodule"]
        checked_oid, initialized = self._submodule_checkout.get(file.path, (None, True))
        if not initialized:
            details.append("Not initialized")
        else:
            if file.submodule_expected_oid:
                details.append(f"Expected commit: {file.submodule_expected_oid}")
            if checked_oid:
                details.append(f"Checked out commit: {checked_oid}")
        if ahead:
            details.append(f"Commits to push: {ahead}")
        if behind:
            details.append(f"Commits to pull: {behind}")
        details.append("Double-click to open this repository")
        return "\n".join(details)

    def _render_tree(
        self,
        tree: ChangesTreeWidget,
        files: list[tuple[FileStatus, Qt.CheckState]],
        selected_path: str | None,
        *,
        preserve_scroll: bool,
        checkable: bool,
    ) -> QTreeWidgetItem | None:
        vertical_scroll = tree.verticalScrollBar().value()
        horizontal_scroll = tree.horizontalScrollBar().value()
        self._render_generation += 1
        render_generation = self._render_generation
        blocker = QSignalBlocker(tree)
        tree.clear()
        tree.setRootIsDecorated(self.tree_mode)
        selected_item: QTreeWidgetItem | None = None
        folders: dict[tuple[str, ...], QTreeWidgetItem] = {}
        for file, state in sorted(files, key=lambda value: value[0].path.casefold()):
            parent: QTreeWidgetItem | None = None
            if self.tree_mode:
                parts = PurePosixPath(file.path).parts
                for depth in range(len(parts) - 1):
                    key = parts[: depth + 1]
                    folder = folders.get(key)
                    if folder is None:
                        folder = QTreeWidgetItem([parts[depth]])
                        folder.setData(0, _FOLDER_ROLE, True)
                        if checkable:
                            folder.setFlags(
                                folder.flags() | Qt.ItemFlag.ItemIsUserCheckable
                            )
                            folder.setCheckState(0, Qt.CheckState.Unchecked)
                        else:
                            folder.setFlags(
                                folder.flags() & ~Qt.ItemFlag.ItemIsUserCheckable
                            )
                        if parent is None:
                            tree.addTopLevelItem(folder)
                        else:
                            parent.addChild(folder)
                        folders[key] = folder
                    parent = folder
            item = QTreeWidgetItem([self._file_label(file)])
            staged_view = (
                True
                if tree is self.staged_tree
                else False if tree is self.unstaged_tree else None
            )
            item.setIcon(0, _status_icon(file, staged_view=staged_view))
            item.setToolTip(0, self._file_tooltip(file))
            item.setData(0, Qt.ItemDataRole.UserRole, file)
            if checkable:
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(0, state)
            else:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
            if parent is None:
                tree.addTopLevelItem(item)
            else:
                parent.addChild(item)
            if file.path == selected_path:
                selected_item = item
        if self.tree_mode:
            for index in range(tree.topLevelItemCount()):
                root = tree.topLevelItem(index)
                if root is not None:
                    self._compact_folder_chain(root)
            selected_item = self._find_file_item(tree, selected_path)
            for index in range(tree.topLevelItemCount()):
                root = tree.topLevelItem(index)
                if root is not None and checkable:
                    self._refresh_folder_state(root)
            tree.expandAll()
        del blocker
        if preserve_scroll:
            self._pending_scroll_restore = (
                render_generation,
                vertical_scroll,
                horizontal_scroll,
            )
            self._scroll_restore_timer.start(0)
        return selected_item

    @Slot()
    def _restore_scroll_position(self) -> None:
        pending = self._pending_scroll_restore
        self._pending_scroll_restore = None
        if pending is None:
            return
        render_generation, vertical, horizontal = pending
        if render_generation != self._render_generation:
            return
        self.tree.verticalScrollBar().setValue(vertical)
        self.tree.horizontalScrollBar().setValue(horizontal)

    def _compact_folder_chain(self, item: QTreeWidgetItem) -> None:
        while item.data(0, _FOLDER_ROLE) is True and item.childCount() == 1:
            child = item.child(0)
            assert child is not None
            if child.data(0, _FOLDER_ROLE) is not True:
                break
            child = item.takeChild(0)
            assert child is not None
            item.setText(0, f"{item.text(0)}/{child.text(0)}")
            while child.childCount():
                grandchild = child.takeChild(0)
                assert grandchild is not None
                item.addChild(grandchild)
        for index in range(item.childCount()):
            child = item.child(index)
            assert child is not None
            self._compact_folder_chain(child)

    def _find_file_item(
        self, tree: QTreeWidget, path: str | None
    ) -> QTreeWidgetItem | None:
        if path is None:
            return None
        pending: list[QTreeWidgetItem] = []
        for index in range(tree.topLevelItemCount()):
            item = tree.topLevelItem(index)
            if item is not None:
                pending.append(item)
        while pending:
            item = pending.pop()
            value = item.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(value, FileStatus) and value.path == path:
                return item
            for index in range(item.childCount()):
                child = item.child(index)
                assert child is not None
                pending.append(child)
        return None

    def find_file_item(
        self, tree: QTreeWidget, path: str | None
    ) -> QTreeWidgetItem | None:
        return self._find_file_item(tree, path)

    @Slot(QTreeWidgetItem, int)
    def _item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if column != 0:
            return
        sender = self.sender()
        tree = sender if isinstance(sender, QTreeWidget) else self.tree
        checked = item.checkState(0) != Qt.CheckState.Unchecked
        if item.data(0, _FOLDER_ROLE) is True:
            blocker = QSignalBlocker(tree)
            target = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
            self._set_descendant_state(item, target)
            del blocker
            files = self._descendant_files(item)
        else:
            value = item.data(0, Qt.ItemDataRole.UserRole)
            files = (value,) if isinstance(value, FileStatus) else ()
        for file in files:
            if checked:
                self._selected_paths.add(file.path)
            else:
                self._selected_paths.discard(file.path)
        self._sync_matching_items()
        self._update_selection_controls()
        self.selection_changed.emit()

    @Slot(int)
    def _select_all_changed(self, state: int) -> None:
        if Qt.CheckState(state) == Qt.CheckState.PartiallyChecked:
            return
        if Qt.CheckState(state) == Qt.CheckState.Checked:
            self._selected_paths = set(self._visible_files)
        else:
            self._selected_paths.clear()
        self._sync_matching_items()
        self._update_selection_controls()
        self.selection_changed.emit()

    def _sync_matching_items(self) -> None:
        for tree in self.all_trees:
            blocker = QSignalBlocker(tree)
            pending = [
                tree.topLevelItem(index) for index in range(tree.topLevelItemCount())
            ]
            for item in pending:
                if item is not None:
                    self._sync_item_state(item)
            del blocker

    def _sync_item_state(self, item: QTreeWidgetItem) -> Qt.CheckState:
        value = item.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(value, FileStatus):
            state = (
                Qt.CheckState.Checked
                if value.path in self._selected_paths
                else Qt.CheckState.Unchecked
            )
            item.setCheckState(0, state)
            return state
        states: list[Qt.CheckState] = []
        for index in range(item.childCount()):
            child = item.child(index)
            assert child is not None
            states.append(self._sync_item_state(child))
        if states and all(state == Qt.CheckState.Checked for state in states):
            state = Qt.CheckState.Checked
        elif states and all(state == Qt.CheckState.Unchecked for state in states):
            state = Qt.CheckState.Unchecked
        else:
            state = Qt.CheckState.PartiallyChecked
        item.setCheckState(0, state)
        return state

    def _set_all_tree_states(self, tree: QTreeWidget, state: Qt.CheckState) -> None:
        for index in range(tree.topLevelItemCount()):
            item = tree.topLevelItem(index)
            if item is not None:
                item.setCheckState(0, state)
                self._set_descendant_state(item, state)

    def _update_selection_controls(self) -> None:
        files = self.action_files()
        selected = bool(files)
        count = len(files)
        has_unstaged = any(file.has_worktree_change or file.unmerged for file in files)
        has_staged = any(file.is_staged and not file.unmerged for file in files)
        safe = selected and all(not file.unmerged for file in files)
        self.stage_button.setEnabled(selected and (self._amend_mode or has_unstaged))
        self.unstage_button.setEnabled(selected and (self._amend_mode or has_staged))
        self.stash_button.setEnabled(safe and has_unstaged)
        self.discard_button.setEnabled(safe and has_unstaged)
        self.stage_action.setEnabled(self.stage_button.isEnabled())
        self.unstage_action.setEnabled(self.unstage_button.isEnabled())
        self.stash_action.setEnabled(self.stash_button.isEnabled())
        self.discard_action.setEnabled(self.discard_button.isEnabled())
        current = self.action_files()
        submodule = current[0] if len(current) == 1 and current[0].submodule != "N..." else None
        checked_oid, initialized = self._submodule_checkout.get(
            submodule.path if submodule else "", (None, True)
        )
        del checked_oid
        self.submodule_init_action.setVisible(submodule is not None and not initialized)
        self.submodule_update_action.setVisible(submodule is not None and initialized)
        self.submodule_sync_action.setVisible(submodule is not None)
        self.submodule_init_recursive_action.setVisible(
            submodule is not None and not initialized
        )
        self.submodule_update_recursive_action.setVisible(
            submodule is not None and initialized
        )
        self.submodule_sync_recursive_action.setVisible(submodule is not None)
        self.submodule_actions_separator.setVisible(submodule is not None)
        suffix = f" ({count})" if count else ""
        self.stage_button.setText(f"Stage{suffix}")
        self.stash_button.setText(f"Stash{suffix}")
        self.unstage_button.setText(f"Unstage{suffix}")
        self.discard_button.setText(f"Discard{suffix}")
        blocker = QSignalBlocker(self.stage_all)
        if not self._visible_files or not self._selected_paths:
            self.stage_all.setCheckState(Qt.CheckState.Unchecked)
        elif len(self._selected_paths) == len(self._visible_files):
            self.stage_all.setCheckState(Qt.CheckState.Checked)
        else:
            self.stage_all.setCheckState(Qt.CheckState.PartiallyChecked)
        self.stage_all.setEnabled(bool(self._visible_files))
        del blocker

    def _current_submodule(self) -> FileStatus | None:
        files = self.action_files()
        if len(files) == 1 and files[0].submodule != "N...":
            return files[0]
        return None

    @Slot()
    def _request_submodule_init(self) -> None:
        if (file := self._current_submodule()) is not None:
            self.submodule_init_requested.emit(file)

    @Slot()
    def _request_submodule_update(self) -> None:
        if (file := self._current_submodule()) is not None:
            self.submodule_update_requested.emit(file)

    @Slot()
    def _request_submodule_sync(self) -> None:
        if (file := self._current_submodule()) is not None:
            self.submodule_sync_requested.emit(file)

    @Slot()
    def _request_submodule_init_recursive(self) -> None:
        if (file := self._current_submodule()) is not None:
            self.submodule_init_recursive_requested.emit(file)

    @Slot()
    def _request_submodule_update_recursive(self) -> None:
        if (file := self._current_submodule()) is not None:
            self.submodule_update_recursive_requested.emit(file)

    @Slot()
    def _request_submodule_sync_recursive(self) -> None:
        if (file := self._current_submodule()) is not None:
            self.submodule_sync_recursive_requested.emit(file)

    @Slot(int)
    def _view_mode_selected(self, _index: int) -> None:
        mode = self.view_mode.currentData()
        if not isinstance(mode, str):
            return
        if self._settings is not None:
            self._settings.setValue("changes/viewMode", mode)
        self.view_mode_changed.emit(mode)

    @Slot(int)
    def _presentation_mode_selected(self, _index: int) -> None:
        mode = self.presentation_mode.currentData()
        if not isinstance(mode, str):
            return
        self.tree_stack.setCurrentIndex(1 if mode == "split" else 0)
        if self._settings is not None:
            self._settings.setValue("changes/presentationMode", mode)
        self.presentation_mode_changed.emit(mode)

    def _descendant_files(self, root: QTreeWidgetItem) -> tuple[FileStatus, ...]:
        files: list[FileStatus] = []
        for index in range(root.childCount()):
            child = root.child(index)
            assert child is not None
            value = child.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(value, FileStatus) and not value.unmerged:
                files.append(value)
            else:
                files.extend(self._descendant_files(child))
        return tuple(files)

    def _set_descendant_state(
        self, root: QTreeWidgetItem, state: Qt.CheckState
    ) -> None:
        for index in range(root.childCount()):
            child = root.child(index)
            assert child is not None
            if child.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                child.setCheckState(0, state)
            self._set_descendant_state(child, state)

    def _refresh_folder_state(self, item: QTreeWidgetItem) -> Qt.CheckState:
        if item.data(0, _FOLDER_ROLE) is not True:
            return item.checkState(0)
        states = [
            self._refresh_folder_state(child)
            for index in range(item.childCount())
            if (child := item.child(index)) is not None
        ]
        if states and all(state == Qt.CheckState.Checked for state in states):
            state = Qt.CheckState.Checked
        elif states and all(state == Qt.CheckState.Unchecked for state in states):
            state = Qt.CheckState.Unchecked
        else:
            state = Qt.CheckState.PartiallyChecked
        item.setCheckState(0, state)
        return state


def _status_label(code: str) -> str:
    return {
        ".": "",
        "M": "Modified",
        "A": "Added",
        "D": "Deleted",
        "R": "Renamed",
        "C": "Copied",
        "U": "Unmerged",
        "T": "Type changed",
        "?": "Untracked",
        "!": "Ignored",
    }.get(code, code)


def _primary_status(file: FileStatus) -> str:
    if file.unmerged:
        return "U"
    if file.worktree_status not in (".", "!"):
        return file.worktree_status
    if file.index_status != ".":
        return file.index_status
    return file.worktree_status


def _status_icon(file: FileStatus, *, staged_view: bool | None = None) -> QIcon:
    icon_name = {
        "M": "status-modified.svg",
        "A": "status-added.svg",
        "D": "status-deleted.svg",
        "R": "status-renamed.svg",
        "C": "status-added.svg",
        "U": "status-conflict.svg",
        "T": "status-modified.svg",
        "?": "status-untracked.svg",
        "!": "status-untracked.svg",
    }.get(_primary_status(file), "status-modified.svg")
    canvas = QPixmap(27, 20)
    canvas.fill(Qt.GlobalColor.transparent)
    painter = QPainter(canvas)
    painter.drawPixmap(7, 0, load_icon(icon_name).pixmap(20, 20))
    marker_x = 0
    marker_y = 2
    marker_width = 5
    marker_height = 16
    staged = (
        staged_view
        if staged_view is not None
        else file.is_staged and not file.unmerged
    )
    unstaged = (
        not staged_view
        if staged_view is not None
        else file.has_worktree_change or file.unmerged
    )
    painter.setPen(Qt.PenStyle.NoPen)
    if staged and unstaged:
        painter.setBrush(QColor("#2f6fed"))
        painter.drawRoundedRect(
            marker_x, marker_y, marker_width, marker_height // 2, 2, 2
        )
        painter.setBrush(QColor("#e29416"))
        painter.drawRoundedRect(
            marker_x,
            marker_y + marker_height // 2,
            marker_width,
            marker_height // 2,
            2,
            2,
        )
    elif staged:
        painter.setBrush(QColor("#2f6fed"))
        painter.drawRoundedRect(
            marker_x, marker_y, marker_width, marker_height, 2, 2
        )
    elif unstaged:
        painter.setBrush(QColor("#e29416"))
        painter.drawRoundedRect(
            marker_x, marker_y, marker_width, marker_height, 2, 2
        )
    painter.end()
    return QIcon(canvas)


def _status_tooltip(file: FileStatus) -> str:
    lines = [file.path]
    if file.original_path is not None:
        lines.append(f"Renamed from: {file.original_path}")
    index = "Untracked" if file.index_status == "?" else _status_label(file.index_status)
    worktree = _status_label(file.worktree_status)
    if index:
        lines.append(f"Staged: {index}")
    if worktree:
        lines.append(f"Not staged: {worktree}")
    return "\n".join(lines)
