"""Immutable, serializable contracts shared by twin processes.

All distances are millimetres, feeds are mm/min, spindle values are RPM, and
simulation time is integer nanoseconds.  These records intentionally contain
no Qt, socket, multiprocessing, or application-controller references.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
import math
from pathlib import Path
from typing import Any


class HazardKind(StrEnum):
    TRAVEL_LIMIT = "travel_limit"
    MACHINE_COLLISION = "machine_collision"
    TOOL_STOCK = "tool_stock"
    HOLDER_STOCK = "holder_stock"
    TOOL_FIXTURE = "tool_fixture"
    HOLDER_FIXTURE = "holder_fixture"
    TOOL_BED = "tool_bed"
    RAPID_STOCK = "rapid_stock"
    SPINDLE_OFF_ENTRY = "spindle_off_entry"
    EXCESSIVE_DEPTH = "excessive_depth"
    RETAINED_GOUGE = "retained_gouge"
    STALLED_MOTION = "stalled_motion"
    DIVERGENCE = "commanded_executed_divergence"
    SUPERVISOR_UNAVAILABLE = "supervisor_unavailable"
    PROTOCOL = "protocol"


@dataclass(frozen=True)
class SimulationProfile:
    """Validated simulation settings; defaults are the stated TTC 3018 travel."""

    schema_version: int = 1
    travel_x: float = 290.0
    travel_y: float = 170.0
    travel_z: float = 40.0
    safe_z: float = 30.0
    max_feed_x: float = 1500.0
    max_feed_y: float = 1500.0
    max_feed_z: float = 500.0
    acceleration_x: float = 600.0
    acceleration_y: float = 600.0
    acceleration_z: float = 250.0
    steps_per_mm: float = 80.0
    initial_x: float = 0.0
    initial_y: float = 0.0
    initial_z: float = 0.0
    default_wco_x: float = 0.0
    default_wco_y: float = 0.0
    default_wco_z: float = 0.0
    spindle_acceleration: float = 6000.0
    spindle_deceleration: float = 8000.0
    rx_capacity: int = 512
    planner_capacity: int = 15
    stock_resolution: float = 0.5
    max_stock_cells: int = 1_000_000
    tool_radius: float = 1.5
    tool_length: float = 20.0
    holder_radius: float = 6.0
    holder_length: float = 35.0

    @classmethod
    def default_3018(cls) -> "SimulationProfile":
        return cls()

    def validate(self) -> None:
        if self.schema_version != 1:
            raise ValueError(f"Unsupported simulation profile schema: {self.schema_version}")
        finite = (
            self.travel_x, self.travel_y, self.travel_z, self.safe_z,
            self.max_feed_x, self.max_feed_y, self.max_feed_z,
            self.acceleration_x, self.acceleration_y, self.acceleration_z,
            self.steps_per_mm, self.initial_x, self.initial_y, self.initial_z,
            self.default_wco_x, self.default_wco_y, self.default_wco_z,
            self.spindle_acceleration, self.spindle_deceleration,
            self.stock_resolution, self.tool_radius, self.tool_length,
            self.holder_radius, self.holder_length,
        )
        if not all(math.isfinite(float(value)) for value in finite):
            raise ValueError("Simulation profile values must be finite")
        if min(self.travel_x, self.travel_y, self.travel_z) <= 0:
            raise ValueError("Simulation travel must be greater than zero")
        if not 0 < self.safe_z <= self.travel_z:
            raise ValueError("Simulation safe Z must be inside Z travel")
        if min(self.max_feed_x, self.max_feed_y, self.max_feed_z) <= 0:
            raise ValueError("Simulation feeds must be greater than zero")
        if min(self.acceleration_x, self.acceleration_y, self.acceleration_z) <= 0:
            raise ValueError("Simulation accelerations must be greater than zero")
        if self.steps_per_mm <= 0 or self.stock_resolution <= 0:
            raise ValueError("Steps/mm and stock resolution must be greater than zero")
        if self.rx_capacity < 32 or self.planner_capacity < 1:
            raise ValueError("Simulation controller capacities are too small")
        if self.max_stock_cells < 1:
            raise ValueError("Simulation stock cell budget must be positive")
        if min(self.tool_radius, self.tool_length, self.holder_radius, self.holder_length) <= 0:
            raise ValueError("Simulation tool dimensions must be positive")
        for axis, value, maximum in (
            ("X", self.initial_x, self.travel_x),
            ("Y", self.initial_y, self.travel_y),
            ("Z", self.initial_z, self.travel_z),
        ):
            if not 0 <= value <= maximum:
                raise ValueError(f"Initial {axis} position must be inside travel")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return asdict(self)


@dataclass(frozen=True)
class MotionSnapshot:
    block_id: int = 0
    start: tuple[float, float, float] = (0.0, 0.0, 0.0)
    target: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rapid: bool = False
    probing: bool = False
    feed: float = 0.0
    progress: float = 1.0
    path: tuple[tuple[float, float, float], ...] = ()


@dataclass(frozen=True)
class PlantSnapshot:
    time_ns: int
    state: str
    machine_position: tuple[float, float, float]
    work_offset: tuple[float, float, float]
    feed: float
    spindle_target: float
    spindle_rpm: float
    pins: str = ""
    motion: MotionSnapshot | None = None
    sequence: int = 0

    @property
    def work_position(self) -> tuple[float, float, float]:
        return tuple(a - b for a, b in zip(self.machine_position, self.work_offset))

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["work_position"] = self.work_position
        return result


@dataclass(frozen=True)
class Hazard:
    kind: HazardKind
    message: str
    time_ns: int
    position: tuple[float, float, float]
    body_a: str = ""
    body_b: str = ""
    severity: str = "alarm"
    source: str = "backend"
    segment_id: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self) | {"kind": self.kind.value}


@dataclass(frozen=True)
class TraceEvent:
    sequence: int
    time_ns: int
    kind: str
    payload: dict[str, Any] = field(default_factory=dict)
    source: str = "backend"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SimulationFault:
    name: str
    at_sequence: int | None = None
    at_time_ns: int | None = None
    value: str = ""
    enabled: bool = True

    def validate(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("Simulation fault name must be non-empty")
        if self.at_sequence is not None and (not isinstance(self.at_sequence, int) or self.at_sequence < 1):
            raise ValueError("Simulation fault sequence must be a positive integer")
        if self.at_time_ns is not None and (not isinstance(self.at_time_ns, int) or self.at_time_ns < 0):
            raise ValueError("Simulation fault time must be a nonnegative integer")
        if not isinstance(self.value, str):
            raise ValueError("Simulation fault value must be text")

    def matches(self, sequence: int, time_ns: int) -> bool:
        self.validate()
        return bool(self.enabled
                    and (self.at_sequence is None or self.at_sequence == sequence)
                    and (self.at_time_ns is None or time_ns >= self.at_time_ns))


@dataclass(frozen=True)
class SimulationIntent:
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    sequence: int = 0


@dataclass(frozen=True)
class SimulationWorkpiece:
    path: str = ""
    stock_width: float = 40.0
    stock_height: float = 30.0
    stock_thickness: float = 5.0
    origin_x: float = 0.0
    origin_y: float = 0.0
    origin_z: float = 0.0
    collision_only: bool = False

    def validate(self) -> None:
        for value in (self.stock_width, self.stock_height, self.stock_thickness,
                      self.origin_x, self.origin_y, self.origin_z):
            if not math.isfinite(value):
                raise ValueError("Workpiece values must be finite")
        if min(self.stock_width, self.stock_height, self.stock_thickness) <= 0:
            raise ValueError("Workpiece stock dimensions must be positive")
        if self.path and not Path(self.path).exists():
            raise ValueError("Workpiece STEP path does not exist")
