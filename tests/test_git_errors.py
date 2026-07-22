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


def test_push_rejection_suggests_fetch_and_pull() -> None:
    formatted = format_git_error(
        "! [rejected] main -> main (fetch first)\nerror: failed to push some refs",
        operation="push changes",
    )

    assert "Fetch, then Pull or Rebase" in formatted


def test_network_and_authentication_errors_are_understandable() -> None:
    auth = format_git_error("fatal: Authentication failed", operation="fetch changes")
    network = format_git_error(
        "fatal: unable to access remote: Could not resolve host: example.invalid",
        operation="fetch changes",
    )

    assert "credential helper" in auth
    assert "Check your network connection" in network


def test_index_lock_error_explains_safe_recovery() -> None:
    formatted = format_git_error(
        "fatal: Unable to create "
        "'C:/work/project/.git/index.lock': File exists.\n"
        "Another git process seems to be running in this repository.",
        operation="stage files",
    )

    assert "temporarily locked by another Git operation" in formatted
    assert "Wait for it to finish" in formatted
    assert "C:/work/project/.git/index.lock" in formatted
    assert "Another git process" not in formatted
