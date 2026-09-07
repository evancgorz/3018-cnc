"""Independent operator/safety supervisor process."""

from __future__ import annotations

import multiprocessing.connection
import time
from typing import Any

from .collision import CollisionWorld
from .models import Hazard, HazardKind, PlantSnapshot, SimulationProfile, SimulationWorkpiece
from .stock import StockModel


def _snapshot(data: dict[str, Any]) -> PlantSnapshot:
    motion = data.get("motion")
    from .models import MotionSnapshot
    return PlantSnapshot(int(data["time_ns"]), str(data["state"]), tuple(data["machine_position"]),
                         tuple(data["work_offset"]), float(data["feed"]), float(data["spindle_target"]),
                         float(data["spindle_rpm"]), str(data.get("pins", "")),
                         MotionSnapshot(**motion) if motion else None, int(data.get("sequence", 0)))


def supervisor_main(ready: multiprocessing.connection.Connection, control: multiprocessing.connection.Connection,
                    incoming, outgoing, profile_data: dict[str, Any], token: str,
                    workpiece_data: dict[str, Any] | None = None) -> None:
    profile = SimulationProfile(**profile_data)
    profile.validate()
    world = CollisionWorld(profile=profile)
    stock = None
    if workpiece_data:
        workpiece = SimulationWorkpiece(**workpiece_data)
        workpiece.validate()
        stock = StockModel(workpiece, profile)
    ready.send({"version": 1, "token": token, "role": "supervisor"})
    previous: PlantSnapshot | None = None
    active_hazards: set[tuple[str, str, str]] = set()
    last_heartbeat = time.monotonic()
    last_stock_metrics = 0.0
    pending_intents: list[dict[str, Any]] = []
    while True:
        if control.poll():
            message = control.recv()
            if isinstance(message, dict) and message.get("op") == "stop":
                return
            if isinstance(message, dict) and message.get("op") == "scenario_intents":
                pending_intents.extend(item for item in message.get("intents", []) if isinstance(item, dict))
        try:
            message = incoming.get(timeout=0.05)
        except Exception:
            message = None
        if isinstance(message, dict):
            if message.get("type") == "shutdown":
                return
            if message.get("type") == "snapshot":
                current = _snapshot(message["snapshot"])
                if previous is not None and current.state in {"Run", "Jog", "Hold:0", "Hold"}:
                    # Plant positions are machine coordinates, while the
                    # imported workpiece is expressed in work coordinates.
                    # Translate the stock envelope into the current machine
                    # frame before collision checks; otherwise a non-zero
                    # WCO makes every cutting move appear above the stock.
                    hazards = world.check_transition(previous, current,
                                                     rapid=bool(current.motion and current.motion.rapid),
                                                     spindle_on=current.spindle_rpm > 1.0,
                                                     stock=stock,
                                                     stock_offset=current.work_offset)
                    observed: set[tuple[str, str, str]] = set()
                    for hazard in hazards:
                        key = (hazard.kind.value, hazard.body_a, hazard.body_b)
                        observed.add(key)
                        if key not in active_hazards:
                            outgoing.put({"type": "hazard", "hazard": hazard.to_dict()})
                            active_hazards.add(key)
                    for key in active_hazards - observed:
                        outgoing.put({"type": "hazard_clear", "key": key})
                    active_hazards.intersection_update(observed)
                    if stock is not None and current.motion is not None and current.spindle_rpm > 1.0 and not current.motion.rapid:
                        # StockModel stores remaining height above its local
                        # bottom.  Convert the machine's positive-up GRBL Z
                        # (stock top at work-Z 0) into that bounded height.
                        thickness = stock.workpiece.stock_thickness
                        px, py, pz = previous.machine_position
                        cx, cy, cz = current.machine_position
                        offset_x, offset_y, offset_z = current.work_offset
                        bottom = stock.workpiece.origin_z + offset_z - thickness
                        start = (px - stock.workpiece.origin_x - offset_x,
                                 py - stock.workpiece.origin_y - offset_y,
                                 max(0.0, min(thickness, pz - bottom)))
                        end = (cx - stock.workpiece.origin_x - offset_x,
                               cy - stock.workpiece.origin_y - offset_y,
                               max(0.0, min(thickness, cz - bottom)))
                        stock.remove_swept_segment(start, end, profile.tool_radius)
                    now = time.monotonic()
                    if stock is not None and now - last_stock_metrics >= 0.2:
                        outgoing.put({"type": "stock_metrics", "metrics": stock.metrics().__dict__})
                        last_stock_metrics = now
                elif active_hazards:
                    for key in active_hazards:
                        outgoing.put({"type": "hazard_clear", "key": key})
                    active_hazards.clear()
                previous = current
            elif message.get("type") == "telemetry_overflow":
                outgoing.put({"type": "hazard", "hazard": Hazard(HazardKind.SUPERVISOR_UNAVAILABLE, "Backend telemetry overflow", 0, (0, 0, 0), source="supervisor").to_dict()})
        if pending_intents:
            outgoing.put({"type": "intent", "intent": pending_intents.pop(0)})
        if time.monotonic() - last_heartbeat >= 0.5:
            outgoing.put({"type": "heartbeat", "time": time.monotonic()})
            last_heartbeat = time.monotonic()
