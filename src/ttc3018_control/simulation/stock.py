"""Bounded deterministic stock/target model for executed 2.5D removal."""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from typing import Any, Iterable

from .models import SimulationProfile, SimulationWorkpiece


@dataclass(frozen=True)
class StepTargetMetadata:
    """Immutable normalized STEP observation passed to simulation/supervisor."""

    path: str
    width: float
    height: float
    thickness: float
    loop_count: int
    feature_count: int
    collision_only: bool = False
    origin_x: float = 0.0
    origin_y: float = 0.0
    origin_z: float = 0.0


def load_step_target(path: Path, *, plane: str = "Auto (best 2.5D orientation)") -> StepTargetMetadata:
    """Load a STEP fixture through the existing isolated OCP importer.

    The returned metadata is observation-only; it cannot acknowledge commands
    or change the virtual controller. Unsupported removal details are surfaced
    as ``collision_only`` instead of being silently guessed.
    """
    from ..step_geometry import load_step_isolated
    model = load_step_isolated(Path(path), plane)
    min_x = min(loop.bounds[0] for loop in model.loops)
    min_y = min(loop.bounds[1] for loop in model.loops)
    collision_only = (model.face_plane != "XY" or any(patch.tilted for patch in model.surface_patches)
                      or not bool(model.surface_patches or model.features))
    return StepTargetMetadata(str(model.path), float(model.width), float(model.height),
                              float(model.thickness), len(model.loops), len(model.features),
                              collision_only=collision_only, origin_x=float(min_x), origin_y=float(min_y))


@dataclass(frozen=True)
class StockMetrics:
    stock_volume: float
    removed_volume: float
    remaining_volume: float
    target_volume: float | None
    gouged_volume: float
    uncovered_volume: float
    cell_count: int
    resolution: float
    undercut_volume: float = 0.0
    overcut_volume: float = 0.0
    collision_only: bool = False


