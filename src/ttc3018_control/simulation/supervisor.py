"""Independent operator/safety supervisor process."""

from __future__ import annotations

import multiprocessing.connection
import time
from typing import Any

from .models import Hazard, HazardKind, PlantSnapshot, SimulationFault, SimulationProfile, SimulationWorkpiece
from .operator import IndependentVirtualOperator
from .geometry import CoordinateFrame, executed_path
from .stock import StockModel
from .plant import ProbeBoundary


def _snapshot(data: dict[str, Any], fallback_sequence: int = 0) -> PlantSnapshot:
    motion = data.get("motion")
    from .models import MotionSnapshot
    sequence = int(data.get("sequence", 0))
    if sequence <= fallback_sequence:
        sequence = fallback_sequence + 1
    if motion:
        motion = dict(motion)
        motion["start"] = tuple(motion.get("start", (0.0, 0.0, 0.0)))
        motion["target"] = tuple(motion.get("target", (0.0, 0.0, 0.0)))
        motion["path"] = tuple(tuple(point) for point in motion.get("path", ()))
        motion = MotionSnapshot(**motion)
    return PlantSnapshot(int(data["time_ns"]), str(data["state"]), tuple(data["machine_position"]),
                         tuple(data["work_offset"]), float(data["feed"]), float(data["spindle_target"]),
                         float(data["spindle_rpm"]), str(data.get("pins", "")), motion, sequence)


def _emit_assessment(outgoing, assessment) -> None:
    for hazard in assessment.hazards:
        outgoing.put({"type": "hazard", "hazard": hazard.to_dict()})
    for key in assessment.cleared:
        outgoing.put({"type": "hazard_clear", "key": key})
    for intent in assessment.intents:
        outgoing.put({"type": "operator_intent", "intent": intent.to_dict()})


def supervisor_main(ready: multiprocessing.connection.Connection, control: multiprocessing.connection.Connection,
                    incoming, outgoing, profile_data: dict[str, Any], token: str,
                    workpiece_data: dict[str, Any] | None = None,
                    faults_data: list[dict[str, Any]] | None = None,
                    probe_boundary_data: dict[str, Any] | None = None) -> None:
    """Run the actor without importing application, transport, or backend code."""
    profile = SimulationProfile(**profile_data)
    profile.validate()
    workpiece = SimulationWorkpiece(**workpiece_data) if workpiece_data else None
    if workpiece is not None:
        workpiece.validate()
    # Keep the supervisor's geometry configuration independently validated;
    # it never calls the backend probe implementation or mutates plant state.
    if probe_boundary_data:
        ProbeBoundary.from_dict(probe_boundary_data)
    operator = IndependentVirtualOperator(profile, workpiece=workpiece)
    faults = [SimulationFault(**data) for data in faults_data or ()]
    for fault in faults:
        fault.validate()
    stock = StockModel.from_workpiece(workpiece, profile) if workpiece is not None else None
    ready.send({"version": 1, "token": token, "role": "supervisor"})
    pending_intents: list[dict[str, Any]] = []
    last_heartbeat = time.monotonic()
    last_sequence = 0
    previous_snapshot: PlantSnapshot | None = None
    while True:
        if control.poll():
            message = control.recv()
            if isinstance(message, dict) and message.get("op") == "stop":
                return
            if isinstance(message, dict) and message.get("op") == "scenario_intents":
                pending_intents.extend(item for item in message.get("intents", []) if isinstance(item, dict))
            if isinstance(message, dict) and message.get("op") == "install_fault":
                fault = SimulationFault(**dict(message.get("fault", {})))
                fault.validate()
                faults.append(fault)
            if isinstance(message, dict) and message.get("op") == "clear_faults":
                faults.clear()
        try:
            message = incoming.get(timeout=0.05)
        except Exception:
            message = None
        if isinstance(message, dict):
            if message.get("type") == "shutdown":
                return
            if message.get("type") == "snapshot":
                current = _snapshot(message["snapshot"], last_sequence)
                last_sequence = current.sequence
                has_backend_verdict = "backend_hazards" in message
                raw_expected = message.get("backend_hazards", ())
                expected: list[Hazard] | None = [] if has_backend_verdict else None
                for item in raw_expected or ():
                    if not isinstance(item, dict) or item.get("kind") not in {kind.value for kind in HazardKind}:
                        continue
                    assert expected is not None
                    expected.append(Hazard(HazardKind(item["kind"]), str(item.get("message", "")),
                                           int(item.get("time_ns", current.time_ns)),
                                           tuple(item.get("position", current.machine_position)),
                                           str(item.get("body_a", "")), str(item.get("body_b", ""))))
                previous = previous_snapshot
                _emit_assessment(outgoing, operator.observe(current, expected_hazards=expected))
                previous_snapshot = current
                if (stock is not None and previous is not None
                        and (current.motion is not None or previous.motion is not None)
                        and current.spindle_rpm > 1.0
                        and not bool(current.motion and current.motion.rapid)):
                    frame = CoordinateFrame(tuple(current.work_offset))
                    thickness = stock.workpiece.stock_thickness
                    path = []
                    for point in executed_path(previous, current):
                        work_point = frame.machine_to_work(point)
                        path.append((
                            work_point[0] - stock.workpiece.origin_x,
                            work_point[1] - stock.workpiece.origin_y,
                            max(0.0, min(thickness,
                                work_point[2] - stock.workpiece.origin_z + thickness)),
                        ))
                    stock.remove_swept_path(path, profile.tool_radius)
                if stock is not None:
                    outgoing.put({"type": "stock_metrics", "metrics": stock.metrics().__dict__})
            elif message.get("type") == "telemetry_overflow":
                _emit_assessment(outgoing, operator.report_failure("Backend telemetry overflow"))
        if pending_intents:
            user_intent = pending_intents.pop(0)
            for operator_intent in operator.consume_intent(user_intent):
                outgoing.put({"type": "operator_intent", "intent": operator_intent.to_dict()})
            outgoing.put({"type": "intent", "intent": user_intent})
        heartbeat_lost = any(fault.name == "supervisor_heartbeat_loss"
                             and fault.matches(last_sequence, previous_snapshot.time_ns if previous_snapshot else 0)
                             for fault in faults)
        if time.monotonic() - last_heartbeat >= 0.5 and not heartbeat_lost:
            outgoing.put({"type": "heartbeat", "time": time.monotonic()})
            last_heartbeat = time.monotonic()
