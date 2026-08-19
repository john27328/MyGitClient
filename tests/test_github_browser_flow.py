from mygitclient.github.browser_flow import parse_callback_query


def test_parse_callback_query_extracts_code_with_matching_state() -> None:
    code, error = parse_callback_query(
        "/callback?code=abc123&state=xyz", expected_state="xyz"
    )

    assert code == "abc123"
    assert error is None


def test_parse_callback_query_rejects_mismatched_state() -> None:
    code, error = parse_callback_query(
        "/callback?code=abc123&state=wrong", expected_state="xyz"
    )

    assert code is None
    assert error is not None and "failed validation" in error


def test_parse_callback_query_rejects_missing_state() -> None:
    code, error = parse_callback_query("/callback?code=abc123", expected_state="xyz")

    assert code is None
    assert error is not None and "failed validation" in error


def test_parse_callback_query_surfaces_github_error() -> None:
    code, error = parse_callback_query(
        "/callback?error=access_denied&error_description=The+user+cancelled&state=xyz",
        expected_state="xyz",
    )

    assert code is None
    assert error == "GitHub authorization failed: The user cancelled"


def test_parse_callback_query_requires_code() -> None:
    code, error = parse_callback_query("/callback?state=xyz", expected_state="xyz")

    assert code is None
    assert error == "GitHub did not return an authorization code."
