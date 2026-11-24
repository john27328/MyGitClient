from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from weakref import ref

from PySide6.QtCore import QPoint, QProcess, QSettings, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QMenu, QPlainTextEdit, QWidget
from pytest import MonkeyPatch, mark
from pytestqt.qtbot import QtBot

from mygitclient.git.models import CommitFileChange, StashFilesSnapshot, StashInfo
from mygitclient.git.parsers import parse_unified_diff
from mygitclient.git.service import GitService
from mygitclient.theme import Theme
from mygitclient.ui.conflict_editor import ConflictEditor
from mygitclient.ui.diff_view import DiffView
from mygitclient.ui.file_reveal_menu import FileRevealMenu
from mygitclient.ui.history_panel import HistoryPanel
from mygitclient.ui.inline_diff import InlineDiffWidget
from mygitclient.ui.main_window import MainWindow


def test_file_menu_does_not_keep_its_widget_or_controller_alive(qtbot: QtBot) -> None:
    class Controller:
        def reveal(self) -> None:
            pass

        def has_file(self) -> bool:
            return True

    widget = QPlainTextEdit()
    qtbot.addWidget(widget)
    controller = Controller()
    menu = FileRevealMenu(widget, reveal=controller.reveal, has_file=controller.has_file)
    assert menu.parent() is widget
    controller_ref = ref(controller)
    del controller
    assert controller_ref() is None
    widget_ref = ref(widget)
    del widget
    assert widget_ref() is None


def _choose_reveal(widget: QWidget, *, enabled: bool = True) -> None:
    shown: list[bool] = []

    def choose() -> None:
        popup = QApplication.activePopupWidget()
        assert isinstance(popup, QMenu)
        try:
            action = next(
                item for item in popup.actions() if item.objectName() == "revealFileAction"
            )
            shown.append(True)
            assert action.isEnabled() is enabled
            if isinstance(widget, QPlainTextEdit):
                assert any("Copy" in item.text().replace("&", "") for item in popup.actions())
            if enabled:
                action.trigger()
        finally:
            popup.close()

    QTimer.singleShot(0, choose)
    widget.customContextMenuRequested.emit(QPoint(2, 2))
    assert shown == [True]


@mark.parametrize("surface", [
    "diff", "side_old", "side_new", "file_header", "gutter", "side_old_gutter", "side_new_gutter",
])
def test_diff_context_menu_reveals_its_current_file(
    qtbot: QtBot, tmp_path: Path, surface: str
) -> None:
    view = DiffView(QSettings(str(tmp_path / "diff.ini"), QSettings.Format.IniFormat))
    qtbot.addWidget(view)
    widget = getattr(view, surface)
    assert isinstance(widget, QWidget)
    revealed: list[str] = []
    view.file_reveal_requested.connect(revealed.append)
    _choose_reveal(widget, enabled=False)
    for path in ("first.txt", "folder/second.txt"):
        view.display_diff(
            parse_unified_diff(b"@@ -1 +1 @@\n-old\n+new\n", path, staged=False),
            selection_key=(tmp_path, path, False), preserve_scroll=False, whole_file_staged=False,
        )
        _choose_reveal(widget)
    assert revealed == ["first.txt", "folder/second.txt"]
    view.reset()
    _choose_reveal(widget, enabled=False)
    assert len(revealed) == 2


@mark.parametrize("surface", [
    "file_label", "result_edit", "current_edit", "incoming_edit",
    "binary_current", "binary_incoming",
])
def test_conflict_context_menu_reveals_its_file_without_modifying_it(
    qtbot: QtBot, tmp_path: Path, surface: str
) -> None:
    path = tmp_path / "conflict.txt"
    text = "<<<<<<< HEAD\nours\n=======\ntheirs\n>>>>>>> topic\n"
    path.write_text(text, encoding="utf-8")
    editor = ConflictEditor()
    qtbot.addWidget(editor)
    editor.load_file(path, path.name)
    widget = getattr(editor, surface)
    assert isinstance(widget, QWidget)
    revealed: list[object] = []
    editor.file_reveal_requested.connect(revealed.append)
    _choose_reveal(widget)
    assert revealed == [path]
    assert path.read_text(encoding="utf-8") == text
    editor.clear()
    _choose_reveal(widget, enabled=False)


def test_inline_stash_diff_has_a_file_reveal_action(qtbot: QtBot, tmp_path: Path) -> None:
    panel = HistoryPanel()
    qtbot.addWidget(panel)
    panel.show()
    stash = StashInfo("stash@{0}", "a" * 40, "Saved work")
    change = CommitFileChange("M", "folder/tracked.txt")
    panel.show_stash(stash)
    panel.show_stash_files(StashFilesSnapshot(tmp_path, stash, (change,)))
    item = panel.files.topLevelItem(0)
    assert item is not None
    item.setExpanded(True)
    widget = panel.findChild(InlineDiffWidget)
    assert widget is not None
    revealed: list[object] = []
    panel.file_reveal_requested.connect(revealed.append)
    # The path is available even while the preview is still loading.
    _choose_reveal(widget)
    assert revealed == [change]


@mark.parametrize("view_name", ["diffView", "reviewDiffView", "studyDiffView"])
@mark.parametrize("location", ["file", "ancestor", "repository"])
def test_all_diff_views_open_the_correct_file_or_nearest_existing_folder(
    qtbot: QtBot, monkeypatch: MonkeyPatch, tmp_path: Path, view_name: str, location: str
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    subprocess.run(["git", "init", "--initial-branch=main", str(repository)], check=True,
                   capture_output=True)
    path = repository / "folder" / "removed" / "file name.txt"
    if location == "file":
        path.parent.mkdir(parents=True)
        path.write_text("content\n", encoding="utf-8")
    elif location == "ancestor":
        (repository / "folder").mkdir()
    settings = QSettings(str(tmp_path / "ui.ini"), QSettings.Format.IniFormat)
    window = MainWindow(settings, Theme.SYSTEM)
    qtbot.addWidget(window)
    service = window.findChild(GitService)
    assert service is not None
    with qtbot.waitSignal(service.status_ready, timeout=5000):
        window.open_repository(repository)
    opened: list[Path] = []
    detached: list[tuple[str, list[str], str]] = []

    def open_url(url: QUrl) -> bool:
        opened.append(Path(url.toLocalFile()))
        return True

    def start_detached(program: str, arguments: list[str], directory: str) -> tuple[bool, int]:
        detached.append((program, arguments, directory))
        return True, 1

    monkeypatch.setattr(QDesktopServices, "openUrl", open_url)
    monkeypatch.setattr(QProcess, "startDetached", start_detached)
    view = window.findChild(DiffView, view_name)
    assert view is not None
    relative = path.relative_to(repository).as_posix()
    view.display_diff(
        parse_unified_diff(b"@@ -1 +1 @@\n-old\n+new\n", relative, staged=False),
        selection_key=(repository, relative, False), preserve_scroll=False, whole_file_staged=False,
    )
    _choose_reveal(view.file_header)
    folder = (
        path.parent if location == "file"
        else repository / "folder" if location == "ancestor"
        else repository
    )
    if sys.platform == "win32":
        arguments = ["/select,", str(path)] if location == "file" else [str(folder)]
        assert detached == [("explorer.exe", arguments, str(folder))]
    else:
        assert opened == [folder]
    # Historical paths must never let file navigation leave the repository.
    view.file_reveal_requested.emit("../../outside.txt")
    assert len(opened) + len(detached) == 1
    window.close()
