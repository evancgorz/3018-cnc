"""Synthetic-safe parity capture and comparison for future twin/A-B sessions."""

from __future__ import annotations

from dataclasses import dataclass, asdict
import json
import math
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class ParityTolerance:
    position_mm: float = 0.05
    feed_mm_min: float = 2.0
    spindle_rpm: float = 100.0
    timing_seconds: float = 0.5

    def validate(self) -> None:
        if not all(math.isfinite(v) and v >= 0 for v in asdict(self).values()):
            raise ValueError("Parity tolerances must be finite and nonnegative")


@dataclass(frozen=True)
class ParityDifference:
    category: str
    message: str
    left: Any = None
    right: Any = None
    tolerated: bool = False


@dataclass(frozen=True)
class ParityReport:
    matched: bool
    differences: tuple[ParityDifference, ...]
    ignored_fields: tuple[str, ...]
    tolerances: ParityTolerance

    def to_dict(self) -> dict[str, Any]:
        return {"matched": self.matched,
                "differences": [asdict(item) for item in self.differences],
                "ignored_fields": list(self.ignored_fields),
                "tolerances": asdict(self.tolerances)}


class ParityCapture:
    """Versioned capture container; physical capture is intentionally inert here."""

    VERSION = 1

    def __init__(self, events: Iterable[dict[str, Any]] = (), *, source: str = "unknown") -> None:
        self.source = source
        self.events = [dict(event) for event in events]

    @classmethod
    def from_json(cls, path: Path) -> "ParityCapture":
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("schema_version") != cls.VERSION or not isinstance(data.get("events"), list):
            raise ValueError("Unsupported or malformed parity capture")
        return cls(data["events"], source=str(data.get("source", "unknown")))

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": self.VERSION, "source": self.source, "events": self.events}

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2) + "\n", encoding="utf-8")


def compare_captures(twin: ParityCapture, physical: ParityCapture, *, tolerance: ParityTolerance | None = None,
                    ignored_fields: Iterable[str] = ("wall_time", "pid", "port")) -> ParityReport:
    tolerance = tolerance or ParityTolerance()
    tolerance.validate()
    ignored = tuple(sorted(set(ignored_fields)))
    differences: list[ParityDifference] = []
    if len(twin.events) != len(physical.events):
        differences.append(ParityDifference("count", "Event counts differ", len(twin.events), len(physical.events)))
    for index, (left, right) in enumerate(zip(twin.events, physical.events), start=1):
        for key in sorted(set(left) | set(right)):
            if key in ignored:
                continue
            a, b = left.get(key), right.get(key)
            if a == b:
                continue
            if key in {"x", "y", "z", "position_mm"} and isinstance(a, (int, float)) and isinstance(b, (int, float)):
                delta = abs(float(a) - float(b))
                differences.append(ParityDifference("numeric", f"Event {index} {key} differs by {delta:g}", a, b, delta <= tolerance.position_mm))
            elif key in {"time_ns", "elapsed_seconds"} and isinstance(a, (int, float)) and isinstance(b, (int, float)):
                delta = abs(float(a) - float(b)) / (1_000_000_000 if key == "time_ns" else 1)
                differences.append(ParityDifference("timing", f"Event {index} {key} timing differs by {delta:g}", a, b, delta <= tolerance.timing_seconds))
            else:
                differences.append(ParityDifference("semantic", f"Event {index} {key} differs", a, b))
    return ParityReport(not any(not item.tolerated for item in differences), tuple(differences), ignored, tolerance)


def reject_physical_capture_without_authorization(*, authorized: bool, endpoint: str = "") -> None:
    """Guard future hardware capture entry points; never default to physical access."""
    if not authorized:
        raise PermissionError("Physical A/B capture requires a separate explicit user authorization")
    if not endpoint:
        raise ValueError("An explicitly selected physical endpoint is required")
