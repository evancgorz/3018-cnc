"""Qt-independent guarded motion workflows for the TTC 3018."""

from __future__ import annotations

import math
import time
from typing import Callable

from ..grbl import Position, REALTIME_JOG_CANCEL, GrblStatus, make_jog
from .machine_session import ActionOutcome, MachineSession


class MotionService:
    """Own jog sequencing, acknowledgements, and motion-only transient state."""

    LIVE_JOG_LEASE_SECONDS = 0.4
    LIVE_JOG_SEGMENT_SECONDS = 0.2
    LIVE_JOG_COMPLETION_TOLERANCE_MM = 0.005

    def __init__(
        self,
        session: MachineSession,
        send_line: Callable[[bytes], None],
        send_realtime: Callable[[bytes], None],
        on_notice: Callable[[str], None] | None = None,
        on_change: Callable[[], None] | None = None,
        on_position_complete: Callable[[], None] | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.session = session
        self._send_line = send_line
        self._send_realtime = send_realtime
        self._on_notice = on_notice or (lambda _message: None)
        self._on_change = on_change or (lambda: None)
        self._on_position_complete = on_position_complete or (lambda: None)
        self._clock = clock or time.monotonic
        self._pending_acks = 0
        self._position_queue: list[tuple[str, float, float]] = []
        self._position_move_active = False
        self._live_jog_axis: str | None = None
        self._live_jog_axis_last: str | None = None
        self._live_jog_direction = 0.0
        self._live_jog_motion_seen = False
        self._live_jog_stop_pending = False
        self._live_jog_lease_token: str | None = None
        self._live_jog_lease_expires_at: float | None = None
        self._live_jog_limit_distance = 0.0
        self._live_jog_start_coordinate = 0.0
        self._live_jog_planned_progress = 0.0
        self._live_jog_feed = 0.0
        self._live_jog_segment_pending_ack = False
        self._live_jog_next_segment_at = 0.0
        self._live_jog_status_generation = 0
        self._live_jog_segment_status_generation = 0
        self._live_jog_segment_ack_generation: int | None = None
        self._live_jog_segment_expected_coordinate: float | None = None
        self._live_jog_segment_completion_observed = False
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
        # Kept as a compatibility property for snapshot consumers. Live jogs
        # now stop exactly where GRBL decelerates; no alignment move follows.
        return False

    @property
    def busy(self) -> bool:
        return bool(
            self._pending_acks
            or self._position_move_active
            or self._live_jog_axis is not None
            or self._live_jog_stop_pending
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

    def start_live_jog(
        self,
        axis: str,
        direction: float,
        allow_unreferenced: bool,
        feed: float,
        *,
        lease_token: str | None = None,
    ) -> ActionOutcome:
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

        if lease_token is not None:
            if not lease_token.strip():
                return ActionOutcome(False, "Live jog ignored — lease token must not be empty")
            if self._pending_acks:
                return ActionOutcome(False, "Live jog ignored — another command is awaiting acknowledgement")
            now = self._clock()
            self._live_jog_axis = axis
            self._live_jog_axis_last = axis
            self._live_jog_direction = direction
            self._live_jog_motion_seen = False
            self._live_jog_stop_pending = False
            self._live_jog_lease_token = lease_token
            self._live_jog_lease_expires_at = now + self.LIVE_JOG_LEASE_SECONDS
            self._live_jog_limit_distance = abs(distance)
            self._live_jog_start_coordinate = current
            self._live_jog_planned_progress = 0.0
            self._live_jog_feed = feed
            self._live_jog_segment_pending_ack = False
            self._live_jog_next_segment_at = now
            if not self._send_next_live_jog_segment(now):
                self._clear_live_jog()
                return ActionOutcome(False, "Live jog not sent — command could not be queued")
            self._changed()
            return ActionOutcome(True, "Live jog started")

        # The no-token path remains for isolated legacy callers. Production
        # dispatchers require a press-scoped lease and use short segments below.
        self._live_jog_axis = axis
        self._live_jog_axis_last = axis
        self._live_jog_direction = direction
        self._live_jog_motion_seen = False
        self._live_jog_stop_pending = False
        try:
            # One envelope-bounded GRBL jog stays smooth until the operator
            # releases the control. GRBL's realtime jog cancel is the sole
            # stop path; no queued pulses or post-release correction follow.
            self._send_line(make_jog(axis, distance, feed))
        except (RuntimeError, ValueError) as exc:
            self._clear_live_jog()
            return ActionOutcome(False, f"Live jog not sent — {exc}")
        self._pending_acks += 1
        self._changed()
        return ActionOutcome(True, "Live jog started")

    def renew_live_jog(self, token: str, now: float | None = None) -> bool:
        """Renew only the currently held, unexpired press lease."""
        tick = self._now(now)
        if self._live_jog_lease_expires_at is not None and tick >= self._live_jog_lease_expires_at:
            self._expire_live_jog()
            return False
        if (
            not token
            or token != self._live_jog_lease_token
            or self._live_jog_axis is None
            or self._live_jog_lease_expires_at is None
        ):
            return False
        self._live_jog_lease_expires_at = tick + self.LIVE_JOG_LEASE_SECONDS
        return True

    def poll_live_jog(self, now: float | None = None) -> None:
        """Expire unrenewed leases and pace the next bounded jog segment."""
        tick = self._now(now)
        if self._live_jog_lease_token is None or self._live_jog_axis is None:
            return
        if self._live_jog_lease_expires_at is None or tick >= self._live_jog_lease_expires_at:
            self._expire_live_jog()
            return
        status = self.session.status
        if status is None or status.state not in {"Idle", "Jog"}:
            self._abort_leased_jog("Live jog stopped — machine state changed", send_cancel=True)
            return
        if (
            self._live_jog_segment_pending_ack
            or self._pending_acks
            or not self._live_jog_segment_completion_observed
            or tick < self._live_jog_next_segment_at
        ):
            return
        if self._remaining_live_jog_distance() <= 2 * self.LIVE_JOG_COMPLETION_TOLERANCE_MM:
            axis = self._live_jog_axis
            self._clear_live_jog()
            self._on_notice(f"Live jog stopped at the {axis} travel limit")
            self._changed()
            return
        if not self._send_next_live_jog_segment(tick):
            self._abort_leased_jog("Live jog stopped — next segment could not be queued", send_cancel=True)

    def stop_live_jog(self, lease_token: str | None = None) -> ActionOutcome:
        if (
            self._live_jog_lease_token is not None
            and lease_token is not None
            and lease_token != self._live_jog_lease_token
        ):
            return ActionOutcome(False, "Live jog stop ignored — lease token does not match")
        if self._live_jog_axis is None and not self._live_jog_stop_pending:
            return ActionOutcome(True, "Live jog is not active")
        if self._live_jog_axis is not None:
            self._live_jog_axis_last = self._live_jog_axis
            self._live_jog_axis = None
        # Invalidate before writing realtime cancel. A racing poll or stale
        # heartbeat cannot enqueue another segment after release.
        self._invalidate_live_jog_lease()
        self._live_jog_segment_pending_ack = False
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
        self._live_jog_status_generation += 1
        if self._live_jog_lease_token is not None and self._live_jog_axis is not None:
            if status.state not in {"Idle", "Jog"}:
                self._abort_leased_jog("Live jog stopped — machine state changed", send_cancel=True)
                return
            self._observe_leased_jog_position(status)
            if (
                not self._live_jog_segment_pending_ack
                and self._live_jog_segment_ack_generation is not None
                and self._live_jog_status_generation > self._live_jog_segment_status_generation
                and self._live_jog_status_generation > self._live_jog_segment_ack_generation
                and status.state == "Idle"
                and self._live_jog_segment_at_expected_position(status)
            ):
                self._live_jog_segment_completion_observed = True
            if (
                status.state == "Idle"
                and self._live_jog_segment_completion_observed
                and self._remaining_live_jog_distance() <= 2 * self.LIVE_JOG_COMPLETION_TOLERANCE_MM
                and not self._live_jog_segment_pending_ack
            ):
                axis = self._live_jog_axis
                self._clear_live_jog()
                self._on_notice(f"Live jog stopped at the {axis} travel limit")
                self._changed()
                return
            if self._live_jog_stop_pending and status.can_jog and not self._pending_acks:
                self._finish_live_jog_stop()
            return
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
        is_ack = lowered == "ok" or lowered.startswith("error:") or lowered.startswith("alarm:")
        if not is_ack:
            return False
        if not self._pending_acks:
            if lowered.startswith("alarm:") and self._live_jog_lease_token is not None:
                self._abort_leased_jog(f"Live jog stopped — GRBL replied: {text}", send_cancel=True)
                return True
            return False
        self._pending_acks -= 1
        if lowered == "ok":
            if self._position_move_active:
                self._send_next_position_move()
            if self._live_jog_lease_token is not None and self._live_jog_segment_pending_ack:
                self._live_jog_segment_pending_ack = False
                self._live_jog_segment_ack_generation = self._live_jog_status_generation
                self._live_jog_segment_completion_observed = False
        elif self._live_jog_lease_token is not None and self._live_jog_axis is not None:
            self._abort_leased_jog(f"Live jog stopped — GRBL replied: {text}", send_cancel=True)
        elif self._position_move_active:
            self._position_queue = []
            self._position_move_active = False
            self._phase = "failed"
            self._on_notice(f"Position move stopped — GRBL replied: {text}")
        elif self._live_jog_axis is not None:
            self._clear_live_jog()
            self._on_notice(f"Live jog stopped — GRBL replied: {text}")
        self._changed()
        return True

    def cancel(self) -> None:
        if self._live_jog_lease_token is not None and self._live_jog_axis is not None:
            self._invalidate_live_jog_lease()
            self._best_effort_jog_cancel()
        self._clear_live_jog()
        self._position_queue = []
        self._position_move_active = False
        self._pending_acks = 0
        self._phase = "idle"
        self._changed()

    def reset(self) -> None:
        self.cancel()

    def _finish_live_jog_stop(self) -> None:
        if not self._live_jog_stop_pending or self._pending_acks:
            return
        self._clear_live_jog()
        self._on_notice("Jog stopped")

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
        self._live_jog_motion_seen = False
        self._live_jog_stop_pending = False
        self._invalidate_live_jog_lease()
        self._live_jog_limit_distance = 0.0
        self._live_jog_start_coordinate = 0.0
        self._live_jog_planned_progress = 0.0
        self._live_jog_feed = 0.0
        self._live_jog_segment_pending_ack = False
        self._live_jog_next_segment_at = 0.0
        self._live_jog_segment_status_generation = self._live_jog_status_generation
        self._live_jog_segment_ack_generation = None
        self._live_jog_segment_expected_coordinate = None
        self._live_jog_segment_completion_observed = False

    def _send_next_live_jog_segment(self, now: float) -> bool:
        axis = self._live_jog_axis
        if (
            axis is None
            or self._live_jog_lease_token is None
            or self._live_jog_segment_pending_ack
            or self._pending_acks
        ):
            return False
        remaining = self._remaining_live_jog_distance()
        if remaining <= 0.001 or not 0 < self._live_jog_feed <= 1500:
            return False
        distance = min(remaining, self._live_jog_feed * self.LIVE_JOG_SEGMENT_SECONDS / 60.0)
        if distance <= 2 * self.LIVE_JOG_COMPLETION_TOLERANCE_MM:
            return False
        signed_distance = self._live_jog_direction * distance
        base_progress = max(
            self._live_jog_planned_progress,
            self._observed_live_jog_progress(),
        )
        next_progress = base_progress + distance
        duration = distance / self._live_jog_feed * 60.0
        self._live_jog_planned_progress = next_progress
        self._live_jog_segment_pending_ack = True
        self._live_jog_segment_status_generation = self._live_jog_status_generation
        self._live_jog_segment_ack_generation = None
        self._live_jog_segment_expected_coordinate = (
            self._live_jog_start_coordinate + self._live_jog_direction * next_progress
        )
        self._live_jog_segment_completion_observed = False
        # An ACK only confirms acceptance. A fresh Idle report at this endpoint
        # is also required before the next segment can be sent.
        self._live_jog_next_segment_at = now + duration
        self._pending_acks += 1
        try:
            self._send_line(make_jog(axis, signed_distance, self._live_jog_feed))
        except (RuntimeError, ValueError):
            if self._live_jog_segment_pending_ack:
                self._pending_acks -= 1
            self._live_jog_planned_progress = base_progress
            self._live_jog_segment_pending_ack = False
            self._live_jog_segment_ack_generation = None
            self._live_jog_segment_expected_coordinate = None
            self._live_jog_segment_completion_observed = False
            return False
        return True

    def _remaining_live_jog_distance(self) -> float:
        progress = max(self._live_jog_planned_progress, self._observed_live_jog_progress())
        return max(0.0, self._live_jog_limit_distance - progress)

    def _observed_live_jog_progress(self) -> float:
        axis = self._live_jog_axis
        if axis is None:
            return 0.0
        position = self.session.virtual_position if self.session.envelope.trusted else self.session.machine_position
        if position is None:
            return 0.0
        current = getattr(position, axis.lower())
        progress = (current - self._live_jog_start_coordinate) * self._live_jog_direction
        return min(self._live_jog_limit_distance, max(0.0, progress))

    def _observe_leased_jog_position(self, status: GrblStatus) -> None:
        # Status is already applied to MachineSession by the controller.
        # Reading progress here caps remaining travel using both plan and telemetry.
        position = self._position_for_status(status)
        if position is None or self._live_jog_axis is None:
            return
        current = getattr(position, self._live_jog_axis.lower())
        progress = (current - self._live_jog_start_coordinate) * self._live_jog_direction
        self._live_jog_planned_progress = max(
            self._live_jog_planned_progress,
            min(self._live_jog_limit_distance, max(0.0, progress)),
        )

    def _live_jog_segment_at_expected_position(self, status: GrblStatus) -> bool:
        if self._live_jog_axis is None or self._live_jog_segment_expected_coordinate is None:
            return False
        position = self._position_for_status(status)
        if position is None:
            return False
        current = getattr(position, self._live_jog_axis.lower())
        return abs(current - self._live_jog_segment_expected_coordinate) <= self.LIVE_JOG_COMPLETION_TOLERANCE_MM

    def _position_for_status(self, status: GrblStatus) -> Position | None:
        machine_position = status.machine_position
        if machine_position is None:
            return None
        if self.session.envelope.trusted:
            return self.session.envelope.relative_position(machine_position)
        return machine_position

    def _expire_live_jog(self) -> None:
        if self._live_jog_axis is None or self._live_jog_lease_token is None:
            return
        self._on_notice("Live jog lease expired; stopping motion")
        self.stop_live_jog(self._live_jog_lease_token)

    def _abort_leased_jog(self, message: str, *, send_cancel: bool) -> None:
        if self._live_jog_lease_token is None and self._live_jog_axis is None:
            return
        if self._live_jog_axis is not None:
            self._live_jog_axis_last = self._live_jog_axis
        self._invalidate_live_jog_lease()
        self._live_jog_axis = None
        self._live_jog_direction = 0.0
        self._live_jog_motion_seen = False
        self._live_jog_stop_pending = False
        self._live_jog_segment_pending_ack = False
        self._live_jog_limit_distance = 0.0
        self._live_jog_start_coordinate = 0.0
        self._live_jog_planned_progress = 0.0
        self._live_jog_feed = 0.0
        self._live_jog_next_segment_at = 0.0
        self._live_jog_segment_status_generation = self._live_jog_status_generation
        self._live_jog_segment_ack_generation = None
        self._live_jog_segment_expected_coordinate = None
        self._live_jog_segment_completion_observed = False
        if send_cancel:
            self._best_effort_jog_cancel()
        self._on_notice(message)
        self._changed()

    def _invalidate_live_jog_lease(self) -> None:
        self._live_jog_lease_token = None
        self._live_jog_lease_expires_at = None

    def _best_effort_jog_cancel(self) -> None:
        try:
            self._send_realtime(REALTIME_JOG_CANCEL)
        except RuntimeError:
            pass

    def _now(self, supplied: float | None) -> float:
        tick = self._clock() if supplied is None else supplied
        if not math.isfinite(tick):
            raise ValueError("Live jog clock must return a finite time")
        return tick

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
