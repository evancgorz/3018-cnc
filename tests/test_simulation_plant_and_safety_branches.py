from __future__ import annotations

import math

import pytest

from ttc3018_control.simulation.clock import SimulationClock
from ttc3018_control.simulation.collision import CollisionWorld, Fixture, compare_snapshots
from ttc3018_control.simulation.geometry import AABB, MachineGeometryProfile, swept_bounds
from ttc3018_control.simulation.models import HazardKind, PlantSnapshot, SimulationProfile, SimulationWorkpiece
from ttc3018_control.simulation.plant import MotionBlock, VirtualMachinePlant
from ttc3018_control.simulation.stock import StockModel


def snap(pos, *, t=1, state="Idle", spindle=0.0, motion=None):
    return PlantSnapshot(t, state, tuple(pos), (0, 0, 0), 100, spindle, spindle, motion=motion)


def test_clock_validation_and_wall_reset():
    clock = SimulationClock()
    for value in ("bad", -1, 1001):
        with pytest.raises(ValueError):
            clock.set_speed(value)
    with pytest.raises(ValueError):
        clock.advance(-1)
    with pytest.raises(ValueError):
        clock.advance_wall(-1)
    clock.set_speed(2)
    assert clock.advance_wall(0.25) == 500_000_000
    assert SimulationClock.wall_now_ns() > 0
    clock.reset()
    assert clock.time_ns == 0


@pytest.mark.parametrize("kwargs", [
    {"safe_z": 0}, {"safe_z": 41}, {"rx_capacity": 31},
    {"planner_capacity": 0}, {"max_stock_cells": 0}, {"tool_radius": 0},
    {"initial_x": 999}, {"schema_version": 2}, {"stock_resolution": 0},
])
def test_profile_validation_families(kwargs):
    with pytest.raises(ValueError):
        SimulationProfile(**kwargs).validate()


def test_plant_spindle_motion_callbacks_and_invalid_inputs():
    plant = VirtualMachinePlant(SimulationProfile())
    with pytest.raises(ValueError):
        plant.set_spindle(float("nan"))
    with pytest.raises(ValueError):
        plant.set_spindle(-1)
    with pytest.raises(ValueError):
        plant.enqueue((0, 0, 0), feed=0)
    with pytest.raises(ValueError):
        plant.enqueue((math.inf, 0, 0), feed=1)
    completed = []
    plant.on_block_complete = completed.append
    plant.set_spindle(6000)
    plant.advance(1_000_000_000)
    assert plant.spindle_rpm > 0
    plant.enqueue((0, 0, 0), feed=100)
    plant.advance(1)
    plant.enqueue((0, 0, 0), feed=100)
    plant.advance(1_000_000_000)
    assert completed
    plant.set_spindle(0)
    plant.advance(1_000_000_000)
    assert plant.spindle_rpm == 0
    plant.set_work_offset((1, 2, 3), "XZ")
    assert plant.work_offset == [1, 0, 3]
    with pytest.raises(ValueError):
        plant.set_work_offset((math.inf, 0, 0), "X")


def test_plant_hold_resume_cancel_reset_polyline_and_limit():
    plant = VirtualMachinePlant(SimulationProfile())
    plant.enqueue((20, 0, 0), feed=600, rapid=True)
    plant.advance(100_000_000)
    plant.request_hold()
    assert plant.state.startswith("Hold")
    held = plant.machine_position
    plant.advance(100_000_000)
    assert plant.machine_position != held or plant.current_speed == 0
    plant.resume()
    plant.advance(5_000_000_000)
    assert plant.machine_position[0] == pytest.approx(20, abs=.001)
    plant.enqueue((30, 0, 0), feed=600, rapid=True)
    plant.cancel_jog()
    assert not plant.busy
    plant.enqueue((40, 0, 0), feed=600)
    plant.reset()
    assert plant.state == "Idle" and not plant.busy
    plant.on_limit = lambda pos: None
    plant.position[0] = 999
    plant._check_limits()
    assert plant.state == "Alarm"
    block = MotionBlock(1, (0, 0, 0), (1, 1, 1), 100, points=((0, 0, 0), (0, 0, 0), (1, 1, 1)))
    assert block.path[-1] == (1, 1, 1)
    assert plant._point_at_path(((0, 0, 0),), 0, 0) == (0, 0, 0)
    assert plant._axis_feed_limit(MotionBlock(1, (1, 1, 1), (1, 1, 1), 100)) == 100
    assert plant._path_acceleration(MotionBlock(1, (1, 1, 1), (1, 1, 1), 100)) > 0


