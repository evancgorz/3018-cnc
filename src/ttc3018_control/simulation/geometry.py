"""Conservative parametric 3018 geometry used for rendering and safety checks."""

from __future__ import annotations

from dataclasses import dataclass
import math

from .models import PlantSnapshot, SimulationProfile


@dataclass(frozen=True)
class AABB:
    min_x: float
    min_y: float
    min_z: float
    max_x: float
    max_y: float
    max_z: float

    def validate(self) -> None:
        if not all(math.isfinite(v) for v in self.__dict__.values()):
            raise ValueError("Geometry bounds must be finite")
        if self.min_x > self.max_x or self.min_y > self.max_y or self.min_z > self.max_z:
            raise ValueError("Geometry bounds are inverted")

    def intersects(self, other: "AABB", *, tolerance: float = 0.0) -> bool:
        return not (
            self.max_x < other.min_x - tolerance or other.max_x < self.min_x - tolerance
            or self.max_y < other.min_y - tolerance or other.max_y < self.min_y - tolerance
            or self.max_z < other.min_z - tolerance or other.max_z < self.min_z - tolerance
        )

    def expanded(self, value: float) -> "AABB":
        return AABB(self.min_x - value, self.min_y - value, self.min_z - value,
                    self.max_x + value, self.max_y + value, self.max_z + value)

    def union(self, other: "AABB") -> "AABB":
        return AABB(min(self.min_x, other.min_x), min(self.min_y, other.min_y), min(self.min_z, other.min_z),
                    max(self.max_x, other.max_x), max(self.max_y, other.max_y), max(self.max_z, other.max_z))


@dataclass(frozen=True)
class GeometryBody:
    name: str
    bounds: AABB
    moving: bool = False
    category: str = "machine"


@dataclass(frozen=True)
class MachineGeometryProfile:
    """Visual/collision proxies; travel is authoritative, body dimensions are not factory CAD."""

    schema_version: int = 1
    base_margin: float = 8.0
    frame_height: float = 45.0
    gantry_height: float = 38.0
    spindle_radius: float = 10.0
    carriage_width: float = 35.0
    carriage_depth: float = 35.0
    holder_radius: float = 6.0
    tool_radius: float = 1.5
    tool_length: float = 20.0
    holder_length: float = 35.0

    def validate(self) -> None:
        if self.schema_version != 1:
            raise ValueError("Unsupported geometry schema")
        values = self.__dict__.copy()
        values.pop("schema_version")
        if not all(math.isfinite(float(v)) and float(v) > 0 for v in values.values()):
            raise ValueError("Geometry proxy dimensions must be finite and positive")

    @classmethod
    def default_3018(cls, profile: SimulationProfile | None = None) -> "MachineGeometryProfile":
        return cls(tool_radius=(profile.tool_radius if profile else 1.5),
                   tool_length=(profile.tool_length if profile else 20.0),
                   holder_radius=(profile.holder_radius if profile else 6.0),
                   holder_length=(profile.holder_length if profile else 35.0))

    def bodies(self, snapshot: PlantSnapshot, machine: SimulationProfile) -> tuple[GeometryBody, ...]:
        self.validate()
        x, y, z = snapshot.machine_position
        # These are deliberately conservative collision/render proxies. The tip
        # coordinate follows GRBL exactly; gantry/body dimensions are not claimed
        # as manufacturer measurements.
        base = GeometryBody("bed", AABB(-self.base_margin, -self.base_margin, -8.0,
                                        machine.travel_x + self.base_margin,
                                        machine.travel_y + self.base_margin, -0.1))
        # Uprights sit just outside the authoritative tool-center envelope;
        # the holder at X=0/X=max is therefore a safe nominal pose, while an
        # out-of-envelope or swept overshoot can still intersect the frame.
        left = GeometryBody("left-upright", AABB(-2 * self.base_margin, -self.base_margin, 0.0,
                                                  -self.base_margin, machine.travel_y + self.base_margin,
                                                  self.frame_height))
        right = GeometryBody("right-upright", AABB(machine.travel_x + self.base_margin, -self.base_margin, 0.0,
                                                   machine.travel_x + 2 * self.base_margin,
                                                   machine.travel_y + self.base_margin, self.frame_height))
        gantry = GeometryBody("x-gantry", AABB(-self.base_margin, y - self.carriage_depth / 2,
                                                self.gantry_height - 4,
                                                machine.travel_x + self.base_margin, y + self.carriage_depth / 2,
                                                self.gantry_height + 4), moving=True)
        carriage = GeometryBody("z-carriage", AABB(x - self.carriage_width / 2, y - self.carriage_depth / 2,
                                                    z, x + self.carriage_width / 2,
                                                    y + self.carriage_depth / 2, z + self.frame_height), moving=True)
        # GRBL Z is the cutter-tip coordinate in the application's positive-up
        # convention. The cutter and holder extend upward from the tip; a
        # negative work-Z therefore enters stock while the holder stays clear.
        tool = GeometryBody("cutter", AABB(x - self.tool_radius, y - self.tool_radius,
                                             z, x + self.tool_radius, y + self.tool_radius,
                                             z + self.tool_length), moving=True, category="tool")
        holder = GeometryBody("tool-holder", AABB(x - self.holder_radius, y - self.holder_radius,
                                                   z + self.tool_length, x + self.holder_radius,
                                                   y + self.holder_radius,
                                                   z + self.tool_length + self.holder_length),
                             moving=True, category="tool")
        return (base, left, right, gantry, carriage, holder, tool)


def swept_bounds(previous: PlantSnapshot, current: PlantSnapshot, body_name: str,
                 geometry: MachineGeometryProfile, profile: SimulationProfile) -> AABB:
    """Conservative continuous AABB for a moving tool/body between snapshots."""
    positions = [previous.machine_position, current.machine_position]
    boxes = []
    for position in positions:
        snap = PlantSnapshot(current.time_ns, current.state, position, current.work_offset,
                             current.feed, current.spindle_target, current.spindle_rpm, current.pins)
        body = next(body for body in geometry.bodies(snap, profile) if body.name == body_name)
        boxes.append(body.bounds)
    return boxes[0].union(boxes[1])
