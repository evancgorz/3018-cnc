"""Conservative parametric 3018 geometry used for rendering and safety checks."""

from __future__ import annotations

from dataclasses import dataclass
import math

from .models import PlantSnapshot, SimulationProfile


@dataclass(frozen=True)
class CoordinateFrame:
    """Immutable GRBL machine/work frame (WCO is machine minus work)."""

    work_offset: tuple[float, float, float] = (0.0, 0.0, 0.0)

    def __post_init__(self) -> None:
        values = tuple(float(value) for value in self.work_offset)
        if len(values) != 3 or not all(math.isfinite(value) for value in values):
            raise ValueError("Work offset must contain three finite values")
        object.__setattr__(self, "work_offset", values)

    def machine_to_work(self, point: tuple[float, float, float]) -> tuple[float, float, float]:
        values = self._point(point)
        return tuple(value - offset for value, offset in zip(values, self.work_offset))

    def work_to_machine(self, point: tuple[float, float, float]) -> tuple[float, float, float]:
        values = self._point(point)
        return tuple(value + offset for value, offset in zip(values, self.work_offset))

    def work_bounds_to_machine(self, bounds: "AABB") -> "AABB":
        bounds.validate()
        ox, oy, oz = self.work_offset
        return bounds.translated(ox, oy, oz)

    @staticmethod
    def _point(point: tuple[float, float, float]) -> tuple[float, float, float]:
        values = tuple(float(value) for value in point)
        if len(values) != 3 or not all(math.isfinite(value) for value in values):
            raise ValueError("Coordinate point must contain three finite values")
        return values


def frame_for(work_offset: tuple[float, float, float]) -> CoordinateFrame:
    """Return a validated immutable frame for a snapshot's WCO."""
    return CoordinateFrame(tuple(work_offset))


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

    def translated(self, x: float, y: float, z: float) -> "AABB":
        return AABB(self.min_x + x, self.min_y + y, self.min_z + z,
                    self.max_x + x, self.max_y + y, self.max_z + z)

    def penetrates(self, other: "AABB") -> bool:
        """Strict solid overlap; face/edge/point contact alone is safe."""
        return (self.max_x > other.min_x and other.max_x > self.min_x
                and self.max_y > other.min_y and other.max_y > self.min_y
                and self.max_z > other.min_z and other.max_z > self.min_z)

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
    """Conservative continuous AABB, including the active linear/arc path."""
    positions = _path_positions(previous, current)
    boxes = []
    for position in positions:
        snap = PlantSnapshot(current.time_ns, current.state, position, current.work_offset,
                             current.feed, current.spindle_target, current.spindle_rpm, current.pins)
        body = next(body for body in geometry.bodies(snap, profile) if body.name == body_name)
        boxes.append(body.bounds)
    result = boxes[0]
    for box in boxes[1:]:
        result = result.union(box)
    return result


def _path_positions(previous: PlantSnapshot, current: PlantSnapshot) -> tuple[tuple[float, float, float], ...]:
    """Sample the executed portion of a controller polyline, not its future."""
    motion = current.motion or previous.motion
    if motion is None or len(motion.path) < 2:
        return (previous.machine_position, current.machine_position)
    path = tuple(tuple(point) for point in motion.path)
    lengths = [math.dist(path[index], path[index + 1]) for index in range(len(path) - 1)]
    total = sum(lengths)
    if total <= 1e-12:
        return (previous.machine_position, current.machine_position)
    same_block = (previous.motion is not None and current.motion is not None
                  and previous.motion.block_id == current.motion.block_id)
    start_ratio = previous.motion.progress if same_block and previous.motion is not None else 0.0
    end_ratio = current.motion.progress if current.motion is not None else 1.0
    start_ratio = max(0.0, min(1.0, float(start_ratio)))
    end_ratio = max(start_ratio, min(1.0, float(end_ratio)))

    def at(distance: float) -> tuple[float, float, float]:
        remaining = max(0.0, min(total, distance))
        for start, end, length in zip(path, path[1:], lengths):
            if remaining <= length or length <= 1e-12:
                ratio = 0.0 if length <= 1e-12 else remaining / length
                return tuple(a + (b - a) * ratio for a, b in zip(start, end))
            remaining -= length
        return path[-1]

    points = [at(total * start_ratio)]
    distance = 0.0
    for index, length in enumerate(lengths):
        distance += length
        if total * start_ratio < distance < total * end_ratio:
            points.append(path[index + 1])
    points.append(at(total * end_ratio))
    points.extend((previous.machine_position, current.machine_position))
    return tuple(points)


def executed_path(previous: PlantSnapshot, current: PlantSnapshot) -> tuple[tuple[float, float, float], ...]:
    """Public immutable path view used by stock removal and safety assessors."""
    return _path_positions(previous, current)
