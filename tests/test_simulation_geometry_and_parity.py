from __future__ import annotations

import json
import math

import pytest

from ttc3018_control.simulation.collision import CollisionWorld, Fixture
from ttc3018_control.simulation.geometry import AABB, CoordinateFrame
from ttc3018_control.simulation.models import HazardKind, MotionSnapshot, PlantSnapshot, SimulationProfile, SimulationWorkpiece
from ttc3018_control.simulation.operator import IndependentVirtualOperator, OperatorFixture
from ttc3018_control.simulation.parity import ParityCapture, ParityTolerance, compare_captures, reject_physical_capture_without_authorization
from ttc3018_control.simulation.scenarios import built_in_scenarios, run_headless_scenario
from ttc3018_control.simulation.stock import StockModel
from ttc3018_control.simulation.stock import load_step_target


def _snapshot(pos, *, state="Idle", feed=0, spindle=0):
    return PlantSnapshot(1, state, tuple(pos), (0, 0, 0), feed, spindle, spindle)


def test_coordinate_frame_round_trip_and_shifted_work_bounds() -> None:
    frame = CoordinateFrame((10.0, -4.0, 30.0))
    assert frame.work_to_machine((2.0, 5.0, -1.0)) == (12.0, 1.0, 29.0)
    assert frame.machine_to_work((12.0, 1.0, 29.0)) == (2.0, 5.0, -1.0)
    bounds = frame.work_bounds_to_machine(AABB(2, 5, -3, 6, 8, 0))
    assert bounds == AABB(12, 1, 27, 16, 4, 30)
    with pytest.raises(ValueError):
        frame.work_to_machine((math.nan, 0, 0))


@pytest.mark.parametrize("axis", [0, 1, 2])
def test_collision_world_enforces_each_machine_axis_limit(axis: int) -> None:
    profile = SimulationProfile()
    start = [1.0, 1.0, 1.0]
    end = start[:]
    end[axis] = (profile.travel_x, profile.travel_y, profile.travel_z)[axis] + 0.01
    hazards = CollisionWorld(profile).check_transition(
        _snapshot(start), _snapshot(end, state="Run"), rapid=False, spindle_on=True)
    assert any(item.kind is HazardKind.TRAVEL_LIMIT for item in hazards)


def test_arc_path_sweep_catches_first_contact_between_safe_endpoints() -> None:
    profile = SimulationProfile(initial_z=10)
    world = CollisionWorld(profile)
    world.add_fixture(Fixture("arc-clamp", AABB(4, 4, 9, 6, 6, 11)))
    path = ((0.0, 0.0, 10.0), (5.0, 5.0, 10.0), (10.0, 0.0, 10.0))
    motion = MotionSnapshot(block_id=1, start=path[0], target=path[-1], feed=100,
                            progress=1.0, path=path)
    hazards = world.check_transition(
        _snapshot(path[0]),
        PlantSnapshot(2, "Run", path[-1], (0, 0, 0), 100, 500, 500, motion=motion, sequence=2),
        rapid=False, spindle_on=True)
    assert any(item.kind is HazardKind.TOOL_FIXTURE for item in hazards)


def test_backend_and_supervisor_stock_paths_have_identical_full_resolution_metrics() -> None:
    """Independent stock instances consume the same accepted executed path."""
    profile = SimulationProfile(stock_resolution=0.5)
    workpiece = SimulationWorkpiece(stock_width=6.0, stock_height=6.0, stock_thickness=3.0)
    backend_stock = StockModel(workpiece, profile)
    supervisor_stock = StockModel(workpiece, profile)
    executed_path = (
        (0.25, 0.25, 3.0),
        (2.0, 1.5, 2.0),
        (3.5, 4.0, 1.0),
        (5.75, 5.75, 1.5),
    )
    backend_stock.remove_swept_path(executed_path, 0.35)
    supervisor_stock.remove_swept_path(executed_path, 0.35)
    assert backend_stock.to_render_grid() == supervisor_stock.to_render_grid()
    assert backend_stock.metrics() == supervisor_stock.metrics()


def test_stock_top_contact_is_safe_but_penetration_is_not() -> None:
    profile = SimulationProfile()
    stock = StockModel(SimulationWorkpiece(stock_width=20, stock_height=20, stock_thickness=5), profile)
    world = CollisionWorld(profile)
    contact = world.check_transition(_snapshot((10, 10, 0)), _snapshot((10, 10, 0), state="Run"),
                                     rapid=False, spindle_on=False, stock=stock)
    penetration = world.check_transition(_snapshot((10, 10, 0)), _snapshot((10, 10, -0.01), state="Run"),
                                         rapid=False, spindle_on=False, stock=stock)
    assert not any(item.kind is HazardKind.SPINDLE_OFF_ENTRY for item in contact)
    assert any(item.kind is HazardKind.SPINDLE_OFF_ENTRY for item in penetration)


def test_backend_and_operator_match_for_shifted_stock_and_nonzero_wco() -> None:
    profile = SimulationProfile()
    workpiece = SimulationWorkpiece(stock_width=8, stock_height=8, stock_thickness=3,
                                    origin_x=4, origin_y=5)
    offset = (10.0, 20.0, 30.0)
    previous = PlantSnapshot(1, "Idle", (15, 26, 32), offset, 0, 0, 0, sequence=1)
    current = PlantSnapshot(2, "Run", (15, 26, 29), offset, 100, 0, 0, sequence=2)
    world = CollisionWorld(profile)
    backend = world.check_transition(previous, current, rapid=False, spindle_on=False,
                                     stock=StockModel(workpiece, profile), stock_offset=offset)
    operator = IndependentVirtualOperator(profile, workpiece=workpiece)
    operator.observe(previous)
    independent = operator.observe(current).hazards
    backend_keys = {(item.kind, item.body_a, item.body_b) for item in backend}
    operator_keys = {(item.kind, item.body_a, item.body_b) for item in independent}
    assert backend_keys == operator_keys


