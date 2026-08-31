from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import math
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

    def establish_homed(self, machine_position: Position, profile: MachineProfile, homing_ends: dict[str, str]) -> None:
        """Establish the virtual minimum from a confirmed homing position."""
        profile.validate()
        values = {}
        for axis, current, travel in zip("XYZ", (machine_position.x, machine_position.y, machine_position.z), profile.travels):
            end = homing_ends.get(axis, "min")
            if end not in {"min", "max"}:
                raise ValueError(f"{axis} homing end must be min or max")
            values[axis] = current if end == "min" else current - travel
        self.reference = Position(values["X"], values["Y"], values["Z"])
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


def plan_safe_position_jogs(
    current: Position,
    target: Position,
    profile: MachineProfile,
) -> list[tuple[str, float]]:
    """Plan axis jogs to a virtual target, keeping lateral motion at a safe Z."""
    profile.validate()
    tolerance = VirtualEnvelope.TOLERANCE_MM
    for label, position in (("Current", current), ("Target", target)):
        for axis, value, maximum in zip("XYZ", (position.x, position.y, position.z), profile.travels):
            if not math.isfinite(value):
                raise ValueError(f"{label} {axis} coordinate must be a finite number")
            if value < -tolerance or value > maximum + tolerance:
                raise ValueError(
                    f"{label} {axis} coordinate {value:.3f} mm is outside the allowed range "
                    f"0.000 to {maximum:.3f} mm"
                )

    clearance_z = max(current.z, target.z, profile.safe_z)
    moves: list[tuple[str, float]] = []
    if clearance_z - current.z > tolerance:
        moves.append(("Z", clearance_z - current.z))
    for axis, distance in (("X", target.x - current.x), ("Y", target.y - current.y)):
        if abs(distance) > tolerance:
            moves.append((axis, distance))
    if abs(target.z - clearance_z) > tolerance:
        moves.append(("Z", target.z - clearance_z))
    return moves


def work_zero_virtual_target(machine_reference: Position, work_offset: Position) -> Position:
    """Return the virtual-machine coordinate of GRBL work X0 Y0 Z0."""
    return work_offset.minus(machine_reference)


def check_job_bounds(
    minimum: Position,
    maximum: Position,
    work_offset: Position,
    machine_reference: Position,
    profile: MachineProfile,
) -> tuple[bool, str]:
    """Transform work-coordinate job bounds into the virtual machine envelope."""
    profile.validate()
    work_origin = Position(
        work_offset.x - machine_reference.x,
        work_offset.y - machine_reference.y,
        work_offset.z - machine_reference.z,
    )
    for axis, low, high, offset, travel in (
        ("X", minimum.x, maximum.x, work_origin.x, profile.travel_x),
        ("Y", minimum.y, maximum.y, work_origin.y, profile.travel_y),
        ("Z", minimum.z, maximum.z, work_origin.z, profile.travel_z),
    ):
        machine_low = offset + low
        machine_high = offset + high
        if machine_low < -0.001 or machine_high > travel + 0.001:
            return (
                False,
                f"{axis} job range would be {machine_low:.3f}…{machine_high:.3f} mm in the virtual machine "
                f"envelope; allowed range is 0.000…{travel:.3f} mm.",
            )
    return True, "The transformed job bounds fit inside the virtual machine envelope."