class StockModel:
    """Height-map stock with a conservative cell budget.

    Heights are the remaining top surface in workpiece coordinates. This is
    intentionally bounded and transparent; collision checks still cover the
    tool/holder/fixture solids independently.
    """

    def __init__(self, workpiece: SimulationWorkpiece, profile: SimulationProfile | None = None) -> None:
        workpiece.validate()
        self.workpiece = workpiece
        self.profile = profile or SimulationProfile.default_3018()
        self.resolution = self.profile.stock_resolution
        self.nx = max(1, math.ceil(workpiece.stock_width / self.resolution))
        self.ny = max(1, math.ceil(workpiece.stock_height / self.resolution))
        if self.nx * self.ny > self.profile.max_stock_cells:
            raise ValueError("Stock grid exceeds configured cell budget")
        self.heights = [[workpiece.stock_thickness for _ in range(self.nx)] for _ in range(self.ny)]
        self._initial_volume = workpiece.stock_width * workpiece.stock_height * workpiece.stock_thickness
        self._target_heights: list[list[float]] | None = None

    @classmethod
    def from_step_model(cls, model: Any, profile: SimulationProfile | None = None) -> "StockModel":
        """Create a work-frame stock and target field from a planar STEP model."""
        from ..step_geometry import StepPlanarModel
        if not isinstance(model, StepPlanarModel):
            raise TypeError("Expected a normalized StepPlanarModel")
        min_x = min(loop.bounds[0] for loop in model.loops)
        min_y = min(loop.bounds[1] for loop in model.loops)
        collision_only = (model.face_plane not in {"XY", "ARBITRARY"}
                          or any(patch.tilted for patch in model.surface_patches)
                          or (model.face_plane != "ARBITRARY" and not bool(model.surface_patches or model.features)))
        workpiece = SimulationWorkpiece(
            path=str(model.path), stock_width=model.width, stock_height=model.height,
            stock_thickness=model.thickness, origin_x=min_x, origin_y=min_y,
            origin_z=0.0, collision_only=collision_only)
        stock = cls(workpiece, profile)
        if not collision_only:
            stock.set_target_height_field(stock.target_height_field_from_step(model))
        return stock

    @classmethod
    def from_workpiece(cls, workpiece: SimulationWorkpiece,
                       profile: SimulationProfile | None = None) -> "StockModel":
        """Build bounded stock and, when declared, load its isolated STEP target."""
        stock = cls(workpiece, profile)
        if not workpiece.path:
            return stock
        from ..step_geometry import load_step_isolated
        model = load_step_isolated(Path(workpiece.path))
        unsupported = (model.face_plane not in {"XY", "ARBITRARY"}
                       or any(patch.tilted for patch in model.surface_patches)
                       or (model.face_plane != "ARBITRARY" and not bool(model.surface_patches or model.features)))
        if unsupported:
            stock.workpiece = SimulationWorkpiece(
                **{**workpiece.__dict__, "collision_only": True})
            return stock
        stock.set_target_height_field(stock.target_height_field_from_step(model))
        return stock

    def target_height_field_from_step(self, model: Any) -> list[list[float]]:
        """Return a deterministic height map preserving nested pocket islands."""
        from ..step_geometry import StepPlanarModel
        if not isinstance(model, StepPlanarModel):
            raise TypeError("Expected a normalized StepPlanarModel")
        if model.face_plane not in {"XY", "ARBITRARY"} or any(patch.tilted for patch in model.surface_patches):
            raise ValueError("Only normalized planar STEP faces support stock targets")
        min_x = min(loop.bounds[0] for loop in model.loops)
        min_y = min(loop.bounds[1] for loop in model.loops)
        roles = model.loop_roles
        depths = model.loop_depths
        feature_depth = {feature.loop_index: max(0.0, min(model.thickness, feature.depth))
                         for feature in model.features}
        rows: list[list[float]] = []
        for iy in range(self.ny):
            row: list[float] = []
            for ix in range(self.nx):
                x, y = self._cell_center(ix, iy)
                absolute_x, absolute_y = min_x + x, min_y + y
                containing = [index for index, loop in enumerate(model.loops)
                              if _point_in_loop(absolute_x, absolute_y, loop)]
                if not containing:
                    row.append(self.workpiece.stock_thickness)
                    continue
                deepest = max(containing, key=lambda index: depths[index])
                if roles[deepest] == "cutout":
                    row.append(self.workpiece.stock_thickness - feature_depth.get(deepest, 0.0))
                else:
                    row.append(self.workpiece.stock_thickness)
            rows.append(row)
        return rows

    def _cell_area(self, ix: int, iy: int) -> float:
        """Return the exact XY area represented by a bounded grid cell."""
        width = min(self.resolution, max(0.0, self.workpiece.stock_width - ix * self.resolution))
        height = min(self.resolution, max(0.0, self.workpiece.stock_height - iy * self.resolution))
        return width * height

    def _cell_center(self, ix: int, iy: int) -> tuple[float, float]:
        """Return the center of a full or partial boundary cell."""
        width = min(self.resolution, max(0.0, self.workpiece.stock_width - ix * self.resolution))
        height = min(self.resolution, max(0.0, self.workpiece.stock_height - iy * self.resolution))
        return ix * self.resolution + width / 2, iy * self.resolution + height / 2

    def _cell_bounds(self, ix: int, iy: int) -> tuple[float, float, float, float]:
        """Return the exact XY rectangle represented by one bounded cell."""
        return (
            ix * self.resolution,
            iy * self.resolution,
            min(self.workpiece.stock_width, (ix + 1) * self.resolution),
            min(self.workpiece.stock_height, (iy + 1) * self.resolution),
        )

    @property
    def cell_count(self) -> int:
        return self.nx * self.ny

    def set_target_height_field(self, heights: Iterable[Iterable[float]]) -> None:
        rows = [list(map(float, row)) for row in heights]
        if len(rows) != self.ny or any(len(row) != self.nx for row in rows):
            raise ValueError("Target height field dimensions do not match stock")
        if any(not math.isfinite(v) or v < 0 or v > self.workpiece.stock_thickness for row in rows for v in row):
            raise ValueError("Target heights must be finite and inside stock")
        self._target_heights = rows

    @property
    def target_height_field(self) -> list[list[float]] | None:
        """Return a defensive copy of the immutable target observation."""
        return None if self._target_heights is None else [row[:] for row in self._target_heights]

    def remove_cylinder(self, x: float, y: float, bottom_z: float, radius: float) -> float:
        if radius <= 0 or not all(math.isfinite(v) for v in (x, y, bottom_z, radius)):
            raise ValueError("Invalid cutter sweep")
        return self.remove_swept_segment((x, y, bottom_z), (x, y, bottom_z), radius)

    def remove_swept_segment(self, start: tuple[float, float, float], end: tuple[float, float, float], radius: float) -> float:
        start = _finite_point(start)
        end = _finite_point(end)
        if radius <= 0 or not math.isfinite(radius):
            raise ValueError("Invalid cutter sweep")
        min_x = min(start[0], end[0]) - radius
        max_x = max(start[0], end[0]) + radius
        min_y = min(start[1], end[1]) - radius
        max_y = max(start[1], end[1]) + radius
        # Expand the integer range by a tiny deterministic epsilon so a
        # sweep tangent to a cell boundary still visits both adjacent cells.
        boundary_epsilon = 1e-12 * max(1.0, self.resolution)
        first_x = max(0, math.floor((min_x - boundary_epsilon) / self.resolution))
        last_x = min(self.nx - 1, math.floor((max_x + boundary_epsilon) / self.resolution))
        first_y = max(0, math.floor((min_y - boundary_epsilon) / self.resolution))
        last_y = min(self.ny - 1, math.floor((max_y + boundary_epsilon) / self.resolution))
        if first_x > last_x or first_y > last_y:
            return 0.0
        # A linear segment has its minimum Z at one of its endpoints.  Using
        # that minimum for every intersected cell is conservative and stable
        # for ramps while retaining the accepted executed segment as the sole
        # source of removal.
        bottom_z = min(start[2], end[2])
        removed = 0.0
        for iy in range(first_y, last_y + 1):
            for ix in range(first_x, last_x + 1):
                if not _segment_intersects_cell(start[:2], end[:2], self._cell_bounds(ix, iy), radius):
                    continue
                new_height = max(0.0, min(self.heights[iy][ix], bottom_z))
                removed += max(0.0, self.heights[iy][ix] - new_height) * self._cell_area(ix, iy)
                self.heights[iy][ix] = new_height
        return removed

    def remove_swept_path(self, points: Iterable[tuple[float, float, float]], radius: float) -> float:
        """Remove only along the accepted, executed TCP polyline."""
        path = tuple(_finite_point(point) for point in points)
        if len(path) < 2:
            return 0.0
        return sum(self.remove_swept_segment(start, end, radius)
                   for start, end in zip(path, path[1:]))

    def metrics(self) -> StockMetrics:
        remaining = sum(
            self.heights[iy][ix] * self._cell_area(ix, iy)
            for iy in range(self.ny) for ix in range(self.nx)
        )
        target_volume = None
        gouged = uncovered = 0.0
        if self._target_heights is not None:
            target_volume = sum(
                self._target_heights[iy][ix] * self._cell_area(ix, iy)
                for iy in range(self.ny) for ix in range(self.nx)
            )
            for iy, (actual_row, target_row) in enumerate(zip(self.heights, self._target_heights)):
                for ix, (actual, target) in enumerate(zip(actual_row, target_row)):
                    area = self._cell_area(ix, iy)
                    gouged += max(0.0, target - actual) * area
                    uncovered += max(0.0, actual - target) * area
        return StockMetrics(self._initial_volume, self._initial_volume - remaining, remaining,
                            target_volume, gouged, uncovered, self.cell_count, self.resolution,
                            undercut_volume=uncovered, overcut_volume=gouged,
                            collision_only=self.workpiece.collision_only)

    def to_render_grid(self) -> list[list[float]]:
        return [row[:] for row in self.heights]


