from __future__ import annotations

DEFAULT_STASH_MESSAGE = "MyGitClient selected files"


def validate_stash_message(message: str) -> str:
    message = message.strip()
    if not message or any(ord(character) < 32 for character in message):
        raise ValueError("Enter a stash name on a single line.")
    return message


def renamed_stash_commit(content: bytes, message: str) -> bytes:
    """Keep the stash trees, parents and identity; replace only its message."""
    message = validate_stash_message(message)
    header, separator, body = content.partition(b"\n\n")
    if not separator or not header.startswith(b"tree ") or header.count(b"\nparent ") < 2:
        raise ValueError("Git returned an invalid stash commit.")
    # A signature over the old message cannot be retained on the renamed commit.
    headers: list[bytes] = []
    signature = False
    for line in header.split(b"\n"):
        if not line.startswith(b" "):
            signature = line.startswith((b"gpgsig ", b"gpgsig-sha256 "))
        if not signature:
            headers.append(line)
    _subject, _newline, remainder = body.partition(b"\n")
    return b"\n".join(headers) + b"\n\n" + message.encode("utf-8") + b"\n" + remainder
