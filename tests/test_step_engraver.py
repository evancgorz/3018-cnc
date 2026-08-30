from __future__ import annotations

import math
from pathlib import Path

import pytest
from shapely.geometry import Polygon

from ttc3018_control.gcode import parse_gcode
from ttc3018_control.step_engraver import _best_stroke_orientation, _improve_tagged_order, _pocket_path_cost, _pocket_strokes, _planar_surface_paths, _schedule_depth_groups, _scheduled_path_cost, generate_step_gcode
from ttc3018_control.step_geometry import PlanarLoop, PlanarSurfacePatch, Point2D, StepFeature, StepPlanarModel, load_step_isolated


def _model() -> StepPlanarModel:
    outer = PlanarLoop(tuple(Point2D(x, y) for x, y in ((0, 0), (40, 0), (40, 25), (0, 25))))
    hole = PlanarLoop(
        tuple(Point2D(10 + 4 * math.cos(index * math.tau / 32), 12.5 + 4 * math.sin(index * math.tau / 32)) for index in range(32))
    )
    return StepPlanarModel(Path("plate.step"), (outer, hole), 5, 5, (0, 0, 0, 40, 25, 5))


def _solid_model() -> StepPlanarModel:
    outer = PlanarLoop(tuple(Point2D(x, y) for x, y in ((0, 0), (40, 0), (40, 25), (0, 25))))
    return StepPlanarModel(Path("solid-plate.step"), (outer,), 5, 5, (0, 0, 0, 40, 25, 5))


def _translated_model() -> StepPlanarModel:
    outer = PlanarLoop(tuple(Point2D(x, y) for x, y in ((-10, -8), (30, -8), (30, 17), (-10, 17))))
    hole = PlanarLoop(
        tuple(Point2D(-5 + 4 * math.cos(index * math.tau / 32), 4.5 + 4 * math.sin(index * math.tau / 32)) for index in range(32))
    )
    return StepPlanarModel(Path("translated-plate.step"), (outer, hole), 5, 5, (-10, -8, 0, 30, 17, 5))


@pytest.mark.parametrize("mode", ["Engraving", "Profile cutout", "Outside contour", "Inside contour", "Pocket", "Hole", "Slot"])
def test_step_modes_generate_parser_accepted_metric_gcode(mode: str) -> None:
    job = generate_step_gcode(
        _model(), mode=mode, stock_width=50, stock_height=35, zero_location="Center", depth=-1, passes=2,
        stock_thickness=5,
    )

    program = parse_gcode(job.gcode)

    expected_depth = -5.2 if mode == "Profile cutout" else -1
    assert program.bounds.minimum.z == pytest.approx(expected_depth)
    assert program.bounds.maximum.z == pytest.approx(3)
    assert job.stroke_count > 0
    if mode == "Profile cutout":
        assert job.gcode.count("G1 Z") >= job.stroke_count * 2
        assert job.profile_simulation is not None
        assert job.profile_simulation.passed
        assert "; Simulation profile:" in job.gcode
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
    assert "; Placement offset X1.5 Y1.5; path envelope is nonnegative" in job.gcode
    assert "; Metrics cut " in job.gcode
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


