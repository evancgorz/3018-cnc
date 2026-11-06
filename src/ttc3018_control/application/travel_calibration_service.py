"""Guarded travel-envelope calibration using a homing switch as the datum."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from statistics import median
from typing import Callable

from ..grbl import GrblStatus, Position, REALTIME_JOG_CANCEL, REALTIME_SOFT_RESET, make_jog
from ..machine_config import MachineDefinition, SwitchMode
from ..machine_state import MachineProfile
from .machine_session import ActionOutcome, MachineSession


class TravelCalibrationState(StrEnum):
    IDLE = "idle"
    SETTINGS = "settings"
    HOMING = "homing"
    BASELINE = "baseline"
    SEARCHING = "searching"
    VALIDATING = "validating"
    READY = "ready"
    FAILED = "failed"
    CANCELED = "canceled"


@dataclass(frozen=True)
class TravelCalibrationOptions:
    increment_mm: float = 10.0
    max_overshoot_mm: float = 30.0
    search_feed: float = 120.0
    return_feed: float = 600.0
    stall_threshold_mm: float = 0.5
    validation_tolerance_mm: float = 0.75
    switch_search_mm: float = 5.0

    def validate(self) -> None:
        if not 1.0 <= self.increment_mm <= 25.0:
            raise ValueError("Calibration increment must be between 1 and 25 mm")
        if not self.increment_mm <= self.max_overshoot_mm <= 100.0:
            raise ValueError("Maximum overshoot must be at least one increment and no more than 100 mm")
        if not 10.0 <= self.search_feed <= 300.0:
            raise ValueError("Calibration search feed must be between 10 and 300 mm/min")
        if not 50.0 <= self.return_feed <= 1500.0:
            raise ValueError("Calibration return feed must be between 50 and 1500 mm/min")
        if not 0.1 <= self.stall_threshold_mm <= 2.0:
            raise ValueError("Stall threshold must be between 0.1 and 2 mm")
        if not self.stall_threshold_mm <= self.validation_tolerance_mm <= 2.0:
            raise ValueError("Validation tolerance must be between the stall threshold and 2 mm")
        if not 1.0 <= self.switch_search_mm <= 10.0:
            raise ValueError("Switch search distance must be between 1 and 10 mm")


class TravelCalibrationService:
    """Infer physical travel from lost motion relative to known home switches.

    GRBL is open-loop and never reports a motor stall. Each trial therefore
    starts from a fresh home, moves away in bounded gentle chunks, returns until
    the axis home input triggers, and compares that trigger coordinate with a
    baseline. A repeatable positive discrepancy is missed travel at the far stop.
    """

    def __init__(self, session: MachineSession, send_line: Callable[[bytes], None],
                 send_realtime: Callable[[bytes], None], on_notice: Callable[[str], None] | None = None) -> None:
        self.session = session
        self._send_line = send_line
        self._send_realtime = send_realtime
        self._notice = on_notice or (lambda _message: None)
        self.state = TravelCalibrationState.IDLE
        self.options = TravelCalibrationOptions()
        self.definition: MachineDefinition | None = None
        self.axis_index = 0
        self.axis = "X"
        self.phase = ""
        self.progress = 0.0
        self.results: dict[str, float] = {}
        self.baselines: dict[str, float] = {}
        self.samples: dict[str, list[float]] = {axis: [] for axis in "XYZ"}
        self.failure_reason = ""
        self._awaiting_ack = False
        self._motion_seen = False
        self._home_ack = False
        self._home_position: Position | None = None
        self._candidate = 0.0
        self._remaining = 0.0
        self._return_trigger: float | None = None
        self._mode = "search"
        self._settings: dict[int, float] = {}
        self._return_pin_released_seen = False

    @property
    def active(self) -> bool:
        return self.state in {TravelCalibrationState.SETTINGS, TravelCalibrationState.HOMING, TravelCalibrationState.BASELINE,
                              TravelCalibrationState.SEARCHING, TravelCalibrationState.VALIDATING}

    @property
    def can_accept(self) -> bool:
        return self.state is TravelCalibrationState.READY and set(self.results) == set("XYZ")

    @property
    def status_text(self) -> str:
        if self.state is TravelCalibrationState.FAILED:
            return f"Travel calibration failed — {self.failure_reason}"
        if self.state is TravelCalibrationState.READY:
            values = " · ".join(f"{axis} {self.results[axis]:.2f} mm" for axis in "XYZ")
            return f"Validation passed — {values}. Review and accept to save."
        if self.active:
            return f"{self.axis} · {self.phase.replace('_', ' ')} · {self.progress:.0f}%"
        return "Travel calibration not started"

    def snapshot(self) -> dict[str, object]:
        return {"state": self.state.value, "axis": self.axis, "phase": self.phase,
                "progress": self.progress, "results": dict(self.results),
                "can_accept": self.can_accept, "status": self.status_text,
                "failure_reason": self.failure_reason}

    def start(self, definition: MachineDefinition, options: TravelCalibrationOptions, *,
              connected: bool, status_fresh: bool, spindle_off: bool,
              homing_inputs_safe: bool) -> ActionOutcome:
        if self.active:
            return ActionOutcome(False, "Travel calibration is already active")
        try:
            options.validate()
        except ValueError as exc:
            return ActionOutcome(False, str(exc))
        if not connected or not status_fresh or self.session.status is None or self.session.status.state != "Idle":
            return ActionOutcome(False, "Connect and wait for a fresh Idle status before calibration")
        if not spindle_off:
            return ActionOutcome(False, "Turn the spindle off before calibration")
        if not homing_inputs_safe:
            return ActionOutcome(False, "All commissioned homing inputs must be released before calibration")
        if any(item.switch_mode is SwitchMode.NONE for item in definition.axes.values()):
            return ActionOutcome(False, "Configure one homing switch for every axis before calibration")
        if any(item.hard_limit for item in definition.axes.values()):
            return ActionOutcome(False, "Disable hard-limit handling during travel calibration; switch pins remain monitored by Pine")
        self.reset()
        self.definition = definition
        self.options = options
        self.axis_index = 0
        self.axis = "X"
        self._mode = "baseline"
        self.state = TravelCalibrationState.SETTINGS
        self.phase = "checking_grbl_settings"
        try:
            self._send_line(b"$$\n")
        except RuntimeError as exc:
            return self._fail(f"GRBL settings could not be queried — {exc}")
        return ActionOutcome(True, "Checking GRBL soft limits and homing settings before calibration")

    def abort(self) -> ActionOutcome:
        if not self.active:
            return ActionOutcome(False, "Travel calibration is not active")
        try:
            self._send_realtime(REALTIME_SOFT_RESET if self.state is TravelCalibrationState.HOMING else REALTIME_JOG_CANCEL)
        except RuntimeError:
            pass
        self.state = TravelCalibrationState.CANCELED
        self.phase = "canceled"
        self.session.invalidate_reference("Travel calibration canceled; home again before motion")
        self._notice("Travel calibration canceled; home the machine again before motion")
        return ActionOutcome(True, "Travel calibration canceled")

    def reset(self) -> None:
        self.state = TravelCalibrationState.IDLE
        self.axis_index = 0
        self.axis = "X"
        self.phase = ""
        self.progress = 0.0
        self.results = {}
        self.baselines = {}
        self.samples = {axis: [] for axis in "XYZ"}
        self.failure_reason = ""
        self._awaiting_ack = False
        self._motion_seen = False
        self._home_ack = False
        self._home_position = None
        self._candidate = 0.0
        self._remaining = 0.0
        self._return_trigger = None
        self._mode = "search"
        self._settings = {}
        self._return_pin_released_seen = False

    def handle_response(self, response: str) -> bool:
        if not self.active:
            return False
        text = response.strip().lower()
        if self.state is TravelCalibrationState.SETTINGS:
            if text.startswith("$") and "=" in text:
                try:
                    key, value = text[1:].split("=", 1)
                    self._settings[int(key)] = float(value)
                except (TypeError, ValueError):
                    self._fail(f"Unrecognized GRBL setting response: {response.strip()}")
                return True
            if text == "ok":
                required = {20, 27, 130, 131, 132}
                if not required.issubset(self._settings):
                    self._fail("GRBL did not report $20, $27, and $130-$132; calibration cannot verify its bounds")
                elif int(self._settings[20]) != 0:
                    self._fail("GRBL soft limits ($20) must be disabled for physical travel discovery")
                else:
                    self.phase = "initial_home"
                    self._send_home()
                return True
            if text.startswith("error:") or text.startswith("alarm:"):
                self._fail(f"GRBL settings query failed — {response.strip()}")
                return True
            return False
        if not (text == "ok" or text.startswith("error:") or text.startswith("alarm:")):
            return False
        if text != "ok":
            self._fail(f"GRBL replied {response.strip()}; check soft-limit settings and re-home")
            return True
        if self.state is TravelCalibrationState.HOMING:
            self._home_ack = True
        else:
            self._awaiting_ack = False
        return True

    def observe_status(self, status: GrblStatus) -> None:
        if not self.active or self.definition is None:
            return
        if status.state in {"Alarm", "Door"}:
            self._fail(f"GRBL reported {status.state}")
            return
        if self.state is TravelCalibrationState.HOMING:
            if self._home_ack and status.state == "Idle" and status.machine_position is not None:
                ends = {axis: self.definition.axes[axis].switch_end.value for axis in "XYZ"}
                self.session.envelope.establish_homed(status.machine_position, self.definition.to_profile(), ends)
                self._home_position = status.machine_position
                self._after_home()
            return
        if status.state in {"Jog", "Run"}:
            self._motion_seen = True
        if self.phase in {"baseline_return", "trial_return", "validation_return"}:
            if self.axis not in status.pins:
                self._return_pin_released_seen = True
            if (self._return_pin_released_seen and self.axis in status.pins
                    and self._return_trigger is None and status.machine_position is not None):
                self._return_trigger = getattr(status.machine_position, self.axis.lower())
                try:
                    self._send_realtime(REALTIME_JOG_CANCEL)
                except RuntimeError as exc:
                    self._fail(f"Could not stop at the {self.axis} home switch — {exc}")
                    return
            if self._return_trigger is not None and status.state == "Idle" and not self._awaiting_ack:
                self._finish_return()
            elif self._motion_seen and status.state == "Idle" and not self._awaiting_ack:
                self._fail(f"{self.axis} home switch did not trigger during the calibration return")
            return
        if status.state == "Idle" and not self._awaiting_ack:
            self._motion_seen = False
            if self.phase in {"trial_outbound", "validation_outbound"}:
                self._send_next_outbound()

    def _send_home(self) -> ActionOutcome:
        try:
            self._send_line(b"$H\n")
        except RuntimeError as exc:
            return self._fail(f"Homing command was not sent — {exc}")
        self.state = TravelCalibrationState.HOMING
        self._home_ack = False
        self._awaiting_ack = False
        self._motion_seen = False
        return ActionOutcome(True, "Travel calibration started with a fresh home")

    def _after_home(self) -> None:
        if self._mode == "baseline":
            self.state = TravelCalibrationState.BASELINE
            self.phase = "baseline_return"
            self._send_return(self._return_search_distance())
            return
        if self._mode == "search":
            self.state = TravelCalibrationState.SEARCHING
            self.phase = "trial_outbound"
            configured = self.session.profile.travel_for(self.axis)
            if self._candidate <= 0:
                self._candidate = max(self.options.increment_mm, configured - self.options.increment_mm)
            self._remaining = self._candidate
            self._send_next_outbound()
            return
        if self._mode == "complete":
            self.state = TravelCalibrationState.READY
            self.phase = "awaiting_acceptance"
            self.progress = 100.0
            self._notice(self.status_text)
            return
        self.state = TravelCalibrationState.VALIDATING
        self.phase = "validation_outbound"
        self._candidate = self.results[self.axis] + max(1.0, self.options.stall_threshold_mm * 2.0)
        self._remaining = self._candidate
        self._send_next_outbound()

    def _send_next_outbound(self) -> None:
        if self._remaining <= 0.001:
            self.phase = "validation_return" if self._mode == "validation" else "trial_return"
            distance = (self._candidate + self._return_search_distance())
            self._send_return(distance)
            return
        distance = min(self.options.increment_mm, self._remaining)
        self._remaining -= distance
        self._send_axis_jog(self._away_sign() * distance, self.options.search_feed)

    def _send_return(self, distance: float) -> None:
        self._return_trigger = None
        self._return_pin_released_seen = False
        self._send_axis_jog(-self._away_sign() * distance, self.options.return_feed)

    def _send_axis_jog(self, distance: float, feed: float) -> None:
        try:
            self._send_line(make_jog(self.axis, distance, feed))
        except (RuntimeError, ValueError) as exc:
            self._fail(f"{self.axis} calibration motion was not sent — {exc}")
            return
        self._awaiting_ack = True
        self._motion_seen = False

    def _finish_return(self) -> None:
        assert self._return_trigger is not None
        trigger = self._return_trigger
        if self.phase == "baseline_return":
            self.baselines[self.axis] = trigger
            self._mode = "search"
            self.phase = "home_after_baseline"
            self._send_home()
            return
        baseline = self.baselines[self.axis]
        lost = max(0.0, self._away_sign() * (trigger - baseline))
        if self.phase == "validation_return":
            measured = self._candidate - lost
            if lost < self.options.stall_threshold_mm or abs(measured - self.results[self.axis]) > self.options.validation_tolerance_mm:
                self._fail(f"{self.axis} validation measured {measured:.2f} mm after {lost:.2f} mm lost travel; expected {self.results[self.axis]:.2f} mm")
                return
            self.axis_index += 1
            if self.axis_index >= 3:
                self._mode = "complete"
                self.phase = "final_home"
                self._send_home()
                return
            self.axis = "XYZ"[self.axis_index]
            self._mode = "validation"
            self.phase = "home_before_validation"
            self._send_home()
            return
        if lost >= self.options.stall_threshold_mm:
            measured = self._candidate - lost
            if measured <= self.options.increment_mm:
                self._fail(f"{self.axis} measured travel {measured:.2f} mm is implausibly small")
                return
            self.samples[self.axis].append(measured)
            if len(self.samples[self.axis]) < 2:
                self.phase = "repeat_detection_home"
                self._send_home()
                return
            spread = max(self.samples[self.axis]) - min(self.samples[self.axis])
            if spread > self.options.validation_tolerance_mm:
                self._fail(f"{self.axis} stall measurements differ by {spread:.2f} mm")
                return
            self.results[self.axis] = round(float(median(self.samples[self.axis])), 3)
            self.axis_index += 1
            self.progress = self.axis_index / 6.0 * 100.0
            if self.axis_index >= 3:
                self.axis_index = 0
                self.axis = "X"
                self._mode = "validation"
            else:
                self.axis = "XYZ"[self.axis_index]
                self._mode = "baseline"
                self._candidate = 0.0
            self.phase = "home_next_axis"
            self._send_home()
            return
        maximum = self.session.profile.travel_for(self.axis) + self.options.max_overshoot_mm
        self._candidate += self.options.increment_mm
        if self._candidate > maximum + 0.001:
            self._fail(f"No repeatable {self.axis} end stop was detected by {maximum:.1f} mm")
            return
        self.progress = (self.axis_index + min(0.9, self._candidate / maximum)) / 6.0 * 100.0
        self.phase = "home_before_next_trial"
        self._send_home()

    def _away_sign(self) -> float:
        assert self.definition is not None
        return 1.0 if self.definition.axes[self.axis].switch_end.value == "min" else -1.0

    def _return_search_distance(self) -> float:
        return max(self.options.switch_search_mm, self._settings.get(27, 0.0) + 2.0)

    def _fail(self, reason: str) -> ActionOutcome:
        try:
            self._send_realtime(REALTIME_JOG_CANCEL)
        except RuntimeError:
            pass
        self.failure_reason = reason
        self.state = TravelCalibrationState.FAILED
        self.phase = "failed"
        self.session.invalidate_reference(f"Travel calibration failed: {reason}")
        self._notice(self.status_text)
        return ActionOutcome(False, self.status_text)


__all__ = ["TravelCalibrationOptions", "TravelCalibrationService", "TravelCalibrationState"]
