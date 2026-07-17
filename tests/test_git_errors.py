from mygitclient.git.errors import format_git_error


def test_checkout_error_separates_local_changes_from_attribute_warning() -> None:
    message = (
        "#Innosetup is not a valid attribute name: .gitattributes:20\n"
        "error: Your local changes to the following files would be overwritten by checkout:\n"
        "\tnotes/manifest.json\n"
        "Please commit your changes or stash them before you switch branches.\n"
        "Aborting"
    )

    formatted = format_git_error(message, operation="checkout branch")

    assert "Checkout was blocked by local changes" in formatted
    assert "• notes/manifest.json" in formatted
    assert "Repository warning" in formatted
    assert ".gitattributes:20" in formatted
