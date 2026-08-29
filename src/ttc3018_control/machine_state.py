from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path

from .grbl import Position


@dataclass(frozen=True)
class MachineProfile:
    name: str = "Two Trees TTC 3018"
    travel_x: float = 0.0
    travel_y: float = 0.0
    travel_z: float = 0.0
    safe_z: float = 0.0

    def validate(self) -> None:
        if not self.name.strip():
            raise ValueError("Machine name cannot be empty")
        for axis, value in zip("XYZ", self.travels):
            if value <= 0:
                raise ValueError(f"{axis} travel must be greater than zero")
        if not 0 <= self.safe_z <= self.travel_z:
            raise ValueError("Safe Z must be between 0 and the configured Z travel")

    @property
    def travels(self) -> tuple[float, float, float]:
        return self.travel_x, self.travel_y, self.travel_z

    def travel_for(self, axis: str) -> float:
        return getattr(self, f"travel_{axis.lower()}")


class ProfileStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> MachineProfile:
        if not self.path.exists():
            return MachineProfile()
        data = json.loads(self.path.read_text(encoding="utf-8"))
        return MachineProfile(**data)

    def save(self, profile: MachineProfile) -> None:
        profile.validate()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(asdict(profile), indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.path)


class VirtualEnvelope:
    """Session-only coordinates measured from a user-established physical reference."""

    TOLERANCE_MM = 0.001

    def __init__(self) -> None:
        self.reference: Position | None = None
        self.invalid_reason = "No reference has been established"

    @property
    def trusted(self) -> bool:
        return self.reference is not None

    def establish(self, machine_position: Position, profile: MachineProfile) -> None:
        profile.validate()
        self.reference = machine_position
        self.invalid_reason = ""

    def invalidate(self, reason: str) -> None:
        self.reference = None
        self.invalid_reason = reason

    def relative_position(self, machine_position: Position) -> Position | None:
        if self.reference is None:
            return None
        return Position(
            machine_position.x - self.reference.x,
            machine_position.y - self.reference.y,
            machine_position.z - self.reference.z,
        )

    def check_jog(
        self,
        axis: str,
        distance_mm: float,
        machine_position: Position,
        profile: MachineProfile,
    ) -> tuple[bool, str]:
        if not self.trusted:
            return False, self.invalid_reason
        profile.validate()
        relative = self.relative_position(machine_position)
        assert relative is not None
        current = getattr(relative, axis.lower())
        proposed = current + distance_mm
        maximum = profile.travel_for(axis)
        if proposed < -self.TOLERANCE_MM or proposed > maximum + self.TOLERANCE_MM:
            return (
                False,
                f"{axis} jog would end at {proposed:.3f} mm; allowed range is 0.000 to {maximum:.3f} mm",
            )
        return True, f"{axis} target {proposed:.3f} mm is within the virtual envelope"

