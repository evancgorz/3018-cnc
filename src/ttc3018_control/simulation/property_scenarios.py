"""Deterministic long-duration digital-twin property scenarios.

The corpus intentionally drives the same virtual controller, plant, collision
world, and bounded stock objects used by the ordinary headless scenarios.  It
uses only a local seeded PRNG and the virtual clock; no socket, filesystem, or
physical transport is involved during execution.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
import random
from typing import Any

from .collision import CollisionWorld, Fixture
from .controller import VirtualGrblController
from .geometry import AABB, CoordinateFrame
from .models import HazardKind, PlantSnapshot, SimulationFault, SimulationProfile, SimulationWorkpiece
from .plant import VirtualMachinePlant
from .stock import StockModel
from .trace import TraceRecorder


COMPACT_PROPERTY_SEEDS = (1, 2, 3, 5, 8)
DEFAULT_PROPERTY_STEPS = 96
MAX_PROPERTY_STEPS = 4096


@dataclass(frozen=True)
class PropertyScenarioResult:
    seed: int
    steps: int
    passed: bool
    trace_digest: str
    action_count: int
    max_planner_depth: int
    max_response_depth: int
    hazard_count: int
    stock_volumes: tuple[float, ...]
    first_failure: str = ""
    first_failure_step: int | None = None
    first_failure_action: str = ""

    def replay_context(self) -> dict[str, Any]:
        return {
            "seed": self.seed,
            "steps": self.steps,
            "first_failure": self.first_failure,
            "first_failure_step": self.first_failure_step,
            "first_failure_action": self.first_failure_action,
        }


def run_property_scenario(seed: int, *, steps: int = DEFAULT_PROPERTY_STEPS,
                          stress_depth: int = 1) -> PropertyScenarioResult:
    """Run one deterministic mixed-action corpus member with fail-closed checks."""
    if not isinstance(seed, int) or seed < 0:
        raise ValueError("Property seed must be a nonnegative integer")
    if not isinstance(steps, int) or not 1 <= steps <= MAX_PROPERTY_STEPS:
        raise ValueError(f"Property steps must be between 1 and {MAX_PROPERTY_STEPS}")
    if not isinstance(stress_depth, int) or not 1 <= stress_depth <= 16:
        raise ValueError("Property stress depth must be between 1 and 16")
    rng = random.Random(seed)
    profile = SimulationProfile(initial_x=10.0, initial_y=10.0, initial_z=10.0,
                                stock_resolution=1.0, max_stock_cells=10_000)
    plant = VirtualMachinePlant(profile)
    controller = VirtualGrblController(plant)
    controller.boot()
    stock = StockModel(SimulationWorkpiece(stock_width=40, stock_height=30, stock_thickness=5), profile)
    world = CollisionWorld(profile)
    trace = TraceRecorder(source="property", max_events=max(512, steps * (stress_depth + 3)))
    trace.record(0, "property_start", {"seed": seed, "steps": steps, "stress_depth": stress_depth})
    previous = plant.snapshot()
    stock_volumes = [stock.metrics().remaining_volume]
    hazards: set[tuple[str, str, str]] = set()
    actions: list[str] = []
    max_planner = 0
    max_responses = 0
    first_failure = ""
    failure_step: int | None = None
    failure_action = ""
    fixture_added = False

    def fail(step: int, action: str, reason: str) -> None:
        nonlocal first_failure, failure_step, failure_action
        if not first_failure:
            first_failure, failure_step, failure_action = reason, step, action

    def send(data: bytes, label: str) -> tuple[str, ...]:
        controller.receive(data)
        responses = controller.drain()
        trace.record(plant.clock.time_ns, "command", {"action": label,
                     "wire": data.decode("ascii", errors="replace")}, source="controller")
        if responses:
            trace.record(plant.clock.time_ns, "response", {"lines": list(responses)}, source="controller")
        return responses

    def tick(delta_ns: int) -> None:
        nonlocal previous, max_planner, max_responses
        controller.advance(delta_ns)
        current = plant.snapshot()
        trace.record(current.time_ns, "motion", {"snapshot": current.to_dict()}, source="plant")
        max_planner = max(max_planner, len(plant.queue) + (1 if plant.active is not None else 0))
        max_responses = max(max_responses, len(controller._responses))
        for hazard in world.check_transition(
                previous, current,
                rapid=bool(current.motion and current.motion.rapid),
                spindle_on=current.spindle_rpm > 1.0,
                stock=stock):
            key = (hazard.kind.value, hazard.body_a, hazard.body_b)
            if key not in hazards:
                hazards.add(key)
                trace.record(hazard.time_ns, "hazard", hazard.to_dict(), source=hazard.source)
        previous = current
        if not all(math.isfinite(value) and 0.0 <= value <= limit + 1e-6
                   for value, limit in zip(current.machine_position,
                                           (profile.travel_x, profile.travel_y, profile.travel_z))):
            raise AssertionError("machine position left the validated envelope")
        if len(plant.queue) + (1 if plant.active is not None else 0) > profile.planner_capacity:
            raise AssertionError("planner depth exceeded configured capacity")
        if stock.metrics().remaining_volume > stock_volumes[-1] + 1e-8:
            raise AssertionError("stock volume increased")
        stock_volumes.append(stock.metrics().remaining_volume)

    for step in range(steps):
        choices = ("move", "arc", "jog", "hold", "resume", "reset", "spindle",
                   "probe", "wco", "fault", "collision", "backpressure", "disconnect")
        action = choices[rng.randrange(len(choices))]
        actions.append(action)
        try:
            if action == "move":
                x = rng.uniform(2.0, 35.0)
                y = rng.uniform(2.0, 25.0)
                z = rng.uniform(2.0, 15.0)
                send(f"G90 G21 G1 X{x:.3f} Y{y:.3f} Z{z:.3f} F600\n".encode(), action)
                tick(750_000_000)
                if plant.spindle_rpm > 1.0 and plant.active is None:
                    frame = CoordinateFrame(tuple(plant.work_offset))
                    path = [frame.machine_to_work(point) for point in (previous.machine_position, plant.machine_position)]
                    stock.remove_swept_path(path, profile.tool_radius)
            elif action == "arc":
                send(b"G91 G2 X2 Y0 I1 J0 F300\n", action)
                tick(500_000_000)
            elif action == "jog":
                send(b"$J=G91 G21 X1 F600\n", action)
                tick(250_000_000)
            elif action == "hold":
                send(b"!", action)
                tick(100_000_000)
            elif action == "resume":
                send(b"~", action)
                tick(750_000_000)
            elif action == "reset":
                send(b"\x18", action)
                tick(10_000_000)
            elif action == "spindle":
                send((b"M3 S4000\n" if rng.randrange(2) else b"M5\n"), action)
                tick(100_000_000)
            elif action == "probe":
                plant.probe_surface_z = max(1.0, plant.machine_position[2] - 0.5)
                send(b"G91 G38.2 Z-1 F60\n", action)
                tick(500_000_000)
            elif action == "wco":
                send(b"G10 L20 P1 X0 Y0 Z0\n", action)
                tick(10_000_000)
            elif action == "fault":
                fault_name = ("duplicate_ack", "delayed_ack", "probe_failure", "changed_wco")[rng.randrange(4)]
                controller.install_fault(SimulationFault(fault_name, at_sequence=controller._line_sequence + 1,
                                                          value="10" if fault_name == "delayed_ack" else ""))
                send(b"G1 X12 F300\n", action)
                tick(500_000_000)
                controller.clear_faults()
            elif action == "collision":
                if not fixture_added:
                    world.add_fixture(Fixture("property-clamp", AABB(14, 14, 0, 18, 18, 12)))
                    fixture_added = True
                send(b"G1 X16 Y16 Z6 F300\n", action)
                tick(500_000_000)
            elif action == "backpressure":
                for _ in range(min(profile.planner_capacity + 4, 8 * stress_depth)):
                    send(b"G1 X11 F600\n", action)
                deferred_limit = controller.deferred_capacity
                if len(controller._deferred_lines) > deferred_limit:
                    raise AssertionError("deferred command FIFO exceeded bounded stress window")
                tick(2_000_000_000)
            else:  # disconnect/recovery is represented without opening a transport.
                trace.record(plant.clock.time_ns, "disconnect", {"owned_loopback": False}, source="property")
                send(b"\x18", action)
                tick(10_000_000)
                send(b"$X\n", "recovery")
                tick(10_000_000)
        except (AssertionError, RuntimeError, ValueError) as exc:
            fail(step, action, str(exc))
            break
        status = controller.status_line()
        trace.record(plant.clock.time_ns, "status", {"line": status}, source="controller")
        if not status.startswith("<") or not status.endswith(">"):
            fail(step, action, "status framing invariant failed")
            break

    trace.record(plant.clock.time_ns, "property_end", {
        "seed": seed, "steps": steps, "actions": actions,
        "hazards": sorted(hazards), "remaining_volume": stock.metrics().remaining_volume,
    })
    return PropertyScenarioResult(
        seed, steps, not first_failure, trace.digest(), len(actions), max_planner,
        max_responses, len(hazards), tuple(stock_volumes), first_failure,
        failure_step, failure_action)


def run_property_corpus(seeds: tuple[int, ...] = COMPACT_PROPERTY_SEEDS, *,
                        steps: int = DEFAULT_PROPERTY_STEPS,
                        stress_depth: int = 1) -> tuple[PropertyScenarioResult, ...]:
    """Run the compact deterministic CI corpus."""
    return tuple(run_property_scenario(seed, steps=steps, stress_depth=stress_depth) for seed in seeds)


def write_property_replay_artifact(result: PropertyScenarioResult, path: Path) -> None:
    """Persist compact first-failure/replay context without runtime evidence."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema_version": 1, **asdict(result),
                                "replay": result.replay_context()}, indent=2) + "\n",
                     encoding="utf-8")
