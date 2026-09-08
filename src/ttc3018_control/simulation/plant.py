"""Authoritative deterministic 3-axis machine plant."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Callable, Iterable

from .clock import SimulationClock
from .models import MotionSnapshot, PlantSnapshot, SimulationProfile


@dataclass
class MotionBlock:
    block_id: int
    start: tuple[float, float, float]
    target: tuple[float, float, float]
    feed: float
    rapid: bool = False
    probing: bool = False
    points: tuple[tuple[float, float, float], ...] = ()
    progress: float = 0.0

    @property
    def path(self) -> tuple[tuple[float, float, float], ...]:
        return self.points or (self.start, self.target)


@dataclass(frozen=True)
class ProbeCornerCircle:
    """Optional conductive vertical corner-circle used by the digital twin.

    Coordinates are machine-frame coordinates.  The circle is deliberately
    optional so the default twin retains the existing Z-only probe semantics.
    """

    center_x: float
    center_y: float
    radius: float
    z: float = 0.0

    def validate(self) -> None:
        values = (self.center_x, self.center_y, self.radius, self.z)
        if not all(math.isfinite(value) for value in values) or self.radius <= 0:
            raise ValueError("Probe corner circle must be finite with a positive radius")

    def to_dict(self) -> dict[str, float]:
        self.validate()
        return {"center_x": self.center_x, "center_y": self.center_y,
                "radius": self.radius, "z": self.z}

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "ProbeCornerCircle":
        circle = cls(float(value["center_x"]), float(value["center_y"]),
                     float(value["radius"]), float(value.get("z", 0.0)))
        circle.validate()
        return circle


@dataclass(frozen=True)
class ProbeBoundary:
    """Validated conductive closed XY polygon for simulation probing.

    Vertices are machine-frame XY coordinates.  The geometry is observation
    configuration only; it cannot acknowledge a command or mutate controller
    state.  A probe move intersects the closed edge continuously and reports
    the first contact along the executed segment.
    """

    vertices: tuple[tuple[float, float], ...]

    def validate(self) -> None:
        points = tuple((float(x), float(y)) for x, y in self.vertices)
        if len(points) < 3 or any(not math.isfinite(value) for point in points for value in point):
            raise ValueError("Probe boundary must contain at least three finite vertices")
        if any(math.dist(first, second) <= 1e-12 for first, second in zip(points, points[1:] + points[:1])):
            raise ValueError("Probe boundary has a zero-length edge")
        area = abs(sum(a[0] * b[1] - b[0] * a[1]
                       for a, b in zip(points, points[1:] + points[:1]))) / 2.0
        if area <= 1e-9:
            raise ValueError("Probe boundary must enclose a nonzero area")
        for first_index, first_start in enumerate(points):
            first_end = points[(first_index + 1) % len(points)]
            for second_index in range(first_index + 1, len(points)):
                if second_index in {first_index, (first_index - 1) % len(points),
                                     (first_index + 1) % len(points)}:
                    continue
                second_start = points[second_index]
                second_end = points[(second_index + 1) % len(points)]
                if _segments_intersect_2d(first_start, first_end, second_start, second_end):
                    raise ValueError("Probe boundary edges must not self-intersect")

    def to_dict(self) -> dict[str, list[list[float]]]:
        self.validate()
        return {"vertices": [[float(x), float(y)] for x, y in self.vertices]}

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "ProbeBoundary":
        raw = value.get("vertices")
        if not isinstance(raw, (list, tuple)):
            raise ValueError("Probe boundary vertices are required")
        try:
            boundary = cls(tuple((float(item[0]), float(item[1])) for item in raw))
        except (TypeError, IndexError, ValueError) as exc:
            raise ValueError("Probe boundary vertices must be finite XY pairs") from exc
        boundary.validate()
        return boundary

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        self.validate()
        xs = [point[0] for point in self.vertices]
        ys = [point[1] for point in self.vertices]
        return min(xs), min(ys), max(xs), max(ys)

    def contains(self, point: tuple[float, float], *, include_boundary: bool = False) -> bool:
        self.validate()
        x, y = (float(point[0]), float(point[1]))
        if not all(math.isfinite(value) for value in (x, y)):
            return False
        inside = False
        for start, end in zip(self.vertices, self.vertices[1:] + self.vertices[:1]):
            if _point_on_segment_2d(start, end, (x, y)):
                return include_boundary
            if (start[1] > y) != (end[1] > y):
                crossing = start[0] + (y - start[1]) * (end[0] - start[0]) / (end[1] - start[1])
                if x < crossing:
                    inside = not inside
        return inside

    def distance_to_boundary(self, point: tuple[float, float]) -> float:
        self.validate()
        return min(_point_segment_distance_2d(point, start, end)
                   for start, end in zip(self.vertices, self.vertices[1:] + self.vertices[:1]))

    def first_contact(self, start: tuple[float, float, float],
                      end: tuple[float, float, float]) -> tuple[float, float, float] | None:
        self.validate()
        start = tuple(float(value) for value in start)
        end = tuple(float(value) for value in end)
        if len(start) != 3 or len(end) != 3 or not all(math.isfinite(value) for value in (*start, *end)):
            raise ValueError("Probe path must contain six finite coordinates")
        candidates: list[float] = []
        for edge_start, edge_end in zip(self.vertices, self.vertices[1:] + self.vertices[:1]):
            candidates.extend(_segment_intersection_parameters(start[:2], end[:2], edge_start, edge_end))
        if not candidates:
            return None
        t = max(0.0, min(1.0, min(candidates)))
        return tuple(start[index] + (end[index] - start[index]) * t for index in range(3))


def _point_on_segment_2d(start: tuple[float, float], end: tuple[float, float],
                         point: tuple[float, float], epsilon: float = 1e-9) -> bool:
    cross = ((end[0] - start[0]) * (point[1] - start[1])
             - (end[1] - start[1]) * (point[0] - start[0]))
    if abs(cross) > epsilon:
        return False
    return (min(start[0], end[0]) - epsilon <= point[0] <= max(start[0], end[0]) + epsilon
            and min(start[1], end[1]) - epsilon <= point[1] <= max(start[1], end[1]) + epsilon)


def _segments_intersect_2d(first_start: tuple[float, float], first_end: tuple[float, float],
                           second_start: tuple[float, float], second_end: tuple[float, float]) -> bool:
    return bool(_segment_intersection_parameters(first_start, first_end, second_start, second_end))


def _segment_intersection_parameters(first_start: tuple[float, float], first_end: tuple[float, float],
                                     second_start: tuple[float, float], second_end: tuple[float, float]) -> tuple[float, ...]:
    dx, dy = first_end[0] - first_start[0], first_end[1] - first_start[1]
    ex, ey = second_end[0] - second_start[0], second_end[1] - second_start[1]
    denominator = dx * ey - dy * ex
    epsilon = 1e-10
    if abs(denominator) > epsilon:
        qx, qy = second_start[0] - first_start[0], second_start[1] - first_start[1]
        t = (qx * ey - qy * ex) / denominator
        u = (qx * dy - qy * dx) / denominator
        if -epsilon <= t <= 1.0 + epsilon and -epsilon <= u <= 1.0 + epsilon:
            return (max(0.0, min(1.0, t)),)
        return ()
    if abs((second_start[0] - first_start[0]) * dy
           - (second_start[1] - first_start[1]) * dx) > epsilon:
        return ()
    length_squared = dx * dx + dy * dy
    if length_squared <= epsilon * epsilon:
        return (0.0,) if _point_on_segment_2d(second_start, second_end, first_start) else ()
    parameters = []
    for point in (second_start, second_end):
        t = ((point[0] - first_start[0]) * dx + (point[1] - first_start[1]) * dy) / length_squared
        if -epsilon <= t <= 1.0 + epsilon:
            parameters.append(max(0.0, min(1.0, t)))
    if parameters:
        return tuple(parameters)
    return ()


def _point_segment_distance_2d(point: tuple[float, float], start: tuple[float, float],
                               end: tuple[float, float]) -> float:
    dx, dy = end[0] - start[0], end[1] - start[1]
    length_squared = dx * dx + dy * dy
    if length_squared <= 1e-24:
        return math.dist(point, start)
    ratio = ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length_squared
    ratio = max(0.0, min(1.0, ratio))
    return math.dist(point, (start[0] + ratio * dx, start[1] + ratio * dy))


class VirtualMachinePlant:
    """Continuous pose source used by both protocol and visual/collision layers."""

    def __init__(self, profile: SimulationProfile | None = None, *, clock: SimulationClock | None = None) -> None:
        self.profile = profile or SimulationProfile.default_3018()
        self.profile.validate()
        self.clock = clock or SimulationClock()
        self.position = [self.profile.initial_x, self.profile.initial_y, self.profile.initial_z]
        self.velocity = [0.0, 0.0, 0.0]
        self.work_offset = [self.profile.default_wco_x, self.profile.default_wco_y, self.profile.default_wco_z]
        self.queue: list[MotionBlock] = []
        self.active: MotionBlock | None = None
        self.state = "Idle"
        self.feed = 0.0
        self.current_speed = 0.0
        self.spindle_target = 0.0
        self.spindle_rpm = 0.0
        self.hold_requested = False
        self.probe_surface_z: float | None = None
        self.probe_corner_circle: ProbeCornerCircle | None = None
        self.probe_boundary: ProbeBoundary | None = None
        self.probe_active = False
        self.probe_contact: tuple[float, float, float] | None = None
        self.pins = ""
        self._next_block_id = 1
        self._sequence = 0
        self.on_block_complete: Callable[[MotionBlock], None] | None = None
        self.on_limit: Callable[[tuple[float, float, float]], None] | None = None

    @property
    def machine_position(self) -> tuple[float, float, float]:
        return tuple(self.position)

    @property
    def work_position(self) -> tuple[float, float, float]:
        return tuple(a - b for a, b in zip(self.position, self.work_offset))

    @property
    def busy(self) -> bool:
        return self.active is not None or bool(self.queue)

    def set_work_offset(self, values: tuple[float, float, float], axes: str = "XYZ") -> None:
        for index, axis in enumerate("XYZ"):
            if axis in axes.upper():
                value = float(values[index])
                if not math.isfinite(value):
                    raise ValueError("Work offset must be finite")
                self.work_offset[index] = value

    def set_spindle(self, target_rpm: float) -> None:
        if not math.isfinite(target_rpm) or target_rpm < 0:
            raise ValueError("Spindle RPM must be finite and nonnegative")
        self.spindle_target = target_rpm

    def enqueue(
        self,
        target: tuple[float, float, float],
        *,
        feed: float,
        rapid: bool = False,
        probing: bool = False,
        points: tuple[tuple[float, float, float], ...] = (),
    ) -> MotionBlock:
        if not all(math.isfinite(value) for value in target) or feed <= 0:
            raise ValueError("Motion target/feed must be finite and positive")
        block_start = tuple(self.position if self.active is None and not self.queue else (self.queue[-1].target if self.queue else self.active.target))
        block = MotionBlock(self._next_block_id, block_start, target, feed, rapid, probing, points)
        self._next_block_id += 1
        self.queue.append(block)
        if self.state == "Idle":
            self.state = "Jog" if probing is False and rapid and not self.queue[:-1] else "Run"
        return block

    def request_hold(self) -> None:
        self.hold_requested = True
        if self.busy:
            self.state = "Hold:0"

    def resume(self) -> None:
        self.hold_requested = False
        if self.active is not None or self.queue:
            self.state = "Jog" if self.active and self.active.rapid and not self.active.probing else "Run"

    def cancel_jog(self) -> None:
        if self.active is not None and self.active.rapid:
            self.active = None
        self.queue = [block for block in self.queue if not block.rapid]
        if not self.busy:
            self.state = "Idle"

    def reset(self) -> None:
        self.queue.clear()
        self.active = None
        self.velocity[:] = [0.0, 0.0, 0.0]
        self.feed = 0.0
        self.current_speed = 0.0
        self.spindle_target = 0.0
        self.hold_requested = False
        self.probe_active = False
        self.probe_contact = None
        self.state = "Idle"

    def advance(self, delta_ns: int) -> PlantSnapshot:
        self.clock.advance(delta_ns)
        dt = delta_ns / 1_000_000_000.0
        self._advance_spindle(dt)
        remaining = dt
        while remaining > 0 and (self.active is not None or self.queue):
            if self.active is None:
                self.active = self.queue.pop(0)
                self.active.start = tuple(self.position)
                if not self.hold_requested:
                    self.state = "Jog" if self.active.rapid else "Run"
            block = self.active
            if self.hold_requested:
                deceleration = self._path_acceleration(block)
                self.current_speed = max(0.0, self.current_speed - deceleration * remaining)
                if self.current_speed > 0 and block.progress < 1.0:
                    distance_total = self._path_location(block)[2]
                    new_distance = min(distance_total, block.progress * distance_total + self.current_speed * remaining)
                    block.progress = 1.0 if distance_total <= 1e-12 else new_distance / distance_total
                    self.position[:] = self._point_at_path(block.path, new_distance, distance_total)
                self.velocity[:] = [0.0, 0.0, 0.0]
                break
            path = block.path
            # Advance along a polyline at the commanded feed. This gives exact
            # deterministic endpoints while preserving intermediate Z/arc points.
            segment_index, local_progress, distance_total = self._path_location(block)
            commanded_speed = min(block.feed, self._axis_feed_limit(block)) / 60.0
            acceleration = self._path_acceleration(block)
            self.current_speed = min(commanded_speed, self.current_speed + acceleration * remaining)
            distance_step = self.current_speed * remaining
            new_distance = min(distance_total, block.progress * distance_total + distance_step)
            block.progress = 1.0 if distance_total <= 1e-12 else new_distance / distance_total
            previous_position = tuple(self.position)
            self.position[:] = self._point_at_path(path, new_distance, distance_total)
            self.feed = block.feed
            self._check_limits()
            if block.probing and self._check_corner_probe(previous_position, tuple(self.position), block):
                block.progress = 1.0
            if block.probing and self.probe_surface_z is not None and self.position[2] <= self.probe_surface_z:
                self.position[2] = self.probe_surface_z
                self.probe_active = True
                self.probe_contact = tuple(self.position)
                block.progress = 1.0
            if block.progress >= 1.0 - 1e-12:
                completed = block
                self.active = None
                self.feed = 0.0
                self.current_speed = 0.0
                self.velocity[:] = [0.0, 0.0, 0.0]
                if self.on_block_complete:
                    self.on_block_complete(completed)
                if not self.queue:
                    self.state = "Idle"
                remaining = 0.0
            else:
                remaining = 0.0
        self._sequence += 1
        return self.snapshot()

    def _check_corner_probe(self, start: tuple[float, float, float],
                            end: tuple[float, float, float], block: MotionBlock) -> bool:
        boundary = self.probe_boundary
        if block.probing and boundary is not None:
            contact = boundary.first_contact(start, end)
            if contact is not None:
                self.position[:] = contact
                self.probe_active = True
                self.probe_contact = contact
                return True
        circle = self.probe_corner_circle
        if not block.probing or circle is None:
            return False
        # The optional plate is a conductive vertical edge.  Probe contact is
        # the first swept XY intersection with its circle; Z probing remains
        # independently governed by probe_surface_z above.
        cx, cy, radius = circle.center_x, circle.center_y, circle.radius
        sx, sy = start[0] - cx, start[1] - cy
        ex, ey = end[0] - cx, end[1] - cy
        dx, dy = ex - sx, ey - sy
        a = dx * dx + dy * dy
        if a <= 1e-18:
            return False
        b = 2.0 * (sx * dx + sy * dy)
        c = sx * sx + sy * sy - radius * radius
        discriminant = b * b - 4.0 * a * c
        if discriminant < -1e-12:
            return False
        roots = () if discriminant < 0 else (
            (-b - math.sqrt(max(0.0, discriminant))) / (2.0 * a),
            (-b + math.sqrt(max(0.0, discriminant))) / (2.0 * a),
        )
        candidates = sorted(t for t in roots if -1e-9 <= t <= 1.0 + 1e-9)
        if not candidates:
            return False
        t = max(0.0, min(1.0, candidates[0]))
        contact = tuple(start[index] + (end[index] - start[index]) * t for index in range(3))
        self.position[:] = contact
        self.probe_active = True
        self.probe_contact = contact
        return True

    def snapshot(self) -> PlantSnapshot:
        motion = None
        if self.active is not None:
            block = self.active
            motion = MotionSnapshot(
                block.block_id, block.start, block.target, block.rapid,
                block.probing, block.feed, block.progress,
                tuple(block.path),
            )
        return PlantSnapshot(
            self.clock.time_ns, self.state, self.machine_position,
            tuple(self.work_offset), self.feed, self.spindle_target,
            self.spindle_rpm, self.pins, motion, self._sequence,
        )

    def _advance_spindle(self, dt: float) -> None:
        delta = self.spindle_target - self.spindle_rpm
        rate = self.profile.spindle_acceleration if delta > 0 else self.profile.spindle_deceleration
        step = rate * dt
        self.spindle_rpm += max(-step, min(step, delta))
        if abs(self.spindle_rpm) < 1e-9:
            self.spindle_rpm = 0.0

    def _axis_feed_limit(self, block: MotionBlock) -> float:
        delta = [abs(b - a) for a, b in zip(block.start, block.target)]
        limits = (self.profile.max_feed_x, self.profile.max_feed_y, self.profile.max_feed_z)
        length = math.sqrt(sum(value * value for value in delta))
        if length <= 1e-12:
            return block.feed
        unit = [value / length for value in delta]
        limits_along_path = [limit / component for limit, component in zip(limits, unit) if component > 1e-12]
        return min([block.feed, *limits_along_path])

    def _path_acceleration(self, block: MotionBlock) -> float:
        delta = [abs(b - a) for a, b in zip(block.start, block.target)]
        length = math.sqrt(sum(value * value for value in delta))
        if length <= 1e-12:
            return min(self.profile.acceleration_x, self.profile.acceleration_y, self.profile.acceleration_z)
        unit = [value / length for value in delta]
        accelerations = (self.profile.acceleration_x, self.profile.acceleration_y, self.profile.acceleration_z)
        return min(acceleration / component for acceleration, component in zip(accelerations, unit) if component > 1e-12)

    def _path_location(self, block: MotionBlock) -> tuple[int, float, float]:
        path = block.path
        lengths = [math.dist(path[i], path[i + 1]) for i in range(len(path) - 1)]
        return 0, 0.0, sum(lengths)

    @staticmethod
    def _point_at_path(path: tuple[tuple[float, float, float], ...], distance: float, total: float) -> tuple[float, float, float]:
        if total <= 1e-12:
            return path[-1]
        remaining = distance
        for start, end in zip(path, path[1:]):
            length = math.dist(start, end)
            if remaining <= length or length <= 1e-12:
                ratio = 0.0 if length <= 1e-12 else remaining / length
                return tuple(a + (b - a) * ratio for a, b in zip(start, end))
            remaining -= length
        return path[-1]

    def _check_limits(self) -> None:
        limits = (self.profile.travel_x, self.profile.travel_y, self.profile.travel_z)
        if any(value < -1e-6 or value > limit + 1e-6 for value, limit in zip(self.position, limits)):
            self.position[:] = [max(0.0, min(value, limit)) for value, limit in zip(self.position, limits)]
            self.state = "Alarm"
            self.queue.clear()
            self.active = None
            if self.on_limit:
                self.on_limit(self.machine_position)
