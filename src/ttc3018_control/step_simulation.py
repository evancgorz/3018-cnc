"""Deterministic, bounded stock simulation for flat 2.5D operations.

This module deliberately models only the part of stock that can be proven by
the current vertical-tool strategies.  It is independent of Qt, OpenCASCADE,
and the controller, so generation can fail closed before a program is loaded
or sent to a machine.  The simulator is not a substitute for a future
resolution-based height map for ramps or a full collision kernel.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable

from shapely.geometry import LineString, Polygon, box
from shapely.ops import unary_union

from .text_engraver import Stroke


class StepSimulationError(ValueError):
    """A generated flat toolpath failed the bounded stock simulation."""


@dataclass(frozen=True)
class StepStockSimulation:
    """Summary of a swept-cutter simulation over a planar stock region."""

    stock_width: float
    stock_height: float
    stock_thickness: float | None
    target_depth: float
    target_area: float
    reachable_area: float
    unreachable_area: float
    swept_area: float
    uncovered_area: float
    allowed_uncovered_area: float
    gouged_area: float
    allowed_gouged_area: float
    checked_strokes: int
    cutting_segments: int
    passes: int

    @property
    def passed(self) -> bool:
        return (
            self.uncovered_area <= self.allowed_uncovered_area
            and self.gouged_area <= self.allowed_gouged_area
        )


def simulate_flat_stock_paths(
    strokes: Iterable[Stroke],
    target_region,
    tool_radius: float,
    target_depth: float,
    *,
    stock_width: float | None = None,
    stock_height: float | None = None,
    stock_thickness: float | None = None,
    breakthrough: float = 0.0,
    passes: int = 1,
    retained_region=None,
    tolerance: float = 0.02,
) -> StepStockSimulation:
    """Sweep a cylindrical cutter over flat paths and verify removal coverage.

    ``target_region`` is the planar material intended for removal.  Every
    centerline must remain in its radius-eroded reachable region, while the
    union of the swept cutter footprints must cover the tool-reachable portion
    of the target region within a small, explicit area tolerance.  Sharp
    corners and other areas smaller than the selected cutter are intentionally
    reported as unreachable instead of being treated as a false coverage
    failure.  If ``retained_region`` is supplied, any
    swept overlap is treated as a gouge and fails closed.

    The stock dimensions are optional because callers that already validated
    the machining envelope may not have a physical XY stock polygon.  When
    supplied, the cutter sweep must remain inside that rectangle.  A physical
    stock thickness limits the requested depth; ``breakthrough`` is the only
    permitted amount below its bottom.
    """
    _validate_number("Tool radius", tool_radius, minimum=0.0, strict=True)
    _validate_number("Target depth", target_depth, maximum=-1e-9, strict=False)
    _validate_number("Tolerance", tolerance, minimum=0.0, strict=False)
    if not isinstance(passes, int) or passes < 1:
        raise StepSimulationError("Simulation pass count must be a positive integer")
    if breakthrough < 0 or not math.isfinite(breakthrough):
        raise StepSimulationError("Simulation breakthrough must be finite and nonnegative")
    if stock_thickness is not None:
        _validate_number("Stock thickness", stock_thickness, minimum=0.0, strict=True)
        if target_depth < -(stock_thickness + breakthrough) - _COORDINATE_TOLERANCE:
            raise StepSimulationError(
                "Simulated cutting depth is deeper than the confirmed physical stock"
            )

    if target_region is None or target_region.is_empty:
        raise StepSimulationError("Cannot simulate an empty stock-removal region")
    target_region = target_region.buffer(0)
    if target_region.is_empty or target_region.area <= 1e-9:
        raise StepSimulationError("The stock-removal region has no measurable area")

    resolved_width = float(stock_width) if stock_width is not None else float(target_region.bounds[2])
    resolved_height = float(stock_height) if stock_height is not None else float(target_region.bounds[3])
    if resolved_width <= 0 or resolved_height <= 0:
        raise StepSimulationError("Simulation stock dimensions must be greater than zero")
    stock_region = box(0.0, 0.0, resolved_width, resolved_height)

    reachable_region = target_region.buffer(-tool_radius, join_style=2)
    if reachable_region.is_empty:
        raise StepSimulationError("The simulated removal region is too small for the selected tool")

    paths = tuple(strokes)
    if not paths:
        raise StepSimulationError("Cannot simulate an empty toolpath")
    swept_parts = []
    segment_count = 0
    for stroke in paths:
        if len(stroke) < 2 or any(
            len(point) != 2 or not all(math.isfinite(value) for value in point)
            for point in stroke
        ):
            raise StepSimulationError("Simulation path contains an invalid point")
        line = LineString(stroke)
        if line.length <= _GEOMETRY_TOLERANCE:
            raise StepSimulationError("Simulation path contains a zero-length stroke")
        if not reachable_region.buffer(tolerance).covers(line):
            raise StepSimulationError(
                "Simulation centerline leaves the tool-reachable removal region"
            )
        segment_count += len(stroke) - 1
        swept_parts.append(line.buffer(tool_radius, cap_style=1, join_style=1))

    swept = unary_union(swept_parts).buffer(0)
    if not stock_region.buffer(_COORDINATE_TOLERANCE).covers(swept):
        raise StepSimulationError("Simulated cutter sweep extends outside the declared stock")
    unreachable_area = target_region.difference(reachable_region).area
    uncovered = reachable_region.difference(swept).area
    allowed_uncovered = max(0.05, reachable_region.area * 0.005, tolerance)
    gouged = 0.0
    if retained_region is not None and not retained_region.is_empty:
        gouged = swept.intersection(retained_region).area
    allowed_gouged = max(0.001, tolerance)
    result = StepStockSimulation(
        resolved_width,
        resolved_height,
        float(stock_thickness) if stock_thickness is not None else None,
        float(target_depth),
        float(target_region.area),
        float(reachable_region.area),
        float(unreachable_area),
        float(swept.intersection(stock_region).area),
        float(uncovered),
        float(allowed_uncovered),
        float(gouged),
        float(allowed_gouged),
        len(paths),
        segment_count,
        passes,
    )
    if not result.passed:
        if result.uncovered_area > result.allowed_uncovered_area:
            raise StepSimulationError(
                f"Simulation leaves {result.uncovered_area:.3f} mm² of intended material uncut"
            )
        raise StepSimulationError(
            f"Simulation gouges {result.gouged_area:.3f} mm² of retained material"
        )
    return result


_GEOMETRY_TOLERANCE = 1e-7
_COORDINATE_TOLERANCE = 0.001


def _validate_number(name: str, value: float, *, minimum: float | None = None, maximum: float | None = None, strict: bool) -> None:
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        raise StepSimulationError(f"{name} must be finite")
    if minimum is not None and (value <= minimum if strict else value < minimum):
        comparator = "greater than" if strict else "at least"
        raise StepSimulationError(f"{name} must be {comparator} {minimum:g}")
    if maximum is not None and value > maximum:
        raise StepSimulationError(f"{name} must be at most {maximum:g}")