@pytest.mark.parametrize("mode", ["Engraving", "Outside contour", "Inside contour", "Pocket", "Hole", "Slot", "Profile cutout"])
def test_translated_step_geometry_is_shifted_into_nonnegative_work_xy(mode: str) -> None:
    job = generate_step_gcode(
        _translated_model(),
        mode=mode,
        orientation="Top (XY)",
        zero_location="Lower-left",
        stock_width=45,
        stock_height=30,
        tool_diameter=3,
        stock_thickness=5 if mode == "Profile cutout" else None,
        tab_count=0,
        depth=-1,
    )

    program = parse_gcode(job.gcode)
    assert program.bounds.minimum.x >= -0.001
    assert program.bounds.minimum.y >= -0.001
    assert min(point[0] for stroke in job.strokes for point in stroke) >= -0.001
    assert min(point[1] for stroke in job.strokes for point in stroke) >= -0.001
    assert job.placement_offset_x > 0
    assert job.placement_offset_y >= 0


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
    # The selector may now choose a connected offset path when it is cheaper
    # than the scanline candidate; retain a broad-clearing sanity bound.
    assert job.cutting_distance > 400
    assert job.rapid_xy_distance < 100
    assert job.retract_count == 1
    assert job.simulation is not None
    assert job.simulation.passed
    assert job.simulation.uncovered_area <= job.simulation.allowed_uncovered_area
    assert "; Simulation flat stock:" in job.gcode
    program = parse_gcode(job.gcode)
    assert program.bounds.minimum.z == pytest.approx(-1)


def test_pocket_strategy_selector_prefers_lower_weighted_cost() -> None:
    region = Polygon(((0, 0), (40, 0), (40, 25), (0, 25)))
    selected = _pocket_strokes(region, 1.5, 3)

    assert _pocket_path_cost(selected) < math.inf
    assert len(selected) == 1


def test_pocket_uses_one_safe_connected_path_for_a_round_region() -> None:
    region = Polygon(tuple(
        (20 + 12 * math.cos(index * math.tau / 64), 15 + 12 * math.sin(index * math.tau / 64))
        for index in range(64)
    ))

    selected = _pocket_strokes(region, 1.5, 3)

    assert len(selected) == 1
    assert len(selected[0]) > 10
    assert _pocket_path_cost(selected) < 500


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
    assert job.surface_simulation is not None
    assert job.surface_simulation.passed
    assert "; Simulation planar surface:" in job.gcode
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


def test_planar_surface_rejects_overlapping_patches_with_different_heights() -> None:
    boundary = PlanarLoop(tuple(Point2D(x, y) for x, y in ((0, 0), (20, 0), (20, 10), (0, 10))))
    patches = (
        PlanarSurfacePatch((boundary,), 0, 0, 0),
        PlanarSurfacePatch((boundary,), -0.1, 0, 1),
    )

    with pytest.raises(ValueError, match="ambiguous heights"):
        _planar_surface_paths(patches, "Top (XY)", Polygon(((0, 0), (20, 0), (20, 10), (0, 10))), 3, 0, 0)


def test_detected_features_keep_individual_depths() -> None:
    outer = PlanarLoop(tuple(Point2D(x, y) for x, y in ((0, 0), (50, 0), (50, 30), (0, 30))))
    holes = tuple(
        PlanarLoop(
            tuple(Point2D(cx + 5 * math.cos(index * math.tau / 32), 15 + 5 * math.sin(index * math.tau / 32)) for index in range(32))
        )
        for cx in (15, 35)
    )
    model = StepPlanarModel(
        Path("multi-depth.step"), (outer, *holes), 5, 5, (0, 0, 0, 50, 30, 5),
        features=(StepFeature("Recess", 1, 1), StepFeature("Recess", 2, 3)),
    )

    job = generate_step_gcode(model, mode="Detected feature", tool_diameter=3, passes=2)
    program = parse_gcode(job.gcode)
    assert program.bounds.minimum.z == pytest.approx(-3)
    assert "G1 Z-0.5 F100" in job.gcode
    assert "G1 Z-1.5 F100" in job.gcode
    assert "G1 Z-3 F100" in job.gcode
    assert job.gcode.index("G1 Z-1.5 F100") < job.gcode.index("G1 Z-0.5 F100")
    assert job.operations[0].target_depth == pytest.approx(-3)
    assert job.operations[1].target_depth == pytest.approx(-1)
    assert len(job.feature_simulations) == 2
    assert all(simulation.passed for simulation in job.feature_simulations)
    assert job.gcode.count("; Simulation feature ") == 2
    assert job.gcode.index("; Operation feature-depth-0:") < job.gcode.index("; Operation feature-depth-1:")


