"""Qt-independent engraving job lifecycle orchestration."""

from __future__ import annotations

import re
import time
from typing import Callable, Sequence
from pathlib import Path

from ..gcode import GCodeProgram, load_gcode, parse_gcode
from ..grbl import GrblStatus, REALTIME_HOLD, REALTIME_RESUME, REALTIME_SOFT_RESET
from ..job import JobStreamer
from ..machine_state import check_job_bounds
from .machine_session import ActionOutcome, MachineSession


class JobService:
    """Own acknowledgement-driven streaming and post-job spindle sequencing."""

    DEFAULT_RX_CAPACITY = 127
    MAX_REPORTED_RX_CAPACITY = 4096
    # The DLC32 advertises roughly 1.2 KB, but its ESP32 TCP-to-GRBL bridge can
    # become unreliable when a desktop sender fills that window to its edge in
    # one burst. 512 bytes keeps substantially more than the 15-slot motion
    # planner supplied while retaining ample bridge and status-report headroom.
    MAX_STREAM_WINDOW = 512
    REQUIRED_SPINDLE_STOP_ACKS = 2

    def __init__(
        self,
        session: MachineSession,
        send_line: Callable[[bytes], None],
        send_realtime: Callable[[bytes], None],
        on_notice: Callable[[str], None] | None = None,
        on_change: Callable[[], None] | None = None,
        on_ready_to_return: Callable[[], None] | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.session = session
        self._send_line = send_line
        self._send_realtime = send_realtime
        self._on_notice = on_notice or (lambda _message: None)
        self._on_change = on_change or (lambda: None)
        self._on_ready_to_return = on_ready_to_return or (lambda: None)
        self.streamer = JobStreamer(self._send_line)
        self.program: GCodeProgram | None = None
        self._completion_waiting_for_idle = False
        self._spindle_stop_pending = False
        self._spindle_stop_acks = 0
        self._return_waiting_for_idle = False
        self._reported_rx_capacity = self.DEFAULT_RX_CAPACITY
        self._restart_requires_reload = False
        self._clock = clock or time.monotonic
        self._timing_started_at: float | None = None
        self._elapsed_seconds = 0.0

    @property
    def state(self) -> str:
        return self.streamer.state

    @property
    def active(self) -> bool:
        return bool(
            self.state in {"running", "paused"}
            or self._completion_waiting_for_idle
            or self._spindle_stop_pending
            or self._return_waiting_for_idle
        )

    @property
    def progress(self) -> float:
        return self.streamer.progress

    @property
    def estimated_seconds(self) -> float:
        return self.program.estimated_seconds if self.program is not None else 0.0

    @property
    def elapsed_seconds(self) -> float:
        if self._timing_started_at is None:
            return self._elapsed_seconds
        return max(self._elapsed_seconds, self._elapsed_seconds + self._clock() - self._timing_started_at)

    @property
    def remaining_seconds(self) -> float | None:
        if self.program is None or self.program.estimated_seconds <= 0:
            return None
        return max(0.0, self.program.estimated_seconds - self.elapsed_seconds)

    def load_program(self, path: Path) -> GCodeProgram:
        program = load_gcode(path)
        self.program = program
        self._restart_requires_reload = False
        self._changed()
        return program

    def load_generated(self, gcode: str, filename: str) -> GCodeProgram:
        program = parse_gcode(gcode, Path(filename))
        self.program = program
        self._restart_requires_reload = False
        self._changed()
        return program

    def preflight(self) -> tuple[bool, str]:
        if self.program is None:
            return False, "Load a validated G-code program first."
        if not self.session.envelope.trusted or self.session.envelope.reference is None:
            return False, "Establish the manual machine reference first."
        if self.session.work_offset is None:
            return False, "A fresh GRBL work-offset report is required."
        return check_job_bounds(
            self.program.bounds.minimum,
            self.program.bounds.maximum,
            self.session.work_offset,
            self.session.envelope.reference,
            self.session.profile,
        )

    @property
    def spindle_stop_pending(self) -> bool:
        return self._spindle_stop_pending

    @property
    def return_waiting_for_idle(self) -> bool:
        return self._return_waiting_for_idle

    @property
    def restart_requires_reload(self) -> bool:
        return self._restart_requires_reload

    def start(self, commands: Sequence[str] | None = None) -> ActionOutcome:
        if self._restart_requires_reload:
            return ActionOutcome(False, "Job not started — reload and review the program after the previous failure")
        if commands is None:
            if self.program is None:
                return ActionOutcome(False, "Job not started — no validated G-code is loaded")
            commands = self.program.commands
        try:
            commands = self._motion_commands_without_terminal_stop(commands)
        except ValueError as exc:
            return ActionOutcome(False, f"Job not started — {exc}")
        try:
            self.streamer.buffer_capacity = self._reported_rx_capacity
            self.streamer.start(commands)
        except (RuntimeError, ValueError) as exc:
            return ActionOutcome(False, f"Job not started — {exc}")
        self._completion_waiting_for_idle = False
        self._spindle_stop_pending = False
        self._spindle_stop_acks = 0
        self._return_waiting_for_idle = False
        self._elapsed_seconds = 0.0
        self._timing_started_at = self._clock()
        self._changed()
        return ActionOutcome(True, "Engraving job started")

    def pause(self) -> ActionOutcome:
        try:
            self._send_realtime(REALTIME_HOLD)
            self.streamer.pause()
        except RuntimeError as exc:
            return ActionOutcome(False, f"Pause failed — {exc}")
        self._freeze_timing()
        self._changed()
        return ActionOutcome(True, "Job paused")

    def resume(self) -> ActionOutcome:
        try:
            self._send_realtime(REALTIME_RESUME)
            self.streamer.resume()
        except RuntimeError as exc:
            return ActionOutcome(False, f"Resume failed — {exc}")
        self._timing_started_at = self._clock()
        self._changed()
        return ActionOutcome(True, "Job resumed")

    def abort(self, reason: str = "Aborted by operator") -> None:
        self.streamer.abort(reason)
        self._freeze_timing()
        self._completion_waiting_for_idle = False
        self._spindle_stop_pending = False
        self._spindle_stop_acks = 0
        self._return_waiting_for_idle = False
        self._changed()

    def handle_response(self, response: str) -> bool:
        text = response.strip()
        lowered = text.lower()
        if self._spindle_stop_pending:
            if lowered == "ok":
                self._spindle_stop_pending = False
                self._spindle_stop_acks += 1
                self._return_waiting_for_idle = True
                self._on_notice(
                    "Job complete; spindle stop accepted, waiting for GRBL Idle at 0 RPM"
                )
            elif lowered.startswith("error:") or lowered.startswith("alarm:"):
                self._spindle_stop_pending = False
                self._return_waiting_for_idle = False
                reason = f"spindle stop acknowledgement failed — {text}"
                self.streamer.fail(reason)
                self._fail_closed(reason)
            else:
                return False
            self._changed()
            return True

        was_active = self.active
        handled = self.streamer.handle_response(text)
        if not handled:
            return False
        if was_active and self.streamer.state == "complete":
            # Command acknowledgement means accepted, not physically executed.
            # Wait for authoritative Idle before M5 so DLC32 firmware never has
            # to synchronize spindle stop against a populated motion planner.
            self._completion_waiting_for_idle = True
            self._on_notice("Job motion accepted; waiting for GRBL Idle before spindle stop")
        elif was_active and self.streamer.state == "failed":
            self._fail_closed(self.streamer.error)
        self._changed()
        return True

    def observe_status(self, status: GrblStatus) -> None:
        reported_capacity = self._rx_capacity_from_status(status)
        if reported_capacity is not None:
            self._reported_rx_capacity = max(self._reported_rx_capacity, reported_capacity)
        if self.active and status.state in {"Alarm", "Door", "Sleep"}:
            reason = f"controller entered {status.state} during the job"
            self.streamer.fail(reason)
            self._fail_closed(reason)
            self._changed()
            return
        if self._completion_waiting_for_idle and status.can_jog:
            self._freeze_timing()
            self._completion_waiting_for_idle = False
            self._request_spindle_stop("Job motion finished; spindle stop sent")
            self._changed()
            return
        # An M5 acknowledgement only confirms that GRBL accepted the command.
        # In particular, DLC32 status traffic can still report Idle while the
        # spindle output remains active. Never begin the automatic return until
        # an authoritative status report confirms both Idle and zero spindle
        # speed.
        if self._return_waiting_for_idle and status.can_jog and status.spindle == 0:
            if self._spindle_stop_acks < self.REQUIRED_SPINDLE_STOP_ACKS:
                self._return_waiting_for_idle = False
                self._request_spindle_stop(
                    "Zero RPM reported; spindle stop verification sent before return motion"
                )
                self._changed()
                return
            self._return_waiting_for_idle = False
            self._on_notice("Job complete; spindle stopped and GRBL Idle, returning to work zero")
            self._on_ready_to_return()
            self._changed()

    def reset(self) -> None:
        was_active = self.active
        if was_active:
            self.streamer.abort("Controller reset")
            self._restart_requires_reload = True
        self._freeze_timing()
        self._completion_waiting_for_idle = False
        self._spindle_stop_pending = False
        self._spindle_stop_acks = 0
        self._return_waiting_for_idle = False
        self._reported_rx_capacity = self.DEFAULT_RX_CAPACITY
        self.streamer.buffer_capacity = self.DEFAULT_RX_CAPACITY
        self._changed()

    @classmethod
    def _rx_capacity_from_status(cls, status: GrblStatus) -> int | None:
        """Return the usable RX window advertised by GRBL's ``Bf`` field.

        ``Bf`` contains planner slots and currently free serial RX bytes. Idle
        reports expose the controller's full receive window. Keep one byte
        unused for ring-buffer implementations and reject implausible values so
        malformed status text can never make streaming unbounded.
        """
        value = status.fields.get("Bf")
        if value is None:
            return None
        parts = value.split(",", 1)
        if len(parts) != 2:
            return None
        try:
            free_bytes = int(parts[1])
        except ValueError:
            return None
        usable = free_bytes - 1
        if usable < cls.DEFAULT_RX_CAPACITY or usable > cls.MAX_REPORTED_RX_CAPACITY:
            return None
        return min(usable, cls.MAX_STREAM_WINDOW)

    def _changed(self) -> None:
        self._on_change()

    def _freeze_timing(self) -> None:
        if self._timing_started_at is not None:
            self._elapsed_seconds = max(
                self._elapsed_seconds,
                self._elapsed_seconds + self._clock() - self._timing_started_at,
            )
            self._timing_started_at = None

    def _fail_closed(self, reason: str) -> None:
        self._freeze_timing()
        self._restart_requires_reload = True
        self._completion_waiting_for_idle = False
        self._spindle_stop_pending = False
        self._spindle_stop_acks = 0
        self._return_waiting_for_idle = False
        try:
            # A failure can leave later buffered commands queued behind the
            # rejected line. Feed-hold and soft reset are realtime bytes, so
            # they do not wait behind that queue. GRBL reset also forces the
            # spindle output off and invalidates position trust.
            self._send_realtime(REALTIME_HOLD)
            self._send_realtime(REALTIME_SOFT_RESET)
        except RuntimeError as exc:
            self._on_notice(
                f"Job failed — emergency stop command could not be sent ({exc}); remove machine power"
            )
        else:
            self._on_notice(
                f"Job failed — {reason}; motion queue reset and spindle stop requested. "
                "Re-establish references and reload the job before restarting."
            )

    def _request_spindle_stop(self, notice: str) -> None:
        """Send one completion-owned M5 or fail closed if it cannot be sent."""
        try:
            self._send_line(b"M5\n")
        except RuntimeError as exc:
            reason = f"spindle stop was not sent — {exc}"
            self.streamer.fail(reason)
            self._fail_closed(reason)
            return
        self._spindle_stop_pending = True
        self._on_notice(notice)

    @staticmethod
    def _motion_commands_without_terminal_stop(commands: Sequence[str]) -> tuple[str, ...]:
        """Remove terminal program/spindle stops so they can run after Idle.

        The DLC32 firmware can freeze while processing M5 against buffered
        motion. Mid-program M5/M2 therefore fails closed; generated jobs place
        both on standalone terminal lines, which this lifecycle owns safely.
        """
        prepared = list(commands)
        if prepared and prepared[-1].strip().upper() == "M2":
            prepared.pop()
        if prepared and prepared[-1].strip().upper() == "M5":
            prepared.pop()
        terminal_code = re.compile(r"(?:^|\s)M(?:0*2|0*5)(?:\.0+)?(?:\s|$)", re.IGNORECASE)
        if any(terminal_code.search(command) for command in prepared):
            raise ValueError("M5 and M2 are supported only as standalone terminal commands")
        if not prepared:
            raise ValueError("job contains no motion or setup commands before its terminal stop")
        return tuple(prepared)

    def bind_callbacks(
        self,
        *,
        on_notice: Callable[[str], None] | None = None,
        on_change: Callable[[], None] | None = None,
        on_ready_to_return: Callable[[], None] | None = None,
    ) -> None:
        """Attach a presentation/event adapter without exposing streamer state."""
        if on_notice is not None:
            self._on_notice = on_notice
        if on_change is not None:
            self._on_change = on_change
        if on_ready_to_return is not None:
            self._on_ready_to_return = on_ready_to_return
