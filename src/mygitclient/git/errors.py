class GitError(RuntimeError):
    """Base error raised by the Git integration."""


class GitNotFoundError(GitError):
    """Raised when the Git executable cannot be located."""


class GitParseError(GitError):
    """Raised when machine-readable Git output is malformed."""

