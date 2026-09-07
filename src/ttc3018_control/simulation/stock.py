"""Bounded deterministic stock/target model for executed 2.5D removal."""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from typing import Iterable

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


def load_step_target(path: Path, *, plane: str = "Auto (best 2.5D orientation)") -> StepTargetMetadata:
    """Load a STEP fixture through the existing isolated OCP importer.

    The returned metadata is observation-only; it cannot acknowledge commands
    or change the virtual controller. Unsupported removal details are surfaced
    as ``collision_only`` instead of being silently guessed.
    """
    from ..step_geometry import load_step_isolated
    model = load_step_isolated(Path(path), plane)
    return StepTargetMetadata(str(model.path), float(model.width), float(model.height),
                              float(model.thickness), len(model.loops), len(model.features),
                              collision_only=not bool(model.surface_patches or model.features))


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
                            target_volume, gouged, uncovered, self.cell_count, self.resolution)

    def to_render_grid(self) -> list[list[float]]:
        return [row[:] for row in self.heights]
