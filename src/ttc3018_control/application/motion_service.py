"""Qt-independent guarded motion workflows for the TTC 3018."""

from __future__ import annotations

import math
from typing import Callable

from ..grbl import Position, REALTIME_JOG_CANCEL, GrblStatus, make_jog
from .machine_session import ActionOutcome, MachineSession


class MotionService:
    """Own jog sequencing, acknowledgements, and motion-only transient state."""

    # Never issue a live-jog command for the entire remaining axis travel.
    # Release/cancel is still the normal stop path, but bounding each command
    # makes a short click safe even if the release event or realtime cancel is
    # delayed or lost.
    LIVE_JOG_CHUNK_MM = 1.0

    def __init__(
        self,
        session: MachineSession,
        send_line: Callable[[bytes], None],
        send_realtime: Callable[[bytes], None],
        on_notice: Callable[[str], None] | None = None,
        on_change: Callable[[], None] | None = None,
        on_position_complete: Callable[[], None] | None = None,
    ) -> None:
        self.session = session
        self._send_line = send_line
        self._send_realtime = send_realtime
        self._on_notice = on_notice or (lambda _message: None)
        self._on_change = on_change or (lambda: None)
        self._on_position_complete = on_position_complete or (lambda: None)
        self._pending_acks = 0
        self._position_queue: list[tuple[str, float, float]] = []
        self._position_move_active = False
        self._live_jog_axis: str | None = None
        self._live_jog_axis_last: str | None = None
        self._live_jog_direction = 0.0
        self._live_jog_first_distance: float | None = None
        self._live_jog_position: Position | None = None
        self._live_jog_feed = 500.0
        self._live_jog_motion_seen = False
        self._live_jog_stop_pending = False
        self._live_jog_alignment_pending = False
        self._phase = "idle"

    @property
    def pending_acks(self) -> int:
        return self._pending_acks

    @property
    def position_move_active(self) -> bool:
        return self._position_move_active

    @property
    def live_jog_axis(self) -> str | None:
        return self._live_jog_axis

    @property
    def live_jog_stop_pending(self) -> bool:
        return self._live_jog_stop_pending

    @property
    def live_jog_alignment_pending(self) -> bool:
        return self._live_jog_alignment_pending

    @property
    def busy(self) -> bool:
        return bool(
            self._pending_acks
            or self._position_move_active
            or self._live_jog_axis is not None
            or self._live_jog_stop_pending
            or self._live_jog_alignment_pending
        )

    @property
    def phase(self) -> str:
        return self._phase

    def jog(self, axis: str, distance: float, feed: float) -> ActionOutcome:
        if not self.session.can_move:
            return ActionOutcome(False, "GRBL is not Idle with a machine position.")
        outcome = self.session.check_jog(axis, distance)
        if not outcome.accepted:
            return outcome
        try:
            self._send_line(make_jog(axis, distance, feed))
        except (RuntimeError, ValueError) as exc:
            return ActionOutcome(False, f"Jog not sent — {exc}")
        self._pending_acks += 1
        self._changed()
        return ActionOutcome(True, outcome.message)

    def start_live_jog(self, axis: str, direction: float, allow_unreferenced: bool, feed: float) -> ActionOutcome:
        axis = axis.upper()
        direction = 1.0 if direction > 0 else -1.0
        if axis not in {"X", "Y", "Z"}:
            return ActionOutcome(False, "Live jog ignored — axis must be X, Y, or Z")
        if self._live_jog_axis is not None:
            return ActionOutcome(False, "Live jog is already active")
        if not self.session.can_move:
            return ActionOutcome(False, "Live jog ignored — machine is not ready or GRBL is not Idle")
        if not self.session.envelope.trusted and not allow_unreferenced:
            return ActionOutcome(False, "Unreferenced jogging requires operator acknowledgement")
        position = self.session.virtual_position if self.session.envelope.trusted else self.session.machine_position
        if position is None:
            return ActionOutcome(False, "Live jog ignored — current position is unavailable")
        current = getattr(position, axis.lower())
        if self.session.envelope.trusted:
            distance = self.session.profile.travel_for(axis) - current if direction > 0 else -current
        else:
            distance = direction * self.session.profile.travel_for(axis)
        if abs(distance) <= 0.001:
            return ActionOutcome(False, f"Live jog ignored — already at the {axis} travel limit")
        self._live_jog_axis = axis
        self._live_jog_axis_last = axis
        self._live_jog_direction = direction
        self._live_jog_first_distance = distance
        self._live_jog_position = position
        self._live_jog_feed = feed
        self._live_jog_motion_seen = False
        self._live_jog_stop_pending = False
        self._live_jog_alignment_pending = False
        self._send_next_live_jog(feed)
        self._changed()
        return ActionOutcome(True, "Live jog started")

    def stop_live_jog(self) -> ActionOutcome:
        if self._live_jog_axis is None:
            return ActionOutcome(True, "Live jog is not active")
        self._live_jog_axis_last = self._live_jog_axis
        self._live_jog_axis = None
        self._live_jog_first_distance = None
        self._live_jog_stop_pending = True
        try:
            self._send_realtime(REALTIME_JOG_CANCEL)
        except RuntimeError as exc:
            self._clear_live_jog()
            return ActionOutcome(False, f"Live jog stop failed — {exc}")
        self._changed()
        return ActionOutcome(True, "Live jog stop requested")

    def move_to(self, target: Position, feed: float) -> ActionOutcome:
        if not self.session.can_move:
            return ActionOutcome(False, "Position move ignored — machine is not ready")
        if not 0 < feed <= 1500:
            return ActionOutcome(False, "Jog feed must be between 0 and 1500 mm/min")
        outcome, moves = self.session.plan_move_to(target)
        if not outcome.accepted:
            return outcome
        self._position_queue = [(axis, distance, feed) for axis, distance in moves]
        self._position_move_active = bool(self._position_queue)
        self._phase = "queued"
        self._send_next_position_move()
        self._changed()
        return ActionOutcome(True, outcome.message)

    def return_to_work_zero(
        self,
        feed: float,
        persisted_work_offset: Position | None = None,
    ) -> ActionOutcome:
        outcome, moves = self.session.plan_return_to_work_zero(persisted_work_offset)
        if not outcome.accepted:
            return outcome
        self._position_queue = [(axis, distance, feed) for axis, distance in moves]
        self._position_move_active = bool(self._position_queue)
        self._phase = "queued"
        self._send_next_position_move()
        self._changed()
        return ActionOutcome(True, f"{outcome.message.rstrip('.')} via safe Z")

    def return_to_reference(self, feed: float) -> ActionOutcome:
        return self.move_to(Position(0.0, 0.0, 0.0), feed)

    def observe_status(self, status: GrblStatus) -> None:
        if self._live_jog_axis is not None:
            if not status.can_jog:
                self._live_jog_motion_seen = True
            elif self._live_jog_motion_seen and not self._pending_acks:
                axis = self._live_jog_axis
                self._clear_live_jog()
                self._on_notice(f"Live jog stopped at the {axis} travel limit")
        if self._live_jog_stop_pending and status.can_jog and not self._pending_acks:
            self._finish_live_jog_stop()

    def handle_response(self, response: str, feed: float) -> bool:
        text = response.strip()
        lowered = text.lower()
        if not self._pending_acks or not (lowered == "ok" or lowered.startswith("error:") or lowered.startswith("alarm:")):
            return False
        self._pending_acks -= 1
        if lowered == "ok":
            if self._position_move_active:
                self._send_next_position_move()
            elif self._live_jog_axis is not None:
                self._send_next_live_jog(feed)
            elif self._live_jog_alignment_pending:
                self._clear_live_jog()
                self._on_notice("Live jog stopped at a whole millimeter")
        elif self._position_move_active:
            self._position_queue = []
            self._position_move_active = False
            self._phase = "failed"
            self._on_notice(f"Position move stopped — GRBL replied: {text}")
        elif self._live_jog_axis is not None:
            self._clear_live_jog()
            self._on_notice(f"Live jog stopped — GRBL replied: {text}")
        elif self._live_jog_alignment_pending:
            self._clear_live_jog()
            self._on_notice(f"Whole-millimeter stop correction rejected — {text}")
        self._changed()
        return True

    def cancel(self) -> None:
        self._clear_live_jog()
        self._position_queue = []
        self._position_move_active = False
        self._pending_acks = 0
        self._phase = "idle"
        self._changed()

    def reset(self) -> None:
        self.cancel()

    def _send_next_live_jog(self, feed: float) -> None:
        if self._live_jog_axis is None or self._live_jog_stop_pending or self._live_jog_alignment_pending:
            return
        axis = self._live_jog_axis
        distance = self._live_jog_first_distance
        if distance is None:
            return
        self._live_jog_first_distance = None
        current = self._live_jog_position
        if current is None:
            self._clear_live_jog()
            return
        direction = 1.0 if distance > 0 else -1.0
        chunk = direction * min(abs(distance), self.LIVE_JOG_CHUNK_MM)
        remaining = distance - chunk
        self._live_jog_first_distance = remaining if abs(remaining) > 0.001 else None
        proposed = self._position_with_axis_delta(current, axis, chunk)
        if self.session.envelope.trusted:
            maximum = self.session.profile.travel_for(axis)
            proposed_value = getattr(proposed, axis.lower())
            if proposed_value < -0.001 or proposed_value > maximum + 0.001:
                self._clear_live_jog()
                self._on_notice(f"Live jog stopped at the {axis} travel limit")
                return
        try:
            self._send_line(make_jog(axis, chunk, feed))
        except (RuntimeError, ValueError) as exc:
            self._clear_live_jog()
            self._on_notice(f"Live jog stopped — {exc}")
            return
        self._pending_acks += 1
        self._live_jog_position = proposed

        # The final bounded segment has reached the trusted travel limit. It
        # remains active until its acknowledgement so a held button still has
        # a deterministic end state, but no further segment will be emitted.
        if self._live_jog_first_distance is None and abs(distance) <= self.LIVE_JOG_CHUNK_MM + 0.001:
            self._live_jog_first_distance = None

    def _finish_live_jog_stop(self) -> None:
        if not self._live_jog_stop_pending or self._pending_acks:
            return
        position = self.session.virtual_position if self.session.envelope.trusted else self.session.machine_position
        if position is None:
            self._clear_live_jog()
            self._on_notice("Live jog stopped; final position was unavailable")
            return
        axis = self._live_jog_axis_last or "X"
        current = getattr(position, axis.lower())
        # Snap from the settled position without ever reversing the operator's
        # requested direction. Status reports can lag continuous motion, so a
        # nearest-coordinate correction could otherwise move backward after
        # release. The directional snap is deterministic and below one mm.
        if self._live_jog_direction > 0:
            target = math.ceil(current - 0.001)
        else:
            target = math.floor(current + 0.001)
        distance = target - current
        if abs(distance) <= 0.001:
            self._clear_live_jog()
            self._on_notice("Live jog stopped at a whole millimeter without reversing")
            return
        if self.session.envelope.trusted:
            maximum = self.session.profile.travel_for(axis)
            if target < -0.001 or target > maximum + 0.001:
                self._clear_live_jog()
                self._on_notice("Live jog stopped; nearest whole-millimeter position is outside the travel envelope")
                return
        try:
            self._send_line(make_jog(axis, distance, self._live_jog_feed))
        except (RuntimeError, ValueError) as exc:
            self._clear_live_jog()
            self._on_notice(f"Whole-millimeter stop correction failed — {exc}")
            return
        self._pending_acks += 1
        self._live_jog_stop_pending = False
        self._live_jog_alignment_pending = True

    def _send_next_position_move(self) -> None:
        if not self._position_move_active or self._pending_acks:
            return
        if not self._position_queue:
            self._position_move_active = False
            self._phase = "complete"
            self._on_notice("Position move complete")
            self._on_position_complete()
            return
        axis, distance, feed = self._position_queue.pop(0)
        if axis == "Z":
            self._phase = "raising_safe_z" if distance > 0 else "lowering_z"
        elif axis == "X":
            self._phase = "moving_x"
        else:
            self._phase = "moving_y"
        try:
            self._send_line(make_jog(axis, distance, feed))
        except (RuntimeError, ValueError) as exc:
            self._position_queue = []
            self._position_move_active = False
            self._phase = "failed"
            self._on_notice(f"Position move stopped — {exc}")
            return
        self._pending_acks += 1

    def _clear_live_jog(self) -> None:
        if self._live_jog_axis is not None:
            self._live_jog_axis_last = self._live_jog_axis
        self._live_jog_axis = None
        self._live_jog_direction = 0.0
        self._live_jog_first_distance = None
        self._live_jog_position = None
        self._live_jog_feed = 500.0
        self._live_jog_motion_seen = False
        self._live_jog_stop_pending = False
        self._live_jog_alignment_pending = False

    @staticmethod
    def _position_with_axis_delta(position: Position, axis: str, distance: float) -> Position:
        values = {"X": position.x, "Y": position.y, "Z": position.z}
        values[axis] += distance
        return Position(values["X"], values["Y"], values["Z"])

    def _changed(self) -> None:
        self._on_change()

    def bind_callbacks(
        self,
        *,
        on_notice: Callable[[str], None] | None = None,
        on_change: Callable[[], None] | None = None,
        on_position_complete: Callable[[], None] | None = None,
    ) -> None:
        """Attach a presentation/event adapter without changing motion rules."""
        if on_notice is not None:
            self._on_notice = on_notice
        if on_change is not None:
            self._on_change = on_change
        if on_position_complete is not None:
            self._on_position_complete = on_position_complete
