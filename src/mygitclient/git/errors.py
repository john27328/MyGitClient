import re


class GitError(RuntimeError):
    """Base error raised by the Git integration."""


class GitNotFoundError(GitError):
    """Raised when the Git executable cannot be located."""


class GitParseError(GitError):
    """Raised when machine-readable Git output is malformed."""


def format_git_error(message: str, *, operation: str) -> str:
    lines = [line.strip() for line in message.splitlines() if line.strip()]
    attribute_warnings = [
        line for line in lines if "is not a valid attribute name" in line
    ]
    errors = [line for line in lines if line not in attribute_warnings]
    text = "\n".join(errors) or f"Could not {operation}"
    lowered = text.casefold()
    if "index.lock" in lowered and "file exists" in lowered:
        lock_match = re.search(
            r"unable to create ['\"](?P<path>.+?index\.lock)['\"]",
            text,
            flags=re.IGNORECASE,
        )
        lock_path = lock_match.group("path") if lock_match is not None else None
        text = (
            "This repository is temporarily locked by another Git operation. "
            "Wait for it to finish, then try again."
        )
        if lock_path is not None:
            text += (
                "\n\nIf no other Git application is running and the error persists, "
                f"remove the stale lock file:\n{lock_path}"
            )
    elif "non-fast-forward" in lowered or "fetch first" in lowered:
        text = (
            "Push was rejected because the remote branch contains changes you do not "
            "have locally. Fetch, then Pull or Rebase, and push again."
        )
    elif "authentication failed" in lowered or "could not read username" in lowered:
        text = (
            "Authentication failed. Check the remote URL and your system Git credential "
            "helper, then try again."
        )
    elif any(
        marker in lowered
        for marker in ("could not resolve host", "failed to connect", "network is unreachable")
    ):
        text = "Could not reach the remote. Check your network connection and remote URL."
    if "local changes to the following files would be overwritten by checkout" in text:
        marker = (
            "error: Your local changes to the following files would be overwritten "
            "by checkout:"
        )
        paths: list[str] = []
        collecting = False
        for line in errors:
            if line == marker:
                collecting = True
            elif collecting and line.startswith(("Please ", "Aborting")):
                collecting = False
            elif collecting:
                paths.append(line)
        file_list = "\n".join(f"• {path}" for path in paths)
        text = (
            "Checkout was blocked by local changes. Commit or discard them, or enable "
            "‘Stash changes and restore after checkout’."
        )
        if file_list:
            text += f"\n\nAffected files:\n{file_list}"
    if attribute_warnings:
        text += (
            "\n\nRepository warning: fix the invalid entry in .gitattributes:\n"
            + "\n".join(attribute_warnings)
        )
    return text
