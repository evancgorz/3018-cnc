from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path

import pytest

from ttc3018_control.simulation.collision import CollisionWorld, Fixture
from ttc3018_control.simulation.geometry import AABB
from ttc3018_control.simulation.models import PlantSnapshot, SimulationProfile, SimulationWorkpiece
from ttc3018_control.simulation.plant import VirtualMachinePlant
from ttc3018_control.simulation.stock import StockModel
from ttc3018_control.simulation.controller import VirtualGrblController
from ttc3018_control.step_engraver import generate_step_gcode
from ttc3018_control.step_geometry import load_step_isolated
from ttc3018_control.step_simulation import StepSimulationError


ROOT = Path(__file__).parents[1]


def _job():
    model = load_step_isolated(ROOT / "examples" / "showcase-pocket-island.step")
    return model, generate_step_gcode(
        model,
        mode="Detected feature",
        stock_width=model.width + 3.175,
        stock_height=model.height + 3.175,
        stock_thickness=model.thickness,
        tool_diameter=3.175,
        max_stepdown=2,
        spindle_rpm=6000,
    )


def _stock(job, thickness: float, *, retain_island: bool = True) -> StockModel:
    profile = SimulationProfile(stock_resolution=0.5)
    stock = StockModel(SimulationWorkpiece(stock_width=job.stock_width, stock_height=job.stock_height,
                                            stock_thickness=thickness), profile)
    rows = []
    for iy in range(stock.ny):
        y = (iy + 0.5) * stock.resolution
        row = []
        for ix in range(stock.nx):
            x = (ix + 0.5) * stock.resolution
            pocket = 5 <= x <= 35 and 5 <= y <= 25
            island = retain_island and 16 <= x <= 24 and 12 <= y <= 18
            row.append(2.0 if pocket and not island else thickness)
        rows.append(row)
    stock.set_target_height_field(rows)
    return stock


def _execute(job, stock: StockModel, *, spindle: bool = True, rapid: bool = False,
             shift_x: float = 0.0):
    profile = stock.profile
    profile = SimulationProfile(
        **{**profile.to_dict(), "initial_z": 6.0}
    )
    plant = VirtualMachinePlant(profile)
    controller = VirtualGrblController(plant)
    controller.receive(b"G10 L20 P1 Z0\n")
    controller.drain()
    removed = 0.0
    for original in job.gcode.splitlines():
        if not original or original.startswith(";"):
            continue
        if not spindle and original.startswith("M3"):
            continue
        line = original
        if shift_x:
            line = re.sub(r"X(-?\d+(?:\.\d+)?)", lambda m: f"X{float(m.group(1)) + shift_x:g}", line)
        if rapid and line.startswith("G1"):
            line = "G0" + line[2:]
        before = plant.snapshot()
        controller.receive((line + "\n").encode())
        controller.drain()
        controller.advance(30_000_000_000)
        after = plant.snapshot()
        if original.startswith("G1") and spindle and not rapid and plant.spindle_rpm > 1:
            offset = plant.work_offset[2]
            convert = lambda z: max(0.0, min(stock.workpiece.stock_thickness,
                                             z - offset + stock.workpiece.stock_thickness))
            removed += stock.remove_swept_segment(
                (before.machine_position[0], before.machine_position[1], convert(before.machine_position[2])),
                (after.machine_position[0], after.machine_position[1], convert(after.machine_position[2])),
                profile.tool_radius,
            )
    return controller, removed


def test_generated_pocket_island_executes_against_target_height_field():
    model, job = _job()
    stock = _stock(job, model.thickness)
    initial_metrics = stock.metrics()
    assert initial_metrics.remaining_volume == pytest.approx(initial_metrics.stock_volume)
    assert initial_metrics.removed_volume == pytest.approx(0)
    controller, removed = _execute(job, stock)
    metrics = stock.metrics()
    assert controller.plant.work_offset[2] == 6
    assert removed > 1500
    assert metrics.removed_volume > 1400
    assert metrics.uncovered_volume < 0.02 * metrics.target_volume
    assert metrics.gouged_volume == pytest.approx(0, abs=0.001)
    # The retained center island remains at stock height.
    assert stock.heights[int(14 / stock.resolution)][int(20 / stock.resolution)] == pytest.approx(model.thickness)


