from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence


SendLine = Callable[[bytes], None]


@dataclass
class JobStreamer:
    """Conservative GRBL sender: one line is outstanding until GRBL acknowledges it."""

    send_line: SendLine
    commands: Sequence[str] = ()
    next_index: int = 0
    awaiting_ack: bool = False
    state: str = "idle"
    error: str = ""

    @property
    def completed(self) -> int:
        return self.next_index - (1 if self.awaiting_ack else 0)

    @property
    def total(self) -> int:
        return len(self.commands)

    @property
    def progress(self) -> float:
        return self.completed / self.total if self.total else 0.0

    def start(self, commands: Sequence[str]) -> None:
        if self.state in {"running", "paused"}:
            raise RuntimeError("A job is already active")
        if not commands:
            raise ValueError("Job has no commands")
        self.commands = tuple(commands)
        self.next_index = 0
        self.awaiting_ack = False
        self.error = ""
        self.state = "running"
        try:
            self._send_next()
        except Exception:
            self.state = "failed"
            self.awaiting_ack = False
            raise

    def handle_response(self, response: str) -> bool:
        text = response.strip()
        lowered = text.lower()
        if lowered == "ok" and self.awaiting_ack:
            self.awaiting_ack = False
            if self.next_index >= self.total:
                self.state = "complete"
            elif self.state == "running":
                self._send_next()
            return True
        if (lowered.startswith("error:") or lowered.startswith("alarm:")) and self.state in {"running", "paused"}:
            self.awaiting_ack = False
            self.state = "failed"
            self.error = text
            return True
        return False

    def pause(self) -> None:
        if self.state != "running":
            raise RuntimeError("Job is not running")
        self.state = "paused"

    def resume(self) -> None:
        if self.state != "paused":
            raise RuntimeError("Job is not paused")
        self.state = "running"
        if not self.awaiting_ack:
            self._send_next()

    def abort(self, reason: str = "Aborted by operator") -> None:
        if self.state not in {"running", "paused"}:
            return
        self.state = "aborted"
        self.awaiting_ack = False
        self.error = reason

    def _send_next(self) -> None:
        if self.state != "running" or self.awaiting_ack:
            return
        if self.next_index >= self.total:
            self.state = "complete"
            return
        command = self.commands[self.next_index]
        self.send_line((command + "\n").encode("ascii"))
        self.next_index += 1
        self.awaiting_ack = True
