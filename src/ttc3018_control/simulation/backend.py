"""Spawn-safe loopback GRBL server for the digital twin."""

from __future__ import annotations

import json
import multiprocessing.connection
import queue
import select
import socket
import time
from typing import Any

from .controller import VirtualGrblController
from .collision import CollisionWorld
from .geometry import CoordinateFrame, executed_path
from .models import SimulationProfile
from .models import SimulationWorkpiece
from .plant import VirtualMachinePlant
from .stock import StockModel


def backend_main(ready: multiprocessing.connection.Connection, control: multiprocessing.connection.Connection,
                telemetry, profile_data: dict[str, Any], token: str,
                workpiece_data: dict[str, Any] | None = None, speed: str = "realtime") -> None:
    profile = SimulationProfile(**profile_data)
    profile.validate()
    plant = VirtualMachinePlant(profile)
    controller = VirtualGrblController(plant)
    collision_world = CollisionWorld(profile=profile)
    stock: StockModel | None = None
    previous_snapshot = None
    if workpiece_data:
        # Validate the workpiece in the owned child so malformed settings fail
        # closed even when the parent process was bypassed.
        workpiece = SimulationWorkpiece(**workpiece_data)
        workpiece.validate()
        stock = StockModel.from_workpiece(workpiece, profile)
    speed_factor = {"realtime": 1.0, "2x": 2.0, "5x": 5.0, "10x": 10.0, "uncapped": 50.0}.get(speed)
    if speed_factor is None:
        raise ValueError(f"Unknown simulation speed: {speed}")
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    server.settimeout(0.05)
    client: socket.socket | None = None
    try:
        host, port = server.getsockname()
        ready.send({"version": 1, "token": token, "host": host, "port": port})
        last = time.monotonic()
        last_telemetry = last
        while True:
            if control.poll():
                message = control.recv()
                if isinstance(message, dict) and message.get("op") == "stop":
                    return
                if isinstance(message, dict) and message.get("op") == "interlock":
                    plant.request_hold()
                    plant.reset()
                    controller.alarm = True
                    controller.plant.state = "Alarm"
                    if client is not None:
                        try:
                            client.sendall(b"ALARM:1\n")
                        except OSError:
                            pass
            if client is None:
                try:
                    client, _address = server.accept()
                    client.settimeout(0.01)
                    for line in controller.boot():
                        client.sendall(line.encode("utf-8") + b"\n")
                except socket.timeout:
                    client = None
            else:
                try:
                    readable, _, _ = select.select([client], [], [], 0)
                except (OSError, ValueError):
                    readable = []
                if readable:
                    try:
                        data = client.recv(4096)
                        if not data:
                            client.close(); client = None
                        else:
                            controller.receive(data)
                            for line in controller.drain():
                                client.sendall(line.encode("utf-8") + b"\n")
                    except (OSError, TimeoutError):
                        try: client.close()
                        except OSError: pass
                        client = None
            now = time.monotonic()
            delta_ns = max(0, min(50_000_000, round((now - last) * 1_000_000_000)))
            last = now
            if delta_ns:
                controller.advance(round(delta_ns * speed_factor))
                # Delayed/fault-injected acknowledgements are scheduled by
                # ``advance`` rather than by the receive path.  Drain after
                # advancing as well, otherwise a delayed ACK can remain in
                # the controller queue forever when the client is idle.
                if client is not None:
                    for line in controller.drain():
                        try:
                            client.sendall(line.encode("utf-8") + b"\n")
                        except OSError:
                            try: client.close()
                            except OSError: pass
                            client = None
                            break
                # A backend loop can run much faster than its consumers.  A
                # bounded observation cadence prevents redundant snapshots
                # from filling the owner and supervisor queues.
                if now - last_telemetry >= 0.02:
                    current_snapshot = controller.plant.snapshot()
                    snapshot = current_snapshot.to_dict()
                    backend_hazards = ()
                    if previous_snapshot is not None and current_snapshot.state in {"Run", "Jog", "Hold:0", "Hold"}:
                        backend_hazards = collision_world.check_transition(
                            previous_snapshot,
                            current_snapshot,
                            rapid=bool(current_snapshot.motion and current_snapshot.motion.rapid),
                            spindle_on=current_snapshot.spindle_rpm > 1.0,
                            stock=stock,
                            stock_offset=current_snapshot.work_offset,
                        )
                        if (stock is not None and current_snapshot.motion is not None
                                and current_snapshot.spindle_rpm > 1.0 and not current_snapshot.motion.rapid):
                            frame = CoordinateFrame(tuple(current_snapshot.work_offset))
                            thickness = stock.workpiece.stock_thickness
                            path = []
                            for point in executed_path(previous_snapshot, current_snapshot):
                                work_point = frame.machine_to_work(point)
                                path.append((work_point[0] - stock.workpiece.origin_x,
                                             work_point[1] - stock.workpiece.origin_y,
                                             max(0.0, min(thickness, work_point[2] - stock.workpiece.origin_z + thickness))))
                            stock.remove_swept_path(path, profile.tool_radius)
                    previous_snapshot = current_snapshot
                    telemetry_item = {
                        "type": "snapshot",
                        "snapshot": snapshot,
                        "backend_hazards": [hazard.to_dict() for hazard in backend_hazards],
                    }
                    try:
                        telemetry.put_nowait(telemetry_item)
                    except queue.Full:
                        # Losing telemetry is a safety failure; tell the owner
                        # and keep the controller deterministic until shutdown.
                        try: telemetry.put_nowait({"type": "telemetry_overflow"})
                        except queue.Full: pass
                    last_telemetry = now
    finally:
        if client is not None:
            try: client.close()
            except OSError: pass
        server.close()
