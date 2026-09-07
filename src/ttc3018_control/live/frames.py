"""Bounded latest-frame hub shared by desktop and mobile viewers."""

from __future__ import annotations

from dataclasses import dataclass
import threading
import time


@dataclass(frozen=True)
class Frame:
    generation: int
    jpeg: bytes
    captured_at: float


class FrameHub:
    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._frame: Frame | None = None
        self._closed = False

    def publish(self, jpeg: bytes) -> int:
        if not jpeg:
            return 0
        with self._condition:
            generation = (self._frame.generation + 1) if self._frame else 1
            self._frame = Frame(generation, bytes(jpeg), time.monotonic())
            self._condition.notify_all()
            return generation

    def latest(self) -> Frame | None:
        with self._condition:
            return self._frame

    def wait_next(self, previous_generation: int, timeout: float = 2.0) -> Frame | None:
        deadline = time.monotonic() + timeout
        with self._condition:
            while not self._closed and (self._frame is None or self._frame.generation <= previous_generation):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._condition.wait(remaining)
            return self._frame

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._condition.notify_all()