def test_scheduler_reverses_open_path_to_use_nearest_endpoint() -> None:
    stroke = ((10, 0), (20, 0))

    assert _best_stroke_orientation(stroke, (21, 0)) == ((20, 0), (10, 0))


def test_scheduler_rotates_closed_path_to_nearest_vertex() -> None:
    stroke = ((0, 0), (10, 0), (10, 10), (0, 10), (0, 0))

    oriented = _best_stroke_orientation(stroke, (9, 9))

    assert oriented[0] == (10, 10)
    assert oriented[-1] == oriented[0]


def test_scheduler_local_improvement_never_increases_rapid_cost() -> None:
    paths = [
        (((10, 0), (11, 0)), False),
        (((20, 10), (21, 10)), False),
        (((0, 10), (1, 10)), False),
        (((20, 0), (21, 0)), False),
    ]

    improved = _improve_tagged_order(paths)

    assert _scheduled_path_cost(improved) <= _scheduled_path_cost(paths)
    current = (0.0, 0.0)
    actual_cost = 0.0
    for stroke, _is_outer in improved:
        actual_cost += math.dist(current, stroke[0])
        current = stroke[-1]
    assert actual_cost == pytest.approx(_scheduled_path_cost(improved))


def test_detected_scheduler_preserves_operation_group_order_over_depth_sorting() -> None:
    groups = (
        ((((20, 0), (21, 0)),), -1.0),
        ((((1, 0), (2, 0)),), -3.0),
    )

    scheduled = _schedule_depth_groups(groups)

    assert [depth for _stroke, depth in scheduled] == [-1.0, -3.0]
    assert scheduled[0][0] == ((20, 0), (21, 0))


def test_path_metrics_match_cross_pass_machine_position() -> None:
    job = generate_step_gcode(
        _solid_model(),
        mode="Pocket",
        stock_width=45,
        stock_height=30,
        tool_diameter=3,
        depth=-1,
        passes=2,
    )

    # The second pass starts at the first path from the prior path's endpoint;
    # there is no hidden XY return to work zero between passes. The metric must
    # therefore match the parsed rapid segments exactly.
    program = parse_gcode(job.gcode)
    actual_rapid = sum(
        math.dist((segment.start.x, segment.start.y), (segment.end.x, segment.end.y))
        for segment in program.segments
        if segment.rapid
    )
    assert job.rapid_xy_distance == pytest.approx(actual_rapid)
    assert job.estimated_minutes > 0
    assert "; Estimated duration " in job.gcode


def test_duration_estimate_uses_explicit_motion_assumptions() -> None:
    from ttc3018_control.step_engraver import _estimate_duration_minutes

    # 60 mm cutting at 60 mm/min is one minute; the remaining motion is
    # 30 mm of rapid XY and one 3 mm retract/plunge cycle.
    estimate = _estimate_duration_minutes(60, 30, 1, 3, -2, 60, 120)
    expected = 1 + 30 / 3000 + 3 / 3000 + 2 / 120
    assert estimate == pytest.approx(expected)

    with pytest.raises(ValueError, match="non-finite"):
        _estimate_duration_minutes(math.inf, 0, 1, 3, -1, 60, 120)


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
    with pytest.raises(ValueError, match="confirmed physical stock"):
        generate_step_gcode(_model(), mode="Profile cutout")
    with pytest.raises(ValueError, match="Stock thickness"):
        generate_step_gcode(_model(), mode="Profile cutout", stock_thickness=0)
    with pytest.raises(ValueError, match="Tab height"):
        generate_step_gcode(_model(), mode="Profile cutout", stock_thickness=2, tab_height=2)
    with pytest.raises(ValueError, match="too short"):
        generate_step_gcode(
            _model(), mode="Profile cutout", stock_width=50, stock_height=35,
            zero_location="Center", stock_thickness=5, tab_count=12, tab_width=20,
        )


