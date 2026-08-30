from __future__ import annotations

import math
from pathlib import Path

import pytest

from ttc3018_control.gcode import parse_gcode
from ttc3018_control.step_engraver import generate_step_gcode
from ttc3018_control.step_geometry import PlanarLoop, Point2D, StepPlanarModel


def _model() -> StepPlanarModel:
    outer = PlanarLoop(tuple(Point2D(x, y) for x, y in ((0, 0), (40, 0), (40, 25), (0, 25))))
    hole = PlanarLoop(
        tuple(Point2D(10 + 4 * math.cos(index * math.tau / 32), 12.5 + 4 * math.sin(index * math.tau / 32)) for index in range(32))
    )
    return StepPlanarModel(Path("plate.step"), (outer, hole), 5, 5, (0, 0, 0, 40, 25, 5))


@pytest.mark.parametrize("mode", ["Engraving", "Outside contour", "Inside contour", "Pocket", "Hole"])
def test_step_modes_generate_parser_accepted_metric_gcode(mode: str) -> None:
    job = generate_step_gcode(
        _model(), mode=mode, stock_width=50, stock_height=35, zero_location="Center", depth=-1, passes=2
    )

    program = parse_gcode(job.gcode)

    assert program.bounds.minimum.z == pytest.approx(-1)
    assert program.bounds.maximum.z == pytest.approx(3)
    assert job.stroke_count > 0
    assert job.gcode.count("G1 Z") == job.stroke_count * 2


def test_outside_contour_rejects_stock_that_cannot_contain_tool_offset() -> None:
    with pytest.raises(ValueError, match="outside the declared stock"):
        generate_step_gcode(_model(), mode="Outside contour", tool_diameter=3, stock_width=40, stock_height=25)


def test_invalid_depth_pass_settings_are_rejected() -> None:
    with pytest.raises(ValueError, match="whole number"):
        generate_step_gcode(_model(), passes=0)
    with pytest.raises(ValueError, match="Tool diameter"):
        generate_step_gcode(_model(), tool_diameter=0)


def test_malformed_normalized_loop_is_rejected() -> None:
    malformed = StepPlanarModel(
        Path("bad.step"),
        (PlanarLoop((Point2D(0, 0), Point2D(1, 1))),),
        0,
        0,
        (0, 0, 0, 1, 1, 0),
    )
    with pytest.raises(ValueError, match="at least three points"):
        generate_step_gcode(malformed)
