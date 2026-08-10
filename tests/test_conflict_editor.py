from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

from PySide6.QtWidgets import QComboBox, QPlainTextEdit, QPushButton, QStackedWidget
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


def test_conflict_editor_compares_full_sides_with_base(qtbot: QtBot, tmp_path: Path) -> None:
    path = tmp_path / "conflicted.txt"
    path.write_text(_conflicted_text(), encoding="utf-8")
    editor = ConflictEditor()
    qtbot.addWidget(editor)
    editor.load_file(path, "conflicted.txt")
    editor.set_versions(b"same\nbase\n", b"same\ncurrent\n", b"same\nincoming\n")
    combo = editor.findChild(QComboBox, "conflictComparisonCombo")
    assert combo is not None

    combo.setCurrentIndex(combo.findData("base-current"))
    assert editor.current_edit.toPlainText() == "same\nbase\n"
    assert editor.incoming_edit.toPlainText() == "same\ncurrent\n"
    assert editor.current_edit.extraSelections()
    assert editor.incoming_edit.extraSelections()

    combo.setCurrentIndex(combo.findData("base-incoming"))
    assert editor.incoming_edit.toPlainText() == "same\nincoming\n"


def test_conflict_editor_requests_external_merge_tool(qtbot: QtBot) -> None:
    editor = ConflictEditor()
    qtbot.addWidget(editor)

    with qtbot.waitSignal(editor.mergetool_requested, timeout=1000):
        editor.mergetool_button.click()


def test_conflict_editor_uses_binary_mode_and_emits_side_choice(
    qtbot: QtBot, tmp_path: Path
) -> None:
    path = tmp_path / "asset.bin"
    path.write_bytes(b"\x00worktree")
    editor = ConflictEditor()
    qtbot.addWidget(editor)
    choices: list[str] = []
    editor.binary_choice_requested.connect(choices.append)

    editor.load_file(path, "asset.bin")
    editor.set_versions(
        b"\x00base", b"\x00current", b"\x00incoming",
        (("binary", "set"), ("diff", "unset"), ("merge", "custom-driver")),
    )

    assert editor.mode_stack.currentIndex() == 2
    assert "SHA-256" in editor.binary_current.text()
    assert "custom-driver" in editor.binary_current.text()
    editor.use_incoming_button.click()
    assert choices == ["theirs"]


def test_conflict_editor_previews_archive_contents(qtbot: QtBot, tmp_path: Path) -> None:
    archive_bytes = BytesIO()
    with ZipFile(archive_bytes, "w") as archive:
        archive.writestr("docs/readme.txt", "hello")
        archive.writestr("images/icon.png", b"not-an-image")
    data = archive_bytes.getvalue()
    path = tmp_path / "bundle.zip"
    path.write_bytes(data)
    editor = ConflictEditor()
    qtbot.addWidget(editor)

    editor.load_file(path, "bundle.zip")
    editor.set_versions(b"", data, data, (("binary", "set"),))

    assert "Archive contents · 2 files" in editor.binary_current.text()
    assert "docs/readme.txt" in editor.binary_current.text()
