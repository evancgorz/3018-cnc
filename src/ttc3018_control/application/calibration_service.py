"""Application-owned automatic XYZ calibration over ordinary GRBL traffic."""

from __future__ import annotations

from typing import Callable

from ..grbl import GrblStatus, Position, parse_probe_report
from ..simulation.safety import (
    AutoXYZCalibrationWorkflow, CalibrationCommissioningRecord,
    CalibrationFailure, CalibrationPlateDefinition, CalibrationState, PlateContact,
)
from .machine_session import ActionOutcome


class AutoXYZCalibrationService:
    """Serialize a commissioned plate plan through send/response/status APIs.

    The service never reaches into a controller or plant.  It owns only the
    transaction state and emits ordinary G-code through the callback supplied
    by :class:`ApplicationController`.
    """

    def __init__(self, send_manual: Callable[[bytes], None], *, on_notice: Callable[[str], None] | None = None,
                 require_idle_boundary: bool = True) -> None:
        self._send_manual = send_manual
        self._on_notice = on_notice or (lambda _message: None)
        self.workflow: AutoXYZCalibrationWorkflow | None = None
        self._index = 0
        self._awaiting_ack = False
        self._awaiting_probe = False
        self._probe_report_seen = False
        self._z_report_seen = False
        self._wco_fresh = False
        self._envelope = (0.0, 0.0, 0.0)
        self._z_queued = False
        self._z_contact: float | None = None
        self._work_offset_pending = False
        self._expected_work_offset: Position | None = None
        self._require_idle_boundary = bool(require_idle_boundary)
        self._awaiting_idle = False
        self.last_status: GrblStatus | None = None

    @property
    def state(self) -> CalibrationState:
        return self.workflow.state if self.workflow is not None else CalibrationState.IDLE

    @property
    def active(self) -> bool:
        return self.state not in {CalibrationState.IDLE, CalibrationState.COMPLETE, CalibrationState.FAILED}

    @property
    def failure(self) -> CalibrationFailure:
        return self.workflow.failure_code if self.workflow is not None else CalibrationFailure.NONE

    @property
    def status_text(self) -> str:
        if self.workflow is None:
            return "Auto XYZ calibration idle"
        if self.state is CalibrationState.FAILED:
            return f"Auto XYZ calibration failed — {self.workflow.failure_reason}"
        return f"Auto XYZ calibration {self.state.value}"

    @property
    def awaiting_ack(self) -> bool:
        return self._awaiting_ack

    @property
    def work_offset_confirmation_pending(self) -> bool:
        return self._work_offset_pending

    @property
    def expected_work_offset(self) -> Position | None:
        return self._expected_work_offset

    def start(self, *, seed: tuple[float, float, float], definition: CalibrationPlateDefinition,
              commissioning_record: CalibrationCommissioningRecord | None,
              reference_trusted: bool, controller_idle: bool, spindle_rpm: float,
              envelope: tuple[float, float, float]) -> ActionOutcome:
        if self.active:
            return ActionOutcome(False, "Auto XYZ calibration is already active")
        workflow = AutoXYZCalibrationWorkflow(definition)
        if not workflow.start(seed=seed, reference_trusted=reference_trusted,
                             controller_idle=controller_idle, spindle_rpm=spindle_rpm,
                             envelope=envelope, commissioning_record=commissioning_record):
            self.workflow = workflow
            self._on_notice(workflow.failure_reason)
            return ActionOutcome(False, workflow.failure_reason)
        self.workflow = workflow
        self._index = 0
        self._envelope = tuple(float(value) for value in envelope)
        self._wco_fresh = False
        self._z_queued = False
        self._z_contact = None
        self._awaiting_idle = False
        self._work_offset_pending = False
        self._expected_work_offset = None
        self.last_status = None
        outcome = self._send_next()
        if not outcome.accepted:
            return outcome
        return ActionOutcome(True, "Auto XYZ calibration started over the ordinary GRBL boundary")

    def handle_response(self, response: str) -> bool:
        if self.workflow is None or not self.active:
            return False
        text = response.strip()
        lowered = text.lower()
        if lowered.startswith("error:") or lowered.startswith("alarm:"):
            self._fail(f"Calibration failed — GRBL replied: {text}", CalibrationFailure.COLLISION if lowered.startswith("alarm:") else CalibrationFailure.NONE)
            return True
        report = parse_probe_report(text)
        if report is not None:
            if not self._awaiting_probe or self._probe_report_seen:
                self._fail("Calibration received an unexpected or duplicate probe report")
                return True
            position, success = report
            if not success:
                self._fail("Calibration probe reported no contact", CalibrationFailure.NO_CONTACT)
                return True
            self._probe_report_seen = True
            if self._is_z_probe():
                self._z_report_seen = True
                if not self._wco_fresh:
                    self._fail("fresh WCO and in-envelope Z touch are required", CalibrationFailure.STALE_WCO)
                else:
                    self._z_contact = position.z
                    self._expected_work_offset = Position(position.x, position.y, position.z)
                    # After G10 L20 the work origin is at the touch point;
                    # retract by the machine-safe delta, not a second absolute
                    # safe-Z distance that could exceed travel.
                    if self.workflow.commands and self.workflow.commands[-1].strip().upper().startswith("G0 G91 Z"):
                        delta = self.workflow.definition.safe_z - position.z
                        self.workflow.commands[-1] = f"G91 G0 Z{delta:.3f}"
            else:
                if not self.workflow.record_contact(PlateContact(position.x, position.y, position.z)):
                    self._on_notice(self.workflow.failure_reason)
            self._maybe_advance()
            return True
        if lowered == "ok":
            if not self._awaiting_ack:
                return False
            self._awaiting_ack = False
            self._maybe_advance()
            return True
        return False

    def observe_status(self, status: GrblStatus) -> bool:
        if self.workflow is None or not self.active:
            return False
        self.last_status = status
        if status.work_offset is not None:
            self._wco_fresh = True
            expected = self._expected_work_offset
            matches = expected is None or all(
                abs(actual - target) <= 0.001
                for actual, target in zip((status.work_offset.x, status.work_offset.y, status.work_offset.z),
                                          (expected.x, expected.y, expected.z))
            )
            if self._work_offset_pending and matches:
                self._work_offset_pending = False
        if status.state in {"Alarm", "Door"}:
            self._fail(f"Calibration failed — GRBL reported {status.state}", CalibrationFailure.COLLISION)
            return True
        if self._awaiting_idle and not self._awaiting_ack and status.state == "Idle":
            self._awaiting_idle = False
            self._maybe_advance()
        return False

    def abort(self, reason: str = "Calibration cancelled") -> ActionOutcome:
        if self.workflow is None or not self.active:
            return ActionOutcome(False, "Auto XYZ calibration is not active")
        self._fail(reason)
        return ActionOutcome(True, reason)

    def reset(self) -> None:
        self.workflow = None
        self._index = 0
        self._awaiting_ack = self._awaiting_probe = False
        self._awaiting_idle = False
        self._probe_report_seen = self._z_report_seen = False
        self._wco_fresh = False
        self._z_queued = False
        self._z_contact = None
        self._work_offset_pending = False
        self._expected_work_offset = None
        self.last_status = None

    def _is_z_probe(self) -> bool:
        if self.workflow is None or self._index >= len(self.workflow.commands):
            return False
        return "G38.2 Z" in self.workflow.commands[self._index].strip().upper()

    def _maybe_advance(self) -> None:
        if self._awaiting_ack or self._awaiting_idle or (self._awaiting_probe and not self._probe_report_seen):
            return
        self._index += 1
        self._awaiting_probe = False
        self._probe_report_seen = False
        self._z_report_seen = False
        if self.workflow is not None and self.workflow.state is CalibrationState.FITTED and not self._z_queued:
            self.workflow.begin_z_touch()
            self._z_queued = True
        if self.workflow is not None and self._index >= len(self.workflow.commands):
            if self.workflow.state is CalibrationState.Z_TOUCH and self._z_contact is not None:
                if self.workflow.complete_z_touch(self._z_contact, wco_fresh=self._wco_fresh,
                                                  envelope=self._envelope):
                    self._on_notice("Auto XYZ calibration complete; fresh WCO and safe Z confirmed")
                else:
                    self._on_notice(self.workflow.failure_reason)
            return
        self._send_next()

    def _send_next(self) -> ActionOutcome:
        if self.workflow is None or self._index >= len(self.workflow.commands):
            return ActionOutcome(True, "Calibration command sequence complete")
        command = self.workflow.commands[self._index]
        try:
            self._send_manual((command.rstrip() + "\n").encode("ascii"))
        except (RuntimeError, ValueError) as exc:
            self._fail(f"Calibration command was not sent — {exc}")
            return ActionOutcome(False, self.workflow.failure_reason if self.workflow else str(exc))
        self._awaiting_ack = True
        self._awaiting_probe = "G38.2" in command.strip().upper()
        self._awaiting_idle = self._require_idle_boundary and any(token in command.strip().upper() for token in ("G0", "G1", "G2", "G3", "G38.2"))
        self._work_offset_pending = command.strip().upper().startswith("G10 L20")
        self._probe_report_seen = False
        return ActionOutcome(True, "Calibration command sent")

    def _fail(self, message: str, code: CalibrationFailure = CalibrationFailure.NONE) -> None:
        if self.workflow is not None:
            self.workflow.fail(message, code)
        self._awaiting_ack = self._awaiting_probe = False
        self._work_offset_pending = False
        self._expected_work_offset = None
        self._on_notice(message)
