"""Validated action registry over public ApplicationController methods."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Callable

from ..application.controller import JobStartAuthorization
from ..application.machine_session import ActionOutcome
from ..application.probing_service import ProbePlan
from ..machine_state import MachineProfile
from ..step_prepare_settings import StepPrepareSettings
from ..grbl import Position
from .runtime import BackendRuntime


class ActionRejected(ValueError):
    pass


def _string(payload: dict[str, Any], key: str, *, default: str | None = None) -> str:
    value = payload.get(key, default)
    if not isinstance(value, str) or not value.strip():
        raise ActionRejected(f"{key} must be a non-empty string")
    return value.strip()


def _number(payload: dict[str, Any], key: str, *, default: float | None = None) -> float:
    value = payload.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ActionRejected(f"{key} must be a number")
    value = float(value)
    if not value == value or abs(value) == float("inf"):
        raise ActionRejected(f"{key} must be finite")
    return value


def _integer(payload: dict[str, Any], key: str, *, default: int | None = None) -> int:
    value = payload.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ActionRejected(f"{key} must be an integer")
    return int(value)


def _boolean(payload: dict[str, Any], key: str, *, default: bool | None = None) -> bool:
    value = payload.get(key, default)
    if not isinstance(value, bool):
        raise ActionRejected(f"{key} must be boolean")
    return value


def _mapping(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise ActionRejected(f"{key} must be an object")
    return dict(value)


def _outcome(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, JobStartAuthorization):
        return {"accepted": value.accepted, "message": value.message, "token": value.token}
    if isinstance(value, ActionOutcome):
        return {"accepted": value.accepted, "message": value.message}
    if hasattr(value, "accepted") and hasattr(value, "message"):
        result = {"accepted": bool(value.accepted), "message": str(value.message)}
        for key in ("mode", "host", "port"):
            item = getattr(value, key, None)
            if item is not None:
                result[key] = getattr(item, "value", item)
        return result
    if value is None:
        return {"accepted": True, "message": "Action completed"}
    if is_dataclass(value):
        return asdict(value)
    return {"accepted": True, "message": str(value), "value": value}


class ActionDispatcher:
    """Expose a deliberately finite, typed set of guarded operations."""

    ACTIONS = frozenset({
        "discover-usb", "connect-usb", "connect-wifi", "auto-connect", "connect-simulation",
        "configure-simulation", "disconnect", "status", "capabilities", "home",
        "safety-input-status", "acknowledge-safety-input",
        "invalidate-reference", "jog", "move-to", "live-jog-start",
        "live-jog-stop", "live-jog-renew", "cancel-jog", "hold", "resume", "work-zero",
        "return-reference", "return-work-zero", "probe", "probe-work-z",
        "abort-probe", "spindle-start", "spindle-stop", "load-job",
        "load-generated-job", "review-job", "preflight", "authorize-job-start",
        "start-job", "pause-job", "resume-job", "abort-job", "save-connection",
        "continue-to-home", "cancel-recovery", "automatic-continuation",
        "save-profile", "save-machine-capabilities", "save-probe-capabilities",
        "save-probe-configuration", "save-homing-declarations", "save-z-plate-settings",
        "save-step-settings", "simulation", "simulation-limit",
        "commission-plate", "export-simulation-evidence", "auto-xyz-start",
        "auto-xyz-abort", "touch-input-test", "touch-commission",
        "touch-ack-remove", "touch-continue-to-surface", "touch-commission-save", "travel-calibration-start",
        "travel-calibration-abort", "travel-calibration-accept", "shutdown",
    })

    _KEYS = {
        "discover-usb": set(), "connect-usb": {"port"}, "connect-wifi": {"host", "port"},
        "auto-connect": set(),
        "connect-simulation": set(), "configure-simulation": {"speed", "workpiece"},
        "disconnect": {"reason"}, "status": set(), "capabilities": set(),
        "safety-input-status": set(), "acknowledge-safety-input": set(),
        "home": set(), "invalidate-reference": {"reason"},
        "jog": {"axis", "distance", "feed"},
        "move-to": {"x", "y", "z", "feed"}, "cancel-jog": set(),
        "live-jog-start": {"axis", "direction", "allow_unreferenced", "feed", "lease_token"},
        "live-jog-stop": set(), "live-jog-renew": {"token"},
        "hold": set(), "resume": set(), "work-zero": {"axes"},
        "return-reference": {"feed"}, "return-work-zero": {"feed"},
        "probe": {"axis", "fast_distance", "slow_distance", "retract", "safe_retract",
                  "fast_feed", "slow_feed", "retract_feed", "wcs_slot", "offset_axis",
                  "offset_value", "purpose"},
        "probe-work-z": set(), "abort-probe": {"reason"},
        "spindle-start": {"rpm"}, "spindle-stop": set(), "load-job": {"path"},
        "load-generated-job": {"gcode", "filename"},
        "review-job": set(), "preflight": set(),
        "authorize-job-start": {"review_acknowledged", "physical_preflight_confirmed"},
        "start-job": {"token"}, "pause-job": set(), "resume-job": set(),
        "abort-job": {"reason"}, "save-connection": {"mode", "host", "port", "usb_port"},
        "save-profile": {"name", "travel_x", "travel_y", "travel_z", "safe_z"},
        "save-machine-capabilities": {"limit_switches", "z_plate", "tool_setter", "movable_xyz", "fixed_fixture"},
        "save-probe-capabilities": {"z_plate", "tool_setter", "movable_xyz", "fixed_xyz"},
        "save-probe-configuration": {"z_plate", "tool_setter", "movable_xyz", "fixed_xyz",
                                      "thickness", "active_low", "fast_feed", "slow_feed",
                                      "max_search", "retract", "safe_retract", "tolerance"},
        "save-homing-declarations": {"declarations"},
        "save-z-plate-settings": {"thickness", "active_low", "fast_feed", "slow_feed",
                                   "max_search", "retract", "safe_retract", "tolerance"},
        "save-step-settings": {"orientation", "zero_location", "tool_diameter", "passes",
                                "max_stepdown", "safe_z", "cut_feed", "plunge_feed",
                                "spindle_rpm", "breakthrough", "tab_count", "tab_width", "tab_height"},
        "simulation": {"operation", "reset_asserted", "speed", "workpiece", "path"},
        "simulation-limit": {"axis", "active"},
        "commission-plate": set(), "export-simulation-evidence": {"path"},
        "auto-xyz-start": {"x", "y", "z"}, "auto-xyz-abort": set(),
        "touch-input-test": set(), "touch-commission": set(),
        "touch-ack-remove": set(), "touch-continue-to-surface": {"transaction_id"}, "touch-commission-save": {"samples"},
        "travel-calibration-start": {"increment_mm", "max_overshoot_mm", "search_feed", "return_feed"},
        "travel-calibration-abort": set(), "travel-calibration-accept": set(),
        "shutdown": {"safe_abort"},
        "continue-to-home": set(), "cancel-recovery": set(),
        "automatic-continuation": {"enabled"},
    }

    _SAFETY_RECOVERY_ACTIONS = frozenset({
        "status", "capabilities", "safety-input-status", "acknowledge-safety-input",
        "hold", "pause-job", "cancel-jog", "live-jog-stop", "abort-probe", "abort-job",
        "spindle-stop", "travel-calibration-abort", "disconnect", "shutdown",
        "cancel-recovery",
    })

    def __init__(self, runtime: BackendRuntime) -> None:
        self.runtime = runtime
        self._pending_confirmations: dict[str, str] = {}
        self._idempotent: dict[str, tuple[str, dict[str, Any]]] = {}
        self._max_idempotent = 256

    def invoke(self, action: str, payload: dict[str, Any] | None = None, *,
               expected_revision: int | None = None, idempotency_key: str = "") -> dict[str, Any]:
        if not isinstance(action, str) or action not in self.ACTIONS:
            raise ActionRejected("unknown or unsupported action")
        payload = payload or {}
        if not isinstance(payload, dict):
            raise ActionRejected("action payload must be an object")
        unknown = set(payload) - self._KEYS[action]
        if unknown:
            raise ActionRejected(f"unsupported arguments for {action}: {', '.join(sorted(unknown))}")
        # Stop intent must never be discarded because telemetry changed, nor
        # replay a cached success while a later operation is still moving.
        urgent = action in {"live-jog-stop", "cancel-jog", "hold", "pause-job", "spindle-stop", "abort-job", "abort-probe", "cancel-recovery"}
        if urgent or action == "live-jog-renew":
            expected_revision = None
            idempotency_key = ""
        if expected_revision is not None and int(expected_revision) != self.runtime.state_revision:
            raise ActionRejected(
                f"state revision mismatch: expected {expected_revision}, current {self.runtime.state_revision}"
            )
        if self.runtime.safety_input_blocks_motion and action not in self._SAFETY_RECOVERY_ACTIONS:
            status = self.runtime.safety_input_status
            raise ActionRejected(
                f"action {action} rejected while independent safety input is {status.state.value}: {status.reason}"
            )
        if idempotency_key:
            if not isinstance(idempotency_key, str) or not idempotency_key.strip() or len(idempotency_key) > 128:
                raise ActionRejected("idempotency_key is invalid")
            fingerprint = hashlib.sha256(json.dumps(
                {"action": action, "payload": payload}, sort_keys=True, default=str,
                separators=(",", ":"),
            ).encode("utf-8")).hexdigest()
            previous = self._idempotent.get(idempotency_key)
            if previous is not None:
                if previous[0] != fingerprint:
                    raise ActionRejected("idempotency key was already used for a different command")
                return dict(previous[1])
        handler = getattr(self, f"_action_{action.replace('-', '_')}")
        if action in {"hold", "pause-job", "abort-job", "cancel-recovery", "spindle-stop",
                      "load-job", "load-generated-job", "jog", "move-to", "work-zero", "disconnect",
                      "live-jog-start", "home", "return-reference", "return-work-zero", "probe", "probe-work-z",
                      "invalidate-reference", "save-profile", "save-machine-capabilities", "save-probe-capabilities",
                      "save-probe-configuration", "save-homing-declarations", "save-z-plate-settings",
                      "auto-xyz-start", "connect-usb", "connect-wifi", "auto-connect", "connect-simulation",
                      "configure-simulation", "spindle-start", "start-job", "resume-job", "resume"}:
            self.runtime._automatic_continuation.disable(f"Automatic continuation canceled by {action}")
        result = _outcome(handler(payload))
        if idempotency_key:
            self._idempotent[idempotency_key] = (fingerprint, dict(result))
            while len(self._idempotent) > self._max_idempotent:
                self._idempotent.pop(next(iter(self._idempotent)))
        return result

    def confirmation_response(self, token: str, accepted: bool) -> dict[str, Any]:
        if not isinstance(token, str) or not token or len(token) > 256:
            raise ActionRejected("confirmation token is invalid")
        if not isinstance(accepted, bool):
            raise ActionRejected("confirmation accepted value must be boolean")
        operation = self._pending_confirmations.pop(token, None)
        if operation is None:
            raise ActionRejected("This approval was canceled, replaced, or already used; select the action again")
        if not isinstance(accepted, bool):
            raise ActionRejected("confirmation accepted value must be boolean")
        if not accepted:
            return {"accepted": False, "message": "Operation canceled by operator"}
        if operation == "start-job":
            return self.invoke("start-job", {"token": token})
        raise ActionRejected("confirmation operation is unsupported")

    def _action_connect_usb(self, p):
        return self.runtime.application.connect_usb(_string(p, "port"))

    def _action_connect_wifi(self, p):
        host = _string(p, "host")
        port = int(_number(p, "port"))
        if not 1 <= port <= 65535:
            raise ActionRejected("port must be between 1 and 65535")
        return self.runtime.application.begin_wifi(host, port)

    def _action_auto_connect(self, p):
        return self.runtime.application.auto_connect_saved()

    def _action_connect_simulation(self, p):
        return self.runtime.application.connect_simulation()

    def _action_discover_usb(self, p):
        ports = self.runtime.application.usb_ports()
        return {"ports": [{"port": str(port), "description": str(description)} for port, description in ports]}

    def _action_configure_simulation(self, p):
        return self.runtime.application.configure_simulation(
            _string(p, "speed"), _string(p, "workpiece", default="Pocket + retained island"))

    def _action_disconnect(self, p):
        return self.runtime.application.disconnect(str(p.get("reason", "Disconnected by operator")))

    def _action_status(self, p):
        self.runtime.poll_once()
        return self.runtime.snapshot()

    def _action_capabilities(self, p):
        return self.runtime.snapshot().get("capabilities", {})

    def _action_safety_input_status(self, p):
        self.runtime.poll_once()
        return self.runtime.safety_input_status.to_dict()

    def _action_acknowledge_safety_input(self, p):
        accepted, message = self.runtime.acknowledge_safety_input()
        return ActionOutcome(accepted, message)

    def _action_home(self, p):
        return self.runtime.application.home_machine()

    def _action_continue_to_home(self, p):
        return self.runtime._job_watchdog_recovery.continue_to_home(self.runtime.application)

    def _action_automatic_continuation(self, p):
        policy = self.runtime._automatic_continuation
        if _boolean(p, "enabled"):
            policy.enable(self.runtime.application)
        else:
            policy.disable()
        return {"accepted": True, **policy.snapshot()}

    def _action_cancel_recovery(self, p):
        return self.runtime._job_watchdog_recovery.cancel()

    def _action_invalidate_reference(self, p):
        self.runtime.application.invalidate_reference(str(p.get("reason", "Invalidated by operator")))
        return ActionOutcome(True, "Machine reference invalidated")

    def _action_jog(self, p):
        axis = _string(p, "axis").upper()
        distance = _number(p, "distance")
        feed = _number(p, "feed", default=500.0)
        if axis not in "XYZ" or not -1000 < distance < 1000 or not 0 < feed <= 1500:
            raise ActionRejected("jog axis, distance, or feed is outside the bounded range")
        return self.runtime.application.jog(axis, distance, feed)

    def _action_cancel_jog(self, p):
        self.runtime.application.cancel_jog()
        return ActionOutcome(True, "Jog cancellation requested")

    def _action_move_to(self, p):
        feed = _number(p, "feed", default=500.0)
        if not 0 < feed <= 1500:
            raise ActionRejected("feed is outside the bounded range")
        target = Position(_number(p, "x"), _number(p, "y"), _number(p, "z"))
        return self.runtime.application.move_to(target, feed)

    def _action_live_jog_start(self, p):
        axis = _string(p, "axis").upper()
        direction = _number(p, "direction")
        feed = _number(p, "feed", default=500.0)
        allowed = _boolean(p, "allow_unreferenced", default=False)
        if axis not in "XYZ" or direction not in {-1.0, 1.0} or not 0 < feed <= 1500:
            raise ActionRejected("live jog axis, direction, or feed is outside the bounded range")
        token = _string(p, "lease_token")
        if not token or len(token) > 128:
            raise ActionRejected("A held jog requires a bounded press token")
        return self.runtime.application.start_live_jog(axis, direction, allowed, feed, lease_token=token)

    def _action_live_jog_renew(self, p):
        return self.runtime.application.renew_live_jog(_string(p, "token"))

    def _action_live_jog_stop(self, p):
        return self.runtime.application.stop_live_jog()

    def _action_travel_calibration_start(self, p):
        return self.runtime.application.start_travel_calibration(
            increment_mm=_number(p, "increment_mm", default=10.0),
            max_overshoot_mm=_number(p, "max_overshoot_mm", default=30.0),
            search_feed=_number(p, "search_feed", default=120.0),
            return_feed=_number(p, "return_feed", default=600.0),
        )

    def _action_travel_calibration_abort(self, p):
        return self.runtime.application.abort_travel_calibration()

    def _action_travel_calibration_accept(self, p):
        return self.runtime.application.accept_travel_calibration()

    def _action_hold(self, p):
        return self.runtime.application.hold()

    def _action_resume(self, p):
        return self.runtime.application.resume()

    def _action_work_zero(self, p):
        return self.runtime.application.set_work_zero(_string(p, "axes", default="XYZ"))

    def _action_return_reference(self, p):
        feed = _number(p, "feed", default=500.0)
        if not 0 < feed <= 1500:
            raise ActionRejected("feed is outside the bounded range")
        return self.runtime.application.return_to_reference(feed)

    def _action_return_work_zero(self, p):
        feed = _number(p, "feed", default=500.0)
        if not 0 < feed <= 1500:
            raise ActionRejected("feed is outside the bounded range")
        return self.runtime.application.return_to_work_zero(feed)

    def _action_probe(self, p):
        axis = _string(p, "axis").upper()
        if axis not in "XYZ":
            raise ActionRejected("probe axis must be X, Y, or Z")
        plan = ProbePlan(
            axis, _number(p, "fast_distance"), _number(p, "slow_distance"),
            _number(p, "retract"), _number(p, "safe_retract"),
            _number(p, "fast_feed", default=100.0), _number(p, "slow_feed", default=25.0),
            _number(p, "retract_feed", default=100.0),
            wcs_slot=_integer(p, "wcs_slot", default=1),
            offset_axis=str(p.get("offset_axis", "")),
            offset_value=_number(p, "offset_value", default=0.0),
            purpose=_string(p, "purpose", default="operator"),
        )
        return self.runtime.application.start_probe(plan)

    def _action_probe_work_z(self, p):
        return self.runtime.application.probe_work_z()

    def _action_abort_probe(self, p):
        return self.runtime.application.abort_probe(str(p.get("reason", "Aborted by operator")))

    def _action_spindle_start(self, p):
        rpm = int(_number(p, "rpm"))
        if not 1 <= rpm <= 24000:
            raise ActionRejected("spindle RPM is outside the bounded range")
        return self.runtime.application.start_spindle(rpm)

    def _action_spindle_stop(self, p):
        return self.runtime.application.stop_spindle()

    def _action_load_job(self, p):
        path = Path(_string(p, "path"))
        program = self.runtime.application.load_program(path)
        self.runtime.publish_snapshot()
        return ActionOutcome(True, f"Loaded job {path.name} ({len(getattr(program, 'commands', ())) } commands)")

    def _action_load_generated_job(self, p):
        gcode = _string(p, "gcode")
        filename = _string(p, "filename")
        if len(gcode.encode("utf-8")) > 192 * 1024:
            raise ActionRejected("generated G-code exceeds the bounded payload size")
        program = self.runtime.application.load_generated(gcode, filename)
        self.runtime.publish_snapshot()
        return ActionOutcome(True, f"Loaded generated job {filename} ({len(getattr(program, 'commands', ())) } commands)")

    def _action_review_job(self, p):
        fits, reason = self.runtime.application.preflight()
        return {"accepted": bool(fits), "message": str(reason), "fits": bool(fits)}

    def _action_preflight(self, p):
        fits, reason = self.runtime.application.preflight()
        return {"accepted": bool(fits), "message": str(reason), "fits": bool(fits)}

    def _action_authorize_job_start(self, p):
        review = bool(p.get("review_acknowledged", False))
        physical = bool(p.get("physical_preflight_confirmed", False))
        result = self.runtime.application.authorize_job_start(
            review_acknowledged=review, physical_preflight_confirmed=physical)
        if result.accepted and result.token:
            self._pending_confirmations[result.token] = "start-job"
        return result

    def _action_start_job(self, p):
        token = _string(p, "token")
        self._pending_confirmations.pop(token, None)
        return self.runtime.application.start_authorized_job(token)

    def _action_pause_job(self, p):
        return self.runtime.application.pause_job()

    def _action_resume_job(self, p):
        return self.runtime.application.resume_job()

    def _action_abort_job(self, p):
        self.runtime.application.abort_job(str(p.get("reason", "Aborted by operator")))
        return ActionOutcome(True, "Job abort requested")

    def _action_save_connection(self, p):
        mode = _string(p, "mode")
        if mode == "USB serial":
            self.runtime.application.save_usb_settings(_string(p, "usb_port"))
        elif mode == "Wi-Fi TCP":
            port = _integer(p, "port")
            if not 1 <= port <= 65535:
                raise ActionRejected("port must be between 1 and 65535")
            self.runtime.application.save_wifi_settings(_string(p, "host"), port)
        else:
            raise ActionRejected("connection mode is unsupported")
        return ActionOutcome(True, "Connection settings saved")

    def _action_save_profile(self, p):
        profile = MachineProfile(
            _string(p, "name", default="Two Trees TTC 3018"),
            _number(p, "travel_x"), _number(p, "travel_y"),
            _number(p, "travel_z"), _number(p, "safe_z"),
        )
        try:
            self.runtime.application.save_profile(profile)
        except (OSError, TypeError, ValueError) as exc:
            return ActionOutcome(False, f"Machine profile rejected — {exc}")
        return ActionOutcome(True, "Machine profile saved")

    def _action_save_machine_capabilities(self, p):
        return self.runtime.application.save_capabilities(
            limit_switches=_boolean(p, "limit_switches"), z_plate=_boolean(p, "z_plate"),
            tool_setter=_boolean(p, "tool_setter"), movable_xyz=_boolean(p, "movable_xyz"),
            fixed_fixture=_boolean(p, "fixed_fixture"),
        )

    def _action_save_probe_capabilities(self, p):
        return self.runtime.application.save_probe_capabilities(
            z_plate=_boolean(p, "z_plate"), tool_setter=_boolean(p, "tool_setter"),
            movable_xyz=_boolean(p, "movable_xyz"), fixed_xyz=_boolean(p, "fixed_xyz"),
        )

    def _action_save_probe_configuration(self, p):
        return self.runtime.application.save_probe_configuration(
            z_plate=_boolean(p, "z_plate"), tool_setter=_boolean(p, "tool_setter"),
            movable_xyz=_boolean(p, "movable_xyz"), fixed_xyz=_boolean(p, "fixed_xyz"),
            plate_thickness=_number(p, "thickness"), active_low=_boolean(p, "active_low"),
            fast_feed=_number(p, "fast_feed"), slow_feed=_number(p, "slow_feed"),
            max_search=_number(p, "max_search"), retract=_number(p, "retract"),
            safe_retract=_number(p, "safe_retract"), tolerance=_number(p, "tolerance"),
        )

    def _action_save_homing_declarations(self, p):
        declarations = _mapping(p, "declarations")
        return self.runtime.application.save_homing_limit_declarations(declarations)

    def _action_save_z_plate_settings(self, p):
        return self.runtime.application.save_z_touch_plate_settings(
            plate_thickness=_number(p, "thickness"), active_low=_boolean(p, "active_low"),
            fast_feed=_number(p, "fast_feed"), slow_feed=_number(p, "slow_feed"),
            max_search=_number(p, "max_search"), retract=_number(p, "retract"),
            safe_retract=_number(p, "safe_retract"), tolerance=_number(p, "tolerance"),
        )

    def _action_save_step_settings(self, p):
        defaults = StepPrepareSettings()
        settings = StepPrepareSettings(
            orientation=_string(p, "orientation", default=defaults.orientation),
            zero_location=_string(p, "zero_location", default=defaults.zero_location),
            tool_diameter=_number(p, "tool_diameter", default=defaults.tool_diameter),
            passes=_integer(p, "passes", default=defaults.passes),
            max_stepdown=_number(p, "max_stepdown", default=defaults.max_stepdown),
            safe_z=_number(p, "safe_z", default=defaults.safe_z),
            cut_feed=_number(p, "cut_feed", default=defaults.cut_feed),
            plunge_feed=_number(p, "plunge_feed", default=defaults.plunge_feed),
            spindle_rpm=_integer(p, "spindle_rpm", default=defaults.spindle_rpm),
            breakthrough=_number(p, "breakthrough", default=defaults.breakthrough),
            tab_count=_integer(p, "tab_count", default=defaults.tab_count),
            tab_width=_number(p, "tab_width", default=defaults.tab_width),
            tab_height=_number(p, "tab_height", default=defaults.tab_height),
        )
        try:
            self.runtime.application.save_step_prepare_settings(settings)
        except (OSError, TypeError, ValueError) as exc:
            return ActionOutcome(False, f"STEP preparation settings rejected — {exc}")
        return ActionOutcome(True, "STEP preparation settings saved")

    def _action_simulation(self, p):
        name = _string(p, "operation")
        if name == "connect":
            return self.runtime.application.connect_simulation()
        if name == "estop":
            return self.runtime.application.inject_simulation_estop(reset_asserted=bool(p.get("reset_asserted", False)))
        if name == "release-estop":
            return self.runtime.application.release_simulation_estop()
        if name == "ack-estop":
            return self.runtime.application.acknowledge_simulation_estop()
        if name == "configure":
            return self.runtime.application.configure_simulation(
                _string(p, "speed"), _string(p, "workpiece", default="Pocket + retained island"))
        if name == "export":
            path = Path(_string(p, "path"))
            return self.runtime.application.export_simulation_trace(path)
        raise ActionRejected("unsupported simulation operation")

    def _action_simulation_limit(self, p):
        axis = _string(p, "axis").upper()
        if axis not in "XYZ":
            raise ActionRejected("simulation limit axis must be X, Y, or Z")
        return self.runtime.application.set_simulation_limit_input(axis, _boolean(p, "active"))

    def _action_commission_plate(self, p):
        return self.runtime.application.commission_simulation_calibration_plate()

    def _action_export_simulation_evidence(self, p):
        path = Path(_string(p, "path"))
        return self.runtime.application.export_simulation_trace(path)

    def _action_auto_xyz_start(self, p):
        return self.runtime.application.start_auto_xyz_calibration((
            _number(p, "x"), _number(p, "y"), _number(p, "z")))

    def _action_auto_xyz_abort(self, p):
        return self.runtime.application.abort_auto_xyz_calibration()

    def _action_touch_input_test(self, p):
        return self.runtime.application.start_z_touch_plate_input_test()

    def _action_touch_commission(self, p):
        return self.runtime.application.start_z_touch_plate_commissioning_sample()

    def _action_touch_continue_to_surface(self, p):
        return self.runtime.application.continue_z_probe_to_surface(_string(p, "transaction_id"))

    def _action_touch_ack_remove(self, p):
        return self.runtime.application.acknowledge_z_touch_plate_removed()

    def _action_touch_commission_save(self, p):
        samples = p.get("samples")
        if not isinstance(samples, list) or not samples:
            raise ActionRejected("samples must be a non-empty array")
        values = tuple(float(value) for value in samples)
        return self.runtime.application.save_z_touch_plate_commissioning(values)

    def _action_shutdown(self, p):
        ok, message = self.runtime.shutdown(safe_abort=bool(p.get("safe_abort", False)))
        return ActionOutcome(ok, message)
