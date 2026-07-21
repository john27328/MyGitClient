from __future__ import annotations

from typing import cast

from PySide6.QtCore import QPoint, QSignalBlocker, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QLineEdit,
    QMenu,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from mygitclient.git.models import BranchesSnapshot, BranchInfo, TagInfo, TagsSnapshot

REF_ROLE = int(Qt.ItemDataRole.UserRole) + 1


class RefsPanel(QWidget):
    ref_selected = Signal(str)
    checkout_requested = Signal(object)
    rename_requested = Signal(object)
    delete_requested = Signal(object)
    force_delete_requested = Signal(object)
    create_tag_requested = Signal()
    delete_tag_requested = Signal(object)
    push_tag_requested = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("historyRefsPanel")
        self._branches: tuple[BranchInfo, ...] = ()
        self._tags: tuple[TagInfo, ...] = ()
        self._selected_ref = ""

        self.filter_edit = QLineEdit()
        self.filter_edit.setObjectName("refsFilterEdit")
        self.filter_edit.setPlaceholderText("Filter branches and tags…")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.textChanged.connect(self._apply_filter)

        self.tree = QTreeWidget()
        self.tree.setObjectName("refsTree")
        self.tree.setHeaderHidden(True)
        self.tree.currentItemChanged.connect(self._current_item_changed)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_context_menu)

        self.context_menu = QMenu(self)
        self.checkout_action = self.context_menu.addAction("Checkout")
        self.checkout_action.triggered.connect(self._checkout_selected)
        self.rename_action = self.context_menu.addAction("Rename…")
        self.rename_action.triggered.connect(self._rename_selected)
        self.delete_action = self.context_menu.addAction("Delete safely…")
        self.delete_action.triggered.connect(self._delete_selected)
        self.force_delete_action = self.context_menu.addAction("Force delete…")
        self.force_delete_action.triggered.connect(self._force_delete_selected)
        self.context_menu.addSeparator()
        self.create_tag_action = self.context_menu.addAction("New tag…")
        self.create_tag_action.triggered.connect(self.create_tag_requested)
        self.delete_tag_action = self.context_menu.addAction("Delete tag…")
        self.delete_tag_action.triggered.connect(self._delete_tag_selected)
        self.push_tag_action = self.context_menu.addAction("Push tag")
        self.push_tag_action.triggered.connect(self._push_tag_selected)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.addWidget(self.filter_edit)
        layout.addWidget(self.tree, 1)

    @property
    def selected_ref(self) -> str:
        return self._selected_ref

    def show_branches(self, snapshot: BranchesSnapshot) -> None:
        self._branches = snapshot.branches
        self._rebuild()

    def show_tags(self, snapshot: TagsSnapshot) -> None:
        self._tags = snapshot.tags
        self._rebuild()

    def reset(self) -> None:
        self._branches = ()
        self._tags = ()
        self._selected_ref = ""
        self.filter_edit.clear()
        self.tree.clear()

    def _rebuild(self) -> None:
        previous_ref = self._selected_ref
        blocker = QSignalBlocker(self.tree)
        self.tree.clear()
        local_root = self._root("Branches")
        remotes_root = self._root("Remotes")
        tags_root = self._root("Tags")
        selected_item: QTreeWidgetItem | None = None
        current_item: QTreeWidgetItem | None = None
        remote_roots: dict[str, QTreeWidgetItem] = {}
        for branch in self._branches:
            label = f"✓ {branch.name}" if branch.current else branch.name
            item = QTreeWidgetItem([label])
            item.setData(0, Qt.ItemDataRole.UserRole, branch)
            item.setData(0, REF_ROLE, branch.full_name)
            if branch.upstream_gone:
                item.setToolTip(0, "Upstream branch no longer exists")
            if branch.remote:
                remote_name, _, short_name = branch.name.partition("/")
                remote_root = remote_roots.get(remote_name)
                if remote_root is None:
                    remote_root = QTreeWidgetItem([remote_name])
                    remote_root.setFlags(
                        remote_root.flags() & ~Qt.ItemFlag.ItemIsSelectable
                    )
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
        for root in (local_root, remotes_root, tags_root):
            root.setExpanded(True)
        for remote_root in remote_roots.values():
            remote_root.setExpanded(True)
        selected_item = selected_item or current_item
        if selected_item is not None:
            self.tree.setCurrentItem(selected_item)
        del blocker
        self._apply_filter(self.filter_edit.text())
        if selected_item is not None:
            selected_ref = selected_item.data(0, REF_ROLE)
            if isinstance(selected_ref, str) and selected_ref != self._selected_ref:
                self._selected_ref = selected_ref
                self.ref_selected.emit(selected_ref)

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
            self.ref_selected.emit(ref)

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

    def _selected_value(self) -> BranchInfo | TagInfo | None:
        item = cast(QTreeWidgetItem | None, self.tree.currentItem())
        if item is None:
            return None
        value = item.data(0, Qt.ItemDataRole.UserRole)
        return value if isinstance(value, (BranchInfo, TagInfo)) else None

    @Slot(QPoint)
    def _show_context_menu(self, position: QPoint) -> None:
        item = self.tree.itemAt(position)
        if item is not None:
            self.tree.setCurrentItem(item)
        value = self._selected_value()
        branch = value if isinstance(value, BranchInfo) else None
        tag = value if isinstance(value, TagInfo) else None
        checkout = branch is not None and not branch.current
        editable = branch is not None and not branch.remote and not branch.current
        self.checkout_action.setVisible(branch is not None)
        self.checkout_action.setEnabled(checkout)
        self.rename_action.setVisible(branch is not None)
        self.rename_action.setEnabled(editable)
        self.delete_action.setVisible(branch is not None)
        self.delete_action.setEnabled(editable)
        self.force_delete_action.setVisible(branch is not None)
        self.force_delete_action.setEnabled(editable)
        self.create_tag_action.setVisible(tag is not None)
        self.delete_tag_action.setVisible(tag is not None)
        self.push_tag_action.setVisible(tag is not None)
        if value is not None:
            self.context_menu.exec(self.tree.viewport().mapToGlobal(position))

    @Slot()
    def _checkout_selected(self) -> None:
        branch = self._selected_value()
        if isinstance(branch, BranchInfo) and not branch.current:
            self.checkout_requested.emit(branch)

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
    def _delete_tag_selected(self) -> None:
        tag = self._selected_value()
        if isinstance(tag, TagInfo):
            self.delete_tag_requested.emit(tag)

    @Slot()
    def _push_tag_selected(self) -> None:
        tag = self._selected_value()
        if isinstance(tag, TagInfo):
            self.push_tag_requested.emit(tag)
