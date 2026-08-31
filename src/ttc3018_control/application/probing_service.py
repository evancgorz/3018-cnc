"""Fail-closed, command-correlated probing workflows.

Probing is deliberately separate from job parsing and streaming.  A probe
transaction owns its acknowledgements and will not apply an offset until a
fresh successful PRB report has completed the requested motion.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Callable

from ..controller_adapters import ControllerAdapter
from ..grbl import GrblStatus, Position, parse_probe_report
from ..machine_state import VirtualEnvelope
from .machine_session import ActionOutcome, MachineSession


class ProbeState(StrEnum):
    IDLE = "idle"
    FAST = "fast_probe"
    RETRACT = "retract"
    WAIT_RELEASE = "wait_release"
    SLOW = "slow_probe"
    APPLY_OFFSET = "apply_offset"
    SAFE_RETRACT = "safe_retract"
    COMPLETE = "complete"
    FAILED = "failed"


@dataclass(frozen=True)
class ProbePlan:
    axis: str
    fast_distance: float
    slow_distance: float
    retract_distance: float
    safe_retract_distance: float
    fast_feed: float
    slow_feed: float
    retract_feed: float
    wcs_slot: int | None = None
    final_work_offset: Position | None = None

    def validate(self) -> None:
        if self.axis.upper() not in {"X", "Y", "Z"}:
            raise ValueError("Probe axis must be X, Y, or Z")
        if not self.fast_distance or not self.slow_distance:
            raise ValueError("Probe search distances cannot be zero")
        if self.retract_distance <= 0 or self.safe_retract_distance <= 0:
            raise ValueError("Probe retract distances must be positive")
        if not all(value > 0 for value in (self.fast_feed, self.slow_feed, self.retract_feed)):
            raise ValueError("Probe feeds must be positive")
        if self.final_work_offset is not None and self.wcs_slot is None:
            raise ValueError("A final work offset requires a WCS slot")


class ProbingService:
    def __init__(
        self,
        session: MachineSession,
        adapter: ControllerAdapter,
        send_line: Callable[[bytes], None],
        *,
        on_notice: Callable[[str], None] | None = None,
    ) -> None:
        self.session = session
        self.adapter = adapter
        self._send_line = send_line
        self._on_notice = on_notice or (lambda _message: None)
        self.state = ProbeState.IDLE
        self.plan: ProbePlan | None = None
        self.fast_report: Position | None = None
        self.slow_report: Position | None = None
        self._ack_pending = False
        self._probe_report_seen = False

    @property
    def active(self) -> bool:
        return self.state not in {ProbeState.IDLE, ProbeState.COMPLETE, ProbeState.FAILED}

    def start(self, plan: ProbePlan, *, connected: bool, spindle_off: bool) -> ActionOutcome:
        if self.active:
            return ActionOutcome(False, "A probe transaction is already active.")
        try:
            plan.validate()
        except ValueError as exc:
            return self._fail(str(exc))
        if not connected:
            return self._fail("Probing requires a connected controller.")
        if not spindle_off:
            return self._fail("Turn the spindle off before probing.")
        if not self.session.envelope.trusted:
            return self._fail("Probe the machine reference before probing the workpiece.")
        if self.session.status is None or not self.session.status.can_jog:
            return self._fail("GRBL must be Idle before probing.")
        if self.session.status.pins and "P" in self.session.status.pins.upper():
            return self._fail("The probe input must be open before probing.")
        self.plan = plan
        self.fast_report = None
        self.slow_report = None
        self._probe_report_seen = False
        try:
            self._send_line(self.adapter.probe_command(plan.axis, plan.fast_distance, plan.fast_feed))
        except (RuntimeError, ValueError) as exc:
            return self._fail(f"Probe was not sent — {exc}")
        self.state = ProbeState.FAST
        self._ack_pending = True
        return ActionOutcome(True, "Fast probe started; waiting for a fresh probe report.")

    def handle_response(self, response: str) -> bool:
        if not self.active:
            return False
        text = response.strip()
        lowered = text.lower()
        if lowered.startswith("error:") or lowered.startswith("alarm:"):
            self._fail(f"Probe failed — GRBL replied: {text}")
            return True
        report = parse_probe_report(text)
        if report is not None:
            position, success = report
            if not success or self._probe_report_seen:
                self._fail("Probe did not produce a fresh successful touch.")
                return True
            self._probe_report_seen = True
            if self.state is ProbeState.FAST:
                self.fast_report = position
                self.state = ProbeState.RETRACT
                self._ack_pending = False
                self._send_retract()
                return True
            if self.state is ProbeState.SLOW:
                self.slow_report = position
                self.state = ProbeState.APPLY_OFFSET if self.plan and self.plan.final_work_offset else ProbeState.SAFE_RETRACT
                self._ack_pending = False
                if self.state is ProbeState.APPLY_OFFSET:
                    self._send_offset()
                else:
                    self._send_safe_retract()
                return True
            return False
        if lowered == "ok":
            if not self._ack_pending:
                return True
            self._ack_pending = False
            if self.state is ProbeState.RETRACT:
                self.state = ProbeState.WAIT_RELEASE
            elif self.state is ProbeState.APPLY_OFFSET:
                self._send_safe_retract()
            elif self.state is ProbeState.SAFE_RETRACT:
                self.state = ProbeState.COMPLETE
                self._on_notice("Probe completed and the machine is at safe Z.")
            return True
        return False

    def observe_status(self, status: GrblStatus) -> bool:
        if self.state is ProbeState.WAIT_RELEASE:
            if status.state in {"Alarm", "Door"}:
                self._fail(f"Probe failed — GRBL reported {status.state}.")
                return True
            if status.can_jog and "P" not in status.pins.upper():
                assert self.plan is not None
                self._probe_report_seen = False
                try:
                    self._send_line(self.adapter.probe_command(self.plan.axis, self.plan.slow_distance, self.plan.slow_feed))
                except (RuntimeError, ValueError) as exc:
                    self._fail(f"Slow probe was not sent — {exc}")
                    return True
                self.state = ProbeState.SLOW
                self._ack_pending = True
                return True
        return False

    def cancel(self) -> None:
        self.state = ProbeState.FAILED
        self.plan = None
        self._ack_pending = False
        self._on_notice("Probe cancelled; no work offset was changed.")

    def reset(self) -> None:
        self.state = ProbeState.IDLE
        self.plan = None
        self.fast_report = None
        self.slow_report = None
        self._ack_pending = False
        self._probe_report_seen = False

    def _send_retract(self) -> None:
        assert self.plan is not None
        try:
            self._send_line(self.adapter.retract_command(self.plan.axis, self.plan.retract_distance, self.plan.retract_feed))
            self._ack_pending = True
        except (RuntimeError, ValueError) as exc:
            self._fail(f"Probe retract was not sent — {exc}")

    def _send_offset(self) -> None:
        assert self.plan is not None and self.plan.wcs_slot is not None and self.plan.final_work_offset is not None
        try:
            self._send_line(self.adapter.work_offset_command(self.plan.wcs_slot, self.plan.final_work_offset))
            self._ack_pending = True
        except (RuntimeError, ValueError) as exc:
            self._fail(f"Probe work offset was not sent — {exc}")

    def _send_safe_retract(self) -> None:
        assert self.plan is not None
        try:
            self.state = ProbeState.SAFE_RETRACT
            self._send_line(self.adapter.retract_command(self.plan.axis, self.plan.safe_retract_distance, self.plan.retract_feed))
            self._ack_pending = True
        except (RuntimeError, ValueError) as exc:
            self._fail(f"Probe safe retract was not sent — {exc}")

    def _fail(self, message: str) -> ActionOutcome:
        self.state = ProbeState.FAILED
        self._ack_pending = False
        self._on_notice(message)
        return ActionOutcome(False, message)
