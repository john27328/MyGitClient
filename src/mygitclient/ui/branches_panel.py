from __future__ import annotations

from typing import cast

from PySide6.QtCore import QPoint, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from mygitclient.git.models import BranchesSnapshot, BranchInfo


class BranchesPanel(QWidget):
    checkout_requested = Signal(object)
    create_requested = Signal()
    rename_requested = Signal(object)
    delete_requested = Signal(object)
    force_delete_requested = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.tree = QTreeWidget()
        self.tree.setObjectName("branchesTree")
        self.tree.setHeaderLabels(["Branch", "Upstream", "Tracking", "Commit"])
        self.tree.setColumnWidth(0, 260)
        self.tree.setColumnWidth(1, 220)
        self.tree.setColumnWidth(2, 140)
        self.tree.currentItemChanged.connect(self._selection_changed)
        self.tree.itemClicked.connect(self._item_clicked)
        self.tree.itemDoubleClicked.connect(self._item_activated)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_context_menu)

        self.context_menu = QMenu(self)
        self.checkout_action = self.context_menu.addAction("Checkout")
        self.checkout_action.setObjectName("checkoutBranchContextAction")
        self.checkout_action.triggered.connect(self._checkout_selected)
        self.rename_action = self.context_menu.addAction("Rename…")
        self.rename_action.setObjectName("renameBranchContextAction")
        self.rename_action.triggered.connect(self._rename_selected)
        self.context_menu.addSeparator()
        self.delete_action = self.context_menu.addAction("Delete safely…")
        self.delete_action.setObjectName("deleteBranchContextAction")
        self.delete_action.triggered.connect(self._delete_selected)
        self.force_delete_action = self.context_menu.addAction("Force delete…")
        self.force_delete_action.setObjectName("forceDeleteBranchContextAction")
        self.force_delete_action.triggered.connect(self._force_delete_selected)

        self.checkout_button = QPushButton("Checkout selected")
        self.checkout_button.setObjectName("checkoutBranchButton")
        self.checkout_button.setEnabled(False)
        self.checkout_button.setToolTip(
            "Switch to the selected branch. You can also double-click a branch."
        )
        self.checkout_button.clicked.connect(self._checkout_selected)
        self.create_button = QPushButton("New branch…")
        self.create_button.setObjectName("createBranchButton")
        self.create_button.clicked.connect(self.create_requested)
        self.rename_button = QPushButton("Rename…")
        self.rename_button.setObjectName("renameBranchButton")
        self.rename_button.setEnabled(False)
        self.rename_button.clicked.connect(self._rename_selected)
        self.delete_button = QPushButton("Delete…")
        self.delete_button.setObjectName("deleteBranchButton")
        self.delete_button.setEnabled(False)
        self.delete_button.clicked.connect(self._delete_selected)
        self.autostash = QCheckBox("Stash changes and restore after checkout")
        self.autostash.setObjectName("checkoutAutostashCheckBox")
        self.hint = QLabel("Select a branch, then click Checkout selected — or double-click it.")
        self.hint.setObjectName("branchCheckoutHint")

        buttons = QHBoxLayout()
        buttons.addWidget(self.checkout_button)
        buttons.addWidget(self.create_button)
        buttons.addWidget(self.rename_button)
        buttons.addWidget(self.delete_button)
        buttons.addWidget(self.autostash)
        buttons.addStretch(1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(buttons)
        layout.addWidget(self.hint)
        layout.addWidget(self.tree)

    def show_branches(self, snapshot: BranchesSnapshot) -> None:
        self.tree.clear()
        local_root = QTreeWidgetItem(["Local"])
        remote_root = QTreeWidgetItem(["Remote"])
        for root in (local_root, remote_root):
            root.setFlags(root.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self.tree.addTopLevelItem(root)
        for branch in snapshot.branches:
            tracking = _tracking_label(branch)
            label = f"● {branch.name}" if branch.current else branch.name
            item = QTreeWidgetItem(
                [label, branch.upstream or "", tracking, branch.oid[:8]]
            )
            item.setData(0, Qt.ItemDataRole.UserRole, branch)
            item.setToolTip(0, branch.full_name)
            (remote_root if branch.remote else local_root).addChild(item)
        local_root.setExpanded(True)
        remote_root.setExpanded(True)
        self.tree.resizeColumnToContents(0)

    def reset(self) -> None:
        self.tree.clear()
        self.checkout_button.setEnabled(False)
        self.rename_button.setEnabled(False)
        self.delete_button.setEnabled(False)

    @Slot()
    def _selection_changed(self) -> None:
        branch = self._selected_branch()
        self._update_actions(branch)

    @Slot(QTreeWidgetItem, int)
    def _item_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        branch = item.data(0, Qt.ItemDataRole.UserRole)
        self._update_actions(branch if isinstance(branch, BranchInfo) else None)

    def _update_actions(self, branch: BranchInfo | None) -> None:
        can_checkout = branch is not None and not branch.current
        editable = branch is not None and not branch.remote and not branch.current
        self.checkout_button.setEnabled(can_checkout)
        self.checkout_action.setEnabled(can_checkout)
        self.rename_button.setEnabled(editable)
        self.rename_action.setEnabled(editable)
        self.delete_button.setEnabled(editable)
        self.delete_action.setEnabled(editable)
        self.force_delete_action.setEnabled(editable)

    @Slot(QPoint)
    def _show_context_menu(self, position: QPoint) -> None:
        item = self.tree.itemAt(position)
        if item is not None:
            self.tree.setCurrentItem(item)
        branch = self._selected_branch()
        self._update_actions(branch)
        if branch is not None:
            self.context_menu.exec(self.tree.viewport().mapToGlobal(position))

    @Slot()
    def _rename_selected(self) -> None:
        branch = self._selected_branch()
        if branch is not None and not branch.remote and not branch.current:
            self.rename_requested.emit(branch)

    @Slot()
    def _delete_selected(self) -> None:
        branch = self._selected_branch()
        if branch is not None and not branch.remote and not branch.current:
            self.delete_requested.emit(branch)

    @Slot()
    def _force_delete_selected(self) -> None:
        branch = self._selected_branch()
        if branch is not None and not branch.remote and not branch.current:
            self.force_delete_requested.emit(branch)

    @Slot()
    def _checkout_selected(self) -> None:
        branch = self._selected_branch()
        if branch is not None and not branch.current:
            self.checkout_requested.emit(branch)

    @Slot(QTreeWidgetItem, int)
    def _item_activated(self, item: QTreeWidgetItem, _column: int) -> None:
        branch = item.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(branch, BranchInfo) and not branch.current:
            self.checkout_requested.emit(branch)

    def _selected_branch(self) -> BranchInfo | None:
        item = cast(QTreeWidgetItem | None, self.tree.currentItem())
        if item is None:
            return None
        value = item.data(0, Qt.ItemDataRole.UserRole)
        return value if isinstance(value, BranchInfo) else None


def _tracking_label(branch: BranchInfo) -> str:
    if branch.upstream_gone:
        return "Gone"
    parts: list[str] = []
    if branch.ahead:
        parts.append(f"↑ {branch.ahead}")
    if branch.behind:
        parts.append(f"↓ {branch.behind}")
    return "  ".join(parts)
