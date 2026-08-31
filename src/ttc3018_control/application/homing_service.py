"""Explicit, acknowledgement-and-status-confirmed GRBL homing workflow."""

from __future__ import annotations

from enum import StrEnum
from typing import Callable

from ..grbl import GrblStatus
from ..machine_config import MachineDefinition
from .machine_session import ActionOutcome, MachineSession


class HomingState(StrEnum):
    IDLE = "idle"
    WAITING_ACK = "waiting_ack"
    WAITING_IDLE = "waiting_idle"
    COMPLETE = "complete"
    FAILED = "failed"


class HomingService:
    def __init__(self, session: MachineSession, send_line: Callable[[bytes], None], on_notice: Callable[[str], None] | None = None) -> None:
        self.session = session
        self._send_line = send_line
        self._on_notice = on_notice or (lambda _message: None)
        self.state = HomingState.IDLE
        self._acknowledged = False

    @property
    def active(self) -> bool:
        return self.state in {HomingState.WAITING_ACK, HomingState.WAITING_IDLE}

    def start(self, definition: MachineDefinition, *, connected: bool, spindle_off: bool) -> ActionOutcome:
        if self.active:
            return ActionOutcome(False, "Homing is already active.")
        if not connected:
            return self._fail("Homing requires a connected controller.")
        if not spindle_off:
            return self._fail("Turn the spindle off before homing.")
        if not definition.controller.value.startswith("grbl"):
            return self._fail("The selected controller does not support homing.")
        if any(axis.switch_mode.value == "none" for axis in definition.axes.values()):
            return self._fail("Configure and commission one homing switch for every axis first.")
        if self.session.status is None or self.session.status.state not in {"Idle", "Alarm"}:
            return self._fail("GRBL must be Idle or Alarm before homing.")
        try:
            self._send_line(b"$H\n")
        except RuntimeError as exc:
            return self._fail(f"Homing was not sent — {exc}")
        self.state = HomingState.WAITING_ACK
        self._acknowledged = False
        return ActionOutcome(True, "Homing started; waiting for GRBL acknowledgement and a fresh Idle position.")

    def handle_response(self, response: str) -> bool:
        if not self.active:
            return False
        text = response.strip().lower()
        if text.startswith("error:") or text.startswith("alarm:"):
            self._fail(f"Homing failed — GRBL replied: {response.strip()}")
            return True
        if text == "ok":
            self._acknowledged = True
            self.state = HomingState.WAITING_IDLE
            return True
        return False

    def observe_status(self, status: GrblStatus, definition: MachineDefinition) -> bool:
        if not self.active:
            return False
        if status.state in {"Alarm", "Door"}:
            self._fail(f"Homing failed — GRBL reported {status.state}.")
            return True
        if self._acknowledged and status.state == "Idle" and status.machine_position is not None:
            ends = {axis: definition.axes[axis].switch_end.value for axis in "XYZ"}
            self.session.envelope.establish_homed(status.machine_position, definition.to_profile(), ends)
            self.state = HomingState.COMPLETE
            self._on_notice("Homing complete; the machine reference is trusted for this session.")
            return True
        return False

    def reset(self, reason: str = "Homing reset") -> None:
        self.state = HomingState.IDLE
        self._acknowledged = False
        self.session.envelope.invalidate(reason)

    def _fail(self, message: str) -> ActionOutcome:
        self.state = HomingState.FAILED
        self._acknowledged = False
        self.session.envelope.invalidate(message)
        self._on_notice(message)
        return ActionOutcome(False, message)
