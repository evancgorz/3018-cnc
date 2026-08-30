"""Qt-independent engraving job lifecycle orchestration."""

from __future__ import annotations

from typing import Callable, Sequence
from pathlib import Path

from ..gcode import GCodeProgram, load_gcode, parse_gcode
from ..grbl import GrblStatus, REALTIME_HOLD, REALTIME_RESUME, make_jog
from ..job import JobStreamer
from .machine_session import ActionOutcome


class JobService:
    """Own acknowledgement-driven streaming and post-job spindle sequencing."""

    def __init__(
        self,
        send_line: Callable[[bytes], None],
        send_realtime: Callable[[bytes], None],
        on_notice: Callable[[str], None] | None = None,
        on_change: Callable[[], None] | None = None,
        on_ready_to_return: Callable[[], None] | None = None,
    ) -> None:
        self._send_line = send_line
        self._send_realtime = send_realtime
        self._on_notice = on_notice or (lambda _message: None)
        self._on_change = on_change or (lambda: None)
        self._on_ready_to_return = on_ready_to_return or (lambda: None)
        self.streamer = JobStreamer(self._send_line)
        self.program: GCodeProgram | None = None
        self._spindle_stop_pending = False
        self._return_waiting_for_idle = False

    @property
    def state(self) -> str:
        return self.streamer.state

    @property
    def active(self) -> bool:
        return self.state in {"running", "paused"}

    @property
    def progress(self) -> float:
        return self.streamer.progress

    def load_program(self, path: Path) -> GCodeProgram:
        program = load_gcode(path)
        self.program = program
        self._changed()
        return program

    def load_generated(self, gcode: str, filename: str) -> GCodeProgram:
        program = parse_gcode(gcode, Path(filename))
        self.program = program
        self._changed()
        return program

    @property
    def spindle_stop_pending(self) -> bool:
        return self._spindle_stop_pending

    @property
    def return_waiting_for_idle(self) -> bool:
        return self._return_waiting_for_idle

    def start(self, commands: Sequence[str] | None = None) -> ActionOutcome:
        if commands is None:
            if self.program is None:
                return ActionOutcome(False, "Job not started — no validated G-code is loaded")
            commands = self.program.commands
        try:
            self.streamer.start(commands)
        except (RuntimeError, ValueError) as exc:
            return ActionOutcome(False, f"Job not started — {exc}")
        self._changed()
        return ActionOutcome(True, "Engraving job started")

    def pause(self) -> ActionOutcome:
        try:
            self._send_realtime(REALTIME_HOLD)
            self.streamer.pause()
        except RuntimeError as exc:
            return ActionOutcome(False, f"Pause failed — {exc}")
        self._changed()
        return ActionOutcome(True, "Job paused")

    def resume(self) -> ActionOutcome:
        try:
            self._send_realtime(REALTIME_RESUME)
            self.streamer.resume()
        except RuntimeError as exc:
            return ActionOutcome(False, f"Resume failed — {exc}")
        self._changed()
        return ActionOutcome(True, "Job resumed")

    def abort(self, reason: str = "Aborted by operator") -> None:
        self.streamer.abort(reason)
        self._spindle_stop_pending = False
        self._return_waiting_for_idle = False
        self._changed()

    def handle_response(self, response: str) -> bool:
        text = response.strip()
        lowered = text.lower()
        if self._spindle_stop_pending:
            if lowered == "ok":
                self._spindle_stop_pending = False
                self._return_waiting_for_idle = True
                self._on_notice("Job complete; spindle stopped, waiting for GRBL Idle")
            elif lowered.startswith("error:") or lowered.startswith("alarm:"):
                self._spindle_stop_pending = False
                self._return_waiting_for_idle = False
                self._on_notice(f"Spindle stop acknowledgement failed — {text}")
            else:
                return False
            self._changed()
            return True

        was_active = self.active
        handled = self.streamer.handle_response(text)
        if not handled:
            return False
        if was_active and self.streamer.state == "complete":
            try:
                self._send_line(b"M5\n")
            except RuntimeError as exc:
                self._on_notice(f"Job complete but spindle stop was not sent — {exc}")
            else:
                self._spindle_stop_pending = True
        self._changed()
        return True

    def observe_status(self, status: GrblStatus) -> None:
        if self._return_waiting_for_idle and status.can_jog:
            self._return_waiting_for_idle = False
            self._on_ready_to_return()
            self._changed()

    def reset(self) -> None:
        if self.active:
            self.streamer.abort("Controller reset")
        self._spindle_stop_pending = False
        self._return_waiting_for_idle = False
        self._changed()

    def _changed(self) -> None:
        self._on_change()
