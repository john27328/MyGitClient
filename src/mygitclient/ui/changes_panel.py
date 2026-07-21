from __future__ import annotations

from pathlib import PurePosixPath

from PySide6.QtCore import QRect, QSettings, QSignalBlocker, Qt, Signal, Slot
from PySide6.QtGui import QAction, QMouseEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
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
                if current == Qt.CheckState.Checked
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

    folder_stage_requested = Signal(object, bool)
    view_mode_changed = Signal(str)

    def __init__(self, settings: QSettings | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._settings = settings
        self.tree = ChangesTreeWidget()
        self.tree.setObjectName("changesTree")
        self.tree.setHeaderLabel("Changes")
        self.tree.setRootIsDecorated(False)
        self.tree.setMinimumWidth(280)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.ActionsContextMenu)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.itemChanged.connect(self._item_changed)

        self.discard_action = QAction("Discard changes…", self.tree)
        self.discard_action.setObjectName("discardChangesAction")
        self.discard_action.setEnabled(False)
        self.ignore_action = QAction("Add to .gitignore", self.tree)
        self.ignore_action.setObjectName("ignoreFileAction")
        self.ignore_action.setEnabled(False)
        self.stash_action = QAction("Stash selected changes", self.tree)
        self.stash_action.setObjectName("stashSelectedAction")
        self.stash_action.setEnabled(False)
        self.tree.addAction(self.discard_action)
        self.tree.addAction(self.stash_action)
        self.tree.addAction(self.ignore_action)

        self.stage_all = QCheckBox("Stage all changes")
        self.stage_all.setObjectName("stageAllCheckBox")
        self.stage_all.setTristate(True)

        self.view_mode = QComboBox()
        self.view_mode.setObjectName("changesViewModeCombo")
        self.view_mode.addItem("List", "list")
        self.view_mode.addItem("Tree", "tree")
        saved_mode = settings.value("changes/viewMode", "list") if settings else "list"
        index = self.view_mode.findData(saved_mode)
        self.view_mode.setCurrentIndex(max(0, index))
        self.view_mode.currentIndexChanged.connect(self._view_mode_selected)

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

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        options = QHBoxLayout()
        options.addWidget(self.stage_all)
        options.addStretch(1)
        options.addWidget(self.view_mode)
        layout.addLayout(options)
        layout.addWidget(self.tree)
        layout.addWidget(self.commit_message)
        layout.addWidget(self.commit_description)
        layout.addWidget(commit_actions)
        layout.addWidget(self.commit_error)
        self.hide()

    @property
    def tree_mode(self) -> bool:
        return self.view_mode.currentData() == "tree"

    def show_files(
        self,
        files: list[tuple[FileStatus, Qt.CheckState]],
        selected_path: str | None,
    ) -> QTreeWidgetItem | None:
        blocker = QSignalBlocker(self.tree)
        self.tree.clear()
        self.tree.setRootIsDecorated(self.tree_mode)
        selected_item: QTreeWidgetItem | None = None
        folders: dict[tuple[str, ...], QTreeWidgetItem] = {}
        for file, state in files:
            parent: QTreeWidgetItem | None = None
            display_name = file.path
            if self.tree_mode:
                parts = PurePosixPath(file.path).parts
                for depth in range(len(parts) - 1):
                    key = parts[: depth + 1]
                    folder = folders.get(key)
                    if folder is None:
                        folder = QTreeWidgetItem([parts[depth]])
                        folder.setData(0, _FOLDER_ROLE, True)
                        folder.setFlags(
                            folder.flags()
                            | Qt.ItemFlag.ItemIsUserCheckable
                        )
                        folder.setCheckState(0, Qt.CheckState.Unchecked)
                        if parent is None:
                            self.tree.addTopLevelItem(folder)
                        else:
                            parent.addChild(folder)
                        folders[key] = folder
                    parent = folder
                display_name = parts[-1]
            item = QTreeWidgetItem([display_name])
            item.setIcon(0, load_icon(_status_icon(file)))
            item.setToolTip(0, _status_tooltip(file))
            item.setData(0, Qt.ItemDataRole.UserRole, file)
            if not file.unmerged:
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(0, state)
            if parent is None:
                self.tree.addTopLevelItem(item)
            else:
                parent.addChild(item)
            if file.path == selected_path:
                selected_item = item
        if self.tree_mode:
            for index in range(self.tree.topLevelItemCount()):
                root = self.tree.topLevelItem(index)
                if root is not None:
                    self._compact_folder_chain(root)
            selected_item = self._find_file_item(selected_path)
            for index in range(self.tree.topLevelItemCount()):
                root = self.tree.topLevelItem(index)
                if root is not None:
                    self._refresh_folder_state(root)
            self.tree.expandAll()
        del blocker
        return selected_item

    def _compact_folder_chain(self, item: QTreeWidgetItem) -> None:
        while item.data(0, _FOLDER_ROLE) is True and item.childCount() == 1:
            child = item.takeChild(0)
            item.setText(0, f"{item.text(0)}/{child.text(0)}")
            if child.data(0, _FOLDER_ROLE) is True:
                while child.childCount():
                    item.addChild(child.takeChild(0))
                continue
            item.setData(0, _FOLDER_ROLE, None)
            item.setData(0, Qt.ItemDataRole.UserRole, child.data(0, Qt.ItemDataRole.UserRole))
            item.setIcon(0, child.icon(0))
            item.setToolTip(0, child.toolTip(0))
            item.setFlags(child.flags())
            if child.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                item.setCheckState(0, child.checkState(0))
        for index in range(item.childCount()):
            self._compact_folder_chain(item.child(index))

    def _find_file_item(self, path: str | None) -> QTreeWidgetItem | None:
        if path is None:
            return None
        pending: list[QTreeWidgetItem] = []
        for index in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(index)
            if item is not None:
                pending.append(item)
        while pending:
            item = pending.pop()
            value = item.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(value, FileStatus) and value.path == path:
                return item
            for index in range(item.childCount()):
                pending.append(item.child(index))
        return None

    @Slot(QTreeWidgetItem, int)
    def _item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if column != 0 or item.data(0, _FOLDER_ROLE) is not True:
            return
        should_stage = item.checkState(0) != Qt.CheckState.Unchecked
        files = self._descendant_files(item)
        blocker = QSignalBlocker(self.tree)
        target = Qt.CheckState.Checked if should_stage else Qt.CheckState.Unchecked
        self._set_descendant_state(item, target)
        del blocker
        if files:
            self.folder_stage_requested.emit(files, should_stage)

    @Slot(int)
    def _view_mode_selected(self, _index: int) -> None:
        mode = self.view_mode.currentData()
        if not isinstance(mode, str):
            return
        if self._settings is not None:
            self._settings.setValue("changes/viewMode", mode)
        self.view_mode_changed.emit(mode)

    def _descendant_files(self, root: QTreeWidgetItem) -> tuple[FileStatus, ...]:
        files: list[FileStatus] = []
        for index in range(root.childCount()):
            child = root.child(index)
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
            if child.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                child.setCheckState(0, state)
            self._set_descendant_state(child, state)

    def _refresh_folder_state(self, item: QTreeWidgetItem) -> Qt.CheckState:
        if item.data(0, _FOLDER_ROLE) is not True:
            return item.checkState(0)
        states = [
            self._refresh_folder_state(item.child(index))
            for index in range(item.childCount())
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


def _status_icon(file: FileStatus) -> str:
    return {
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