def test_generated_mutations_fail_independently_for_shift_depth_tool_spindle_rapid_island_and_fixture():
    model, job = _job()
    baseline = _stock(job, model.thickness)
    _execute(job, baseline)
    baseline_uncovered = baseline.metrics().uncovered_volume

    shifted = _stock(job, model.thickness)
    _execute(job, shifted, shift_x=2)
    assert shifted.metrics().uncovered_volume > baseline_uncovered + 1

    spindle_off = _stock(job, model.thickness)
    _execute(job, spindle_off, spindle=False)
    assert spindle_off.metrics().removed_volume == pytest.approx(0)
    assert spindle_off.metrics().uncovered_volume > 1000

    rapid = _stock(job, model.thickness)
    _execute(job, rapid, rapid=True)
    assert rapid.metrics().removed_volume == pytest.approx(0)

    no_island = _stock(job, model.thickness, retain_island=False)
    _execute(job, no_island)
    assert no_island.metrics().uncovered_volume > 100

    with pytest.raises(StepSimulationError, match="deeper"):
        generate_step_gcode(model, mode="Pocket", depth=-6, stock_thickness=model.thickness)
    with pytest.raises(ValueError, match="No usable"):
        generate_step_gcode(model, mode="Detected feature", tool_diameter=20, stock_thickness=model.thickness)

    world = CollisionWorld(SimulationProfile(initial_z=5))
    world.add_fixture(Fixture("generated-clamp", AABB(6, 6, 3, 10, 10, 5)))
    previous = PlantSnapshot(1, "Run", (6.6, 6.6, 3.5), (0, 0, 0), 300, 6000, 6000)
    current = PlantSnapshot(2, "Run", (8, 6.6, 3.5), (0, 0, 0), 300, 6000, 6000)
    assert any(item.kind.value == "tool_fixture" for item in world.check_transition(
        previous, current, rapid=False, spindle_on=True,
    ))


def test_step_model_builds_shifted_work_frame_target_and_retains_nested_island():
    model = load_step_isolated(ROOT / "examples" / "showcase-pocket-island.step")
    shifted_loops = tuple(
        replace(loop, points=tuple(type(point)(point.x + 11.0, point.y - 7.0) for point in loop.points))
        for loop in model.loops
    )
    shifted = replace(model, loops=shifted_loops, loop_parents=())
    stock = StockModel.from_step_model(shifted, SimulationProfile(stock_resolution=0.5))
    assert stock.workpiece.origin_x == pytest.approx(11.0)
    assert stock.workpiece.origin_y == pytest.approx(-7.0)
    assert not stock.workpiece.collision_only
    # The pocket is three millimetres deep, while its nested island remains at
    # the uncut stock height.  Samples are deliberately taken away from loop
    # boundaries so this is stable across grid resolutions.
    target = stock.target_height_field
    assert target is not None
    pocket = target[int(10 / stock.resolution)][int(10 / stock.resolution)]
    island = target[int(15 / stock.resolution)][int(20 / stock.resolution)]
    assert pocket == pytest.approx(2.0)
    assert island == pytest.approx(5.0)
    assert stock.metrics().target_volume is not None


def test_declared_step_workpiece_loads_target_at_production_stock_boundary():
    path = ROOT / "examples" / "showcase-pocket-island.step"
    workpiece = SimulationWorkpiece(path=str(path), stock_width=40, stock_height=30, stock_thickness=5)
    stock = StockModel.from_workpiece(workpiece, SimulationProfile(stock_resolution=1.0))
    assert stock.target_height_field is not None
    assert stock.metrics().collision_only is False
    assert stock.metrics().target_volume is not None


def test_step_target_rejects_unsupported_orientation_as_collision_only():
    model = load_step_isolated(ROOT / "examples" / "showcase-pocket-island.step")
    unsupported = replace(model, face_plane="XZ")
    stock = StockModel.from_step_model(unsupported, SimulationProfile(stock_resolution=1.0))
    metrics = stock.metrics()
    assert stock.workpiece.collision_only
    assert metrics.collision_only
    assert metrics.target_volume is None
    assert metrics.removed_volume == pytest.approx(0.0)


def test_swept_path_metrics_are_replay_stable_and_report_overcut_undercut():
    model = load_step_isolated(ROOT / "examples" / "showcase-pocket-island.step")
    profile = SimulationProfile(stock_resolution=1.0)
    one = StockModel.from_step_model(model, profile)
    two = StockModel.from_step_model(model, profile)
    path = ((10.0, 10.0, 5.0), (30.0, 10.0, 1.0), (30.0, 20.0, 1.0))
    one.remove_swept_path(path, profile.tool_radius)
    two.remove_swept_path(path, profile.tool_radius)
    assert one.metrics() == two.metrics()
    metrics = one.metrics()
    assert metrics.undercut_volume == pytest.approx(metrics.uncovered_volume)
    assert metrics.overcut_volume == pytest.approx(metrics.gouged_volume)
