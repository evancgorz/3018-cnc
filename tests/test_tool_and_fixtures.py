import pytest

from ttc3018_control.fixture_settings import FixtureRecord, fixture_record_from_dict, fixture_record_to_dict
from ttc3018_control.grbl import Position
from ttc3018_control.tool_settings import ToolSetterRecord, calculate_tool_length_offset


def test_tool_setter_requires_repeatable_three_sample_record() -> None:
    with pytest.raises(ValueError, match="three"):
        ToolSetterRecord("m1", Position(1, 2, 3), 10, samples=(1, 2)).validate()
    record = ToolSetterRecord("m1", Position(1, 2, 3), 10, tolerance=0.05, samples=(4.00, 4.02, 4.01))
    record.validate()
    assert record.commissioned
    with pytest.raises(ValueError, match="repeatability"):
        ToolSetterRecord("m1", Position(1, 2, 3), 10, tolerance=0.05, samples=(4.00, 4.1, 4.01)).validate()


@pytest.mark.parametrize(("reference", "measured", "expected"), [(10, 8, 2), (8, 10, -2)])
def test_tool_offset_math(reference, measured, expected) -> None:
    assert calculate_tool_length_offset(reference, measured) == expected


def test_fixture_round_trip_and_origin_compensation() -> None:
    record = FixtureRecord("m1", "vise", 2, Position(10, 20, 30), Position(1, -2, 0.5), 100, 50)
    restored = fixture_record_from_dict(fixture_record_to_dict(record))
    assert restored == record
    assert record.measured_origin(Position(12, 22, 5)) == Position(13, 20, 5.5)


def test_fixture_validates_wcs_slot() -> None:
    with pytest.raises(ValueError, match="WCS"):
        FixtureRecord("m1", "bad", 7, Position(0, 0, 0)).validate()

