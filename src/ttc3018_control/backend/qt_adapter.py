"""Qt-facing projection over the authenticated backend contract.

The adapter deliberately contains no safety decisions. It reconstructs the
legacy ViewModel shape from the latest authoritative snapshot and forwards every
machine-affecting operation through the finite backend action registry.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import queue
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable
import time
import uuid

from ..application.connection_service import ConnectionOutcome
from ..application.machine_session import ActionOutcome
from ..application.state import ConnectionMode
from ..connection_settings import ConnectionSettings
from ..gcode import Bounds, GCodeError, GCodeProgram, Point, Segment
from ..grbl import GrblStatus, Position
from ..machine_config import MachineDefinition, ProbeKind
from ..machine_state import MachineProfile
from ..simulation.settings import SimulationSettings
from .client import BackendRequestRejected, BackendUnavailable
from .contracts import BackendEvent


def _position(value: Any) -> Position | None:
    if not isinstance(value, dict):
        return None
    try:
        return Position(float(value["x"]), float(value["y"]), float(value["z"]))
    except (KeyError, TypeError, ValueError):
        return None


def _point(value: Any) -> Point:
    if not isinstance(value, dict):
        return Point(0.0, 0.0, 0.0)
    return Point(float(value.get("x", 0.0)), float(value.get("y", 0.0)), float(value.get("z", 0.0)))


def _status(value: Any) -> GrblStatus | None:
    if not isinstance(value, dict):
        return None
    return GrblStatus(str(value.get("state", "Unknown")), _position(value.get("machine_position")),
                      _position(value.get("work_position")), _position(value.get("work_offset")),
                      value.get("feed"), value.get("spindle"), str(value.get("pins", "")),
                      dict(value.get("fields", {})))


@dataclass
class _Service:
    phase: str = ""
    state: Any = "idle"
    active: bool = False
    work_offset_confirmed: bool = False
    active_offset: float | None = None
    streamer: Any = None

    def __post_init__(self) -> None:
        if self.streamer is None:
            self.streamer = SimpleNamespace(error="", completed=0, total=0)


class BackendApplicationAdapter:
    """Compatibility-shaped application facade backed only by IPC facts."""

    def __init__(self, client, root: Path):
        self.client = client
        self._root = Path(root)
        self._snapshot: dict[str, Any] = {}
        self._events: queue.Queue = queue.Queue()
        self._event_sequence = 0
        self._callbacks: dict[str, Callable[..., Any]] = {}
        self.backend_unavailable = False
        self._backend_error = ""
        self._retry_after = 0.0
        self.settings = ConnectionSettings()
        self.simulation_settings = SimulationSettings()
        self.session = SimpleNamespace()
        self.motion = _Service()
        self.job = _Service()
        self.homing = _Service(state=SimpleNamespace(value="idle"))
        self.probing = _Service()
        self.calibration = _Service()
        self.tool_setting = _Service()
        self.fixtures = _Service()
        self._program: GCodeProgram | None = None
        self._program_provenance: dict[str, Any] = {}
        self._refresh()

    @property
    def root(self) -> Path:
        return self._root

    @property
    def snapshot(self) -> dict[str, Any]:
        return dict(self._snapshot)

    @property
    def state_revision(self) -> int:
        return int(self._snapshot.get("revision", self._snapshot.get("state_revision", 0)))

    def _refresh(self) -> None:
        try:
            self._snapshot = dict(self.client.snapshot())
            backend = self._snapshot.get("backend", {})
            self.backend_unavailable = isinstance(backend, dict) and not bool(backend.get("available", True))
            self._backend_error = str(self._snapshot.get("backend_error", ""))
        except (BackendUnavailable, OSError, ValueError, TypeError) as exc:
            self.backend_unavailable = True
            self._backend_error = str(exc)
            if self._snapshot:
                self._snapshot = dict(self._snapshot)
                backend = self._snapshot.get("backend", {})
                backend = dict(backend) if isinstance(backend, dict) else {}
                backend["available"] = False
                self._snapshot["backend"] = backend
                self._snapshot["status_state"] = "unavailable"
                self._snapshot["status_fresh"] = False
                self._snapshot["backend_error"] = self._backend_error
            else:
                self._snapshot = {
                    "schema_version": 1, "protocol_version": 1,
                    "backend": {"available": False, "session_id": ""},
                    "status_state": "unavailable", "connection_mode": "",
                    "connected": False, "status_fresh": False,
                    "reference_trusted": False, "work_zero_confirmed": False,
                    "backend_error": self._backend_error,
                }
        connection = self._snapshot.get("connection", {})
        connection = connection if isinstance(connection, dict) else {}
        mode = str(self._snapshot.get("connection_mode", connection.get("mode", "")))
        self.settings = ConnectionSettings(
            wifi_host=str(connection.get("saved_wifi_host", connection.get("endpoint", "192.168.4.1"))) or "192.168.4.1",
            wifi_port=int(connection.get("saved_wifi_port", connection.get("port", 23)) or 23),
            preferred_transport=str(connection.get("preferred_transport", mode or "USB serial")),
            usb_port=str(connection.get("usb_port", "")),
        )
        self._program = self._program_from_snapshot(self._snapshot.get("program_detail"))
        provenance = self._snapshot.get("program_provenance", {})
        self._program_provenance = dict(provenance) if isinstance(provenance, dict) else {}
        program_detail = self._snapshot.get("program_detail", {})
        self.program_preview = (
            dict(program_detail.get("preview", {}))
            if isinstance(program_detail, dict) and isinstance(program_detail.get("preview"), dict)
            else {}
        )
        self.program_execution_layer = (
            dict(program_detail.get("execution_layer", {}))
            if isinstance(program_detail, dict) and isinstance(program_detail.get("execution_layer"), dict)
            else {}
        )
        job = self._snapshot.get("job", {})
        job = job if isinstance(job, dict) else {}
        self.job.state = self.job_state
        self.job.active = self.job_active
        self.job.streamer = SimpleNamespace(error=str(job.get("error", "")),
                                             completed=int(job.get("completed", 0) or 0),
                                             total=int(job.get("total", 0) or 0))
        self.motion.active = bool(self._snapshot.get("active_operation"))
        self.motion.phase = str(self._snapshot.get("active_operation", ""))
        homing_state = str(self._snapshot.get("homing_state", "idle"))
        self.homing.state = SimpleNamespace(value=homing_state)
        self.homing.active = homing_state in {"waiting_ack", "waiting_idle"}
        self.calibration.state = SimpleNamespace(value=str(self._snapshot.get("auto_xyz_calibration_state", "idle")))
        self.calibration.active = self.calibration.state.value in {"searching", "fitted", "z_touch", "active", "running"}
        self.calibration.work_offset_confirmed = bool(self._snapshot.get("auto_xyz_wco_confirmed", False))
        reference = _position(self._snapshot.get("reference"))
        work_offset = _position(self._snapshot.get("work_offset"))
        self.session.envelope = SimpleNamespace(reference=reference, trusted=self.reference_trusted)
        self.session.work_offset = work_offset
        self.session.machine_position = self.machine_position
        self.session.virtual_position = self.virtual_position
        self.session.work_zero_confirmed = self.work_zero_confirmed
        self.session.profile = self.profile
        self.session.can_move = bool(self.can_jog)
        self.session.confirmed_work_zero_axes = set("XYZ") if self.work_zero_confirmed else set()
        self.session.awaiting_work_zero_report = False

    @staticmethod
    def _program_from_snapshot(value: Any) -> GCodeProgram | None:
        if not isinstance(value, dict) or not value.get("path"):
            return None
        bounds = value.get("bounds", {})
        bounds = bounds if isinstance(bounds, dict) else {}
        try:
            parsed_bounds = Bounds(_point(bounds.get("minimum")), _point(bounds.get("maximum")))
            raw_segments = value.get("segments", ())
            segments = tuple(
                Segment(_point(item.get("start")), _point(item.get("end")), bool(item.get("rapid", False)), item.get("feed"))
                for item in raw_segments if isinstance(item, dict)
            ) if isinstance(raw_segments, (list, tuple)) else ()
            raw_commands = value.get("commands", ())
            commands = tuple(str(item) for item in raw_commands) if isinstance(raw_commands, (list, tuple)) else ()
            count = int(value.get("command_count", len(commands)))
            if not commands and count:
                commands = tuple("<validated backend command>" for _ in range(count))
            raw_header_comments = value.get("header_comments", ())
            header_comments = tuple(str(item) for item in raw_header_comments) if isinstance(raw_header_comments, (list, tuple)) else ()
            return GCodeProgram(Path(str(value["path"])), commands, segments, parsed_bounds,
                                float(value.get("estimated_seconds", 0.0)),
                                str(value.get("source_sha256", "")),
                                header_comments)
        except (KeyError, TypeError, ValueError):
            return None

    def bind_callbacks(self, **callbacks) -> None:
        self._callbacks.update({key: value for key, value in callbacks.items() if callable(value)})

    def _notify_change(self) -> None:
        callback = self._callbacks.get("on_change")
        if callback is not None:
            callback()

    def application_events(self):
        self.poll_backend()
        items = []
        while True:
            try:
                items.append(self._events.get_nowait())
            except queue.Empty:
                return tuple(items)

    def poll_backend(self) -> tuple[BackendEvent, ...]:
        now = time.monotonic()
        if self.backend_unavailable and now < self._retry_after:
            return ()
        try:
            if self.backend_unavailable:
                previous_session = self.backend_session_id
                self.client.attach()
                if previous_session and previous_session != self.backend_session_id:
                    self._event_sequence = 0
            result = self.client.events(after=self._event_sequence, limit=100)
            events = tuple(BackendEvent.from_dict(item) for item in result.get("events", ()))
            if events:
                self._event_sequence = max(event.sequence for event in events)
            self._refresh()
            self.backend_unavailable = False
            self._retry_after = 0.0
            for event in events:
                self._events.put(event)
            if events:
                self._notify_change()
            return events
        except (BackendUnavailable, OSError, ValueError, TypeError):
            self._retry_after = now + 1.0
            self._refresh()
            self.backend_unavailable = True
            if not self._backend_error:
                self._backend_error = "Backend event polling failed"
            self._snapshot["backend_error"] = self._backend_error
            return ()

    def transport_events(self): return self._events
    def poll_wifi_setup(self, now): return None
    def poll_wifi(self): return None
    def poll_simulation(self): self.poll_backend(); return ()
    def check_job_watchdog(self): return None
    def handle_transport_response(self, response, feed=500.0): return None, False

    def request_status(self):
        try:
            self.client.invoke("status", expected_revision=self.state_revision)
            self._refresh()
        except (BackendUnavailable, BackendRequestRejected, OSError, ValueError, TypeError):
            self.backend_unavailable = True

    def apply_status(self, status):
        self._snapshot["status"] = {"state": status.state}

    def close(self):
        # Closing a frontend client never asks the persistent backend to stop.
        self._callbacks.clear()
        self._events = queue.Queue()

    @property
    def backend_available(self) -> bool:
        backend = self._snapshot.get("backend", {})
        return not self.backend_unavailable and bool(backend.get("available", True)) if isinstance(backend, dict) else False

    @property
    def backend_session_id(self) -> str:
        backend = self._snapshot.get("backend", {})
        return str(backend.get("session_id", "")) if isinstance(backend, dict) else ""

    @property
    def backend_state(self) -> str:
        if self.backend_unavailable:
            return "unavailable"
        return "ready"

    @property
    def backend_error(self) -> str:
        return self._backend_error

    def live_status_snapshot(self, **kwargs): return SimpleNamespace(as_json=lambda: dict(self._snapshot))

    def usb_ports(self):
        try:
            result = self.client.invoke("discover-usb", expected_revision=self.state_revision)
            return [(str(item.get("port", "")), str(item.get("description", "")))
                    for item in result.get("ports", ()) if isinstance(item, dict)]
        except (BackendUnavailable, BackendRequestRejected, OSError, ValueError, TypeError):
            return []

    def set_transport_for_testing(self, value):
        raise RuntimeError("Transport injection is unavailable on the backend client")

    def _invoke_result(self, action: str, **kwargs) -> dict[str, Any]:
        key = f"qt:{action}:{uuid.uuid4().hex}"
        return self.client.invoke(action, expected_revision=self.state_revision,
                                  idempotency_key=key, **kwargs)

    def _invoke(self, action: str, **kwargs) -> ActionOutcome:
        try:
            result = self._invoke_result(action, **kwargs)
            self._refresh()
            return ActionOutcome(bool(result.get("accepted", True)), str(result.get("message", "Action completed")))
        except (BackendUnavailable, BackendRequestRejected, OSError, ValueError, TypeError) as exc:
            return ActionOutcome(False, str(exc))

    def _invoke_ungated(self, action: str, **kwargs) -> ActionOutcome:
        """Forward actions whose backend checks current safety facts atomically."""
        try:
            result = self.client.invoke(action, **kwargs)
            self._refresh()
            return ActionOutcome(bool(result.get("accepted", True)), str(result.get("message", "Action completed")))
        except (BackendUnavailable, BackendRequestRejected, OSError, ValueError, TypeError) as exc:
            return ActionOutcome(False, str(exc))

    def _invoke_connection(
        self, action: str, *, default_mode: ConnectionMode | None = None, **kwargs
    ) -> ConnectionOutcome:
        try:
            result = self._invoke_result(action, **kwargs)
            self._refresh()
            raw_mode = result.get("mode")
            mode = ConnectionMode(raw_mode) if raw_mode is not None else default_mode
            raw_port = result.get("port")
            port = int(raw_port) if raw_port is not None else None
            return ConnectionOutcome(
                bool(result.get("accepted", True)),
                str(result.get("message", "Action completed")),
                mode,
                str(result.get("host", "")),
                port,
            )
        except (BackendUnavailable, BackendRequestRejected, OSError, ValueError, TypeError) as exc:
            return ConnectionOutcome(False, str(exc), default_mode)

    @property
    def machine_definition(self):
        value = self._snapshot.get("machine", {})
        try: return MachineDefinition.from_dict(value)
        except (ValueError, TypeError, KeyError): return MachineDefinition.dedicated_ttc3018()
    @property
    def installed_hardware(self): return self.machine_definition.installed_hardware
    @property
    def machine_id(self): return str(self._snapshot.get("machine_id", self.machine_definition.machine_id))
    @property
    def machine_profiles(self): return (self.machine_definition,)
    @property
    def profile(self):
        value = self._snapshot.get("profile", {})
        value = value if isinstance(value, dict) else {}
        return MachineProfile(str(value.get("name", "Two Trees TTC 3018")), float(value.get("travel_x", 290)),
                              float(value.get("travel_y", 170)), float(value.get("travel_z", 40)),
                              float(value.get("safe_z", 30)))
    @property
    def status(self): return _status(self._snapshot.get("status"))
    @status.setter
    def status(self, value):
        if value is None: self._snapshot["status"] = None
        elif isinstance(value, GrblStatus): self._snapshot["status"] = {"state": value.state}
    @property
    def connected(self): return bool(self._snapshot.get("connected", False))
    @property
    def auto_connection_state(self):
        connection = self._snapshot.get("connection", {})
        return str(connection.get("auto_state", "idle")) if isinstance(connection, dict) else "idle"
    @property
    def auto_connection_failures(self):
        connection = self._snapshot.get("connection", {})
        value = connection.get("auto_failures", ()) if isinstance(connection, dict) else ()
        return tuple(str(item) for item in value) if isinstance(value, (list, tuple)) else ()
    @property
    def status_fresh(self): return bool(self._snapshot.get("status_fresh", False))
    @property
    def status_state(self): return str(self._snapshot.get("status_state", "unavailable"))
    @property
    def connection_setup_only(self):
        connection = self._snapshot.get("connection", {})
        connection = connection if isinstance(connection, dict) else {}
        mode = str(self._snapshot.get("connection_mode", connection.get("mode", "")))
        return bool(
            connection.get("setup_only", False)
            or (
                mode == ConnectionMode.USB.value
                and not bool(self._snapshot.get("operation_transport_ready", True))
            )
        )
    @property
    def supervisor_state(self): return str(self._snapshot.get("supervisor_state", "not_applicable"))
    @property
    def simulation_active(self): return self._snapshot.get("connection_mode") == ConnectionMode.SIMULATION.value
    @property
    def simulation_runtime(self): return None
    @property
    def simulation_hazard_active(self): return bool(self._snapshot.get("safety", {}).get("hazard", False))
    @property
    def simulation_estop_active(self): return str(self._snapshot.get("safety", {}).get("estop", "clear")) == "active"
    @property
    def machine_position(self): return _position(self._snapshot.get("machine_position"))
    @property
    def virtual_position(self): return _position(self._snapshot.get("virtual_position"))
    @property
    def work_offset(self): return _position(self._snapshot.get("work_offset"))
    @property
    def saved_work_zero(self): return _position(self._snapshot.get("saved_work_zero"))
    @property
    def saved_work_zero_axes(self):
        saved = self._snapshot.get("saved_work_zero")
        if not isinstance(saved, dict):
            return frozenset()
        return frozenset(saved.get("confirmed_axes", "XYZ"))
    @property
    def reference_trusted(self): return bool(self._snapshot.get("reference_trusted", False))
    @property
    def work_zero_confirmed(self): return bool(self._snapshot.get("work_zero_confirmed", False))
    @property
    def can_jog(self): return bool(self._snapshot.get("can_jog", False))
    @property
    def can_live_jog(self): return bool(self._snapshot.get("can_live_jog", False))
    @property
    def motion_busy(self): return bool(self._snapshot.get("active_operation"))
    @property
    def live_jog_active(self): return False
    @property
    def job_active(self): return bool(self._snapshot.get("job_active", False))
    @property
    def job_state(self): return str(self._snapshot.get("job_state", self._snapshot.get("job", {}).get("state", "idle")))
    @property
    def job_progress(self): return float(self._snapshot.get("job_progress", self._snapshot.get("job", {}).get("progress", 0.0)))
    @property
    def job_estimated_seconds(self): return float(self._snapshot.get("job", {}).get("estimated_seconds", 0.0))
    @property
    def job_elapsed_seconds(self): return float(self._snapshot.get("job", {}).get("elapsed_seconds", 0.0))
    @property
    def job_remaining_seconds(self): return self._snapshot.get("job", {}).get("remaining_seconds")
    @property
    def job_nonce(self): return str(self._snapshot.get("job_nonce", ""))
    @property
    def watchdog_recovery(self):
        return dict(self._snapshot.get("watchdog_recovery") or {})
    @property
    def automatic_continuation(self):
        return dict(self._snapshot.get("automatic_continuation") or {})
    @property
    def job_recovery(self):
        value = self._snapshot.get("job_recovery", {})
        return dict(value) if isinstance(value, dict) else {}
    @property
    def can_return_to_reference(self): return bool(self._snapshot.get("can_return_to_reference", self.can_jog and self.reference_trusted))
    @property
    def can_home_machine(self): return bool(self._snapshot.get("can_home_machine", False))
    @property
    def can_start_job(self): return bool(self._snapshot.get("can_start_job", False))
    @property
    def transport(self): return None
    @property
    def program(self): return self._program
    @property
    def program_provenance(self): return dict(self._program_provenance)
    @property
    def homing_limit_declarations(self): return self._snapshot.get("machine", {}).get("axes", {})
    @property
    def travel_calibration_snapshot(self): return dict(self._snapshot.get("travel_calibration", {}))
    @property
    def homing_input_observation(self):
        value = self._snapshot.get("safety", {}).get("homing_inputs", {})
        value = value if isinstance(value, dict) else {}
        return SimpleNamespace(state=str(value.get("state", "unknown")), pins=str(value.get("pins", "")), reason=str(value.get("reason", "Backend snapshot unavailable")))
    @property
    def homing_inputs_safe(self): return bool(self._snapshot.get("safety", {}).get("homing_inputs_safe", False))
    @property
    def physical_safety_input_status(self):
        safety = self._snapshot.get("safety", {})
        value = safety.get("physical_estop", {}) if isinstance(safety, dict) else {}
        if not isinstance(value, dict):
            value = {}
        return {
            "state": str(value.get("state", "unknown")),
            "raw_state": str(value.get("raw_state", "unknown")),
            "timestamp": value.get("timestamp", 0.0),
            "sample_timestamp": value.get("sample_timestamp"),
            "session_id": str(value.get("session_id", "")),
            "observed_session_id": str(value.get("observed_session_id", "")),
            "channel_a_closed": value.get("channel_a_closed"),
            "channel_b_closed": value.get("channel_b_closed"),
            "stable_for": value.get("stable_for", 0.0),
            "debounce_seconds": value.get("debounce_seconds", 0.0),
            "stale_after": value.get("stale_after", 0.0),
            "reason": str(value.get("reason", "Backend safety-input status unavailable")),
            "sample_count": int(value.get("sample_count", 0) or 0),
            "adapter_available": bool(value.get("adapter_available", False)),
            "latched": bool(value.get("latched", False)),
            "commissioned": bool(value.get("commissioned", False)),
            "power_removal": str(value.get("power_removal", "unknown")),
            "transition_id": int(value.get("transition_id", 0) or 0),
            "blocks_motion": bool(value.get("blocks_motion", True)),
            "trustworthy_clear": bool(value.get("trustworthy_clear", False)),
            "source": str(value.get("source", "")),
            "raw": dict(value.get("raw", {})) if isinstance(value.get("raw", {}), dict) else {},
        }

    def acknowledge_safety_input(self): return self._invoke("acknowledge-safety-input")

    @property
    def simulation_plate_commissioned(self): return bool(self._snapshot.get("safety", {}).get("simulation_plate_commissioned", False))
    @property
    def z_touch_plate_status(self): return str(self._snapshot.get("safety", {}).get("z_touch_plate", "disabled"))
    @property
    def z_probe_completion_snapshot(self) -> dict[str, Any]:
        value = self._snapshot.get("z_probe_completion", {})
        if not isinstance(value, dict):
            value = {}
        return {
            "state": str(value.get("state", "idle")),
            "message": str(value.get("message", "")),
            "plate_thickness": value.get("plate_thickness"),
            "measured_machine_z": value.get("measured_machine_z"),
            "target_work_z": value.get("target_work_z", 0.0),
            "current_work_z": value.get("current_work_z"),
            "transaction_id": str(value.get("transaction_id", "")),
        }
    @property
    def auto_xyz_calibration_state(self): return str(self._snapshot.get("auto_xyz_calibration_state", "idle"))
    @property
    def auto_xyz_calibration_status(self): return str(self._snapshot.get("auto_xyz_calibration_status", "Unavailable"))
    @property
    def z_touch_plate_definition(self):
        return next((probe for probe in self.machine_definition.probes if probe.kind is ProbeKind.MOVABLE_Z_PLATE and probe.enabled), None)
    @property
    def z_touch_plate_record(self): return None
    @property
    def z_touch_plate_input_message(self): return str(self._snapshot.get("safety", {}).get("z_touch_plate_input_message", ""))
    @property
    def z_touch_plate_input_state(self): return str(self._snapshot.get("safety", {}).get("z_touch_plate_input_state", "unknown"))
    @property
    def z_touch_plate_sample_count(self): return int(self._snapshot.get("safety", {}).get("z_touch_plate_sample_count", 0))
    @property
    def simulation_plate_definition(self): return SimpleNamespace(safe_z=self.profile.safe_z)
    @property
    def simulation_plate_record(self): return None

    def connect_usb(self, port): return self._invoke_connection("connect-usb", default_mode=ConnectionMode.USB, port=port)
    def begin_wifi(self, host, port): return self._invoke_connection("connect-wifi", default_mode=ConnectionMode.WIFI, host=host, port=port)
    def auto_connect_saved(self): return self._invoke_connection("auto-connect")
    def connect_simulation(self): return self._invoke_connection("connect-simulation", default_mode=ConnectionMode.SIMULATION)
    def configure_simulation(self, speed, workpiece="Pocket + retained island"): return self._invoke("configure-simulation", speed=speed, workpiece=workpiece)
    def disconnect(self, reason=None): return self._invoke("disconnect", reason=reason or "Disconnected by operator")
    def invalidate_reference(self, reason="Manually invalidated"): return self._invoke("invalidate-reference", reason=reason)
    def home_machine(self): return self._invoke("home")
    def jog(self, axis, distance, feed=500.0): return self._invoke("jog", axis=axis, distance=distance, feed=feed)
    def start_live_jog(self, axis, direction, allow_unreferenced, feed=500.0, *, lease_token=None):
        payload = {"axis": axis, "direction": direction, "allow_unreferenced": allow_unreferenced, "feed": feed}
        if lease_token is not None:
            payload["lease_token"] = lease_token
        return self._invoke("live-jog-start", **payload)
    def renew_live_jog(self, token): return self._invoke_ungated("live-jog-renew", token=token)
    def stop_live_jog(self): return self._invoke_ungated("live-jog-stop")
    def start_travel_calibration(self, **options): return self._invoke("travel-calibration-start", **options)
    def abort_travel_calibration(self): return self._invoke("travel-calibration-abort")
    def accept_travel_calibration(self): return self._invoke("travel-calibration-accept")
    def cancel_jog(self): return self._invoke("cancel-jog")
    def hold(self): return self._invoke("hold")
    def resume(self): return self._invoke("resume")
    def move_to(self, target, feed=500.0):
        return self._invoke("move-to", x=target.x, y=target.y, z=target.z, feed=feed)
    def return_to_reference(self, feed=500.0): return self._invoke("return-reference", feed=feed)
    def return_to_work_zero(self, feed=500.0): return self._invoke("return-work-zero", feed=feed)
    def set_work_zero(self, axes): return self._invoke("work-zero", axes=axes)
    def start_spindle(self, rpm): return self._invoke("spindle-start", rpm=rpm)
    def stop_spindle(self): return self._invoke("spindle-stop")
    def continue_to_home(self): return self._invoke("continue-to-home")
    def cancel_recovery(self): return self._invoke_ungated("cancel-recovery")
    def pause_job(self): return self._invoke("pause-job")
    def resume_job(self): return self._invoke("resume-job")
    def abort_job(self, reason="Aborted by operator"): return self._invoke("abort-job", reason=reason)
    def start_probe(self, plan):
        return self._invoke("probe", axis=plan.axis, fast_distance=plan.fast_distance,
                            slow_distance=plan.slow_distance, retract=plan.retract,
                            safe_retract=plan.safe_retract, fast_feed=plan.fast_feed,
                            slow_feed=plan.slow_feed, retract_feed=plan.retract_feed,
                            wcs_slot=plan.wcs_slot, offset_axis=plan.offset_axis,
                            offset_value=plan.offset_value, purpose=plan.purpose)
    def abort_probe(self, reason="Aborted by operator"): return self._invoke("abort-probe", reason=reason)
    def probe_work_z(self): return self._invoke_ungated("probe-work-z")
    def continue_z_probe_to_surface(self, transaction_id: str | None = None):
        snapshot = self.z_probe_completion_snapshot
        observed_transaction = (
            str(snapshot.get("transaction_id", "")) if transaction_id is None
            else transaction_id.strip() if isinstance(transaction_id, str) else ""
        )
        if not observed_transaction:
            return ActionOutcome(False, "No current Z-probe result is available to continue")
        return self._invoke_ungated("touch-continue-to-surface", transaction_id=observed_transaction)
    def preflight(self):
        try:
            result = self._invoke_result("preflight")
            return bool(result.get("fits", result.get("accepted", False))), str(result.get("message", ""))
        except (BackendUnavailable, BackendRequestRejected, OSError, ValueError, TypeError) as exc:
            return False, str(exc)
    def authorize_job_start(self, **kwargs):
        try:
            result = self._invoke_result("authorize-job-start", **kwargs)
            return SimpleNamespace(accepted=bool(result.get("accepted", False)), message=str(result.get("message", "")), token=str(result.get("token", "")))
        except (BackendUnavailable, BackendRequestRejected, OSError, ValueError, TypeError) as exc:
            return SimpleNamespace(accepted=False, message=str(exc), token="")
    def start_job(self, authorization_token=None): return self._invoke("start-job", token=authorization_token or "")
    def start_authorized_job(self, token): return self._invoke("start-job", token=token)

    def load_program(self, path: Path):
        try:
            self._invoke_result("load-job", path=str(path))
        except BackendRequestRejected as exc:
            raise GCodeError(str(exc)) from exc
        self._refresh()
        if self._program is None: raise ValueError("Backend did not return a validated program")
        return self._program

    def load_generated(self, gcode: str, filename: str):
        self._invoke_result("load-generated-job", gcode=gcode, filename=filename)
        self._refresh()
        if self._program is None: raise ValueError("Backend did not return a validated generated program")
        return self._program

    def save_wifi_settings(self, host, port):
        self._invoke_result("save-connection", mode="Wi-Fi TCP", host=host, port=port, usb_port="")
        self._refresh()
    def save_usb_settings(self, port):
        self._invoke_result("save-connection", mode="USB serial", host="", port=0, usb_port=port)
        self._refresh()
    def save_profile(self, profile):
        self._invoke_result("save-profile", name=profile.name, travel_x=profile.travel_x, travel_y=profile.travel_y, travel_z=profile.travel_z, safe_z=profile.safe_z)
        self._refresh()
    def save_capabilities(self, **kwargs): return self._invoke("save-machine-capabilities", **kwargs)
    def save_probe_capabilities(self, **kwargs): return self._invoke("save-probe-capabilities", **kwargs)
    def save_probe_configuration(self, **kwargs): return self._invoke("save-probe-configuration", **kwargs)
    def save_homing_limit_declarations(self, declarations):
        return self._invoke("save-homing-declarations", declarations=declarations)
    def save_z_touch_plate_settings(self, *, plate_thickness, active_low, fast_feed, slow_feed,
                                    max_search, retract, safe_retract, tolerance):
        return self._invoke(
            "save-z-plate-settings", thickness=plate_thickness, active_low=active_low,
            fast_feed=fast_feed, slow_feed=slow_feed, max_search=max_search,
            retract=retract, safe_retract=safe_retract, tolerance=tolerance,
        )
    def save_z_plate_capability(self, enabled): return self._invoke("save-machine-capabilities", limit_switches=False, z_plate=enabled, tool_setter=False, movable_xyz=False, fixed_fixture=False)
    def select_machine(self, machine_id): return ActionOutcome(False, "The dedicated TTC 3018 backend has no selectable machine catalog")
    def save_step_prepare_settings(self, settings):
        try:
            result = self._invoke_result("save-step-settings", **asdict(settings))
            self._refresh()
            return ActionOutcome(bool(result.get("accepted", True)), str(result.get("message", "Action completed")))
        except (BackendUnavailable, BackendRequestRejected, OSError, ValueError, TypeError) as exc:
            return ActionOutcome(False, str(exc))
    def start_auto_xyz_calibration(self, seed): return self._invoke("auto-xyz-start", x=seed[0], y=seed[1], z=seed[2])
    def abort_auto_xyz_calibration(self): return self._invoke("auto-xyz-abort")
    def commission_simulation_calibration_plate(self): return self._invoke("commission-plate")
    def set_simulation_limit_input(self, axis, active): return self._invoke("simulation-limit", axis=axis, active=active)
    def inject_simulation_estop(self, reset_asserted=False): return self._invoke("simulation", operation="estop", reset_asserted=reset_asserted)
    def release_simulation_estop(self): return self._invoke("simulation", operation="release-estop", reset_asserted=False)
    def acknowledge_simulation_estop(self): return self._invoke("simulation", operation="ack-estop", reset_asserted=False)
    def start_z_touch_plate_input_test(self): return self._invoke("touch-input-test")
    def start_z_touch_plate_commissioning_sample(self): return self._invoke("touch-commission")
    def acknowledge_z_touch_plate_removed(self): return self._invoke("touch-ack-remove")
    def save_z_touch_plate_commissioning(self, samples): return self._invoke("touch-commission-save", samples=list(samples))
    def export_simulation_trace(self, path): return self._invoke("export-simulation-evidence", path=str(path))
