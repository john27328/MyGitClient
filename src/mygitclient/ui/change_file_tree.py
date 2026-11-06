from __future__ import annotations

from collections.abc import Callable
from pathlib import PurePosixPath

from PySide6.QtCore import QRectF, QSettings, Qt, Signal, Slot
from PySide6.QtGui import QBrush, QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QStyle,
    QTreeWidget,
    QTreeWidgetItem,
    QWidget,
)

from mygitclient.git.models import CommitFileChange

FOLDER_ROLE = int(Qt.ItemDataRole.UserRole) + 1
AUTO_COLLAPSE_THRESHOLD = 1_000

_STATUS_NAMES = {
    "A": "Added",
    "C": "Copied",
    "D": "Deleted",
    "M": "Modified",
    "R": "Renamed",
    "T": "Type changed",
    "U": "Unmerged",
}

# (light theme, dark theme) colours per status letter; others use the palette text colour.
_STATUS_COLORS = {
    "A": ("#2e7d32", "#7bc67e"),
    "C": ("#6a3fb5", "#b79cf0"),
    "D": ("#c62828", "#ef7a7a"),
    "M": ("#1f5fbf", "#7aa7ef"),
    "R": ("#6a3fb5", "#b79cf0"),
    "T": ("#b26a00", "#e8a94a"),
    "U": ("#b26a00", "#e8a94a"),
}


def status_letter(change: CommitFileChange) -> str:
    return change.status[:1].upper() or "?"


def status_name(change: CommitFileChange) -> str:
    return _STATUS_NAMES.get(status_letter(change), change.status)


def status_color(change: CommitFileChange, dark: bool) -> QColor | None:
    colors = _STATUS_COLORS.get(status_letter(change))
    if colors is None:
        return None
    return QColor(colors[1] if dark else colors[0])


def _sort_key(change: CommitFileChange) -> tuple[tuple[int, str], ...]:
    # Folders sort before files at the same depth, like a file manager.
    parts = PurePosixPath(change.path).parts
    return tuple((0, part.casefold()) for part in parts[:-1]) + ((1, parts[-1].casefold()),)


