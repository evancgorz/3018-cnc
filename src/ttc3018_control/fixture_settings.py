"""Named, machine-scoped fixed-fixture records."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math

from .grbl import Position
from .machine_records import MachineRecordStore


@dataclass(frozen=True)
class FixtureRecord:
    machine_id: str
    name: str
    wcs_slot: int
    approach: Position
    probe_compensation: Position = Position(0, 0, 0)
    expected_width: float = 0.0
    expected_height: float = 0.0
    fingerprint: str = ""
    last_origin: Position | None = None

    def validate(self) -> None:
        if not self.machine_id.strip() or not self.name.strip():
            raise ValueError("Fixture requires a machine ID and name")
        if self.wcs_slot not in range(1, 7):
            raise ValueError("Fixture WCS slot must be between 1 and 6")
        values = (*self.approach.__dict__.values(), *self.probe_compensation.__dict__.values(), self.expected_width, self.expected_height)
        if self.last_origin is not None:
            values = (*values, *self.last_origin.__dict__.values())
        if not all(math.isfinite(float(v)) for v in values):
            raise ValueError("Fixture geometry must be finite")
        if self.expected_width < 0 or self.expected_height < 0:
            raise ValueError("Fixture expected dimensions cannot be negative")

    def measured_origin(self, probe_position: Position) -> Position:
        self.validate()
        return Position(probe_position.x + self.probe_compensation.x,
                        probe_position.y + self.probe_compensation.y,
                        probe_position.z + self.probe_compensation.z)


def fixture_record_to_dict(record: FixtureRecord) -> dict:
    record.validate()
    data = asdict(record)
    return data


def fixture_record_from_dict(data: dict) -> FixtureRecord:
    def position(value):
        return Position(**value) if value is not None else None
    record = FixtureRecord(machine_id=str(data["machine_id"]), name=str(data["name"]), wcs_slot=int(data["wcs_slot"]),
                           approach=position(data["approach"]), probe_compensation=position(data.get("probe_compensation", {"x": 0, "y": 0, "z": 0})),
                           expected_width=float(data.get("expected_width", 0)), expected_height=float(data.get("expected_height", 0)),
                           fingerprint=str(data.get("fingerprint", "")), last_origin=position(data.get("last_origin")))
    record.validate()
    return record


class FixtureStore:
    def __init__(self, path):
        self.records = MachineRecordStore(path)

    def load(self, machine_id: str, name: str) -> FixtureRecord | None:
        data = self.records.load(machine_id) or {}
        value = data.get(name)
        return fixture_record_from_dict(value) if value is not None else None

    def save(self, record: FixtureRecord) -> None:
        record.validate()
        data = self.records.load(record.machine_id) or {}
        data[record.name] = fixture_record_to_dict(record)
        self.records.save(record.machine_id, data)

    def clear(self, machine_id: str, name: str) -> None:
        data = self.records.load(machine_id) or {}
        data.pop(name, None)
        if data:
            self.records.save(machine_id, data)
        else:
            self.records.clear(machine_id)
