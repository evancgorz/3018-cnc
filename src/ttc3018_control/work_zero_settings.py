from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path

from .grbl import Position


@dataclass(frozen=True)
class SavedWorkZero:
    """A GRBL work offset, with the axes actually confirmed by fresh status."""

    x: float
    y: float
    z: float
    confirmed_axes: frozenset[str] = frozenset("XYZ")

    def __post_init__(self) -> None:
        axes = self.confirmed_axes
        if isinstance(axes, str):
            axes = frozenset(axes.upper())
        else:
            axes = frozenset(str(axis).upper() for axis in axes)
        object.__setattr__(self, "confirmed_axes", axes)

    @classmethod
    def from_position(cls, position: Position, confirmed_axes: str = "XYZ") -> "SavedWorkZero":
        return cls(position.x, position.y, position.z, frozenset(confirmed_axes.upper()))

    @property
    def position(self) -> Position:
        return Position(self.x, self.y, self.z)

    def validate(self) -> None:
        if not all(math.isfinite(value) for value in (self.x, self.y, self.z)):
            raise ValueError("Saved work-zero coordinates must be finite")
        if not self.confirmed_axes or not self.confirmed_axes <= frozenset("XYZ"):
            raise ValueError("Saved work-zero axes must contain X, Y, or Z")


class WorkZeroStore:
    def __init__(self, path: Path, legacy_machine_id: str | None = None) -> None:
        self.path = path
        self.legacy_machine_id = legacy_machine_id

    def load(self, machine_id: str | None = None) -> SavedWorkZero | None:
        if not self.path.exists():
            return None
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if machine_id is not None and "machines" in data:
            data = data.get("machines", {}).get(machine_id)
            if data is None:
                return None
        elif machine_id is not None and self.legacy_machine_id is not None and machine_id != self.legacy_machine_id:
            return None
        data = dict(data)
        if "confirmed_axes" in data:
            data["confirmed_axes"] = frozenset(data["confirmed_axes"])
        saved = SavedWorkZero(**data)
        saved.validate()
        return saved

    def save(self, saved: SavedWorkZero, machine_id: str | None = None) -> None:
        saved.validate()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        serialized = {
            "x": saved.x,
            "y": saved.y,
            "z": saved.z,
            "confirmed_axes": [axis for axis in "XYZ" if axis in saved.confirmed_axes],
        }
        if machine_id is None:
            data = serialized
        else:
            data = self._load_catalog()
            data.setdefault("machines", {})[machine_id] = serialized
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
