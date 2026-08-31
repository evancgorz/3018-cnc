from __future__ import annotations

from dataclasses import dataclass, field
import math
import re
from typing import Mapping


REALTIME_STATUS = b"?"
REALTIME_HOLD = b"!"
REALTIME_RESUME = b"~"
REALTIME_JOG_CANCEL = b"\x85"
REALTIME_SOFT_RESET = b"\x18"


@dataclass(frozen=True)
class Position:
    x: float
    y: float
    z: float

    def minus(self, other: "Position") -> "Position":
        return Position(self.x - other.x, self.y - other.y, self.z - other.z)


@dataclass(frozen=True)
class GrblStatus:
    state: str
    machine_position: Position | None = None
    work_position: Position | None = None
    work_offset: Position | None = None
    feed: float | None = None
    spindle: float | None = None
    pins: str = ""
    fields: Mapping[str, str] = field(default_factory=dict)

    @property
    def can_jog(self) -> bool:
        return self.state == "Idle"


def _position(value: str) -> Position:
    values = value.split(",")
    if len(values) < 3:
        raise ValueError(f"Expected three coordinates, received {value!r}")
    return Position(*(float(item) for item in values[:3]))


def parse_status(line: str) -> GrblStatus | None:
    """Parse a GRBL angle-bracket status report."""
    line = line.strip()
    start = line.find("<")
    end = line.rfind(">")
    if start < 0 or end <= start:
        return None

    parts = line[start + 1 : end].split("|")
    if not parts or not parts[0]:
        return None

    fields: dict[str, str] = {}
    for part in parts[1:]:
        if ":" in part:
            key, value = part.split(":", 1)
            fields[key] = value

    feed = spindle = None
    if "FS" in fields:
        fs = fields["FS"].split(",")
        if fs:
            feed = float(fs[0])
        if len(fs) > 1:
            spindle = float(fs[1])

    return GrblStatus(
        state=parts[0].split(":", 1)[0],
        machine_position=_position(fields["MPos"]) if "MPos" in fields else None,
        work_position=_position(fields["WPos"]) if "WPos" in fields else None,
        work_offset=_position(fields["WCO"]) if "WCO" in fields else None,
        feed=feed,
        spindle=spindle,
        pins=fields.get("Pn", ""),
        fields=fields,
    )


def make_jog(axis: str, distance_mm: float, feed_mm_min: float) -> bytes:
    axis = axis.upper()
    if axis not in {"X", "Y", "Z"}:
        raise ValueError("Axis must be X, Y, or Z")
    if distance_mm == 0:
        raise ValueError("Jog distance cannot be zero")
    if not 0 < feed_mm_min <= 1500:
        raise ValueError("Jog feed must be between 0 and 1500 mm/min")
    return f"$J=G91 G21 {axis}{distance_mm:g} F{feed_mm_min:g}\n".encode("ascii")


def make_work_zero(axes: str) -> bytes:
    normalized = "".join(axis for axis in "XYZ" if axis in axes.upper())
    if not normalized:
        raise ValueError("At least one of X, Y, or Z is required")
    values = " ".join(f"{axis}0" for axis in normalized)
    return f"G10 L20 P1 {values}\n".encode("ascii")


def make_probe(axis: str, distance_mm: float, feed_mm_min: float) -> bytes:
    """Build a bounded incremental GRBL probe move.

    Probe moves intentionally use ordinary G-code, not ``$J``.  The
    application only exposes this builder to the dedicated probing service;
    ordinary job parsing continues to reject G38.
    """
    axis = axis.upper()
    if axis not in {"X", "Y", "Z"}:
        raise ValueError("Probe axis must be X, Y, or Z")
    if distance_mm == 0 or not -1000 < distance_mm < 1000:
        raise ValueError("Probe distance must be non-zero and bounded")
    if not 0 < feed_mm_min <= 1500:
        raise ValueError("Probe feed must be between 0 and 1500 mm/min")
    return f"G91 G21 G38.2 {axis}{distance_mm:g} F{feed_mm_min:g}\n".encode("ascii")


def make_probe_retract(axis: str, distance_mm: float, feed_mm_min: float) -> bytes:
    axis = axis.upper()
    if axis not in {"X", "Y", "Z"} or distance_mm == 0 or not 0 < feed_mm_min <= 1500:
        raise ValueError("Invalid probe retract")
    return f"G91 G21 {axis}{distance_mm:g} F{feed_mm_min:g}\n".encode("ascii")


def make_work_offset(slot: int, position: Position) -> bytes:
    if slot not in range(1, 7):
        raise ValueError("GRBL work-coordinate slot must be between 1 and 6")
    if not all(math.isfinite(value) for value in (position.x, position.y, position.z)):
        raise ValueError("Work offset coordinates must be finite")
    return f"G10 L20 P{slot} X{position.x:g} Y{position.y:g} Z{position.z:g}\n".encode("ascii")


def make_tool_length_offset(z_offset: float) -> bytes:
    if not math.isfinite(z_offset):
        raise ValueError("Tool length offset must be finite")
    return f"G43.1 Z{z_offset:g}\n".encode("ascii")


def clear_tool_length_offset() -> bytes:
    return b"G49\n"


def parse_setting(line: str) -> tuple[int, float] | None:
    """Parse a GRBL setting response such as ``$22=1``."""
    match = re.fullmatch(r"\s*\$(\d+)\s*=\s*(-?(?:\d+(?:\.\d*)?|\.\d+))\s*", line)
    if match is None:
        return None
    return int(match.group(1)), float(match.group(2))


def parse_probe_report(line: str) -> tuple[Position, bool] | None:
    """Parse GRBL's ``[PRB:x,y,z:1]`` report."""
    match = re.fullmatch(r"\s*\[PRB:([^]]+)\]\s*", line)
    if match is None:
        return None
    values = match.group(1).rsplit(":", 1)
    if len(values) != 2:
        return None
    return _position(values[0]), values[1] == "1"


def parse_tool_length_report(line: str) -> float | None:
    match = re.fullmatch(r"\s*\[TLO:(-?(?:\d+(?:\.\d*)?|\.\d+))\]\s*", line)
    return float(match.group(1)) if match else None


COMMISSIONING_SETTINGS = {5, 6, 20, 21, 22, 23, 24, 25, 26, 27, 130, 131, 132}


def make_setting(number: int, value: float) -> bytes:
    if number not in COMMISSIONING_SETTINGS:
        raise ValueError("Setting is not part of the guarded commissioning set")
    if float(value) < 0:
        raise ValueError("Setting value cannot be negative")
    return f"${number}={float(value):g}\n".encode("ascii")
