import pytest

from mygitclient.github.device_flow import (
    DeviceFlowError,
    parse_device_authorization,
    parse_token_response,
)


def test_parse_device_authorization() -> None:
    authorization = parse_device_authorization(
        {
            "device_code": "device-secret",
            "user_code": "ABCD-1234",
            "verification_uri": "https://github.com/login/device",
            "expires_in": 900,
            "interval": 5,
        }
    )

    assert authorization.user_code == "ABCD-1234"
    assert authorization.expires_in == 900
    assert authorization.interval == 5


def test_parse_device_authorization_surfaces_github_error() -> None:
    with pytest.raises(DeviceFlowError, match="Device Flow is not enabled"):
        parse_device_authorization(
            {"error": "device_flow_disabled", "error_description": "Device Flow is not enabled"}
        )


def test_parse_token_response_supports_pending_and_success() -> None:
    assert parse_token_response({"error": "authorization_pending", "interval": 7}) == (
        None,
        "authorization_pending",
        7,
    )
    assert parse_token_response({"access_token": "github-token", "token_type": "bearer"}) == (
        "github-token",
        None,
        None,
    )
