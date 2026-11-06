"""Qt-free owner of one :class:`ApplicationController` session."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
import base64
from datetime import datetime, timezone
from io import BytesIO
import json
import math
import queue
import threading
import time
from pathlib import Path
from typing import Any, Callable

from PIL import Image, ImageDraw

from ..application.controller import ApplicationController
from ..application.events import ApplicationEvent
from ..application.job_provenance import build_job_provenance
from ..application.state import ApplicationState
from ..grbl import GrblStatus, Position
from .protocol import PROTOCOL_VERSION, SCHEMA_VERSION
from .job_recovery import JobRecoveryStore, empty_pause_bookmark, empty_recovery
from .watchdog_recovery import JobWatchdogRecovery
from .auto_continuation import AutomaticContinuation
from .safety_input import (SafetyInputAdapter, SafetyInputAuditLog, SafetyInputMonitor,
                           SafetyInputSample, SafetyInputStatus)


def _json_value(value: Any) -> Any:
    if isinstance(value, Position):
        return {"x": value.x, "y": value.y, "z": value.z}
    if isinstance(value, GrblStatus):
        return {
            "state": value.state,
            "machine_position": _json_value(value.machine_position),
            "work_position": _json_value(value.work_position),
            "work_offset": _json_value(value.work_offset),
            "feed": value.feed,
            "spindle": value.spindle,
            "pins": value.pins,
            "fields": dict(value.fields),
        }
    if is_dataclass(value):
        return {str(key): _json_value(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (set, frozenset)):
        return [_json_value(item) for item in sorted(value, key=str)]
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if hasattr(value, "value") and not isinstance(value, (str, bytes)):
        return _json_value(value.value)
    if isinstance(value, Path):
        return str(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


class BackendRuntime:
    """Persistent controller runtime with deterministic polling and events.

    The runtime has no Qt imports and owns the only controller instance used by
    a backend process.  ``poll_once`` is intentionally public for unit tests
    and embedded headless operation; ``run`` is just a bounded periodic loop.
    """

    MAX_TRANSPORT_EVENTS_PER_POLL = 256

    def __init__(
        self,
        root: Path,
        *,
        application: ApplicationController | None = None,
        application_factory: Callable[[Path], ApplicationController] | None = None,
        clock: Callable[[], float] = time.monotonic,
        status_interval: float = 0.5,
        max_events: int = 2048,
        safety_input_adapter: SafetyInputAdapter | None = None,
        safety_input_commissioned: bool = False,
        safety_input_debounce_seconds: float = 0.05,
        safety_input_stale_after: float = 0.5,
    ) -> None:
        self.root = Path(root)
        if application is not None:
            self.application = application
        else:
            factory = application_factory or ApplicationController
            try:
                self.application = factory(self.root)
            except TypeError:
                # A zero-argument injected fake is useful for deterministic
                # runtime tests; production ApplicationController always gets
                # the supplied root.
                self.application = factory()  # type: ignore[call-arg]
        # Production clients cannot use USB for operation. Injected controllers
        # retain explicit isolated test/compatibility composition semantics.
        if application is None and application_factory is None:
            self.application._wifi_only_operations = True
            self.application.connection_service.usb_setup_only = True
        self._clock = clock
        self.safety_input_adapter = safety_input_adapter
        self._safety_input = SafetyInputMonitor(
            commissioned=safety_input_commissioned,
            debounce_seconds=safety_input_debounce_seconds,
            stale_after=safety_input_stale_after,
            clock=self._clock,
        )
        self._safety_audit = SafetyInputAuditLog(self.root)
        self._last_safety_transition_id = self._safety_input.status.transition_id
        self._handled_safety_transition_id = self._last_safety_transition_id
        self._restore_safety_latch()
        if safety_input_commissioned and safety_input_adapter is None and not self._safety_input.latched:
            # A commissioned contract without an owner is itself a feedback
            # loss. Fail closed during startup rather than waiting for a poll.
            status = self._safety_input.observe(
                None, now=self._clock(),
                adapter_error="Commissioned safety input adapter is unavailable",
            )
            try:
                self._safety_audit.append(status, event="adapter_unavailable")
            except OSError:
                pass
        self._last_safety_transition_id = self._safety_input.status.transition_id
        self._handled_safety_transition_id = self._last_safety_transition_id
        self.status_interval = max(0.01, float(status_interval))
        self._last_status_poll = 0.0
        self._sequence = 0
        self._events: list[dict[str, Any]] = []
        self._max_events = max(1, int(max_events))
        self._lock = threading.RLock()
        self.closed = False
        self.started_at = self._clock()
        self._last_snapshot: dict[str, Any] = {}
        self._program_provenance_cache_key: tuple[str, str] | None = None
        self._program_provenance_cache: dict[str, Any] = {
            "report_state": "unavailable", "file_sha256": "", "report_name": "",
            "release_status": "", "bundle": "", "details": [], "header_notes": [],
            "verification_text": "", "notice": "No job is loaded.",
        }
        self._state_revision = 0
        self._last_semantic_snapshot: str | None = None
        self._job_recovery_store = JobRecoveryStore(self.root)
        self._job_recovery = self._job_recovery_store.load()
        self._job_recovery_last_signature = ""
        self._job_watchdog_recovery = JobWatchdogRecovery(clock=self._clock)
        self._automatic_continuation = AutomaticContinuation(self.root, self._clock)
        self._emit("runtime", {"message": "Backend runtime ready"})
        if self._safety_input.status.latched:
            self._apply_safety_trip(self._safety_input.status)
        self._refresh_snapshot()

    @property
    def session_id(self) -> str:
        return getattr(self, "_session_id", "")

    @property
    def state_revision(self) -> int:
        """Monotonic semantic revision used for optimistic action checks."""
        return self._state_revision

    def set_session_id(self, session_id: str) -> None:
        with self._lock:
            self._session_id = str(session_id)
            self._safety_input.set_session_id(self._session_id)
            self._publish_safety_input(self._safety_input.status)
            self._refresh_snapshot()

    @property
    def safety_input_status(self) -> SafetyInputStatus:
        with self._lock:
            return self._safety_input.status

    @property
    def safety_input_blocks_motion(self) -> bool:
        with self._lock:
            return self._safety_input.status.blocks_motion

    def update_safety_input(self, sample: SafetyInputSample | None, *, now: float | None = None,
                            adapter_error: str | None = None) -> SafetyInputStatus:
        """Apply a typed observation supplied by the backend-owned adapter.

        This seam is intentionally usable by a fake adapter and tests only in
        the current software run; no physical input is opened by the runtime.
        """

        with self._lock:
            status = self._safety_input.observe(sample, now=now, adapter_error=adapter_error)
            self._publish_safety_input(status)
            self._refresh_snapshot()
            return status

    def acknowledge_safety_input(self, *, now: float | None = None) -> tuple[bool, str]:
        with self._lock:
            if not bool(getattr(self.application, "connected", False)):
                return False, "Safety input acknowledgement rejected — reconnect the controller into a fresh idle state first"
            if bool(getattr(self.application, "job_active", False) or getattr(self.application, "motion_busy", False)):
                return False, "Safety input acknowledgement rejected — abort active machine work first"
            controller_status = getattr(self.application, "status", None)
            if controller_status is None or str(getattr(controller_status, "state", "")) != "Idle":
                return False, "Safety input acknowledgement rejected — wait for a fresh GRBL Idle report first"
            if getattr(controller_status, "spindle", None) not in (None, 0):
                return False, "Safety input acknowledgement rejected — stop the spindle first"
            if self._safety_input.acknowledge(now=now):
                status = self._safety_input.status
                self._publish_safety_input(status, event="acknowledgement")
                self._refresh_snapshot()
                return True, "Safety input acknowledged; re-home before motion"
            return False, "Safety input acknowledgement rejected — release, settle, and verify both channels first"

    def _restore_safety_latch(self) -> None:
        if not self._safety_input.status.commissioned:
            return
        previous = self._safety_audit.last_status()
        if not previous or not bool(previous.get("latched", False)):
            return
        reason = str(previous.get("reason", "Prior safety input trip"))
        timestamp = float(previous.get("timestamp", 0.0) or 0.0)
        self._safety_input.restore_latched(reason=reason, timestamp=timestamp)
        self._last_safety_transition_id = self._safety_input.status.transition_id
        self._handled_safety_transition_id = self._last_safety_transition_id

    def _publish_safety_input(self, status: SafetyInputStatus, *, event: str = "transition") -> None:
        if status.transition_id == self._last_safety_transition_id and event == "transition":
            return
        self._last_safety_transition_id = status.transition_id
        if status.commissioned:
            try:
                self._safety_audit.append(status, event=event)
            except OSError as exc:
                self._emit("error", {"message": f"Safety audit write failed: {exc}"})
        self._emit("safety_input", {"event": event, **status.to_dict()})
        if status.latched and status.transition_id != self._handled_safety_transition_id:
            self._handled_safety_transition_id = status.transition_id
            self._apply_safety_trip(status)

    def _apply_safety_trip(self, status: SafetyInputStatus) -> None:
        """Perform best-effort secondary stop and invalidate software trust."""

        reason = f"Independent safety input {status.state.value}: {status.reason}"
        for name, args in (
            ("hold", ()),
            ("stop_spindle", ()),
            ("cancel_jog", ()),
            ("abort_probe", (reason,)),
        ):
            method = getattr(self.application, name, None)
            if not callable(method):
                continue
            try:
                method(*args)
            except Exception as exc:  # a secondary stop must not prevent the remaining actions
                self._emit("safety_action_error", {"action": name, "message": str(exc)})
        if bool(getattr(self.application, "job_active", False) or getattr(self.application, "motion_busy", False)):
            abort = getattr(self.application, "abort_job", None)
            if callable(abort):
                try:
                    abort(reason)
                except Exception as exc:
                    self._emit("safety_action_error", {"action": "abort_job", "message": str(exc)})
        invalidate = getattr(self.application, "invalidate_safety_trust", None)
        if not callable(invalidate):
            invalidate = getattr(self.application, "invalidate_reference", None)
        if callable(invalidate):
            try:
                invalidate(reason)
            except Exception as exc:
                self._emit("safety_action_error", {"action": "invalidate_reference", "message": str(exc)})

    def _emit(self, kind: str, payload: Any = None) -> dict[str, Any]:
        with self._lock:
            self._sequence += 1
            item = {
                "sequence": self._sequence,
                "kind": str(kind),
                "payload": _json_value(payload if payload is not None else {}),
                "timestamp": self._clock(),
            }
            self._events.append(item)
            del self._events[:-self._max_events]
            return item

    def _drain_controller_events(self) -> None:
        drain = getattr(self.application, "application_events", None)
        for event in drain() if callable(drain) else ():
            if hasattr(event, "message"):
                payload = {"message": event.message, "level": getattr(getattr(event, "level", None), "value", "info")}
            elif hasattr(event, "text"):
                payload = {"kind": getattr(event, "kind", "log"), "text": event.text}
            else:
                payload = _json_value(event)
            self._emit(type(event).__name__, payload)

    def _drain_transport_events(self) -> None:
        event_source = getattr(self.application, "transport_events", None)
        events = event_source() if callable(event_source) else None
        if events is None:
            return
        for _ in range(self.MAX_TRANSPORT_EVENTS_PER_POLL):
            try:
                event = events.get_nowait()
            except queue.Empty:
                return
            except AttributeError:
                return
            kind = str(getattr(event, "kind", "transport"))
            text = str(getattr(event, "text", event))
            self._emit(kind, {"text": text})
            if kind == "error":
                try:
                    self.application.disconnect(f"Connection error: {text}")
                except Exception as exc:
                    self._emit("error", {"message": str(exc)})
                continue
            if kind != "rx":
                continue
            try:
                status, reset = self.application.handle_transport_response(text, 500.0)
                if status is not None:
                    self._emit("status", _json_value(status))
                if reset:
                    self._emit("reset", {"message": "Controller reset"})
                    self._emit("safety_input_diagnostic", {
                        "event": "controller_reset_observed",
                        "physical_estop_inferred": False,
                        "physical_estop": self._safety_input.status.to_dict(),
                    })
                    # A GRBL banner/reset message is positive reset evidence.
                    # Silence alone enters recovery through the watchdog below
                    # and keeps its explicit Continue/Cancel decision.
                    recovery = self._job_watchdog_recovery
                    if not recovery.active or not recovery.snapshot().get("automatic_homing"):
                        self._job_watchdog_recovery.start(
                            self.application, "GRBL controller reset detected",
                            now=self._clock(), auto_home=True,
                        )
            except (RuntimeError, ValueError, TypeError) as exc:
                self._emit("error", {"message": str(exc)})

    def _capabilities(self) -> dict[str, Any]:
        # Import locally to keep the runtime's dependency direction simple:
        # the dispatcher depends on the runtime, while the advertised action
        # names are still taken from the one finite registry.
        from .dispatcher import ActionDispatcher

        supported = (
            "guarded_homing_reference", "manual_work_zero", "metric_gcode",
            "guarded_job_streaming", "bounded_motion", "spindle_control",
            "typed_dual_channel_safety_input",
        )
        simulation_only = (
            "loopback_digital_twin", "supervisor_exercises",
            "commissioned_twin_auto_xyz", "collision_evidence",
        )
        declared: list[str] = []
        definition = getattr(self.application, "machine_definition", None)
        for probe in getattr(definition, "probes", ()):
            kind = getattr(getattr(probe, "kind", None), "value", getattr(probe, "kind", ""))
            if kind and bool(getattr(probe, "enabled", False)) and kind != "movable_z_plate":
                declared.append(str(kind))
        return {
            "actions": sorted(ActionDispatcher.ACTIONS),
            "transport_modes": ["USB serial", "Wi-Fi TCP", "Virtual Machine (Digital Twin)"],
            "supported": list(supported),
            "simulation_only": list(simulation_only),
            "declared_but_unavailable": sorted(declared),
            "hardware_commissioned": [],
            "safety_input": {
                "commissioned": self._safety_input.status.commissioned,
                "power_removal": self._safety_input.status.power_removal,
            },
        }

    def _refresh_snapshot(self) -> dict[str, Any]:
        self._sync_job_recovery()
        state: ApplicationState = self.application.state
        snapshot = _json_value(state)
        # Timing belongs to the backend-owned operation, not the GUI session.
        # Keep the nominal estimate distinct from elapsed execution time.
        snapshot["job"].update({
            "estimated_seconds": float(getattr(self.application, "job_estimated_seconds", 0.0)),
            "elapsed_seconds": float(getattr(self.application, "job_elapsed_seconds", 0.0)),
            "remaining_seconds": getattr(self.application, "job_remaining_seconds", None),
        })
        safety_runtime = getattr(self.application, "simulation_runtime", None)
        safety_status = getattr(safety_runtime, "estop_status", {}) if safety_runtime is not None else {}
        active_hazards = getattr(safety_runtime, "active_hazards", ()) if safety_runtime is not None else ()
        homing = getattr(self.application, "homing", None)
        homing_state = getattr(homing, "state", "idle")
        homing_state = getattr(homing_state, "value", homing_state)
        snapshot.update({
            "schema_version": SCHEMA_VERSION,
            "protocol_version": PROTOCOL_VERSION,
            "sequence": self._sequence,
            "backend": {"available": not self.closed, "session_id": self.session_id,
                         "pid": __import__("os").getpid(), "owner": "pine-backend"},
            "status_state": str(getattr(self.application, "status_state", "unavailable")),
            "session_generation": int(getattr(self.application, "session_generation", 0)),
            "reference": _json_value(getattr(getattr(self.application, "session", None), "envelope", None).reference)
                if getattr(getattr(self.application, "session", None), "envelope", None) is not None else None,
            "work_offset": _json_value(getattr(self.application, "work_offset", None)),
            # The persisted previous work zero is operator-visible context for
            # the guarded return action. It is intentionally separate from the
            # live GRBL WCO and the work-zero-confirmed trust flag.
            "saved_work_zero": _json_value(getattr(self.application, "_saved_work_zero", None)),
            "status_fresh": bool(getattr(self.application, "status_fresh", False)),
            "can_jog": bool(getattr(self.application, "can_jog", False)),
            "can_live_jog": bool(getattr(self.application, "can_live_jog", False)),
            "reference_trusted": bool(getattr(self.application, "reference_trusted", False)),
            "work_zero_confirmed": bool(getattr(self.application, "work_zero_confirmed", False)),
            "homing_state": str(homing_state),
            "can_home_machine": bool(getattr(self.application, "can_home_machine", False)),
            "job_active": bool(getattr(self.application, "job_active", False)),
            "job_state": str(getattr(self.application, "job_state", "idle")),
            "job_progress": float(getattr(self.application, "job_progress", 0.0)),
            "can_return_to_reference": bool(getattr(self.application, "can_return_to_reference", False)),
            "can_start_job": bool(getattr(self.application, "can_start_job", False)),
            "supervisor_state": str(getattr(self.application, "supervisor_state", "unavailable")),
            "z_probe_completion": _json_value(getattr(self.application, "z_probe_completion_snapshot", {})),
            "auto_xyz_calibration_state": str(getattr(self.application, "auto_xyz_calibration_state", "idle")),
            "auto_xyz_calibration_status": str(getattr(self.application, "auto_xyz_calibration_status", "Unavailable")),
            "travel_calibration": _json_value(getattr(self.application, "travel_calibration", None).snapshot())
                if getattr(self.application, "travel_calibration", None) is not None else {},
            "connection": {
                "mode": _json_value(getattr(state, "connection_mode", "")),
                "endpoint": str(getattr(getattr(self.application, "connection_service", None), "endpoint", "")),
                "port": int(getattr(getattr(self.application, "connection_service", None), "port", 0) or 0),
                "preferred_transport": str(getattr(getattr(self.application, "settings", None), "preferred_transport", "USB serial")),
                "saved_wifi_host": str(getattr(getattr(self.application, "settings", None), "wifi_host", "")),
                "saved_wifi_port": int(getattr(getattr(self.application, "settings", None), "wifi_port", 0) or 0),
                "usb_port": str(getattr(getattr(self.application, "settings", None), "usb_port", "")),
                "setup_only": bool(getattr(self.application, "_wifi_only_operations", False)
                    and str(getattr(state, "connection_mode", "")) == "USB serial"),
                "operation_transport_ready": bool(getattr(self.application, "operation_transport_ready", False)),
                "wifi_bootstrap": _json_value(getattr(getattr(self.application, "connection_service", None), "wifi_bootstrap_snapshot", {})),
                "auto_connecting": bool(getattr(getattr(self.application, "connection_service", None), "auto_connecting", False)),
                "auto_state": str(getattr(getattr(self.application, "connection_service", None), "auto_connection_state", "idle")),
                "auto_failures": list(getattr(getattr(self.application, "connection_service", None), "auto_connection_failures", ())),
            },
            "safety": {
                "homing_inputs": _json_value(getattr(self.application, "homing_input_observation", None)),
                "homing_inputs_safe": bool(getattr(self.application, "homing_inputs_safe", False)),
                "z_touch_plate": str(getattr(self.application, "z_touch_plate_status", "disabled")),
                "simulation_plate_commissioned": bool(getattr(self.application, "simulation_plate_commissioned", False)),
                "hazard": bool(active_hazards),
                "estop": "active" if bool(getattr(safety_status, "get", lambda *_: False)("interlocked", False)) else "clear",
                "physical_estop": self._safety_input.status.to_dict(),
                "active_hazards": _json_value(active_hazards),
                "z_touch_plate_input_message": str(getattr(self.application, "z_touch_plate_input_message", "")),
                "z_touch_plate_input_state": str(getattr(self.application, "z_touch_plate_input_state", "unknown")),
                "z_touch_plate_sample_count": int(getattr(self.application, "z_touch_plate_sample_count", 0)),
            },
            "machine": self._machine_snapshot(),
            "program_detail": self._program_snapshot(),
            "program_provenance": self._program_provenance_snapshot(),
            "job_recovery": dict(self._job_recovery),
            "watchdog_recovery": self._job_watchdog_recovery.snapshot(self.application),
            "automatic_continuation": self._automatic_continuation.snapshot(),
            "capabilities": self._capabilities(),
            "authorization": {
                "job_start_available": bool(getattr(self.application, "can_start_job", False)),
                "confirmation_required": bool(getattr(self.application, "job_active", False) is False
                                               and getattr(self.application, "program", None) is not None),
            },
        })
        # Keep client projections honest even if the underlying application
        # has not yet observed the same input through its own status loop.
        # Recovery/diagnostic actions remain available through the dispatcher.
        if self._safety_input.status.blocks_motion:
            snapshot["can_jog"] = False
            snapshot["can_live_jog"] = False
            snapshot["can_return_to_reference"] = False
            snapshot["can_start_job"] = False
            authorization = snapshot.get("authorization")
            if isinstance(authorization, dict):
                authorization["job_start_available"] = False
        semantic = dict(snapshot)
        semantic.pop("sequence", None)
        backend = semantic.get("backend")
        if isinstance(backend, dict):
            backend.pop("pid", None)
        encoded = json.dumps(semantic, sort_keys=True, default=str, separators=(",", ":"))
        if encoded != self._last_semantic_snapshot:
            self._state_revision += 1
            self._last_semantic_snapshot = encoded
        snapshot["revision"] = self._state_revision
        self._last_snapshot = snapshot
        return snapshot

    def _sync_job_recovery(self) -> None:
        """Persist accepted-command evidence without controlling the machine.

        A record is intentionally advisory.  It gives a recovering UI or agent
        the exact file identity and a conservative place to investigate, while
        requiring normal homing, work-zero restoration, and explicit review.
        """
        program = getattr(self.application, "program", None)
        streamer = getattr(getattr(self.application, "job", None), "streamer", None)
        if program is None or streamer is None:
            return
        state = str(getattr(self.application, "job_state", "idle"))
        accepted = int(getattr(streamer, "acknowledged_count", 0) or 0)
        sent = int(getattr(streamer, "next_index", 0) or 0)
        total = int(getattr(streamer, "total", 0) or 0)
        active = bool(getattr(self.application, "job_active", False))
        prior = self._job_recovery
        run_id = str(getattr(self.application, "job_nonce", ""))
        machine_id = str(getattr(self.application, "machine_id", ""))
        source_sha256 = str(getattr(program, "source_sha256", ""))
        prior_bookmark = prior.get("pause_bookmark", empty_pause_bookmark())
        if not isinstance(prior_bookmark, dict):
            prior_bookmark = empty_pause_bookmark()
        same_bookmark_identity = bool(
            prior_bookmark.get("confirmed")
            and prior_bookmark.get("run_id") == run_id
            and prior_bookmark.get("machine_id") == machine_id
            and prior_bookmark.get("source_sha256") == source_sha256
        )
        pause_bookmark = dict(prior_bookmark)
        if active and prior_bookmark.get("confirmed") and not same_bookmark_identity:
            # A new run is a different recovery story, even if it reuses the
            # same file. Never attach an earlier pause to its current state.
            pause_bookmark = empty_pause_bookmark()
            same_bookmark_identity = False
        confirmed_pause = self._confirmed_pause_bookmark(
            program, streamer, state, run_id, machine_id, accepted, sent, total
        )
        if confirmed_pause is not None and (
            not same_bookmark_identity or not bool(prior_bookmark.get("current_for_active_run"))
        ):
            pause_bookmark = confirmed_pause
        elif pause_bookmark.get("confirmed"):
            if state != "paused" or confirmed_pause is None:
                pause_bookmark["live_hold_confirmed"] = False
                pause_bookmark["current_for_active_run"] = False
                if state == "running":
                    pause_bookmark["state"] = "superseded_after_resume"
                elif state == "paused":
                    pause_bookmark["state"] = "awaiting_fresh_hold_confirmation"
        # Do not erase a past failure merely because a program was reloaded.
        if not active and state == "idle" and prior.get("state") not in {"none", "dismissed"}:
            return
        record = empty_recovery()
        record.update({
            "state": state if state in {"running", "paused", "draining", "failed", "aborted", "complete"} else "none",
            "run_id": run_id,
            "machine_id": machine_id,
            "source_sha256": source_sha256,
            "filename": Path(str(getattr(program, "path", ""))).name,
            "path": str(getattr(program, "path", "")),
            "accepted_commands": accepted,
            "sent_commands": sent,
            "total_commands": total,
            "reason": str(getattr(streamer, "error", "")),
            "requires_operator_review": state in {"failed", "aborted"},
            "resume_supported": False,
            "pause_bookmark": pause_bookmark,
        })
        signature = json.dumps(record, sort_keys=True, separators=(",", ":"))
        if signature == self._job_recovery_last_signature:
            return
        self._job_recovery = record
        self._job_recovery_last_signature = signature
        try:
            self._job_recovery_store.save(record)
        except OSError as exc:
            self._job_recovery["persistence_error"] = str(exc)
            self._emit("job_recovery", {"message": "Job recovery evidence was not saved", "error": str(exc)})
        else:
            self._emit("job_recovery", dict(record))

    def _confirmed_pause_bookmark(
        self, program: Any, streamer: Any, state: str, run_id: str,
        machine_id: str, accepted: int, sent: int, total: int,
    ) -> dict[str, Any] | None:
        """Capture diagnostic context only after a post-request fresh Hold report."""
        job = getattr(self.application, "job", None)
        status = getattr(self.application, "status", None)
        if (
            state != "paused"
            or not bool(getattr(self.application, "job_active", False))
            or not bool(getattr(job, "pause_status_confirmed", False))
            or not bool(getattr(self.application, "status_fresh", False))
            or status is None
            or str(getattr(status, "state", "")) not in {"Hold", "Hold:0"}
        ):
            return None
        source_sha256 = str(getattr(program, "source_sha256", ""))
        if not source_sha256 or not run_id or not machine_id:
            return None

        provenance = self._program_provenance_snapshot()
        provenance_hash = str(provenance.get("file_sha256", ""))
        reported_tools = []
        if provenance_hash == source_sha256 and provenance.get("report_state") == "matched":
            details = provenance.get("details", ())
            if isinstance(details, (list, tuple)):
                reported_tools = [str(item) for item in details if str(item).startswith("Reported tool:")]
        tool_setting = getattr(self.application, "tool_setting", None)
        active_offset = getattr(tool_setting, "active_offset", None)
        if isinstance(active_offset, bool) or not isinstance(active_offset, (int, float)):
            active_offset = None

        status_fields = {
            "machine_position": _json_value(getattr(status, "machine_position", None)),
            "work_position": _json_value(getattr(status, "work_position", None)),
            "work_offset": _json_value(getattr(status, "work_offset", None)),
        }
        bookmark = empty_pause_bookmark()
        bookmark.update({
            "state": "confirmed_paused",
            "confirmed": True,
            "live_hold_confirmed": True,
            "current_for_active_run": True,
            "confirmed_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "confirmation_source": "fresh_controller_status_after_pause_request",
            "run_id": run_id,
            "machine_id": machine_id,
            "source_sha256": source_sha256,
            "filename": Path(str(getattr(program, "path", ""))).name,
            "accepted_commands": accepted,
            "sent_commands": sent,
            "total_commands": total,
            "controller_state": str(getattr(status, "state", "")),
            "session_generation": int(getattr(self.application, "session_generation", 0) or 0),
            "position_context": {
                **status_fields,
                "position_is_resume_cursor": False,
            },
            "tool_context": {
                "program_sha256": source_sha256,
                "provenance_report_state": str(provenance.get("report_state", "unavailable")),
                "provenance_report_name": str(provenance.get("report_name", "")),
                "provenance_file_sha256": provenance_hash,
                "reported_tool_details": reported_tools,
                "active_tool_length_offset_mm": active_offset,
                "physical_tool_verified": False,
                "verification_required_before_continuation": True,
            },
        })
        return bookmark

    def _machine_snapshot(self) -> dict[str, Any]:
        definition = getattr(self.application, "machine_definition", None)
        if definition is None:
            return {}
        try:
            data = definition.to_dict()
        except (AttributeError, TypeError, ValueError):
            data = _json_value(definition)
        # These are immutable installed facts, separate from editable values.
        data.setdefault("installed_hardware", {
            "machine": "Two Trees TTC 3018",
            "controller": "MKS DLC32 (GRBL-compatible)",
            "nominal_travel_mm": {"X": 290.0, "Y": 170.0, "Z": 40.0},
            "safe_z_mm": 30.0,
            "limit_inputs": {axis: "installed_or_planned" for axis in "XYZ"},
            "movable_z_plate": "installed",
            "spindle_rpm": 12000,
            "estop": "installed_uncommissioned",
        })
        return _json_value(data)

    def _program_snapshot(self) -> dict[str, Any] | None:
        """Return a bounded, presentation-neutral validated program payload."""
        program = getattr(self.application, "program", None)
        if program is None:
            self._large_preview_cache_program = None
            self._large_preview_cache = None
            return None
        commands = tuple(getattr(program, "commands", ()))
        segments = tuple(getattr(program, "segments", ()))
        preview = None
        # Keep the normal snapshot bounded. Large jobs retain authoritative
        # summary/bounds data and receive a raster made from every move. This
        # preserves the complete XY projection without shipping hundreds of
        # thousands of nested points through the UI binding.
        if len(commands) > 5000 or len(segments) > 5000:
            preview = self._large_program_preview(program, segments)
            commands = ()
            segments = ()
        execution_layer = self._execution_layer_snapshot(program, tuple(getattr(program, "segments", ())))
        return _json_value({
            "path": str(getattr(program, "path", "")),
            "commands": commands,
            "segments": segments,
            "bounds": getattr(program, "bounds", None),
            "estimated_seconds": float(getattr(program, "estimated_seconds", 0.0)),
            "source_sha256": str(getattr(program, "source_sha256", "")),
            "header_comments": getattr(program, "header_comments", ()),
            "preview_available": bool(preview) or bool(commands and segments),
            "preview": preview,
            "execution_layer": execution_layer,
            "command_count": len(getattr(program, "commands", ())),
        })

    def _execution_layer_snapshot(self, program: Any, segments: tuple[Any, ...]) -> dict[str, Any]:
        """Return a bounded vector overlay for the observed cutting layer."""
        status = getattr(self.application, "status", None)
        work = getattr(status, "work_position", None) if status is not None else None
        if work is None:
            machine = getattr(status, "machine_position", None) if status is not None else None
            offset = getattr(self.application, "work_offset", None)
            if machine is not None and offset is not None:
                work = machine.minus(offset)
        if not bool(getattr(self.application, "job_active", False)) or work is None:
            return {"state": "inactive", "strokes": []}
        z = float(work.z)
        selected = [segment for segment in segments if not bool(segment.rapid)
                    and abs(float(segment.end.z) - z) <= 0.015
                    and (float(segment.start.x) != float(segment.end.x)
                         or float(segment.start.y) != float(segment.end.y))]
        if not selected:
            return {"state": "between_layers", "z": z, "strokes": []}
        stride = max(1, (len(selected) + 4999) // 5000)
        strokes: list[list[list[float]]] = []
        current: list[list[float]] = []
        previous: tuple[float, float] | None = None
        for index, segment in enumerate(selected):
            start = (float(segment.start.x), float(segment.start.y))
            end = (float(segment.end.x), float(segment.end.y))
            if previous is not None and start != previous and current:
                strokes.append(current)
                current = []
            if not current:
                current.append([start[0], start[1]])
            if index % stride == 0 or index == len(selected) - 1:
                current.append([end[0], end[1]])
            previous = end
        if current:
            strokes.append(current)
        return {"state": "cutting_layer", "z": z, "strokes": strokes,
                "source_segment_count": len(selected), "render_stride": stride,
                "note": "Current cutting layer; simplified only for live display."}

    def _program_provenance_snapshot(self) -> dict[str, Any]:
        program = getattr(self.application, "program", None)
        if program is None:
            self._program_provenance_cache_key = None
            self._program_provenance_cache = {
                "report_state": "unavailable", "file_sha256": "", "report_name": "",
                "release_status": "", "bundle": "", "details": [], "header_notes": [],
                "verification_text": "", "notice": "No job is loaded.",
            }
            return dict(self._program_provenance_cache)
        path = Path(str(getattr(program, "path", "<memory>")))
        source_sha256 = str(getattr(program, "source_sha256", ""))
        key = (str(path), source_sha256)
        if key != self._program_provenance_cache_key:
            self._program_provenance_cache_key = key
            self._program_provenance_cache = _json_value(
                build_job_provenance(path, source_sha256,
                                     tuple(getattr(program, "header_comments", ()))))
        return dict(self._program_provenance_cache)

    def _large_program_preview(self, program: Any, segments: tuple[Any, ...]) -> dict[str, Any] | None:
        """Rasterize every XY segment for large jobs, cached by program identity.

        The raster is a display representation, not simplified toolpath data:
        every input segment is sent to the line renderer at each output size.
        Coordinates below one output pixel cannot be distinguished visually,
        and that limit is included in the returned note.
        """
        if getattr(self, "_large_preview_cache_program", None) is program:
            return self._large_preview_cache
        self._large_preview_cache_program = program
        self._large_preview_cache = None
        if not segments:
            return None

        bounds = getattr(program, "bounds", None)
        if bounds is None:
            return None
        minimum = getattr(bounds, "minimum", None)
        maximum = getattr(bounds, "maximum", None)
        if minimum is None or maximum is None:
            return None
        min_x, min_y = float(minimum.x), float(minimum.y)
        max_x, max_y = float(maximum.x), float(maximum.y)
        if not all(math.isfinite(value) for value in (min_x, min_y, max_x, max_y)):
            return None

        # Regenerate at successively smaller target resolutions rather than
        # downsampling a coarse approximation. The combined and two categorized
        # layers share a 450 KB PNG budget, leaving room for base64 and JSON in
        # the backend's 1 MiB response cap.
        for width, height in ((1024, 768), (768, 576), (512, 384), (384, 288), (256, 192)):
            padding = 12
            span_x = max(max_x - min_x, 0.001)
            span_y = max(max_y - min_y, 0.001)
            scale = min((width - 2 * padding) / span_x, (height - 2 * padding) / span_y)
            drawn_width = span_x * scale
            drawn_height = span_y * scale
            offset_x = (width - drawn_width) / 2
            offset_y = (height - drawn_height) / 2

            def screen(point: Any) -> tuple[int, int]:
                return (
                    round(offset_x + (float(point.x) - min_x) * scale),
                    round(offset_y + (max_y - float(point.y)) * scale),
                )

            def screen_xy(x: float, y: float) -> tuple[int, int]:
                return (
                    round(offset_x + (x - min_x) * scale),
                    round(offset_y + (max_y - y) * scale),
                )

            images = {
                "all": Image.new("RGBA", (width, height), (0, 0, 0, 0)),
                "cutting": Image.new("RGBA", (width, height), (0, 0, 0, 0)),
                "rapid": Image.new("RGBA", (width, height), (0, 0, 0, 0)),
            }
            drawings = {name: ImageDraw.Draw(image) for name, image in images.items()}
            for drawing in drawings.values():
                drawing.rectangle(
                    (round(offset_x), round(offset_y),
                     round(offset_x + drawn_width), round(offset_y + drawn_height)),
                    outline=(101, 114, 130, 190), width=1,
                )

            run_points: list[tuple[int, int]] = []
            run_rapid: bool | None = None
            previous_end: tuple[float, float] | None = None

            def flush_run() -> None:
                if len(run_points) >= 2:
                    color = (242, 184, 75, 235) if run_rapid else (45, 156, 255, 255)
                    drawings["all"].line(run_points, fill=color, width=1)
                    drawings["rapid" if run_rapid else "cutting"].line(run_points, fill=color, width=1)
                run_points.clear()

            for segment in segments:
                start = segment.start
                end = segment.end
                start_xy = (float(start.x), float(start.y))
                rapid = bool(segment.rapid)
                if run_points and (rapid != run_rapid or start_xy != previous_end):
                    flush_run()
                if not run_points:
                    run_rapid = rapid
                    run_points.append(screen(start))
                run_points.append(screen(end))
                previous_end = (float(end.x), float(end.y))
            flush_run()

            # Mark work zero when it lies within the rendered program bounds.
            # Duplicate the frame/zero onto both categorized layers so either
            # can be inspected alone and remains aligned with the same bounds.
            if min_x <= 0 <= max_x and min_y <= 0 <= max_y:
                zero_x, zero_y = screen_xy(0.0, 0.0)
                for drawing in drawings.values():
                    drawing.ellipse((zero_x - 3, zero_y - 3, zero_x + 3, zero_y + 3),
                                    fill=(64, 196, 217, 255))

            pngs: dict[str, bytes] = {}
            for name, image in images.items():
                output = BytesIO()
                image.save(output, format="PNG", optimize=True, compress_level=9)
                pngs[name] = output.getvalue()
            if sum(map(len, pngs.values())) <= 450_000 or (width, height) == (256, 192):
                data_urls = {
                    name: "data:image/png;base64," + base64.b64encode(png).decode("ascii")
                    for name, png in pngs.items()
                }
                result = {
                    "kind": "raster_xy_all_moves",
                    "data_url": data_urls["all"],
                    "cutting_data_url": data_urls["cutting"],
                    "rapid_data_url": data_urls["rapid"],
                    "path_layers_available": True,
                    "width": width,
                    "height": height,
                    "segment_count": len(segments),
                    "rendered_segment_count": len(segments),
                    "all_segments_rendered": True,
                    "note": (
                        f"Raster preview · every move projected into XY · {width} × {height} px; "
                        "details narrower than one pixel may not be distinguishable."
                    ),
                }
                self._large_preview_cache = result
                return result
        return None

    def poll_once(self, now: float | None = None) -> dict[str, Any]:
        """Advance transport/application state once and return a full snapshot."""
        if self.closed:
            return dict(self._last_snapshot)
        current = self._clock() if now is None else float(now)
        try:
            if self.safety_input_adapter is not None:
                with self._lock:
                    status = self._safety_input.observe_adapter(self.safety_input_adapter, now=current)
                    self._publish_safety_input(status)
            jog_poll = getattr(self.application, "poll_live_jog", None)
            if callable(jog_poll):
                jog_poll()
            completion_poll = getattr(self.application, "poll_z_probe_completion", None)
            if callable(completion_poll):
                completion_poll()
            poll_setup = getattr(self.application, "poll_wifi_setup", None)
            if callable(poll_setup):
                poll_setup(current)
            poll_wifi = getattr(self.application, "poll_wifi", None)
            outcome = poll_wifi() if callable(poll_wifi) else None
            if outcome is not None:
                self._emit("connection", _json_value(outcome))
            if getattr(self.application, "simulation_active", False):
                for item in self.application.poll_simulation():
                    self._emit(str(item.get("type", "simulation")), item)
            self._drain_transport_events()
            recovery_state_before_poll = self._job_watchdog_recovery.snapshot().get("state")
            self._job_watchdog_recovery.poll(
                self.application, now=current, connection_outcome=outcome)
            recovery_state = self._job_watchdog_recovery.snapshot().get("state")
            self._automatic_continuation.poll(self)
            if recovery_state == "waiting-for-idle" and recovery_state_before_poll != recovery_state:
                self._last_status_poll = current
            if (getattr(self.application, "connected", False)
                    and recovery_state != "waiting-for-m5-ack"
                    and current - self._last_status_poll >= self.status_interval):
                self.application.request_status()
                self._last_status_poll = current
                self._emit("status_poll", {})
            watchdog_check = getattr(self.application, "check_job_watchdog", None)
            watchdog = watchdog_check() if callable(watchdog_check) else None
            if watchdog is not None:
                self._emit("watchdog", {"message": str(watchdog)})
                try:
                    # A stream watchdog has already failed the job and issued
                    # realtime hold/reset. Once the saved Wi-Fi endpoint is
                    # back, M5 and a fresh Idle/0-RPM report are required
                    # before the existing guarded-home path can run. Never
                    # resume or restart cutting automatically.
                    self._job_watchdog_recovery.start(
                        self.application, str(watchdog), now=current, auto_home=True)
                except (RuntimeError, ValueError, TypeError, OSError) as exc:
                    self._emit("error", {"message": f"Automatic watchdog recovery could not start: {exc}"})
        except (RuntimeError, ValueError, TypeError, OSError) as exc:
            self._emit("error", {"message": str(exc)})
        self._drain_controller_events()
        return self._refresh_snapshot()

    def events_since(self, sequence: int = 0, limit: int = 100) -> dict[str, Any]:
        if not isinstance(sequence, int) or sequence < 0:
            raise ValueError("sequence must be a nonnegative integer")
        if not isinstance(limit, int) or not 1 <= limit <= 500:
            raise ValueError("event limit must be between 1 and 500")
        with self._lock:
            first = self._events[0]["sequence"] if self._events else self._sequence + 1
            events = [item for item in self._events if item["sequence"] > sequence][:limit]
            return {"events": events, "next_sequence": events[-1]["sequence"] if events else sequence,
                    "latest_sequence": self._sequence,
                    "lost": bool(self._events and sequence < first - 1)}

    def publish_snapshot(self) -> None:
        """Publish a completed action without polling machine transport."""
        with self._lock:
            self._refresh_snapshot()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return _json_value(self._last_snapshot or self._refresh_snapshot())

    def shutdown(self, *, safe_abort: bool = False) -> tuple[bool, str]:
        """Close only when idle, or after an explicit safe abort request."""
        if self.closed:
            return True, "Backend is already shut down"
        active = bool(getattr(self.application, "job_active", False) or getattr(self.application, "motion_busy", False))
        if active and not safe_abort:
            return False, "Backend shutdown rejected while machine work is active; abort safely first"
        try:
            if active:
                self.application.abort_job("Explicit backend shutdown safe-abort")
            self.application.close()
            adapter = self.safety_input_adapter
            if adapter is not None:
                adapter.close()
                self.safety_input_adapter = None
        except (RuntimeError, OSError, ValueError, TypeError) as exc:
            return False, f"Backend shutdown failed — {exc}"
        self.closed = True
        self._emit("shutdown", {"message": "Backend shut down safely"})
        self._refresh_snapshot()
        return True, "Backend shut down safely"

    def run(self, *, stop_event: threading.Event | None = None, interval: float = 0.05) -> None:
        stop_event = stop_event or threading.Event()
        interval = max(0.01, float(interval))
        while not stop_event.is_set() and not self.closed:
            self.poll_once()
            if stop_event.is_set():
                break
            events = getattr(self.application, "transport_events", None)
            pending = events() if callable(events) else None
            is_empty = getattr(pending, "empty", None)
            if callable(is_empty) and not is_empty():
                # The bounded drain left work queued. Recheck safety, watchdog,
                # and other runtime duties before consuming the next batch.
                continue
            wait_for_item = getattr(pending, "wait_for_item", None)
            if callable(wait_for_item):
                wait_for_item(interval)
            else:
                stop_event.wait(interval)
