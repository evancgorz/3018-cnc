from __future__ import annotations

from dataclasses import dataclass, field

from ..grbl import GrblStatus, Position
from ..machine_state import (
    MachineProfile,
    VirtualEnvelope,
    plan_safe_position_jogs,
    work_zero_virtual_target,
)


@dataclass(frozen=True)
class ActionOutcome:
    """An intention-level outcome suitable for any presentation layer."""

    accepted: bool
    message: str


@dataclass
class MachineSession:
    """Own the trust state that sits between GRBL reports and a UI.

    This service deliberately does not know about serial/TCP transports or Qt/
    Tkinter widgets. Callers remain responsible for actually transmitting a
    validated command only after receiving an accepted outcome.
    """

    profile: MachineProfile = field(default_factory=MachineProfile)
    envelope: VirtualEnvelope = field(default_factory=VirtualEnvelope)
    status: GrblStatus | None = None
    work_offset: Position | None = None
    work_zero_confirmed: bool = False
    awaiting_work_zero_report: bool = False

    @property
    def machine_position(self) -> Position | None:
        return self.status.machine_position if self.status else None

    @property
    def can_move(self) -> bool:
        return self.status is not None and self.status.can_jog and self.machine_position is not None

    @property
    def virtual_position(self) -> Position | None:
        position = self.machine_position
        return self.envelope.relative_position(position) if position else None

    def update_status(self, status: GrblStatus) -> None:
        """Apply a fresh controller report and confirm requested XYZ work zero."""
        self.status = status
        if status.work_offset is not None:
            self.work_offset = status.work_offset
            if self.awaiting_work_zero_report:
                self.work_zero_confirmed = True
                self.awaiting_work_zero_report = False

    def establish_reference(self) -> ActionOutcome:
        if not self.can_move:
            return ActionOutcome(False, "Connect and wait for GRBL Idle with a machine position.")
        try:
            self.profile.validate()
        except ValueError as exc:
            return ActionOutcome(False, str(exc))
        assert self.machine_position is not None
        self.envelope.establish(self.machine_position, self.profile)
        self.invalidate_work_zero()
        return ActionOutcome(True, "Virtual machine reference established at the current position.")

    def invalidate_reference(self, reason: str) -> None:
        self.envelope.invalidate(reason)
        self.invalidate_work_zero()

    def request_work_zero_confirmation(self, axes: str) -> ActionOutcome:
        normalized = "".join(axis for axis in "XYZ" if axis in axes.upper())
        if not normalized:
            return ActionOutcome(False, "Select at least one work-zero axis.")
        if self.status is None or not self.status.can_jog:
            return ActionOutcome(False, "GRBL must be Idle before changing work zero.")
        if normalized == "XYZ":
            self.work_zero_confirmed = False
            self.awaiting_work_zero_report = True
            return ActionOutcome(True, "Waiting for GRBL to report the updated XYZ work offset.")
        return ActionOutcome(True, f"{normalized} work zero requested.")

    def invalidate_work_zero(self) -> None:
        self.work_zero_confirmed = False
        self.awaiting_work_zero_report = False

    def check_jog(self, axis: str, distance_mm: float) -> ActionOutcome:
        if not self.can_move:
            return ActionOutcome(False, "GRBL is not Idle with a machine position.")
        position = self.machine_position
        assert position is not None
        if not self.envelope.trusted:
            return ActionOutcome(True, "Unreferenced jog accepted; virtual limits are inactive.")
        try:
            allowed, message = self.envelope.check_jog(axis, distance_mm, position, self.profile)
        except ValueError as exc:
            return ActionOutcome(False, str(exc))
        return ActionOutcome(allowed, message)

    def plan_move_to(self, target: Position) -> tuple[ActionOutcome, list[tuple[str, float]]]:
        if not self.can_move:
            return ActionOutcome(False, "GRBL is not Idle with a machine position."), []
        if not self.envelope.trusted:
            return ActionOutcome(False, "Establish the virtual machine reference first."), []
        current = self.virtual_position
        assert current is not None
        try:
            moves = plan_safe_position_jogs(current, target, self.profile)
        except ValueError as exc:
            return ActionOutcome(False, str(exc)), []
        return ActionOutcome(True, "Position move accepted."), moves

    def plan_return_to_work_zero(self) -> tuple[ActionOutcome, list[tuple[str, float]]]:
        if not self.work_zero_confirmed or self.work_offset is None:
            return ActionOutcome(False, "Work zero is not confirmed by a fresh GRBL report."), []
        if not self.envelope.trusted or self.envelope.reference is None:
            return ActionOutcome(False, "The virtual machine reference is not trusted."), []
        target = work_zero_virtual_target(self.envelope.reference, self.work_offset)
        return self.plan_move_to(target)