def test_valid_spinning_cut_removes_stock_without_entry_alarm() -> None:
    profile = SimulationProfile(stock_resolution=1)
    workpiece = SimulationWorkpiece(stock_width=4, stock_height=4, stock_thickness=2)
    stock = StockModel(workpiece, profile)
    world = CollisionWorld(profile)
    hazards = world.check_transition(_snapshot((2, 2, 2)), _snapshot((2, 2, 0.5), state="Run", spindle=1000),
                                     rapid=False, spindle_on=True, stock=stock)
    assert not any(item.kind in {HazardKind.SPINDLE_OFF_ENTRY, HazardKind.RAPID_STOCK} for item in hazards)
    assert stock.remove_swept_segment((2, 2, 2), (2, 2, 0.5), profile.tool_radius) > 0


def test_operator_latches_stationary_continuous_fixture_contact() -> None:
    operator = IndependentVirtualOperator(
        fixtures=(OperatorFixture("clamp", AABB(8, 8, 0, 12, 12, 20)),))
    operator.observe(_snapshot((10, 10, 6)))
    second = operator.observe(PlantSnapshot(2, "Run", (10, 10, 6), (0, 0, 0), 100, 500, 500, sequence=2))
    third = operator.observe(PlantSnapshot(3, "Run", (10, 10, 6), (0, 0, 0), 100, 500, 500, sequence=3))
    assert any(item.kind is HazardKind.TOOL_FIXTURE for item in second.hazards)
    assert not third.hazards


def test_geometry_world_catches_swept_fixture_and_rapid_stock_collisions() -> None:
    profile = SimulationProfile(initial_z=10)
    world = CollisionWorld(profile=profile)
    world.add_fixture(Fixture("clamp", AABB(8, 8, 0, 12, 12, 12)))
    workpiece = SimulationWorkpiece(stock_width=20, stock_height=20, stock_thickness=5)
    stock = StockModel(workpiece, profile)
    hazards = world.check_transition(_snapshot((0, 10, 10)), _snapshot((20, 10, 10)), rapid=True, spindle_on=False, stock=stock)
    assert any(item.kind is HazardKind.RAPID_STOCK for item in hazards) or any(item.kind is HazardKind.TOOL_FIXTURE for item in hazards)


def test_geometry_world_catches_high_speed_sweep_through_frame_upright() -> None:
    profile = SimulationProfile(initial_x=0.0, initial_y=40.0, initial_z=20.0)
    world = CollisionWorld(profile=profile)
    hazards = world.check_transition(
        _snapshot((-10.0, 40.0, 20.0)), _snapshot((100.0, 40.0, 20.0)),
        rapid=True, spindle_on=False,
    )
    assert any(item.kind is HazardKind.MACHINE_COLLISION for item in hazards)


def test_nominal_tool_center_edge_does_not_false_alarm_against_frame() -> None:
    profile = SimulationProfile(initial_x=0.0, initial_y=40.0, initial_z=20.0)
    world = CollisionWorld(profile=profile)
    hazards = world.check_transition(
        _snapshot((0.0, 40.0, 20.0)), _snapshot((10.0, 40.0, 20.0)),
        rapid=True, spindle_on=False,
    )
    assert not any(item.kind is HazardKind.MACHINE_COLLISION for item in hazards)


def test_stock_removal_is_bounded_and_reports_volume() -> None:
    stock = StockModel(SimulationWorkpiece(stock_width=4, stock_height=4, stock_thickness=2), SimulationProfile(stock_resolution=1))
    removed = stock.remove_swept_segment((2, 2, 2), (2, 2, 0), 1)
    assert removed > 0
    metrics = stock.metrics()
    assert metrics.removed_volume == pytest.approx(removed)
    assert metrics.remaining_volume < metrics.stock_volume


def test_default_step_workpiece_is_loaded_through_isolated_importer() -> None:
    metadata = load_step_target(__import__("pathlib").Path("examples/showcase-pocket-island.step"))
    assert metadata.width == pytest.approx(40, abs=0.1)
    assert metadata.height == pytest.approx(30, abs=0.1)
    assert metadata.thickness == pytest.approx(5, abs=0.1)
    assert metadata.loop_count >= 2


def test_parity_comparison_reports_tolerated_and_semantic_differences() -> None:
    twin = ParityCapture([{"kind": "position", "x": 1.0, "time_ns": 1_000_000_000, "port": 4}])
    physical = ParityCapture([{"kind": "position", "x": 1.02, "time_ns": 1_100_000_000, "port": 5}])
    report = compare_captures(twin, physical)
    assert report.matched
    assert "port" in report.ignored_fields
    physical = ParityCapture([{"kind": "alarm", "x": 2.0}])
    assert not compare_captures(twin, physical).matched


def test_physical_parity_capture_is_inert_without_explicit_authorization() -> None:
    with pytest.raises(PermissionError):
        reject_physical_capture_without_authorization(authorized=False)
    with pytest.raises(ValueError):
        reject_physical_capture_without_authorization(authorized=True)


@pytest.mark.parametrize("name", [item.name for item in built_in_scenarios()])
def test_builtin_scenarios_are_deterministic(name: str) -> None:
    scenario = next(item for item in built_in_scenarios() if item.name == name)
    one = run_headless_scenario(scenario)
    two = run_headless_scenario(scenario)
    assert one.passed and two.passed
    assert one == two
