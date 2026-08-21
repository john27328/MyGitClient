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
    pending = parse_token_response({"error": "authorization_pending", "interval": 7})
    assert not pending.access_token
    assert pending.error == "authorization_pending"
    assert pending.interval == 7

    granted = parse_token_response({"access_token": "github-token", "token_type": "bearer"})
    assert granted.access_token == "github-token"
    assert not granted.error


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
