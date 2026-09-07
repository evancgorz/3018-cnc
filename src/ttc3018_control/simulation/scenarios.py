"""Deterministic headless scenario definitions for development regression."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from .controller import VirtualGrblController
from .collision import CollisionWorld
from .models import SimulationIntent
from .plant import VirtualMachinePlant
from .trace import TraceRecorder


@dataclass(frozen=True)
class Scenario:
    name: str
    seed: int
    intents: tuple[SimulationIntent, ...]
    description: str = ""


@dataclass(frozen=True)
class ScenarioResult:
    name: str
    passed: bool
    final_position: tuple[float, float, float]
    final_state: str
    assertions: tuple[str, ...] = ()
    failures: tuple[str, ...] = ()
    trace_digest: str = ""
    trace_events: tuple[dict[str, Any], ...] = ()
    hazards: tuple[dict[str, Any], ...] = ()
    stock_metrics: dict[str, Any] | None = None


def built_in_scenarios() -> tuple[Scenario, ...]:
    return (
        Scenario("status", 1, (SimulationIntent("status"),), "Startup and fresh status"),
        Scenario("all_axis_motion", 2, (SimulationIntent("move", {"x": 10, "y": 8, "z": 4}), SimulationIntent("move", {"x": 2, "y": 2, "z": 2})), "Coordinated XYZ motion"),
        Scenario("hold_resume", 3, (SimulationIntent("move", {"x": 40, "y": 20, "z": 5}), SimulationIntent("hold"), SimulationIntent("resume")), "Feed hold and resume"),
        Scenario("limit_alarm", 4, (SimulationIntent("move", {"x": 999, "y": 0, "z": 0}),), "Continuous travel limit alarm"),
        Scenario("reset", 5, (SimulationIntent("move", {"x": 20, "y": 20, "z": 5}), SimulationIntent("reset")), "Reset while moving"),
    )


def run_headless_scenario(scenario: Scenario, *, plant: VirtualMachinePlant | None = None,
                          controller: VirtualGrblController | None = None) -> ScenarioResult:
    plant = plant or VirtualMachinePlant()
    controller = controller or VirtualGrblController(plant)
    trace = TraceRecorder(source="scenario")
    collision_world = CollisionWorld(profile=plant.profile)
    hazards: list[dict[str, Any]] = []
    hazard_keys: set[tuple[str, str, str]] = set()

    def record_hazards(items) -> None:
        for item in items:
            key = (item.kind.value, item.body_a, item.body_b)
            if key not in hazard_keys:
                hazard_keys.add(key)
                hazards.append(item.to_dict())
    assertions: list[str] = []
    failures: list[str] = []
    trace.record(0, "scenario_start", {"name": scenario.name, "seed": scenario.seed})
    controller.boot()
    previous_snapshot = plant.snapshot()
    for index, intent in enumerate(scenario.intents):
        trace.record(plant.clock.time_ns, "intent", {"name": intent.name, "arguments": intent.arguments})
        if intent.name == "status":
            controller.receive(b"?")
        elif intent.name == "move":
            args = intent.arguments
            controller.receive(f"G90 G21 G1 X{args.get('x', 0)} Y{args.get('y', 0)} Z{args.get('z', 0)} F600\n".encode())
        elif intent.name == "hold": controller.receive(b"!")
        elif intent.name == "resume": controller.receive(b"~")
        elif intent.name == "reset": controller.receive(b"\x18")
        elif intent.name == "malformed": controller.receive(b"G1 Xnope\n")
        else: failures.append(f"unknown intent {intent.name}")
        controller.drain()
        next_name = scenario.intents[index + 1].name if index + 1 < len(scenario.intents) else ""
        # Leave a move in flight for the safety/user intents that are meant to
        # interrupt it.  Other commands run to deterministic completion.
        if intent.name == "move" and next_name in {"hold", "reset"}:
            current_snapshot = plant.advance(100_000_000)
            record_hazards(collision_world.check_transition(
                previous_snapshot, current_snapshot,
                rapid=bool(current_snapshot.motion and current_snapshot.motion.rapid),
                spindle_on=current_snapshot.spindle_rpm > 1.0,
            ))
            previous_snapshot = current_snapshot
        elif intent.name == "hold":
            current_snapshot = plant.advance(100_000_000)
            record_hazards(collision_world.check_transition(
                previous_snapshot, current_snapshot,
                rapid=bool(current_snapshot.motion and current_snapshot.motion.rapid),
                spindle_on=current_snapshot.spindle_rpm > 1.0,
            ))
            previous_snapshot = current_snapshot
        else:
            for _ in range(10000):
                if not plant.busy:
                    break
                current_snapshot = plant.advance(10_000_000)
                record_hazards(collision_world.check_transition(
                    previous_snapshot, current_snapshot,
                    rapid=bool(current_snapshot.motion and current_snapshot.motion.rapid),
                    spindle_on=current_snapshot.spindle_rpm > 1.0,
                ))
                previous_snapshot = current_snapshot
    snapshot = plant.snapshot()
    if scenario.name == "limit_alarm" and snapshot.state != "Alarm":
        failures.append("limit scenario did not alarm")
    if scenario.name == "reset" and snapshot.state != "Idle":
        failures.append("reset scenario did not settle Idle")
    if scenario.name == "hold_resume" and snapshot.machine_position != (40.0, 20.0, 5.0):
        failures.append("hold/resume did not reach the commanded endpoint")
    if scenario.name == "reset" and snapshot.machine_position == (20.0, 20.0, 5.0):
        failures.append("reset did not interrupt the in-flight move")
    assertions.append(f"final state {snapshot.state}")
    trace.record(snapshot.time_ns, "scenario_end", {"state": snapshot.state, "position": snapshot.machine_position})
    return ScenarioResult(scenario.name, not failures, snapshot.machine_position, snapshot.state,
                          tuple(assertions), tuple(failures), trace.digest(),
                          tuple(event.to_dict() for event in trace.events),
                          tuple(hazards), None)