class ChangeFileTree(QTreeWidget):
    """A commit file list that can also be shown as a folder tree.

    File rows keep their :class:`CommitFileChange` in ``UserRole``; folder rows carry
    their path in :data:`FOLDER_ROLE` and no change, so selection handlers can skip them.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setHeaderHidden(True)
        self.setRootIsDecorated(False)
        self._tree_mode = False
        self._status_icons: dict[tuple[str, str], QIcon] = {}

    @property
    def tree_mode(self) -> bool:
        return self._tree_mode

    def set_tree_mode(self, enabled: bool) -> None:
        self._tree_mode = enabled

    @property
    def selected_change(self) -> CommitFileChange | None:
        item = self.currentItem()
        return self.change(item) if item is not None else None

    @staticmethod
    def change(item: QTreeWidgetItem) -> CommitFileChange | None:
        value = item.data(0, Qt.ItemDataRole.UserRole)
        return value if isinstance(value, CommitFileChange) else None

    def file_items(self) -> list[QTreeWidgetItem]:
        """File rows in display order, skipping folders."""

        items: list[QTreeWidgetItem] = []

        def visit(item: QTreeWidgetItem) -> None:
            if self.change(item) is not None:
                items.append(item)
            for index in range(item.childCount()):
                child = item.child(index)
                if child is not None:
                    visit(child)

        for index in range(self.topLevelItemCount()):
            item = self.topLevelItem(index)
            if item is not None:
                visit(item)
        return items

    def find_file_item(self, path: str) -> QTreeWidgetItem | None:
        for item in self.file_items():
            change = self.change(item)
            if change is not None and change.path == path:
                return item
        return None

    def select_path(self, path: str) -> bool:
        item = self.find_file_item(path)
        if item is None:
            return False
        self.setCurrentItem(item)
        self.scrollToItem(item)
        return True

    def select_first_file(self) -> bool:
        items = self.file_items()
        if not items:
            return False
        self.setCurrentItem(items[0])
        return True

    def show_changes(
        self,
        files: tuple[CommitFileChange, ...],
        configure: Callable[[QTreeWidgetItem, CommitFileChange], None] | None = None,
        *,
        restore_selection: bool = True,
    ) -> QTreeWidgetItem | None:
        """Rebuild the rows; returns the row of the previously selected file, if still listed.

        Signals are left to the caller to block. Folders the user collapsed stay collapsed
        when the same folder is listed again.
        """

        previous = self.selected_change if restore_selection else None
        selected_path = previous.path if previous is not None else None
        collapsed = self._collapsed_folders()
        had_folders = self._has_folders()
        self.clear()
        self.setRootIsDecorated(self._tree_mode)
        dark = self.palette().base().color().lightness() < 128
        ordered = sorted(files, key=_sort_key) if self._tree_mode else files
        folders: dict[tuple[str, ...], QTreeWidgetItem] = {}
        for change in ordered:
            parent: QTreeWidgetItem | None = None
            label = change.path
            if self._tree_mode:
                parts = PurePosixPath(change.path).parts
                label = parts[-1]
                for depth in range(len(parts) - 1):
                    key = parts[: depth + 1]
                    folder = folders.get(key)
                    if folder is None:
                        folder = QTreeWidgetItem([parts[depth]])
                        folder.setData(0, FOLDER_ROLE, "/".join(key))
                        folder.setFlags(folder.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
                        folder.setToolTip(0, "/".join(key))
                        folder.setIcon(
                            0, self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon)
                        )
                        if parent is None:
                            self.addTopLevelItem(folder)
                        else:
                            parent.addChild(folder)
                        folders[key] = folder
                    parent = folder
            item = QTreeWidgetItem([label])
            letter = status_letter(change)
            color = status_color(change, dark)
            if color is not None and letter != "M":
                item.setForeground(0, QBrush(color))
            item.setIcon(0, self._status_icon(letter, color))
            item.setData(0, Qt.ItemDataRole.UserRole, change)
            tooltip = f"{status_name(change)}: {change.path}"
            if change.original_path is not None:
                tooltip += f"\nfrom {change.original_path}"
            item.setToolTip(0, tooltip)
            if configure is not None:
                configure(item, change)
            if parent is None:
                self.addTopLevelItem(item)
            else:
                parent.addChild(item)
        if self._tree_mode:
            for index in range(self.topLevelItemCount()):
                root = self.topLevelItem(index)
                if root is not None:
                    _compact_folder_chain(root)
            if had_folders:
                self.expandAll()
                for item in self._folder_items():
                    if item.data(0, FOLDER_ROLE) in collapsed:
                        item.setExpanded(False)
            elif len(files) > AUTO_COLLAPSE_THRESHOLD:
                self.collapseAll()
            else:
                self.expandAll()
        selected = self.find_file_item(selected_path) if selected_path is not None else None
        if selected is not None:
            parent = selected.parent()
            while parent is not None:
                parent.setExpanded(True)
                parent = parent.parent()
            self.setCurrentItem(selected)
        return selected

    def _folder_items(self) -> list[QTreeWidgetItem]:
        folders: list[QTreeWidgetItem] = []

        def visit(item: QTreeWidgetItem) -> None:
            if isinstance(item.data(0, FOLDER_ROLE), str):
                folders.append(item)
            for index in range(item.childCount()):
                child = item.child(index)
                if child is not None:
                    visit(child)

        for index in range(self.topLevelItemCount()):
            item = self.topLevelItem(index)
            if item is not None:
                visit(item)
        return folders

    def _has_folders(self) -> bool:
        return bool(self._folder_items())

    def _collapsed_folders(self) -> set[str]:
        return {
            path
            for item in self._folder_items()
            if not item.isExpanded() and isinstance(path := item.data(0, FOLDER_ROLE), str)
        }

    def _status_icon(self, letter: str, color: QColor | None) -> QIcon:
        key = (letter, color.name() if color is not None else "")
        cached = self._status_icons.get(key)
        if cached is not None:
            return cached
        size = self.iconSize().height()
        if size <= 0:
            size = self.style().pixelMetric(QStyle.PixelMetric.PM_SmallIconSize)
        ratio = self.devicePixelRatioF()
        pixmap = QPixmap(round(size * ratio), round(size * ratio))
        pixmap.setDevicePixelRatio(ratio)
        pixmap.fill(Qt.GlobalColor.transparent)
        fill = color if color is not None else self.palette().text().color()
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(fill)
        rect = QRectF(1, 1, size - 2, size - 2)
        painter.drawRoundedRect(rect, 3, 3)
        font = QFont(self.font())
        font.setBold(True)
        font.setPixelSize(max(8, size - 6))
        painter.setFont(font)
        painter.setPen(QColor("#ffffff") if fill.lightness() < 160 else QColor("#000000"))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, letter)
        painter.end()
        icon = QIcon(pixmap)
        self._status_icons[key] = icon
        return icon


def _compact_folder_chain(item: QTreeWidgetItem) -> None:
    """Merge single-folder chains such as ``src`` → ``vcs`` into one ``src/vcs`` row."""

    while isinstance(item.data(0, FOLDER_ROLE), str) and item.childCount() == 1:
        child = item.child(0)
        if child is None or not isinstance(child.data(0, FOLDER_ROLE), str):
            break
        child = item.takeChild(0)
        assert child is not None
        item.setText(0, f"{item.text(0)}/{child.text(0)}")
        item.setData(0, FOLDER_ROLE, child.data(0, FOLDER_ROLE))
        item.setToolTip(0, child.toolTip(0))
        while child.childCount():
            grandchild = child.takeChild(0)
            assert grandchild is not None
            item.addChild(grandchild)
    for index in range(item.childCount()):
        child = item.child(index)
        if child is not None:
            _compact_folder_chain(child)


class FileViewModeCombo(QComboBox):
    """List/Tree switch persisted under ``settings_key``."""

    mode_changed = Signal(bool)

    def __init__(
        self,
        settings: QSettings | None,
        settings_key: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._settings_key = settings_key
        self.addItem("List", "list")
        self.addItem("Tree", "tree")
        self.setToolTip("Show changed files as a flat list or a folder tree")
        saved = settings.value(settings_key, "list") if settings is not None else "list"
        self.setCurrentIndex(max(0, self.findData(saved)))
        self.currentIndexChanged.connect(self._selected)

    @property
    def tree_mode(self) -> bool:
        return self.currentData() == "tree"

    @Slot(int)
    def _selected(self, _index: int) -> None:
        mode = self.currentData()
        if not isinstance(mode, str):
            return
        if self._settings is not None:
            self._settings.setValue(self._settings_key, mode)
        self.mode_changed.emit(mode == "tree")


def file_view_mode_row(combo: FileViewModeCombo, *leading: QWidget) -> QHBoxLayout:
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    for widget in leading:
        row.addWidget(widget, 1)
    if not leading:
        row.addStretch(1)
    row.addWidget(combo)
    return row
