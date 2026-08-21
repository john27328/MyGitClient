from mygitclient.github.oauth_http import parse_token_response


def test_parse_token_response_reads_a_granted_token() -> None:
    granted = parse_token_response({"access_token": "github-token", "token_type": "bearer"})

    assert granted.access_token == "github-token"
    assert not granted.error
    assert not granted.refresh_token
    assert granted.expires_in == 0


def test_parse_token_response_keeps_renewal_fields() -> None:
    granted = parse_token_response(
        {
            "access_token": "github-token",
            "refresh_token": "renewal-token",
            "expires_in": 28800,
            "token_type": "bearer",
        }
    )

    assert granted.access_token == "github-token"
    assert granted.refresh_token == "renewal-token"
    assert granted.expires_in == 28800


def test_parse_token_response_surfaces_an_error_without_a_token() -> None:
    refused = parse_token_response({"error": "bad_verification_code"})

    assert not refused.access_token
    assert refused.error == "bad_verification_code"


def test_parse_token_response_ignores_fields_of_the_wrong_type() -> None:
    granted = parse_token_response(
        {"access_token": "github-token", "expires_in": "28800", "refresh_token": None}
    )

    assert granted.access_token == "github-token"
    assert granted.expires_in == 0
    assert not granted.refresh_token