def test_geometry_validation_bodies_and_sweeps():
    with pytest.raises(ValueError):
        AABB(0, 0, 0, math.inf, 1, 1).validate()
    with pytest.raises(ValueError):
        AABB(2, 0, 0, 1, 1, 1).validate()
    with pytest.raises(ValueError):
        MachineGeometryProfile(schema_version=2).validate()
    with pytest.raises(ValueError):
        MachineGeometryProfile(tool_radius=0).validate()
    profile = SimulationProfile()
    geometry = MachineGeometryProfile.default_3018(profile)
    bodies = geometry.bodies(snap((1, 2, 3)), profile)
    assert {body.name for body in bodies} == {"bed", "left-upright", "right-upright", "x-gantry", "z-carriage", "tool-holder", "cutter"}
    assert swept_bounds(snap((0, 0, 0)), snap((3, 4, 5)), "cutter", geometry, profile).max_x > 3
    assert AABB(0, 0, 0, 1, 1, 1).intersects(AABB(1, 1, 1, 2, 2, 2))


def test_collision_every_class_and_divergence():
    profile = SimulationProfile(initial_z=5)
    world = CollisionWorld(profile)
    world.add_fixture(Fixture("clamp", AABB(0, 0, 0, 20, 20, 20)))
    stock = StockModel(SimulationWorkpiece(stock_width=20, stock_height=20, stock_thickness=5), profile)
    all_hazards = world.check_transition(snap((-20, 10, -10)), snap((10, 10, -10)), rapid=True, spindle_on=False, stock=stock, target_cutting=False)
    kinds = {item.kind for item in all_hazards}
    assert HazardKind.TRAVEL_LIMIT in kinds
    assert HazardKind.MACHINE_COLLISION in kinds
    assert HazardKind.TOOL_BED in kinds
    assert HazardKind.TOOL_FIXTURE in kinds
    assert HazardKind.HOLDER_FIXTURE in kinds
    assert HazardKind.RAPID_STOCK in kinds
    assert HazardKind.EXCESSIVE_DEPTH in kinds
    holder_stock = world.check_transition(snap((10, 10, -20)), snap((10, 10, -20)), rapid=False, spindle_on=True, stock=stock)
    assert any(item.kind is HazardKind.HOLDER_STOCK for item in holder_stock)
    off = world.check_transition(snap((10, 10, 2)), snap((10, 10, -1)), rapid=False, spindle_on=False, stock=stock)
    assert any(item.kind is HazardKind.SPINDLE_OFF_ENTRY for item in off)
    gouge = world.check_transition(snap((10, 10, 2)), snap((10, 10, -1)), rapid=False, spindle_on=True, stock=stock, target_cutting=False)
    assert any(item.kind is HazardKind.RETAINED_GOUGE for item in gouge)
    assert compare_snapshots(snap((0, 0, 0)), snap((1, 0, 0))) is not None
    assert compare_snapshots(snap((0, 0, 0)), snap((.0001, 0, 0))) is None


def test_stock_budget_targets_invalid_sweeps_and_metrics():
    with pytest.raises(ValueError):
        StockModel(SimulationWorkpiece(stock_width=100, stock_height=100), SimulationProfile(stock_resolution=.1, max_stock_cells=10))
    stock = StockModel(SimulationWorkpiece(stock_width=4, stock_height=3, stock_thickness=2), SimulationProfile(stock_resolution=1))
    with pytest.raises(ValueError):
        stock.set_target_height_field([[1]])
    with pytest.raises(ValueError):
        stock.set_target_height_field([[math.nan] * 4 for _ in range(3)])
    stock.set_target_height_field([[1] * 4 for _ in range(3)])
    with pytest.raises(ValueError):
        stock.remove_cylinder(1, 1, 1, 0)
    removed = stock.remove_swept_segment((1, 1, 2), (3, 1, 0), 1)
    metrics = stock.metrics()
    assert removed > 0 and metrics.target_volume is not None
    assert metrics.gouged_volume > 0 or metrics.uncovered_volume > 0
    assert stock.to_render_grid() == stock.heights
