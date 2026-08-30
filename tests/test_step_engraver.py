from __future__ import annotations

import math
from pathlib import Path

import pytest

from ttc3018_control.gcode import parse_gcode
from ttc3018_control.step_engraver import generate_step_gcode
from ttc3018_control.step_geometry import PlanarLoop, Point2D, StepPlanarModel, load_step_isolated


def _model() -> StepPlanarModel:
    outer = PlanarLoop(tuple(Point2D(x, y) for x, y in ((0, 0), (40, 0), (40, 25), (0, 25))))
    hole = PlanarLoop(
        tuple(Point2D(10 + 4 * math.cos(index * math.tau / 32), 12.5 + 4 * math.sin(index * math.tau / 32)) for index in range(32))
    )
    return StepPlanarModel(Path("plate.step"), (outer, hole), 5, 5, (0, 0, 0, 40, 25, 5))


def _solid_model() -> StepPlanarModel:
    outer = PlanarLoop(tuple(Point2D(x, y) for x, y in ((0, 0), (40, 0), (40, 25), (0, 25))))
    return StepPlanarModel(Path("solid-plate.step"), (outer,), 5, 5, (0, 0, 0, 40, 25, 5))


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


@pytest.mark.parametrize("mode", ["Outside contour", "Profile cutout"])
def test_lower_left_cutout_anchors_compensated_envelope_at_work_zero(mode: str) -> None:
    job = generate_step_gcode(
        _model(),
        mode=mode,
        zero_location="Lower-left",
        tool_diameter=3,
        stock_width=43,
        stock_height=28,
        stock_thickness=5 if mode == "Profile cutout" else None,
        tab_count=0,
        depth=-1,
    )

    points = [point for stroke in job.strokes for point in stroke]
    assert min(point[0] for point in points) == pytest.approx(0)
    assert min(point[1] for point in points) == pytest.approx(0)
    part_points = [point for stroke in job.model_strokes for point in stroke]
    assert min(point[0] for point in part_points) == pytest.approx(1.5)
    assert min(point[1] for point in part_points) == pytest.approx(1.5)
    assert job.placement_offset_x == pytest.approx(1.5)
    assert job.placement_offset_y == pytest.approx(1.5)
    assert "G0 X0 Y0" in job.gcode
    program = parse_gcode(job.gcode)
    assert program.bounds.minimum.x >= -0.001
    assert program.bounds.minimum.y >= -0.001


def test_lower_left_profile_applies_placement_to_emitted_profile_commands() -> None:
    job = generate_step_gcode(
        _model(),
        mode="Profile cutout",
        zero_location="Lower-left",
        tool_diameter=3,
        stock_width=43,
        stock_height=28,
        stock_thickness=5,
        tab_count=0,
    )

    program = parse_gcode(job.gcode)
    assert program.bounds.minimum.x == pytest.approx(0, abs=0.001)
    assert program.bounds.minimum.y == pytest.approx(0, abs=0.001)
    assert program.bounds.maximum.x == pytest.approx(43, abs=0.001)
    assert program.bounds.maximum.y == pytest.approx(28, abs=0.001)


def test_pocket_uses_connected_scanlines_for_a_broad_solid_region() -> None:
    job = generate_step_gcode(
        _solid_model(),
        mode="Pocket",
        stock_width=45,
        stock_height=30,
        tool_diameter=3,
        depth=-1,
    )

    assert job.stroke_count == 1
    assert len(job.strokes[0]) > 20
    assert job.cutting_distance > 500
    assert job.rapid_xy_distance < 100
    assert job.retract_count == 1
    program = parse_gcode(job.gcode)
    assert program.bounds.minimum.z == pytest.approx(-1)


def test_pocket_does_not_stay_down_across_an_inner_hole() -> None:
    job = generate_step_gcode(
        _model(),
        mode="Pocket",
        stock_width=45,
        stock_height=30,
        tool_diameter=3,
        depth=-1,
    )

    assert job.stroke_count > 1


def test_wedge_planar_surface_generates_varying_bounded_gcode_without_cliff_bridge() -> None:
    model = load_step_isolated(Path(__file__).parents[1] / "examples" / "wedge.step")
    job = generate_step_gcode(
        model,
        mode="Planar surface",
        stock_width=30,
        stock_height=15,
        tool_diameter=3.175,
        passes=2,
        safe_z=3,
    )

    program = parse_gcode(job.gcode)
    assert job.surface_paths
    assert len({round(point[2], 3) for path in job.surface_paths for point in path}) > 5
    assert program.bounds.minimum.z == pytest.approx(-5.983, abs=0.01)
    assert program.bounds.maximum.z == pytest.approx(3)
    assert program.bounds.minimum.x >= -0.001
    assert program.bounds.minimum.y >= -0.001
    cutting_segments = [
        segment for segment in program.segments
        if not segment.rapid and math.hypot(segment.end.x - segment.start.x, segment.end.y - segment.start.y) > 0.1
    ]
    assert all(
        abs(segment.end.z - segment.start.z)
        <= max(0.5, 1.75 * math.hypot(segment.end.x - segment.start.x, segment.end.y - segment.start.y)) + 0.01
        for segment in cutting_segments
    )


def test_centered_cutout_retains_existing_explicit_placement() -> None:
    job = generate_step_gcode(
        _model(),
        mode="Profile cutout",
        zero_location="Center",
        tool_diameter=3,
        stock_width=43,
        stock_height=28,
        stock_thickness=5,
        tab_count=0,
    )

    assert job.placement_offset_x == 0
    assert job.placement_offset_y == 0
    program = parse_gcode(job.gcode)
    assert program.bounds.minimum.x == pytest.approx(0, abs=0.001)
    assert program.bounds.minimum.y == pytest.approx(0, abs=0.001)


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


def test_step_fixtures_distinguish_removed_and_extruded_circle_features() -> None:
    examples = Path(__file__).parents[1] / "examples"
    removed = load_step_isolated(examples / "removed-cylinder.step")
    extruded = load_step_isolated(examples / "extruded-circle.step")

    assert [(feature.kind, feature.loop_index) for feature in removed.features] == [("Recess", 1)]
    assert [(feature.kind, feature.loop_index) for feature in extruded.features] == [("Raised boss", 1)]
    assert removed.features[0].depth == pytest.approx(2)
    assert extruded.features[0].depth == pytest.approx(2)

    removed_job = generate_step_gcode(removed, mode="Detected feature", tool_diameter=3.175, passes=2)
    extruded_job = generate_step_gcode(extruded, mode="Detected feature", tool_diameter=3.175, passes=2)
    removed_program = parse_gcode(removed_job.gcode)
    extruded_program = parse_gcode(extruded_job.gcode)

    removed_points = [point for stroke in removed_job.strokes for point in stroke]
    extruded_points = [point for stroke in extruded_job.strokes for point in stroke]
    removed_width = max(point[0] for point in removed_points) - min(point[0] for point in removed_points)
    extruded_width = max(point[0] for point in extruded_points) - min(point[0] for point in extruded_points)
    assert removed_width < 10  # Clear inside the circular recess.
    assert extruded_width > 25  # Clear the surrounding rectangle, leaving the boss.
    assert removed_program.bounds.minimum.z == pytest.approx(-2)
    assert extruded_program.bounds.minimum.z == pytest.approx(-2)
    assert removed_job.feature_summary == "Recess 2.00 mm"
    assert extruded_job.feature_summary == "Raised boss 2.00 mm"


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
