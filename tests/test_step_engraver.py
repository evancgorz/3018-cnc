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


@pytest.mark.parametrize("mode", ["Engraving", "Profile cutout", "Outside contour", "Inside contour", "Pocket", "Hole"])
def test_step_modes_generate_parser_accepted_metric_gcode(mode: str) -> None:
    job = generate_step_gcode(
        _model(), mode=mode, stock_width=50, stock_height=35, zero_location="Center", depth=-1, passes=2
    )

    program = parse_gcode(job.gcode)

    expected_depth = -5.2 if mode == "Profile cutout" else -1
    assert program.bounds.minimum.z == pytest.approx(expected_depth)
    assert program.bounds.maximum.z == pytest.approx(3)
    assert job.stroke_count > 0
    if mode == "Profile cutout":
        assert job.gcode.count("G1 Z") >= job.stroke_count * 2
    else:
        assert job.gcode.count("G1 Z") == job.stroke_count * 2


def test_profile_cutout_orders_inner_first_and_leaves_outer_tabs() -> None:
    job = generate_step_gcode(
        _model(),
        mode="Profile cutout",
        stock_width=50,
        stock_height=35,
        zero_location="Center",
        tool_diameter=3,
        stock_thickness=5,
        breakthrough=0.2,
        passes=3,
        tab_count=4,
        tab_width=4,
        tab_height=0.8,
    )
    program = parse_gcode(job.gcode)

    inner_x = [point[0] for point in job.strokes[0]]
    outer_x = [point[0] for point in job.strokes[-1]]
    assert max(inner_x) - min(inner_x) == pytest.approx(5, abs=0.05)
    assert max(outer_x) - min(outer_x) == pytest.approx(43, abs=0.05)
    assert program.bounds.minimum.z == pytest.approx(-5.2)
    assert "G1 Z-4.2 F100" in job.gcode
    assert job.stock_thickness == 5
    assert job.breakthrough == pytest.approx(0.2)
    assert job.tab_count == 4


def test_profile_cutout_rejects_invalid_through_cut_and_tabs() -> None:
    with pytest.raises(ValueError, match="Stock thickness"):
        generate_step_gcode(_model(), mode="Profile cutout", stock_thickness=0)
    with pytest.raises(ValueError, match="Tab height"):
        generate_step_gcode(_model(), mode="Profile cutout", stock_thickness=2, tab_height=2)
    with pytest.raises(ValueError, match="too short"):
        generate_step_gcode(
            _model(), mode="Profile cutout", stock_width=50, stock_height=35,
            zero_location="Center", stock_thickness=5, tab_count=12, tab_width=20,
        )


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
