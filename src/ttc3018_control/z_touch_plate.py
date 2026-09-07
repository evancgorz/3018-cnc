"""Persistent evidence and state helpers for a movable Z touch plate.

The plate is a workpiece datum.  It is deliberately separate from fixed
tool-setter records so a rigid puck can never accidentally acquire TLO
semantics.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math
from pathlib import Path

from .commissioning import InputTestResult, InputTestTracker
from .machine_records import MachineRecordStore


@dataclass(frozen=True)
class ZTouchPlateRecord:
    machine_id: str
    samples: tuple[float, ...] = ()
    tolerance: float = 0.05
    fingerprint: str = ""
    input_tested: bool = False
    timestamp: str = ""

    def validate(self) -> None:
        if not self.machine_id.strip():
            raise ValueError("Z touch plate requires a machine ID")
        if not math.isfinite(self.tolerance) or self.tolerance <= 0 or self.tolerance > 10:
            raise ValueError("Z touch plate tolerance must be between 0 and 10 mm")
        if not all(math.isfinite(value) for value in self.samples):
            raise ValueError("Z touch plate samples must be finite")
        if len(self.samples) > 3:
            raise ValueError("Z touch plate commissioning accepts at most three samples")
        if self.samples and len(self.samples) < 3:
            raise ValueError("Z touch plate commissioning requires three samples")
        if self.samples and max(self.samples) - min(self.samples) > self.tolerance:
            raise ValueError("Z touch plate samples exceed the configured tolerance")

    @property
    def commissioned(self) -> bool:
        return len(self.samples) == 3 and max(self.samples) - min(self.samples) <= self.tolerance

    @property
    def status(self) -> str:
        if not self.input_tested:
            return "needs_input_test"
        if not self.commissioned:
            return "needs_commissioning"
        return "ready"

    @classmethod
    def commissioned_record(cls, machine_id: str, samples: tuple[float, ...], tolerance: float,
                            fingerprint: str, *, input_tested: bool = True) -> "ZTouchPlateRecord":
        return cls(machine_id, samples, tolerance, fingerprint, input_tested,
                   datetime.now(timezone.utc).isoformat())


class ZTouchPlateStore:
    def __init__(self, path: Path) -> None:
        self.records = MachineRecordStore(path)

    def load(self, machine_id: str) -> ZTouchPlateRecord | None:
        data = self.records.load(machine_id)
        if data is None:
            return None
        record = ZTouchPlateRecord(
            machine_id=machine_id,
            samples=tuple(float(value) for value in data.get("samples", ())),
            tolerance=float(data.get("tolerance", 0.05)),
            fingerprint=str(data.get("fingerprint", "")),
            input_tested=bool(data.get("input_tested", False)),
            timestamp=str(data.get("timestamp", "")),
        )
        record.validate()
        return record

    def save(self, record: ZTouchPlateRecord) -> None:
        record.validate()
        self.records.save(record.machine_id, {
            "schema_version": 1,
            "samples": list(record.samples),
            "tolerance": record.tolerance,
            "fingerprint": record.fingerprint,
            "input_tested": record.input_tested,
            "timestamp": record.timestamp,
        })

    def clear(self, machine_id: str) -> None:
        self.records.clear(machine_id)


class ZTouchPlateWorkflow:
    """No-motion input-test state and commissioning sample accumulator."""

    def __init__(self) -> None:
        self.input_tracker = InputTestTracker()
        self.input_result = InputTestResult("idle", "Start the Z touch plate input test.")
        self.samples: list[float] = []

    @property
    def input_tested(self) -> bool:
        return self.input_result.passed

    def start_input_test(self, active_pins: str) -> InputTestResult:
        # Limit pins are unrelated to a movable Z-plate test. Some GRBL
        # boards report floating or inverted X/Y/Z inputs even when limit
        # switches are not declared, so only P may gate this no-motion test.
        self.input_result = self.input_tracker.start("P", self._probe_pin(active_pins))
        if self.input_result.state == "blocked":
            self.input_result = InputTestResult(
                "blocked",
                "Probe input is active while the plate is untouched. If touching the plate "
                "makes P disappear, GRBL probe polarity ($6) is reversed; correct it before probing.",
            )
        return self.input_result

    def observe_pins(self, active_pins: str) -> InputTestResult:
        self.input_result = self.input_tracker.update(self._probe_pin(active_pins))
        return self.input_result

    @staticmethod
    def _probe_pin(active_pins: str) -> str:
        return "P" if "P" in active_pins.upper() else ""

    def add_sample(self, trigger_z: float) -> None:
        if not math.isfinite(trigger_z):
            raise ValueError("Z touch plate sample must be finite")
        if len(self.samples) >= 3:
            raise ValueError("Z touch plate commissioning already has three samples")
        self.samples.append(trigger_z)

    def reset_samples(self) -> None:
        self.samples.clear()
