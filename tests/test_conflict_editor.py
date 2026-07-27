from pathlib import Path

from PySide6.QtWidgets import QPlainTextEdit, QPushButton, QStackedWidget
from pytestqt.qtbot import QtBot

from mygitclient.ui.conflict_editor import ConflictEditor


def _conflicted_text() -> str:
    return (
        "before\n"
        "<<<<<<< HEAD\n"
        "current\n"
        "=======\n"
        "incoming\n"
        ">>>>>>> feature\n"
        "after\n"
    )


def test_conflict_editor_compares_and_resolves_selected_block(
    qtbot: QtBot, tmp_path: Path
) -> None:
    path = tmp_path / "conflicted.txt"
    path.write_text(_conflicted_text(), encoding="utf-8")
    editor = ConflictEditor()
    qtbot.addWidget(editor)

    editor.load_file(path, "conflicted.txt")

    stack = editor.findChild(QStackedWidget, "conflictModeStack")
    compare = editor.findChild(QPushButton, "conflictCompareModeButton")
    current = editor.findChild(QPlainTextEdit, "conflictCurrentEdit")
    incoming = editor.findChild(QPlainTextEdit, "conflictIncomingEdit")
    use_both = editor.findChild(QPushButton, "useBothConflictBlockButton")
    save = editor.findChild(QPushButton, "saveResolvedConflictButton")
    assert stack is not None
    assert compare is not None
    assert current is not None
    assert incoming is not None
    assert use_both is not None
    assert save is not None
    assert current.toPlainText() == "current\n"
    assert incoming.toPlainText() == "incoming\n"
    assert not save.isEnabled()

    compare.click()
    assert stack.currentIndex() == 1

    use_both.click()
    assert stack.currentIndex() == 0
    assert editor.result_edit.toPlainText() == "before\ncurrent\nincoming\nafter\n"
    assert save.isEnabled()


def test_conflict_editor_emits_manually_edited_result(
    qtbot: QtBot, tmp_path: Path
) -> None:
    path = tmp_path / "conflicted.txt"
    path.write_text(_conflicted_text(), encoding="utf-8")
    editor = ConflictEditor()
    qtbot.addWidget(editor)
    editor.load_file(path, "conflicted.txt")
    editor.result_edit.setPlainText("manually resolved\n")
    saved: list[tuple[object, str]] = []

    def capture_save(value: object, content: str) -> None:
        saved.append((value, content))

    editor.save_requested.connect(capture_save)

    editor.save_button.click()

    assert saved == [(path, "manually resolved\n")]


def test_conflict_editor_does_not_replace_unsaved_result(
    qtbot: QtBot, tmp_path: Path
) -> None:
    path = tmp_path / "conflicted.txt"
    path.write_text(_conflicted_text(), encoding="utf-8")
    editor = ConflictEditor()
    qtbot.addWidget(editor)
    editor.load_file(path, "conflicted.txt")
    editor.result_edit.insertPlainText("manual change")
    path.write_text("changed on disk\n", encoding="utf-8")

    editor.load_file(path, "conflicted.txt")

    assert "manual change" in editor.result_edit.toPlainText()
