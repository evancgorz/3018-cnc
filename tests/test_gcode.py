from pathlib import Path

import pytest

from ttc3018_control.gcode import GCodeError, Point, parse_gcode, validate_nonnegative_work_xy


def test_parses_metric_absolute_program_and_bounds() -> None:
    program = parse_gcode("G21 G90\nG0 X1 Y2 Z3\nG1 X11 Y7 Z-0.5 F100\nM5", Path("job.nc"))
    assert program.commands == ("G21 G90", "G0 X1 Y2 Z3", "G1 X11 Y7 Z-0.5 F100", "M5")
    assert program.bounds.minimum == Point(0, 0, -0.5)
    assert program.bounds.maximum == Point(11, 7, 3)
    assert len(program.segments) == 2


def test_relative_motion_updates_bounds() -> None:
    program = parse_gcode("G21 G91\nG1 X5 Y-2\nG1 X3 Y4")
    assert program.bounds.minimum == Point(0, -2, 0)
    assert program.bounds.maximum == Point(8, 2, 0)


def test_ij_arc_includes_extrema() -> None:
    program = parse_gcode("G21 G90\nG0 X1 Y0\nG3 X-1 Y0 I-1 J0")
    assert program.bounds.maximum.y == pytest.approx(1, abs=0.01)
    assert program.bounds.minimum.x == pytest.approx(-1, abs=0.01)


def test_work_xy_gate_rejects_negative_arc_extrema_even_when_endpoints_are_safe() -> None:
    program = parse_gcode("G21 G90\nG0 X2 Y0\nG3 X2 Y0 I-1 J0")

    with pytest.raises(GCodeError, match="negative work [XY]"):
        validate_nonnegative_work_xy(program)


def test_work_xy_gate_allows_negative_cutting_z() -> None:
    program = parse_gcode("G21 G90\nG0 X1 Y1 Z1\nG1 X2 Y2 Z-3 F100")

    validate_nonnegative_work_xy(program)


def test_work_xy_gate_rejects_negative_linear_coordinate() -> None:
    program = parse_gcode("G21 G90\nG0 X1 Y1\nG1 X-0.01 Y1 F100")

    with pytest.raises(GCodeError, match="negative work X"):
        validate_nonnegative_work_xy(program)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("G20\nG1 X1", "inch mode"),
        ("$H", "system commands"),
        ("G38.2 Z-5", "unsafe motion"),
        ("M6 T2\nG1 X1", "tool changes"),
        ("G2 X1 Y1 R1", "I/J"),
    ],
)
def test_rejects_unsafe_or_unsupported_programs(text: str, message: str) -> None:
    with pytest.raises(GCodeError, match=message):
        parse_gcode(text)
