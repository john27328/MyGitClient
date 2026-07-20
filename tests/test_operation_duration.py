from mygitclient.ui.main_window import format_operation_duration


def test_operation_duration_formats_minutes_and_hours() -> None:
    assert format_operation_duration(0) == "0:00"
    assert format_operation_duration(65_999) == "1:05"
    assert format_operation_duration(3_661_000) == "1:01:01"
