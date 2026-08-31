"""Machine-scoped fixed tool-setter records and deterministic TLO math."""

from __future__ import annotations

from dataclasses import dataclass
import math

from .grbl import Position
from .machine_records import MachineRecordStore


@dataclass(frozen=True)
class ToolSetterRecord:
    machine_id: str
    approach: Position
    reference_trigger_z: float
    tolerance: float = 0.05
    samples: tuple[float, ...] = ()
    fingerprint: str = ""

    def validate(self) -> None:
        if not self.machine_id.strip():
            raise ValueError("Tool setter requires a machine ID")
        if not all(math.isfinite(v) for v in (*self.approach.__dict__.values(), self.reference_trigger_z, self.tolerance, *self.samples)):
            raise ValueError("Tool setter values must be finite")
        if self.tolerance <= 0:
            raise ValueError("Tool setter tolerance must be greater than zero")
        if self.samples and len(self.samples) < 3:
            raise ValueError("Tool setter commissioning requires at least three samples")
        if self.samples and max(self.samples) - min(self.samples) > self.tolerance:
            raise ValueError("Tool setter samples exceed the configured repeatability tolerance")

    @property
    def commissioned(self) -> bool:
        return len(self.samples) >= 3 and max(self.samples) - min(self.samples) <= self.tolerance


def calculate_tool_length_offset(reference_trigger_z: float, measured_trigger_z: float) -> float:
    if not all(math.isfinite(v) for v in (reference_trigger_z, measured_trigger_z)):
        raise ValueError("Tool setter measurements must be finite")
    return reference_trigger_z - measured_trigger_z


class ToolSetterStore:
    def __init__(self, path) -> None:
        self.records = MachineRecordStore(path)

    def load(self, machine_id: str) -> ToolSetterRecord | None:
        data = self.records.load(machine_id)
        return ToolSetterRecord(
            machine_id=machine_id, approach=Position(**data["approach"]), reference_trigger_z=float(data["reference_trigger_z"]),
            tolerance=float(data["tolerance"]), samples=tuple(data.get("samples", ())), fingerprint=str(data.get("fingerprint", "")),
        ) if data is not None else None

    def save(self, record: ToolSetterRecord) -> None:
        record.validate()
        self.records.save(record.machine_id, {"approach": record.approach.__dict__, "reference_trigger_z": record.reference_trigger_z,
                                              "tolerance": record.tolerance, "samples": list(record.samples), "fingerprint": record.fingerprint})
