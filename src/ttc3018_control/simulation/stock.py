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
        collision_only = (model.face_plane != "XY" or any(patch.tilted for patch in model.surface_patches)
                          or not bool(model.surface_patches or model.features))
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
        unsupported = (model.face_plane != "XY"
                       or any(patch.tilted for patch in model.surface_patches)
                       or not bool(model.surface_patches or model.features))
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
        if model.face_plane != "XY" or any(patch.tilted for patch in model.surface_patches):
            raise ValueError("Only orthogonal planar STEP faces support stock targets")
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
        removed = 0.0
        r2 = radius * radius
        for iy in range(self.ny):
            for ix in range(self.nx):
                cx, cy = self._cell_center(ix, iy)
                if (cx - x) ** 2 + (cy - y) ** 2 > r2:
                    continue
                new_height = max(0.0, min(self.heights[iy][ix], bottom_z))
                removed += max(0.0, self.heights[iy][ix] - new_height) * self._cell_area(ix, iy)
                self.heights[iy][ix] = new_height
        return removed

    def remove_swept_segment(self, start: tuple[float, float, float], end: tuple[float, float, float], radius: float) -> float:
        distance = math.dist(start, end)
        steps = max(1, math.ceil(distance / max(self.resolution / 2, radius / 2)))
        removed = 0.0
        for index in range(steps + 1):
            ratio = index / steps
            point = tuple(a + (b - a) * ratio for a, b in zip(start, end))
            removed += self.remove_cylinder(point[0], point[1], point[2], radius)
        return removed

    def remove_swept_path(self, points: Iterable[tuple[float, float, float]], radius: float) -> float:
        """Remove only along the accepted, executed TCP polyline."""
        path = tuple(tuple(float(value) for value in point) for point in points)
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
