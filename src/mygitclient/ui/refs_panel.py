from __future__ import annotations

from pathlib import Path
from typing import cast

from PySide6.QtCore import QPoint, QSignalBlocker, Qt, Signal, Slot
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QLineEdit,
    QMenu,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from mygitclient.git.models import (
    BranchesSnapshot,
    BranchInfo,
    StashesSnapshot,
    StashInfo,
    TagInfo,
    TagsSnapshot,
)
from mygitclient.workspace import LinkedRepository

REF_ROLE = int(Qt.ItemDataRole.UserRole) + 1


class RefsPanel(QWidget):
    refs_selected = Signal(object)
    checkout_requested = Signal(object)
    rename_requested = Signal(object)
    delete_requested = Signal(object)
    force_delete_requested = Signal(object)
    remote_delete_requested = Signal(object)
    cleanup_gone_requested = Signal(object)
    rebase_requested = Signal(object)
    interactive_rebase_requested = Signal(object)
    merge_requested = Signal(object)
    create_tag_requested = Signal()
    create_branch_requested = Signal()
    create_branch_from_requested = Signal(object)
    create_worktree_requested = Signal(object)
    publish_branch_requested = Signal(object)
    delete_tag_requested = Signal(object)
    push_tag_requested = Signal(object)
    stash_apply_requested = Signal(object)
    stash_pop_requested = Signal(object)
    stash_drop_requested = Signal(object)
    stash_view_requested = Signal(object)
    repository_requested = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("historyRefsPanel")
        self._branches: tuple[BranchInfo, ...] = ()
        self._tags: tuple[TagInfo, ...] = ()
        self._stashes: tuple[StashInfo, ...] = ()
        self._linked_repositories: tuple[LinkedRepository, ...] = ()
        self._selected_ref = ""
        self._comparison_ref = ""

        self.filter_edit = QLineEdit()
        self.filter_edit.setObjectName("refsFilterEdit")
        self.filter_edit.setPlaceholderText("Filter branches and tags…")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.textChanged.connect(self._apply_filter)

        self.compare_combo = QComboBox()
        self.compare_combo.setObjectName("historyCompareRefCombo")
        self.compare_combo.setToolTip(
            "Show commits reachable from one additional branch in the same history."
        )
        self.compare_combo.currentIndexChanged.connect(self._comparison_changed)

        self.autostash = QCheckBox("Auto-stash when switching branches")
        self.autostash.setObjectName("checkoutAutostashCheckBox")

        self.tree = QTreeWidget()
        self.tree.setObjectName("refsTree")
        self.tree.setHeaderHidden(True)
        self.tree.currentItemChanged.connect(self._current_item_changed)
        self.tree.itemDoubleClicked.connect(self._item_activated)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_context_menu)

        self.context_menu = QMenu(self)
        self.create_branch_action = self.context_menu.addAction("New branch…")
        self.create_branch_action.triggered.connect(self.create_branch_requested)
        self.create_branch_from_action = self.context_menu.addAction("New branch from this…")
        self.create_branch_from_action.setObjectName("createBranchFromRefAction")
        self.create_branch_from_action.triggered.connect(self._create_branch_from_selected)
        self.create_worktree_action = self.context_menu.addAction("New worktree from this…")
        self.create_worktree_action.setObjectName("createWorktreeFromRefAction")
        self.create_worktree_action.triggered.connect(self._create_worktree_selected)
        self.checkout_action = self.context_menu.addAction("Checkout")
        self.checkout_action.triggered.connect(self._checkout_selected)
        self.copy_branch_action = self.context_menu.addAction("Copy branch name")
        self.copy_branch_action.setObjectName("copyBranchNameAction")
        self.copy_branch_action.triggered.connect(self._copy_branch_name)
        self.compare_upstream_action = self.context_menu.addAction("Compare with upstream")
        self.compare_upstream_action.setObjectName("compareBranchWithUpstreamAction")
        self.compare_upstream_action.triggered.connect(self._compare_with_upstream)
        self.publish_branch_action = self.context_menu.addAction("Publish to origin")
        self.publish_branch_action.setObjectName("publishBranchAction")
        self.publish_branch_action.triggered.connect(self._publish_selected)
        self.context_menu.addSeparator()
        self.rename_action = self.context_menu.addAction("Rename…")
        self.rename_action.triggered.connect(self._rename_selected)
        self.delete_action = self.context_menu.addAction("Delete safely…")
        self.delete_action.triggered.connect(self._delete_selected)
        self.force_delete_action = self.context_menu.addAction("Force delete…")
        self.force_delete_action.triggered.connect(self._force_delete_selected)
        self.remote_delete_action = self.context_menu.addAction("Delete remote branch…")
        self.remote_delete_action.setObjectName("deleteRemoteBranchAction")
        self.remote_delete_action.triggered.connect(self._delete_remote_selected)
        self.cleanup_gone_action = self.context_menu.addAction("Clean up gone branches…")
        self.cleanup_gone_action.setObjectName("cleanupGoneBranchesAction")
        self.cleanup_gone_action.triggered.connect(self._cleanup_gone_branches)
        self.rebase_action = self.context_menu.addAction("Rebase current branch onto this…")
        self.rebase_action.setObjectName("rebaseOntoBranchAction")
        self.rebase_action.triggered.connect(self._rebase_selected)
        self.interactive_rebase_action = self.context_menu.addAction(
            "Interactive rebase current branch onto this…"
        )
        self.interactive_rebase_action.setObjectName("interactiveRebaseOntoBranchAction")
        self.interactive_rebase_action.triggered.connect(self._interactive_rebase_selected)
        self.merge_action = self.context_menu.addAction("Merge this into current branch…")
        self.merge_action.setObjectName("mergeBranchAction")
        self.merge_action.triggered.connect(self._merge_selected)
        self.context_menu.addSeparator()
        self.create_tag_action = self.context_menu.addAction("New tag…")
        self.create_tag_action.triggered.connect(self.create_tag_requested)
        self.delete_tag_action = self.context_menu.addAction("Delete tag…")
        self.delete_tag_action.triggered.connect(self._delete_tag_selected)
        self.push_tag_action = self.context_menu.addAction("Push tag")
        self.push_tag_action.triggered.connect(self._push_tag_selected)
        self.context_menu.addSeparator()
        self.view_stash_action = self.context_menu.addAction("View stash contents")
        self.view_stash_action.triggered.connect(self._view_stash_selected)
        self.apply_stash_action = self.context_menu.addAction("Apply stash")
        self.apply_stash_action.triggered.connect(self._apply_stash_selected)
        self.pop_stash_action = self.context_menu.addAction("Pop stash")
        self.pop_stash_action.triggered.connect(self._pop_stash_selected)
        self.drop_stash_action = self.context_menu.addAction("Drop stash…")
        self.drop_stash_action.triggered.connect(self._drop_stash_selected)
        self.open_repository_action = self.context_menu.addAction("Open repository")
        self.open_repository_action.triggered.connect(self._open_repository_selected)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.addWidget(self.filter_edit)
        layout.addWidget(self.compare_combo)
        layout.addWidget(self.autostash)
        layout.addWidget(self.tree, 1)

    @property
    def selected_ref(self) -> str:
        return self._selected_ref

    @property
    def selected_refs(self) -> tuple[str, ...]:
        if self._comparison_ref:
            return (self._selected_ref, self._comparison_ref)
        return (self._selected_ref,) if self._selected_ref else ()

    def show_branches(self, snapshot: BranchesSnapshot) -> None:
        self._branches = snapshot.branches
        self._rebuild()

    def show_tags(self, snapshot: TagsSnapshot) -> None:
        self._tags = snapshot.tags
        self._rebuild()

    def show_stashes(self, snapshot: StashesSnapshot) -> None:
        self._stashes = snapshot.stashes
        self._rebuild()

    def show_linked_repositories(self, repositories: tuple[LinkedRepository, ...]) -> None:
        self._linked_repositories = repositories
        self._rebuild()

    def reset(self) -> None:
        self._branches = ()
        self._tags = ()
        self._stashes = ()
        self._linked_repositories = ()
        self._selected_ref = ""
        self._comparison_ref = ""
        self.filter_edit.clear()
        self.compare_combo.clear()
        self.tree.clear()

    def _rebuild(self) -> None:
        previous_ref = self._selected_ref
        blocker = QSignalBlocker(self.tree)
        self.tree.clear()
        local_root = self._root("Branches")
        remotes_root = self._root("Remotes")
        tags_root = self._root("Tags")
        stashes_root = self._root("Stashes")
        submodules_root = self._root("Submodules")
        worktrees_root = self._root("Worktrees")
        selected_item: QTreeWidgetItem | None = None
        current_item: QTreeWidgetItem | None = None
        remote_roots: dict[str, QTreeWidgetItem] = {}
        for branch in self._branches:
            label = self._branch_label(branch)
            item = QTreeWidgetItem([label])
            item.setData(0, Qt.ItemDataRole.UserRole, branch)
            item.setData(0, REF_ROLE, branch.full_name)
            item.setToolTip(0, self._branch_tooltip(branch))
            if branch.current:
                font = QFont(item.font(0))
                font.setBold(True)
                item.setFont(0, font)
            if branch.upstream_gone:
                item.setForeground(0, QBrush(QColor("#d97706")))
            if branch.remote:
                remote_name, _, short_name = branch.name.partition("/")
                remote_root = remote_roots.get(remote_name)
                if remote_root is None:
                    remote_root = QTreeWidgetItem([remote_name])
                    remote_root.setFlags(remote_root.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                    remotes_root.addChild(remote_root)
                    remote_roots[remote_name] = remote_root
                item.setText(0, short_name or branch.name)
                remote_root.addChild(item)
            else:
                local_root.addChild(item)
            if branch.full_name == previous_ref:
                selected_item = item
            if branch.current:
                current_item = item
        for tag in self._tags:
            item = QTreeWidgetItem([tag.name])
            item.setData(0, Qt.ItemDataRole.UserRole, tag)
            item.setData(0, REF_ROLE, f"refs/tags/{tag.name}")
            item.setToolTip(0, tag.subject)
            tags_root.addChild(item)
            if f"refs/tags/{tag.name}" == previous_ref:
                selected_item = item
        for stash in self._stashes:
            item = QTreeWidgetItem([f"{stash.ref}: {stash.subject}"])
            item.setData(0, Qt.ItemDataRole.UserRole, stash)
            item.setData(0, REF_ROLE, stash.ref)
            item.setToolTip(0, stash.oid)
            stashes_root.addChild(item)
            if stash.ref == previous_ref:
                selected_item = item
        submodule_items: dict[Path, QTreeWidgetItem] = {}
        submodules = sorted(
            (linked for linked in self._linked_repositories if linked.kind == "submodule"),
            key=lambda linked: (len(linked.path.parts), str(linked.path).casefold()),
        )
        for linked in submodules:
            item = QTreeWidgetItem([linked.path.name])
            item.setData(0, Qt.ItemDataRole.UserRole, linked)
            item.setToolTip(0, str(linked.path))
            parents = [path for path in submodule_items if linked.path.is_relative_to(path)]
            if parents:
                parent_path = max(parents, key=lambda path: len(path.parts))
                submodule_items[parent_path].addChild(item)
                submodule_items[parent_path].setExpanded(True)
            else:
                submodules_root.addChild(item)
            submodule_items[linked.path] = item
        worktrees = sorted(
            (linked for linked in self._linked_repositories if linked.kind == "worktree"),
            key=lambda linked: str(linked.path).casefold(),
        )
        for linked in worktrees:
            item = QTreeWidgetItem([linked.path.name])
            item.setData(0, Qt.ItemDataRole.UserRole, linked)
            item.setToolTip(0, f"Git worktree\n{linked.path}")
            worktrees_root.addChild(item)
        for root in (local_root, stashes_root, submodules_root, worktrees_root):
            root.setExpanded(True)
        remotes_root.setExpanded(False)
        tags_root.setExpanded(False)
        for remote_root in remote_roots.values():
            remote_root.setExpanded(False)
        selected_item = selected_item or current_item
        if selected_item is not None:
            self.tree.setCurrentItem(selected_item)
        del blocker
        self._apply_filter(self.filter_edit.text())
        if selected_item is not None:
            selected_ref = selected_item.data(0, REF_ROLE)
            if isinstance(selected_ref, str) and selected_ref != self._selected_ref:
                self._selected_ref = selected_ref
                if self._comparison_ref == selected_ref:
                    self._comparison_ref = ""
                self._rebuild_compare_combo()
                self.refs_selected.emit(self.selected_refs)
            else:
                self._rebuild_compare_combo()

    @staticmethod
    def _branch_label(branch: BranchInfo) -> str:
        markers: list[str] = []
        if branch.current:
            markers.append("✓")
        if not branch.remote:
            if branch.upstream_gone:
                markers.append("⚠")
            elif branch.upstream is None:
                markers.append("○")
            if branch.ahead:
                markers.append(f"↑{branch.ahead}")
            if branch.behind:
                markers.append(f"↓{branch.behind}")
        suffix = f"  {' '.join(markers)}" if markers else ""
        return f"{branch.name}{suffix}"

    @staticmethod
    def _branch_tooltip(branch: BranchInfo) -> str:
        if branch.remote:
            return f"Remote branch\nCommit: {branch.oid[:8]}"
        lines = ["Current local branch" if branch.current else "Local branch"]
        if branch.upstream_gone:
            lines.append(f"Upstream gone: {branch.upstream or 'unknown'}")
        elif branch.upstream is None:
            lines.append("Not published; no upstream configured")
        else:
            lines.append(f"Upstream: {branch.upstream}")
            lines.append(f"Ahead: {branch.ahead}; behind: {branch.behind}")
        lines.append(f"Commit: {branch.oid[:8]}")
        return "\n".join(lines)

    def _root(self, label: str) -> QTreeWidgetItem:
        root = QTreeWidgetItem([label])
        root.setFlags(root.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        self.tree.addTopLevelItem(root)
        return root

    @Slot(QTreeWidgetItem, QTreeWidgetItem)
    def _current_item_changed(
        self, current: QTreeWidgetItem | None, _previous: QTreeWidgetItem | None
    ) -> None:
        if current is None:
            return
        ref = current.data(0, REF_ROLE)
        if isinstance(ref, str) and ref != self._selected_ref:
            self._selected_ref = ref
            if self._comparison_ref == ref:
                self._comparison_ref = ""
            self._rebuild_compare_combo()
            self.refs_selected.emit(self.selected_refs)

    def _rebuild_compare_combo(self) -> None:
        blocker = QSignalBlocker(self.compare_combo)
        self.compare_combo.clear()
        self.compare_combo.addItem("No comparison", "")
        selected_index = 0
        for branch in self._branches:
            if branch.full_name == self._selected_ref:
                continue
            self.compare_combo.addItem(branch.name, branch.full_name)
            if branch.full_name == self._comparison_ref:
                selected_index = self.compare_combo.count() - 1
        if selected_index == 0:
            self._comparison_ref = ""
        self.compare_combo.setCurrentIndex(selected_index)
        del blocker

    @Slot(int)
    def _comparison_changed(self, index: int) -> None:
        value = self.compare_combo.itemData(index)
        comparison = value if isinstance(value, str) else ""
        if comparison == self._comparison_ref:
            return
        self._comparison_ref = comparison
        self.refs_selected.emit(self.selected_refs)

    @Slot(str)
    def _apply_filter(self, text: str) -> None:
        query = text.strip().casefold()
        for root_index in range(self.tree.topLevelItemCount()):
            root = self.tree.topLevelItem(root_index)
            if root is not None:
                self._filter_children(root, query)

    def _filter_children(self, parent: QTreeWidgetItem, query: str) -> bool:
        visible = False
        for index in range(parent.childCount()):
            child = parent.child(index)
            descendant_visible = self._filter_children(child, query)
            matches = not query or query in child.text(0).casefold()
            child.setHidden(not matches and not descendant_visible)
            visible = visible or matches or descendant_visible
        parent.setHidden(bool(query) and not visible)
        return visible

    def _selected_value(self) -> BranchInfo | TagInfo | StashInfo | LinkedRepository | None:
        item = cast(QTreeWidgetItem | None, self.tree.currentItem())
        if item is None:
            return None
        value = item.data(0, Qt.ItemDataRole.UserRole)
        supported = (BranchInfo, TagInfo, StashInfo, LinkedRepository)
        return value if isinstance(value, supported) else None

    @Slot(QPoint)
    def _show_context_menu(self, position: QPoint) -> None:
        item_value: object = self.tree.itemAt(position)
        if not isinstance(item_value, QTreeWidgetItem):
            return
        item = item_value
        root_label = item.text(0) if item.data(0, Qt.ItemDataRole.UserRole) is None else ""
        self.tree.setCurrentItem(item)
        value = self._selected_value()
        branch = value if isinstance(value, BranchInfo) else None
        tag = value if isinstance(value, TagInfo) else None
        stash = value if isinstance(value, StashInfo) else None
        linked = value if isinstance(value, LinkedRepository) else None
        checkout = branch is not None and not branch.current
        editable = branch is not None and not branch.remote and not branch.current
        self.create_branch_action.setVisible(branch is not None or root_label == "Branches")
        self.create_branch_from_action.setVisible(branch is not None)
        self.create_worktree_action.setVisible(branch is not None)
        self.create_worktree_action.setEnabled(
            branch is not None and not branch.remote and not branch.current
        )
        self.checkout_action.setVisible(branch is not None)
        self.checkout_action.setEnabled(checkout)
        self.copy_branch_action.setVisible(branch is not None)
        upstream_ref = self._upstream_ref(branch)
        self.compare_upstream_action.setVisible(upstream_ref is not None)
        self.publish_branch_action.setVisible(
            branch is not None and not branch.remote and branch.upstream is None
        )
        self.rename_action.setVisible(branch is not None)
        self.rename_action.setEnabled(editable)
        self.delete_action.setVisible(branch is not None)
        self.delete_action.setEnabled(editable)
        self.force_delete_action.setVisible(branch is not None)
        self.force_delete_action.setEnabled(editable)
        self.remote_delete_action.setVisible(branch is not None and branch.remote)
        self.cleanup_gone_action.setVisible(root_label == "Branches")
        self.cleanup_gone_action.setEnabled(bool(self._gone_branches()))
        self.rebase_action.setVisible(branch is not None)
        self.rebase_action.setEnabled(branch is not None and not branch.current)
        self.interactive_rebase_action.setVisible(branch is not None)
        self.interactive_rebase_action.setEnabled(branch is not None and not branch.current)
        self.merge_action.setVisible(branch is not None)
        self.merge_action.setEnabled(branch is not None and not branch.current)
        self.create_tag_action.setVisible(tag is not None or root_label == "Tags")
        self.delete_tag_action.setVisible(tag is not None)
        self.push_tag_action.setVisible(tag is not None)
        self.apply_stash_action.setVisible(stash is not None)
        self.pop_stash_action.setVisible(stash is not None)
        self.drop_stash_action.setVisible(stash is not None)
        self.view_stash_action.setVisible(stash is not None)
        self.open_repository_action.setVisible(linked is not None)
        if value is not None or root_label in {"Branches", "Tags"}:
            self.context_menu.exec(self.tree.viewport().mapToGlobal(position))

    @Slot(QTreeWidgetItem, int)
    def _item_activated(self, item: QTreeWidgetItem, _column: int) -> None:
        value = item.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(value, LinkedRepository):
            self.repository_requested.emit(value)
        elif isinstance(value, StashInfo):
            self.stash_view_requested.emit(value)
        elif isinstance(value, BranchInfo) and not value.current:
            self.checkout_requested.emit(value)

    @Slot()
    def _view_stash_selected(self) -> None:
        stash = self._selected_value()
        if isinstance(stash, StashInfo):
            self.stash_view_requested.emit(stash)

    @Slot()
    def _checkout_selected(self) -> None:
        branch = self._selected_value()
        if isinstance(branch, BranchInfo) and not branch.current:
            self.checkout_requested.emit(branch)

    @Slot()
    def _create_branch_from_selected(self) -> None:
        branch = self._selected_value()
        if isinstance(branch, BranchInfo):
            self.create_branch_from_requested.emit(branch)

    @Slot()
    def _create_worktree_selected(self) -> None:
        branch = self._selected_value()
        if isinstance(branch, BranchInfo) and not branch.remote and not branch.current:
            self.create_worktree_requested.emit(branch)

    @Slot()
    def _publish_selected(self) -> None:
        branch = self._selected_value()
        if isinstance(branch, BranchInfo) and not branch.remote and branch.upstream is None:
            self.publish_branch_requested.emit(branch)

    @Slot()
    def _compare_with_upstream(self) -> None:
        value = self._selected_value()
        branch = value if isinstance(value, BranchInfo) else None
        upstream_ref = self._upstream_ref(branch)
        if branch is None or upstream_ref is None:
            return
        self._selected_ref = branch.full_name
        self._comparison_ref = upstream_ref
        self._rebuild_compare_combo()
        self.refs_selected.emit(self.selected_refs)

    def _upstream_ref(self, branch: BranchInfo | None) -> str | None:
        if branch is None or branch.remote or branch.upstream is None:
            return None
        return next(
            (
                candidate.full_name
                for candidate in self._branches
                if candidate.remote and candidate.name == branch.upstream
            ),
            None,
        )

    @Slot()
    def _rename_selected(self) -> None:
        branch = self._selected_value()
        if isinstance(branch, BranchInfo) and not branch.remote and not branch.current:
            self.rename_requested.emit(branch)

    @Slot()
    def _delete_selected(self) -> None:
        branch = self._selected_value()
        if isinstance(branch, BranchInfo) and not branch.remote and not branch.current:
            self.delete_requested.emit(branch)

    @Slot()
    def _force_delete_selected(self) -> None:
        branch = self._selected_value()
        if isinstance(branch, BranchInfo) and not branch.remote and not branch.current:
            self.force_delete_requested.emit(branch)

    @Slot()
    def _delete_remote_selected(self) -> None:
        branch = self._selected_value()
        if isinstance(branch, BranchInfo) and branch.remote:
            self.remote_delete_requested.emit(branch)

    @Slot()
    def _copy_branch_name(self) -> None:
        branch = self._selected_value()
        if isinstance(branch, BranchInfo):
            QApplication.clipboard().setText(branch.name)

    @Slot()
    def _cleanup_gone_branches(self) -> None:
        branches = self._gone_branches()
        if branches:
            self.cleanup_gone_requested.emit(branches)

    def _gone_branches(self) -> tuple[BranchInfo, ...]:
        return tuple(
            branch
            for branch in self._branches
            if branch.upstream_gone and not branch.remote and not branch.current
        )

    @Slot()
    def _rebase_selected(self) -> None:
        branch = self._selected_value()
        if isinstance(branch, BranchInfo) and not branch.current:
            self.rebase_requested.emit(branch)

    @Slot()
    def _interactive_rebase_selected(self) -> None:
        branch = self._selected_value()
        if isinstance(branch, BranchInfo) and not branch.current:
            self.interactive_rebase_requested.emit(branch)

    @Slot()
    def _merge_selected(self) -> None:
        branch = self._selected_value()
        if isinstance(branch, BranchInfo) and not branch.current:
            self.merge_requested.emit(branch)

    @Slot()
    def _delete_tag_selected(self) -> None:
        tag = self._selected_value()
        if isinstance(tag, TagInfo):
            self.delete_tag_requested.emit(tag)

    @Slot()
    def _push_tag_selected(self) -> None:
        tag = self._selected_value()
        if isinstance(tag, TagInfo):
            self.push_tag_requested.emit(tag)

    @Slot()
    def _apply_stash_selected(self) -> None:
        stash = self._selected_value()
        if isinstance(stash, StashInfo):
            self.stash_apply_requested.emit(stash)

    @Slot()
    def _pop_stash_selected(self) -> None:
        stash = self._selected_value()
        if isinstance(stash, StashInfo):
            self.stash_pop_requested.emit(stash)

    @Slot()
    def _drop_stash_selected(self) -> None:
        stash = self._selected_value()
        if isinstance(stash, StashInfo):
            self.stash_drop_requested.emit(stash)

    @Slot()
    def _open_repository_selected(self) -> None:
        linked = self._selected_value()
        if isinstance(linked, LinkedRepository):
            self.repository_requested.emit(linked)
