from __future__ import annotations

import json

import pytest

from ttc3018_control.simulation.collision import CollisionWorld, Fixture
from ttc3018_control.simulation.geometry import AABB
from ttc3018_control.simulation.models import HazardKind, PlantSnapshot, SimulationProfile, SimulationWorkpiece
from ttc3018_control.simulation.parity import ParityCapture, ParityTolerance, compare_captures, reject_physical_capture_without_authorization
from ttc3018_control.simulation.scenarios import built_in_scenarios, run_headless_scenario
from ttc3018_control.simulation.stock import StockModel
from ttc3018_control.simulation.stock import load_step_target


def _snapshot(pos, *, state="Idle", feed=0, spindle=0):
    return PlantSnapshot(1, state, tuple(pos), (0, 0, 0), feed, spindle, spindle)


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
