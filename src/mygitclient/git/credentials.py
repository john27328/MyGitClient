from __future__ import annotations

import base64


def github_extraheader_arguments(token: str) -> tuple[str, ...]:
    """Global ``git -c`` arguments authenticating HTTPS requests to github.com.

    Scoped to the github.com URL prefix via ``http.<url>.extraheader`` so the
    token is only ever sent to GitHub, never to any other configured remote.
    """
    credentials = base64.b64encode(f"x-access-token:{token}".encode()).decode("ascii")
    return (
        "-c",
        f"http.https://github.com/.extraheader=AUTHORIZATION: basic {credentials}",
    )
