from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path

from .grbl import Position


@dataclass(frozen=True)
class SavedWorkZero:
    """A GRBL work offset previously confirmed by a fresh status report."""

    x: float
    y: float
    z: float

    @classmethod
    def from_position(cls, position: Position) -> "SavedWorkZero":
        return cls(position.x, position.y, position.z)

    @property
    def position(self) -> Position:
        return Position(self.x, self.y, self.z)

    def validate(self) -> None:
        if not all(math.isfinite(value) for value in (self.x, self.y, self.z)):
            raise ValueError("Saved work-zero coordinates must be finite")


class WorkZeroStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self, machine_id: str | None = None) -> SavedWorkZero | None:
        if not self.path.exists():
            return None
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if machine_id is not None and "machines" in data:
            data = data.get("machines", {}).get(machine_id)
            if data is None:
                return None
        saved = SavedWorkZero(**data)
        saved.validate()
        return saved

    def save(self, saved: SavedWorkZero, machine_id: str | None = None) -> None:
        saved.validate()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        if machine_id is None:
            data = asdict(saved)
        else:
            data = self._load_catalog()
            data.setdefault("machines", {})[machine_id] = asdict(saved)
            data["schema_version"] = 1
        temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.path)

    def clear(self, machine_id: str | None = None) -> None:
        if machine_id is not None and self.path.exists():
            data = self._load_catalog()
            machines = data.get("machines", {})
            if machine_id in machines:
                del machines[machine_id]
                if machines:
                    temporary = self.path.with_suffix(".tmp")
                    temporary.write_text(json.dumps({"schema_version": 1, "machines": machines}, indent=2) + "\n", encoding="utf-8")
                    temporary.replace(self.path)
                else:
                    self.path.unlink()
            return
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass

    def _load_catalog(self) -> dict:
        if not self.path.exists():
            return {"schema_version": 1, "machines": {}}
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if "machines" in data:
            return data
        # A legacy flat value is not assigned to a machine until the caller
        # explicitly saves it with a machine ID.
        return {"schema_version": 1, "machines": {}}