def test_profile_cutout_uses_confirmed_physical_stock_for_through_depth() -> None:
    job = generate_step_gcode(
        _model(),
        mode="Profile cutout",
        stock_width=43,
        stock_height=28,
        tool_diameter=3,
        stock_thickness=2,
        breakthrough=0.2,
        tab_count=0,
    )

    program = parse_gcode(job.gcode)
    assert job.depth == pytest.approx(-2.2)
    assert program.bounds.minimum.z == pytest.approx(-2.2)
    assert "; Through cut: stock 2 mm + breakthrough 0.2 mm" in job.gcode


def test_profile_operation_plan_keeps_inner_cutouts_before_outer_profile() -> None:
    job = generate_step_gcode(
        _model(),
        mode="Profile cutout",
        tool_diameter=3,
        stock_width=43,
        stock_height=28,
        stock_thickness=2,
        tab_count=0,
    )

    assert [operation.operation_id for operation in job.operations] == ["internal-through", "outer-profile"]
    assert job.operations[1].depends_on == ("internal-through",)
    assert "; Operation internal-through:" in job.gcode
    assert "; Operation outer-profile:" in job.gcode


def test_nested_profile_cutout_simulates_islands_and_cutouts() -> None:
    def square(left: float, bottom: float, size: float) -> PlanarLoop:
        return PlanarLoop(tuple(
            Point2D(x, y)
            for x, y in (
                (left, bottom),
                (left + size, bottom),
                (left + size, bottom + size),
                (left, bottom + size),
            )
        ))

    model = StepPlanarModel(
        Path("nested-profile.step"),
        (square(0, 0, 40), square(5, 5, 30), square(10, 10, 20), square(15, 15, 10)),
        5,
        5,
        (0, 0, 0, 40, 40, 5),
        loop_parents=(None, 0, 1, 2),
    )

    job = generate_step_gcode(
        model,
        mode="Profile cutout",
        stock_width=42,
        stock_height=42,
        tool_diameter=2,
        stock_thickness=5,
        tab_count=0,
    )

    assert job.stroke_count == 4
    assert job.profile_simulation is not None
    assert job.profile_simulation.passed
    assert job.profile_simulation.gouged_area == pytest.approx(0)
    assert [operation.feature_indices for operation in job.operations] == [(1, 3), (0, 2)]


def test_nested_detected_recess_preserves_island_at_parent_floor() -> None:
    def square(left: float, bottom: float, size: float) -> PlanarLoop:
        return PlanarLoop(tuple(
            Point2D(x, y)
            for x, y in (
                (left, bottom),
                (left + size, bottom),
                (left + size, bottom + size),
                (left, bottom + size),
            )
        ))

    model = StepPlanarModel(
        Path("nested-recess.step"),
        (square(0, 0, 40), square(5, 5, 30), square(10, 10, 20)),
        5,
        5,
        (0, 0, 0, 40, 40, 5),
        features=(StepFeature("Recess", 1, 3, parent_loop_index=0),),
        loop_parents=(None, 0, 1),
    )

    job = generate_step_gcode(
        model,
        mode="Detected feature",
        stock_width=42,
        stock_height=42,
        tool_diameter=2,
        stock_thickness=5,
    )

    assert job.feature_simulations[0].passed
    assert job.feature_simulations[0].gouged_area == pytest.approx(0)
    assert job.feature_simulations[0].uncovered_area <= job.feature_simulations[0].allowed_uncovered_area


