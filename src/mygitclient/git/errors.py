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
