from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMenu
from pytestqt.qtbot import QtBot

from mygitclient.git.models import CommitFileChange, CommitFilesSnapshot, CommitPage, CommitSummary
from mygitclient.ui.diff_study_panel import DiffStudyPanel

COMMIT = CommitSummary(
    oid="0123456789abcdef",
    parent_oids=("fedcba9876543210",),
    author_name="Test Author",
    author_email="author@example.invalid",
    authored_at="2026-08-24T14:00:00+03:00",
    subject="Add commit details",
)


def test_selected_commit_shows_details_above_files(qtbot: QtBot) -> None:
    panel = DiffStudyPanel()
    qtbot.addWidget(panel)
    panel.show_page(CommitPage(Path("repository"), (COMMIT,), 0, False))
    item = panel.commits.topLevelItem(0)
    assert item is not None

    panel.commits.setCurrentItem(item)

    header = panel.context_label.text().split("\n")
    assert header[0] == "01234567 · Add commit details"
    assert header[1].startswith("Test Author · ")
    assert panel.context_label.text().count("Add commit details") == 1
    assert "0123456789abcdef" in panel.context_label.toolTip()
    assert "Parents: fedcba98" in panel.context_label.toolTip()


def _panel_with_files(
    qtbot: QtBot, settings: QSettings, files: tuple[CommitFileChange, ...]
) -> DiffStudyPanel:
    panel = DiffStudyPanel(settings)
    qtbot.addWidget(panel)
    panel.show_page(CommitPage(Path("repository"), (COMMIT,), 0, False))
    commit_item = panel.commits.topLevelItem(0)
    assert commit_item is not None
    panel.commits.setCurrentItem(commit_item)
    panel.show_files(CommitFilesSnapshot(Path("repository"), COMMIT.oid, files))
    return panel


def test_diff_files_switch_to_tree_without_reloading_the_diff(
    qtbot: QtBot, tmp_path: Path
) -> None:
    settings = QSettings(str(tmp_path / "diff.ini"), QSettings.Format.IniFormat)
    files = (CommitFileChange("M", "src/a.cs"), CommitFileChange("A", "src/b.cs"))
    panel = _panel_with_files(qtbot, settings, files)
    assert panel.select_first_file()
    selected: list[object] = []

    def record(_commit: object, change: object) -> None:
        selected.append(change)

    panel.file_selected.connect(record)

    panel.view_mode.setCurrentIndex(panel.view_mode.findData("tree"))

    folder = panel.files.topLevelItem(0)
    assert folder is not None
    assert folder.text(0) == "src"
    assert [item.text(0) for item in panel.files.file_items()] == ["a.cs", "b.cs"]
    assert panel.files.selected_change == files[0]
    assert selected == []
    assert settings.value("diff/filesViewMode") == "tree"


def test_diff_files_offer_a_context_menu(qtbot: QtBot, tmp_path: Path) -> None:
    settings = QSettings(str(tmp_path / "diff.ini"), QSettings.Format.IniFormat)
    files = (CommitFileChange("M", "src/a.cs"), CommitFileChange("A", "src/b.cs"))
    panel = _panel_with_files(qtbot, settings, files)
    opened: list[object] = []
    revealed: list[object] = []
    panel.file_open_requested.connect(opened.append)
    panel.file_reveal_requested.connect(revealed.append)
    labels: list[str] = []

    def choose(index: int) -> None:
        popup = QApplication.activePopupWidget()
        if not isinstance(popup, QMenu):
            return
        try:
            labels[:] = [action.text() for action in popup.actions() if action.text()]
            for _ in range(index + 1):
                QTest.keyClick(popup, Qt.Key.Key_Down)
            QTest.keyClick(popup, Qt.Key.Key_Return)
        finally:
            popup.close()

    second = panel.files.file_items()[1]
    position = panel.files.visualItemRect(second).center()
    QTimer.singleShot(0, lambda: choose(0))
    panel.files.customContextMenuRequested.emit(position)
    QTimer.singleShot(0, lambda: choose(1))
    panel.files.customContextMenuRequested.emit(position)

    assert labels == ["Open", "Show in File Manager", "Restore file to"]
    assert opened == [files[1]]
    assert revealed == [files[1]]