@pytest.mark.parametrize("removed_tool_diameter", [3.0, 3.175])
def test_step_fixtures_distinguish_removed_and_extruded_circle_features(
    removed_tool_diameter: float,
) -> None:
    examples = Path(__file__).parents[1] / "examples"
    removed = load_step_isolated(examples / "removed-cylinder.step")
    extruded = load_step_isolated(examples / "extruded-circle.step")

    assert [(feature.kind, feature.loop_index) for feature in removed.features] == [("Recess", 1)]
    assert [(feature.kind, feature.loop_index) for feature in extruded.features] == [("Raised boss", 1)]
    assert removed.features[0].depth == pytest.approx(2)
    assert extruded.features[0].depth == pytest.approx(2)
    assert removed.features[0].is_through
    assert not extruded.features[0].is_through

    with pytest.raises(ValueError, match="confirmed stock thickness"):
        generate_step_gcode(removed, mode="Detected feature", tool_diameter=3.175, passes=2)
    removed_job = generate_step_gcode(
        removed,
        mode="Detected feature",
        tool_diameter=removed_tool_diameter,
        passes=2,
        stock_thickness=2,
        breakthrough=0.2,
    )
    extruded_job = generate_step_gcode(extruded, mode="Detected feature", tool_diameter=3.175, passes=2)
    removed_program = parse_gcode(removed_job.gcode)
    extruded_program = parse_gcode(extruded_job.gcode)

    removed_points = [point for stroke in removed_job.strokes for point in stroke]
    extruded_points = [point for stroke in extruded_job.strokes for point in stroke]
    removed_width = max(point[0] for point in removed_points) - min(point[0] for point in removed_points)
    extruded_width = max(point[0] for point in extruded_points) - min(point[0] for point in extruded_points)
    assert removed_width < 10  # Clear inside the circular recess.
    assert extruded_width > 25  # Clear the surrounding rectangle, leaving the boss.
    assert removed_program.bounds.minimum.z == pytest.approx(-2.2)
    assert extruded_program.bounds.minimum.z == pytest.approx(-2)
    assert removed_job.feature_summary == "Recess 2.00 mm"
    assert extruded_job.feature_summary == "Raised boss 2.00 mm"
    assert len(removed_job.feature_simulations) == 1
    assert len(extruded_job.feature_simulations) == 1
    assert removed_job.feature_simulations[0].passed
    assert extruded_job.feature_simulations[0].passed
    assert removed_job.feature_simulations[0].gouged_area <= removed_job.feature_simulations[0].allowed_gouged_area
    assert extruded_job.feature_simulations[0].gouged_area <= extruded_job.feature_simulations[0].allowed_gouged_area


@pytest.mark.parametrize(
    ("fixture", "primary_operation"),
    (
        ("removed-cylinder.step", "feature-depth-0"),
        ("extruded-circle.step", "feature-depth-0"),
        ("wedge.step", "planar-surface"),
    ),
)
def test_automatic_part_machines_geometry_then_cuts_outer_profile(
    fixture: str,
    primary_operation: str,
) -> None:
    model = load_step_isolated(Path(__file__).parents[1] / "examples" / fixture)

    job = generate_step_gcode(
        model,
        mode="Automatic part",
        stock_width=model.width + 3.175,
        stock_height=model.height + 3.175,
        stock_thickness=model.thickness,
        tool_diameter=3.175,
        passes=2,
        max_stepdown=1.0,
    )

    assert [operation.operation_id for operation in job.operations] == [
        primary_operation,
        "outer-profile",
    ]
    assert job.operations[-1].depends_on == (primary_operation,)
    assert job.profile_simulation is not None
    assert job.stock_thickness == pytest.approx(model.thickness)
    points = [point for stroke in job.strokes for point in stroke]
    assert min(point[0] for point in points) == pytest.approx(0)
    assert min(point[1] for point in points) == pytest.approx(0)
    parsed = parse_gcode(job.gcode)
    assert parsed.bounds.minimum.x >= 0
    assert parsed.bounds.minimum.y >= 0
    if fixture == "wedge.step":
        assert job.surface_paths
        assert job.surface_simulation is not None
    else:
        assert job.feature_simulations


