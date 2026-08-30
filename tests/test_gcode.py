from pathlib import Path

import pytest

from ttc3018_control.gcode import GCodeError, Point, parse_gcode


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
