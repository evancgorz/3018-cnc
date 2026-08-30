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

    def load(self) -> SavedWorkZero | None:
        if not self.path.exists():
            return None
        saved = SavedWorkZero(**json.loads(self.path.read_text(encoding="utf-8")))
        saved.validate()
        return saved

    def save(self, saved: SavedWorkZero) -> None:
        saved.validate()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(asdict(saved), indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.path)

    def clear(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
