from __future__ import annotations

from mygitclient.ui.commit_text import generated_commit_text


def test_small_commit_description_lists_every_file() -> None:
    message, description = generated_commit_text(
        [("Add", "README.md"), ("Update", "src/mygitclient/app.py")]
    )

    assert message == "Update 2 files"
    assert description == "- Add README.md\n- Update src/mygitclient/app.py"


def test_large_commit_description_groups_folders_and_has_a_hard_line_limit() -> None:
    changes = [
        ("Update", f"notes/area-{group}/topic-{number}.md")
        for group in range(30)
        for number in range(25)
    ]

    message, description = generated_commit_text(changes)

    assert message == "Update 750 files"
    assert len(description.splitlines()) == 13
    assert "- Update notes/area-0/ (25 files)" in description
    assert description.endswith("- … and 450 more files")
    assert len(description) < 2500