@pytest.mark.parametrize(
    ("fixture", "mode"),
    [
        ("removed-cylinder.step", "Detected feature"),
        ("extruded-circle.step", "Detected feature"),
        ("wedge.step", "Planar surface"),
    ],
)
def test_real_step_jobs_are_deterministic_and_nonnegative(
    fixture: str,
    mode: str,
) -> None:
    model = load_step_isolated(Path(__file__).parents[1] / "examples" / fixture)
    settings = dict(
        mode=mode,
        stock_width=model.width + 6,
        stock_height=model.height + 6,
        tool_diameter=3.175,
        depth=-1,
        passes=2,
        stock_thickness=model.thickness if fixture.startswith("removed") else None,
    )

    first = generate_step_gcode(model, **settings)
    second = generate_step_gcode(model, **settings)

    assert first.gcode == second.gcode
    assert first.strokes == second.strokes
    assert first.operations == second.operations
    assert (
        first.cutting_distance,
        first.rapid_xy_distance,
        first.retract_count,
    ) == pytest.approx((second.cutting_distance, second.rapid_xy_distance, second.retract_count))
    program = parse_gcode(first.gcode)
    assert program.bounds.minimum.x >= -0.001
    assert program.bounds.minimum.y >= -0.001


def test_outside_contour_rejects_stock_that_cannot_contain_tool_offset() -> None:
    with pytest.raises(ValueError, match="outside the declared stock"):
        generate_step_gcode(_model(), mode="Outside contour", tool_diameter=3, stock_width=40, stock_height=25)


def test_invalid_depth_pass_settings_are_rejected() -> None:
    with pytest.raises(ValueError, match="whole number"):
        generate_step_gcode(_model(), passes=0)
    with pytest.raises(ValueError, match="Tool diameter"):
        generate_step_gcode(_model(), tool_diameter=0)
    with pytest.raises(ValueError, match="Machining depth"):
        generate_step_gcode(_model(), depth=math.nan)
    with pytest.raises(ValueError, match="Stock width"):
        generate_step_gcode(_model(), stock_width=math.nan)


def test_slot_mode_requires_an_inner_loop() -> None:
    with pytest.raises(ValueError, match="inner cutout"):
        generate_step_gcode(_solid_model(), mode="Slot")


def test_invalid_normalized_feature_and_surface_values_are_rejected() -> None:
    invalid_feature = StepPlanarModel(
        Path("bad-feature.step"),
        _model().loops,
        5,
        5,
        (0, 0, 0, 40, 25, 5),
        features=(StepFeature("Recess", 99, 1),),
    )
    with pytest.raises(ValueError, match="unknown loop"):
        generate_step_gcode(invalid_feature, mode="Detected feature")

    invalid_surface = StepPlanarModel(
        Path("bad-surface.step"),
        _model().loops,
        5,
        5,
        (0, 0, 0, 40, 25, 5),
        surface_patches=(PlanarSurfacePatch((_model().loops[0],), math.nan, 0, 0),),
    )
    with pytest.raises(ValueError, match="height field"):
        generate_step_gcode(invalid_surface, mode="Planar surface")


def test_max_stepdown_increases_passes_without_changing_final_depth() -> None:
    job = generate_step_gcode(
        _solid_model(),
        mode="Pocket",
        stock_width=45,
        stock_height=30,
        depth=-2.1,
        passes=1,
        max_stepdown=0.5,
    )

    assert job.passes == 5
    assert parse_gcode(job.gcode).bounds.minimum.z == pytest.approx(-2.1)
    assert "; Depth schedule 5 pass(es), maximum stepdown 0.5 mm" in job.gcode


def test_max_stepdown_rejects_impossible_schedules() -> None:
    with pytest.raises(ValueError, match="Maximum stepdown"):
        generate_step_gcode(_solid_model(), max_stepdown=0)
    with pytest.raises(ValueError, match="more than 100"):
        generate_step_gcode(_solid_model(), depth=-20, max_stepdown=0.1)


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
