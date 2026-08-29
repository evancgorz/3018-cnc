import pytest

from ttc3018_control.grbl import Position, make_jog, make_setting, make_work_zero, parse_setting, parse_status


def test_parse_status_from_ttc3018() -> None:
    status = parse_status(
        "<Idle|MPos:7.000,1.000,20.000|Bf:15,128|FS:0,0|Pn:PXYZ|WCO:0.000,0.000,0.000>"
    )
    assert status is not None
    assert status.state == "Idle"
    assert status.machine_position == Position(7.0, 1.0, 20.0)
    assert status.work_offset == Position(0.0, 0.0, 0.0)
    assert status.feed == 0
    assert status.spindle == 0
    assert status.pins == "PXYZ"
    assert status.can_jog


def test_parse_status_tolerates_serial_prefix() -> None:
    status = parse_status("?<Run|WPos:1.250,2.500,3.750|FS:100,0>")
    assert status is not None
    assert status.state == "Run"
    assert status.work_position == Position(1.25, 2.5, 3.75)
    assert not status.can_jog


def test_non_status_line_returns_none() -> None:
    assert parse_status("ok") is None


def test_make_jog() -> None:
    assert make_jog("z", 1, 50) == b"$J=G91 G21 Z1 F50\n"
    assert make_jog("X", -5, 100) == b"$J=G91 G21 X-5 F100\n"


def test_make_work_zero() -> None:
    assert make_work_zero("z") == b"G10 L20 P1 Z0\n"
    assert make_work_zero("ZYX") == b"G10 L20 P1 X0 Y0 Z0\n"


def test_commissioning_settings() -> None:
    assert parse_setting("$22=1") == (22, 1.0)
    assert parse_setting("message") is None
    assert make_setting(27, 2) == b"$27=2\n"
    with pytest.raises(ValueError):
        make_setting(100, 250)


@pytest.mark.parametrize(
    ("axis", "distance", "feed"),
    [("A", 1, 100), ("X", 0, 100), ("X", 1, 0), ("X", 1, 1501)],
)
def test_invalid_jog_is_rejected(axis: str, distance: float, feed: float) -> None:
    with pytest.raises(ValueError):
        make_jog(axis, distance, feed)
