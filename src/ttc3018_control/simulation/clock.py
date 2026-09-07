"""Deterministic virtual time."""

from __future__ import annotations

from dataclasses import dataclass
import time


@dataclass
class SimulationClock:
    """Integer-nanosecond clock; tests call advance, UI calls advance_wall."""

    time_ns: int = 0
    speed: float = 1.0
    manual: bool = True

    SPEEDS = {"realtime": 1.0, "2x": 2.0, "5x": 5.0, "10x": 10.0, "uncapped": 0.0}

    def __post_init__(self) -> None:
        self.set_speed(self.speed)
        if self.time_ns < 0:
            raise ValueError("Simulation clock cannot start before zero")

    def set_speed(self, speed: float | str) -> None:
        if isinstance(speed, str):
            if speed not in self.SPEEDS:
                raise ValueError(f"Unknown simulation speed: {speed}")
            speed = self.SPEEDS[speed]
        if speed < 0 or speed > 1000:
            raise ValueError("Simulation speed must be between zero and 1000")
        self.speed = float(speed)

    def advance(self, delta_ns: int) -> int:
        if not isinstance(delta_ns, int) or delta_ns < 0:
            raise ValueError("Clock advancement must be a nonnegative integer nanosecond count")
        self.time_ns += delta_ns
        return self.time_ns

    def advance_wall(self, wall_seconds: float) -> int:
        if wall_seconds < 0:
            raise ValueError("Wall time cannot move backwards")
        if self.speed == 0:
            # Uncapped is deliberately explicit: callers choose their manual tick.
            return self.time_ns
        return self.advance(round(wall_seconds * self.speed * 1_000_000_000))

    def reset(self) -> None:
        self.time_ns = 0

    @staticmethod
    def wall_now_ns() -> int:
        return time.monotonic_ns()