def _point_in_loop(x: float, y: float, loop: Any) -> bool:
    """Deterministic half-open ray crossing test for STEP polygon samples."""
    points = loop.points
    inside = False
    for first, second in zip(points, points[1:] + points[:1]):
        if (first.y > y) != (second.y > y):
            crossing = (second.x - first.x) * (y - first.y) / (second.y - first.y) + first.x
            if x < crossing:
                inside = not inside
    return inside


def _finite_point(point: Iterable[float]) -> tuple[float, float, float]:
    """Normalize one executed XYZ point and reject malformed/nonfinite data."""
    values = tuple(float(value) for value in point)
    if len(values) != 3 or not all(math.isfinite(value) for value in values):
        raise ValueError("Cutter path points must contain three finite coordinates")
    return values


def _segment_intersects_cell(
    start: tuple[float, float],
    end: tuple[float, float],
    bounds: tuple[float, float, float, float],
    radius: float,
) -> bool:
    """Return whether a cylindrical XY sweep intersects a cell rectangle.

    The distance test is inclusive so tangent contact is represented.  It
    checks the exact segment/rectangle distance rather than sampling cell
    centers, while the caller bounds iteration by the sweep AABB plus radius.
    """
    min_x, min_y, max_x, max_y = bounds
    if _point_in_rectangle(start, bounds) or _point_in_rectangle(end, bounds):
        return True
    edges = (
        ((min_x, min_y), (max_x, min_y)),
        ((max_x, min_y), (max_x, max_y)),
        ((max_x, max_y), (min_x, max_y)),
        ((min_x, max_y), (min_x, min_y)),
    )
    if any(_segments_intersect(start, end, edge_start, edge_end) for edge_start, edge_end in edges):
        return True
    return min(_segment_distance(start, end, edge_start, edge_end) for edge_start, edge_end in edges) <= radius + 1e-12


