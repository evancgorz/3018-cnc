"""Owner-side lifecycle for backend and independent supervisor processes."""

from __future__ import annotations

import multiprocessing as mp
import queue
import secrets
import time
from dataclasses import asdict
from typing import Any

from .backend import backend_main
from .models import Hazard, HazardKind, SimulationProfile, SimulationWorkpiece
from .supervisor import supervisor_main
from .trace import TraceRecorder


class SimulationRuntime:
    # A fast simulation can continuously produce telemetry (and repeated
    # supervisor hazards while an interlock is propagating).  Never let one
    # UI poll monopolize the Qt event loop while draining a live queue.
    MAX_EVENTS_PER_POLL = 256
    MAX_HAZARDS = 256

    def __init__(self, profile: SimulationProfile | None = None,
                 workpiece: SimulationWorkpiece | None = None,
                 speed: str = "realtime") -> None:
        self.profile = profile or SimulationProfile.default_3018()
        self.profile.validate()
        self.workpiece = workpiece
        if self.workpiece is not None:
            self.workpiece.validate()
        if speed not in {"realtime", "2x", "5x", "10x", "uncapped"}:
            raise ValueError(f"Unknown simulation speed: {speed}")
        self.speed = speed
        self.ctx = mp.get_context("spawn")
        self.backend: mp.Process | None = None
        self.supervisor: mp.Process | None = None
        self.endpoint: tuple[str, int] | None = None
        self._backend_control = None
        self._supervisor_control = None
        self._backend_ready = None
        self._supervisor_ready = None
        self._telemetry = None
        self._supervisor_in = None
        self._supervisor_out = None
        self.hazards: list[Hazard] = []
        self.stock_metrics: dict[str, Any] | None = None
        # Hazard episodes are keyed by their semantic bodies, never by the
        # producer timestamp.  A timestamp changes on every telemetry sample
        # during one persistent contact and would otherwise flood both the
        # incident history and the backend interlock channel.
        self._active_hazard_keys: set[tuple[str, str, str]] = set()
        self._interlocked_hazards: set[tuple[str, str, str]] = set()
        self.trace = TraceRecorder(source="runtime", max_events=16_384)
        self.session_token = secrets.token_urlsafe(18)
        self.started = False
        self._last_supervisor_heartbeat = 0.0
        self._supervisor_failure_reported = False
        self._supervisor_overflow_reported = False

    def start(self, timeout: float = 5.0) -> tuple[str, int]:
        if self.started:
            raise RuntimeError("Simulation runtime is already started")
        self.stock_metrics = None
        self.hazards.clear()
        self._active_hazard_keys.clear()
        self._interlocked_hazards.clear()
        self._backend_ready, backend_child = self.ctx.Pipe(False)
        self._backend_control, backend_parent = self.ctx.Pipe(True)
        self._telemetry = self.ctx.Queue(maxsize=2048)
        workpiece_data = asdict(self.workpiece) if self.workpiece is not None else None
        self.backend = self.ctx.Process(target=backend_main, args=(backend_child, backend_parent, self._telemetry, self.profile.to_dict(), self.session_token, workpiece_data, self.speed), name=f"pine-twin-backend-{self.session_token[:6]}")
        self.backend.start()
        try:
            if not self._backend_ready.poll(timeout):
                raise RuntimeError("Digital twin backend handshake timed out")
            ready = self._backend_ready.recv()
            if ready.get("token") != self.session_token or ready.get("version") != 1:
                raise RuntimeError("Digital twin backend handshake mismatch")
            self.endpoint = (str(ready["host"]), int(ready["port"]))
            self._supervisor_ready, supervisor_child = self.ctx.Pipe(False)
            self._supervisor_control, supervisor_parent = self.ctx.Pipe(True)
            self._supervisor_in = self.ctx.Queue(maxsize=2048)
            self._supervisor_out = self.ctx.Queue(maxsize=2048)
            self.supervisor = self.ctx.Process(target=supervisor_main, args=(supervisor_child, supervisor_parent, self._supervisor_in, self._supervisor_out, self.profile.to_dict(), self.session_token, workpiece_data), name=f"pine-twin-supervisor-{self.session_token[:6]}")
            self.supervisor.start()
            if not self._supervisor_ready.poll(timeout):
                raise RuntimeError("Digital twin supervisor handshake timed out")
            supervisor_ready = self._supervisor_ready.recv()
            if supervisor_ready.get("token") != self.session_token or supervisor_ready.get("version") != 1:
                raise RuntimeError("Digital twin supervisor handshake mismatch")
            self.started = True
            self._last_supervisor_heartbeat = time.monotonic()
            self._supervisor_failure_reported = False
            self._supervisor_overflow_reported = False
            self.trace.record(0, "runtime_started", {"profile": self.profile.to_dict()})
            return self.endpoint
        except Exception:
            self.stop()
            raise

    def poll(self) -> tuple[dict[str, Any], ...]:
        if not self.started:
            return ()
        forwarded: list[dict[str, Any]] = []
        telemetry_events = 0
        while telemetry_events < self.MAX_EVENTS_PER_POLL:
            try: item = self._telemetry.get_nowait()
            except queue.Empty: break
            forwarded.append(item)
            telemetry_events += 1
            if item.get("type") == "snapshot":
                snapshot_data = item.get("snapshot", {})
                self.trace.record(int(snapshot_data.get("time_ns", 0)), "status", {
                    "snapshot": snapshot_data,
                    "backend_hazards": item.get("backend_hazards", []),
                }, source="backend")
            if self._supervisor_in is not None:
                try: self._supervisor_in.put_nowait(item)
                except queue.Full:
                    if not self._supervisor_overflow_reported:
                        self._supervisor_overflow_reported = True
                        overflow = Hazard(HazardKind.SUPERVISOR_UNAVAILABLE, "Supervisor queue overflow", 0, (0, 0, 0), source="runtime")
                        self.hazards.append(overflow)
                        self.trace.record(0, "hazard", {"kind": overflow.kind.value, "message": overflow.message}, source=overflow.source)
        supervisor_events = 0
        while self._supervisor_out is not None and supervisor_events < self.MAX_EVENTS_PER_POLL:
            try: item = self._supervisor_out.get_nowait()
            except queue.Empty: break
            forwarded.append(item)
            supervisor_events += 1
            item_type = item.get("type", "supervisor_event")
            if item_type in {"heartbeat", "hazard", "hazard_clear", "stock_metrics", "operator_intent", "intent"}:
                event_time = int(item.get("hazard", {}).get("time_ns", 0))
                prior = self.trace.events
                prior_time = prior[-1].time_ns if prior else 0
                event_time = max(prior_time, event_time)
                self.trace.record(event_time, item_type, dict(item), source="supervisor")
            if item.get("type") == "stock_metrics":
                self.stock_metrics = dict(item.get("metrics", {}))
            if item.get("type") == "hazard":
                hazard_data = item["hazard"]
                key = (str(hazard_data.get("kind", "protocol")),
                       str(hazard_data.get("body_a", "")),
                       str(hazard_data.get("body_b", "")))
                # The supervisor normally performs this edge detection.  Keep
                # the owner-side guard as a second line of defence for queue
                # duplication, reconnect replay, and malformed test actors.
                if key in self._active_hazard_keys:
                    continue
                self._active_hazard_keys.add(key)
                incident = Hazard(HazardKind(hazard_data["kind"]), hazard_data["message"], int(hazard_data["time_ns"]), tuple(hazard_data["position"]), hazard_data.get("body_a", ""), hazard_data.get("body_b", ""), hazard_data.get("severity", "alarm"), hazard_data.get("source", "supervisor"), int(hazard_data.get("segment_id", 0)))
                if len(self.hazards) >= self.MAX_HAZARDS:
                    del self.hazards[: len(self.hazards) - self.MAX_HAZARDS + 1]
                self.hazards.append(incident)
                self.trace.record(incident.time_ns, "hazard", {"kind": incident.kind.value, "body_a": incident.body_a, "body_b": incident.body_b, "message": incident.message}, source=incident.source)
                if self._backend_control is not None and key not in self._interlocked_hazards:
                    self._interlocked_hazards.add(key)
                    try:
                        self._backend_control.send({"op": "interlock", "kind": key[0]})
                    except (BrokenPipeError, EOFError, OSError):
                        pass
            if item.get("type") == "hazard_clear":
                raw_key = item.get("key", ())
                if isinstance(raw_key, (list, tuple)) and len(raw_key) == 3:
                    key = tuple(str(value) for value in raw_key)
                    self._active_hazard_keys.discard(key)
                    self._interlocked_hazards.discard(key)
            if item.get("type") == "heartbeat":
                self._last_supervisor_heartbeat = time.monotonic()
        if self.started and not self.supervisor_healthy and not self._supervisor_failure_reported:
            self._supervisor_failure_reported = True
            hazard = Hazard(HazardKind.SUPERVISOR_UNAVAILABLE,
                            "Digital-twin safety supervisor stopped or heartbeat expired", 0,
                            (0.0, 0.0, 0.0), source="runtime")
            self.hazards.append(hazard)
            try:
                if self._backend_control is not None:
                    self._backend_control.send({"op": "interlock", "kind": hazard.kind.value})
            except (BrokenPipeError, EOFError, OSError):
                pass
        return tuple(forwarded)

    @property
    def supervisor_healthy(self) -> bool:
        """Whether the owned supervisor is alive and recently heartbeating."""
        return bool(self.started and self.supervisor is not None
                    and self.supervisor.is_alive()
                    and self._last_supervisor_heartbeat
                    and time.monotonic() - self._last_supervisor_heartbeat < 2.0)

    def start_scenario(self, intents: list[dict[str, Any]]) -> None:
        """Ask the independent supervisor to emit typed operator intents."""
        if not self.started or self._supervisor_control is None:
            raise RuntimeError("Digital twin supervisor is not running")
        if not isinstance(intents, list):
            raise TypeError("Scenario intents must be a list")
        self._supervisor_control.send({"op": "scenario_intents", "intents": intents})

    def stop(self, timeout: float = 3.0) -> None:
        for control, process in ((self._backend_control, self.backend), (self._supervisor_control, self.supervisor)):
            if process is None:
                continue
            try:
                if control is not None: control.send({"op": "stop"})
            except (BrokenPipeError, EOFError, OSError):
                pass
            process.join(timeout=timeout)
            if process.is_alive():
                # This is an exact child we own; terminate only this PID after
                # graceful shutdown has timed out.
                process.terminate()
                process.join(timeout=timeout)
        self.backend = self.supervisor = None
        self.started = False
        self.endpoint = None
        for channel in (self._telemetry, self._supervisor_in, self._supervisor_out):
            if channel is None:
                continue
            try:
                # Evidence queues are lossy by design; never let shutdown
                # block flushing a stale telemetry burst after the children
                # have already exited.
                channel.cancel_join_thread()
                channel.close()
                channel.join_thread()
            except (AttributeError, OSError, AssertionError):
                pass
        for connection in (self._backend_control, self._supervisor_control, self._backend_ready, self._supervisor_ready):
            if connection is None:
                continue
            try:
                connection.close()
            except (OSError, EOFError):
                pass
        self._telemetry = self._supervisor_in = self._supervisor_out = None
        self._backend_control = self._supervisor_control = None
        self._backend_ready = self._supervisor_ready = None
        self.trace.record(0, "runtime_stopped")

    def __enter__(self) -> "SimulationRuntime":
        self.start()
        return self

    def __exit__(self, *_exc) -> None:
        self.stop()
