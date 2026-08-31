from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Sequence


SendLine = Callable[[bytes], None]


@dataclass
class JobStreamer:
    """Character-counting GRBL sender that keeps the controller RX buffer fed."""

    send_line: SendLine
    commands: Sequence[str] = ()
    next_index: int = 0
    acknowledged_count: int = 0
    # GRBL declares a 128-byte RX ring, but its head/tail implementation must
    # leave one slot empty to distinguish full from empty. The usable payload
    # is therefore 127 bytes including each command's trailing newline.
    buffer_capacity: int = 127
    outstanding_lengths: list[int] = field(default_factory=list)
    state: str = "idle"
    error: str = ""

    @property
    def completed(self) -> int:
        return self.acknowledged_count

    @property
    def awaiting_ack(self) -> bool:
        return bool(self.outstanding_lengths)

    @property
    def buffered_bytes(self) -> int:
        return sum(self.outstanding_lengths)

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
        self.acknowledged_count = 0
        self.outstanding_lengths.clear()
        self.error = ""
        self.state = "running"
        try:
            self._fill_buffer()
        except Exception:
            self.state = "failed"
            self.outstanding_lengths.clear()
            raise

    def handle_response(self, response: str) -> bool:
        text = response.strip()
        lowered = text.lower()
        if lowered == "ok" and self.outstanding_lengths:
            self.outstanding_lengths.pop(0)
            self.acknowledged_count += 1
            if self.next_index >= self.total and not self.outstanding_lengths:
                self.state = "complete"
            elif self.state == "running":
                self._fill_buffer()
            return True
        if (lowered.startswith("error:") or lowered.startswith("alarm:")) and self.state in {"running", "paused"}:
            self.outstanding_lengths.clear()
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
        self._fill_buffer()

    def abort(self, reason: str = "Aborted by operator") -> None:
        if self.state not in {"running", "paused"}:
            return
        self.state = "aborted"
        self.outstanding_lengths.clear()
        self.error = reason

    def fail(self, reason: str) -> None:
        """Fail an active stream because of an external controller state."""
        if self.state not in {"running", "paused", "complete"}:
            return
        self.state = "failed"
        self.outstanding_lengths.clear()
        self.error = reason

    def _fill_buffer(self) -> None:
        if self.state != "running":
            return
        while self.next_index < self.total:
            encoded = (self.commands[self.next_index] + "\n").encode("ascii")
            length = len(encoded)
            if length > self.buffer_capacity:
                raise ValueError(
                    f"G-code line {self.next_index + 1} is {length} bytes; "
                    f"GRBL RX capacity is {self.buffer_capacity}"
                )
            if self.outstanding_lengths and self.buffered_bytes + length > self.buffer_capacity:
                return
            self.send_line(encoded)
            self.outstanding_lengths.append(length)
            self.next_index += 1
        if not self.outstanding_lengths:
            self.state = "complete"