def _point_in_rectangle(point: tuple[float, float], bounds: tuple[float, float, float, float]) -> bool:
    min_x, min_y, max_x, max_y = bounds
    return min_x <= point[0] <= max_x and min_y <= point[1] <= max_y


def _segments_intersect(
    first_start: tuple[float, float], first_end: tuple[float, float],
    second_start: tuple[float, float], second_end: tuple[float, float],
) -> bool:
    epsilon = 1e-12

    def orientation(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> float:
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    def on_segment(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> bool:
        return (min(a[0], b[0]) - epsilon <= c[0] <= max(a[0], b[0]) + epsilon
                and min(a[1], b[1]) - epsilon <= c[1] <= max(a[1], b[1]) + epsilon)

    first = orientation(first_start, first_end, second_start)
    second = orientation(first_start, first_end, second_end)
    third = orientation(second_start, second_end, first_start)
    fourth = orientation(second_start, second_end, first_end)
    if ((first > epsilon and second < -epsilon) or (first < -epsilon and second > epsilon)) \
            and ((third > epsilon and fourth < -epsilon) or (third < -epsilon and fourth > epsilon)):
        return True
    return ((abs(first) <= epsilon and on_segment(first_start, first_end, second_start))
            or (abs(second) <= epsilon and on_segment(first_start, first_end, second_end))
            or (abs(third) <= epsilon and on_segment(second_start, second_end, first_start))
            or (abs(fourth) <= epsilon and on_segment(second_start, second_end, first_end)))


def _point_segment_distance(point: tuple[float, float], start: tuple[float, float], end: tuple[float, float]) -> float:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length_squared = dx * dx + dy * dy
    if length_squared <= 1e-24:
        return math.dist(point, start)
    ratio = ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length_squared
    ratio = max(0.0, min(1.0, ratio))
    return math.dist(point, (start[0] + ratio * dx, start[1] + ratio * dy))


def _segment_distance(
    first_start: tuple[float, float], first_end: tuple[float, float],
    second_start: tuple[float, float], second_end: tuple[float, float],
) -> float:
    if _segments_intersect(first_start, first_end, second_start, second_end):
        return 0.0
    return min(
        _point_segment_distance(first_start, second_start, second_end),
        _point_segment_distance(first_end, second_start, second_end),
        _point_segment_distance(second_start, first_start, first_end),
        _point_segment_distance(second_end, first_start, first_end),
    )
