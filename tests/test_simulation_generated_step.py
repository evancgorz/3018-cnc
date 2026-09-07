from __future__ import annotations

import re
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
