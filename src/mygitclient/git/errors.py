import re
from dataclasses import dataclass
from enum import StrEnum


class GitError(RuntimeError):
    """Base error raised by the Git integration."""


class GitNotFoundError(GitError):
    """Raised when the Git executable cannot be located."""


class GitParseError(GitError):
    """Raised when machine-readable Git output is malformed."""


class GitErrorCategory(StrEnum):
    LOCKED = "locked"
    NON_FAST_FORWARD = "non_fast_forward"
    AUTHENTICATION = "authentication"
    NETWORK = "network"
    LOCAL_CHANGES = "local_changes"
    CONFLICT = "conflict"
    MISSING_REFERENCE = "missing_reference"
    PERMISSION = "permission"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class GitErrorDetails:
    category: GitErrorCategory
    summary: str
    recovery: str | None = None
    details: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    raw_message: str = ""

    @property
    def display_message(self) -> str:
        sections = [self.summary]
        if self.recovery:
            sections.append(self.recovery)
        if self.details:
            sections.append("Affected files:\n" + "\n".join(f"• {item}" for item in self.details))
        if self.warnings:
            sections.append(
                "Repository warning: fix the invalid entry in .gitattributes:\n"
                + "\n".join(self.warnings)
            )
        return "\n\n".join(sections)


def analyze_git_error(message: str, *, operation: str) -> GitErrorDetails:
    lines = [line.strip() for line in message.splitlines() if line.strip()]
    warnings = tuple(
        line for line in lines if "is not a valid attribute name" in line
    )
    errors = [line for line in lines if line not in warnings]
    text = "\n".join(errors) or f"Could not {operation}"
    lowered = text.casefold()
    if "index.lock" in lowered and "file exists" in lowered:
        lock_match = re.search(
            r"unable to create ['\"](?P<path>.+?index\.lock)['\"]",
            text,
            flags=re.IGNORECASE,
        )
        lock_path = lock_match.group("path") if lock_match is not None else None
        recovery = "Wait for it to finish, then try again."
        if lock_path is not None:
            recovery += (
                " If no other Git application is running and the error persists, "
                f"remove the stale lock file:\n{lock_path}"
            )
        return GitErrorDetails(
            GitErrorCategory.LOCKED,
            "This repository is temporarily locked by another Git operation.",
            recovery,
            warnings=warnings,
            raw_message=message,
        )
    if "non-fast-forward" in lowered or "fetch first" in lowered:
        return GitErrorDetails(
            GitErrorCategory.NON_FAST_FORWARD,
            "Push was rejected because the remote branch contains changes you do not have locally.",
            "Fetch, then Pull or Rebase, and push again.",
            warnings=warnings,
            raw_message=message,
        )
    if "authentication failed" in lowered or "could not read username" in lowered:
        return GitErrorDetails(
            GitErrorCategory.AUTHENTICATION,
            "Authentication failed.",
            "Check the remote URL and your system Git credential helper, then try again.",
            warnings=warnings,
            raw_message=message,
        )
    if any(
        marker in lowered
        for marker in ("could not resolve host", "failed to connect", "network is unreachable")
    ):
        return GitErrorDetails(
            GitErrorCategory.NETWORK,
            "Could not reach the remote.",
            "Check your network connection and remote URL, then try again.",
            warnings=warnings,
            raw_message=message,
        )
    if "local changes to the following files would be overwritten by checkout" in lowered:
        paths: list[str] = []
        collecting = False
        for line in errors:
            local_changes_marker = (
                "local changes to the following files would be overwritten by checkout"
            )
            if local_changes_marker in line.casefold():
                collecting = True
            elif collecting and line.startswith(("Please ", "Aborting")):
                collecting = False
            elif collecting:
                paths.append(line)
        return GitErrorDetails(
            GitErrorCategory.LOCAL_CHANGES,
            "Checkout was blocked by local changes.",
            "Commit or discard them, or enable ‘Stash changes and restore after checkout’.",
            tuple(paths),
            warnings,
            message,
        )
    if "conflict" in lowered or "automatic merge failed" in lowered:
        return GitErrorDetails(
            GitErrorCategory.CONFLICT,
            f"Could not {operation} because Git found conflicts.",
            "Resolve the conflicted files, then continue or abort the operation.",
            warnings=warnings,
            raw_message=message,
        )
    if any(
        marker in lowered
        for marker in ("unknown revision", "ambiguous argument", "did not match any file")
    ):
        return GitErrorDetails(
            GitErrorCategory.MISSING_REFERENCE,
            f"Could not {operation} because the selected reference or path no longer exists.",
            "Refresh the repository and select an existing item.",
            warnings=warnings,
            raw_message=message,
        )
    if "permission denied" in lowered or "access is denied" in lowered:
        return GitErrorDetails(
            GitErrorCategory.PERMISSION,
            f"Could not {operation} because access was denied.",
            "Check file permissions and make sure another application is not holding the file.",
            warnings=warnings,
            raw_message=message,
        )
    return GitErrorDetails(
        GitErrorCategory.UNKNOWN,
        text,
        warnings=warnings,
        raw_message=message,
    )


def format_git_error(message: str, *, operation: str) -> str:
    return analyze_git_error(message, operation=operation).display_message
