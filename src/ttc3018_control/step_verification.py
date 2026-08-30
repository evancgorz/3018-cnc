"""Deterministic, geometry-only verification for STEP clearing paths."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable

from shapely.geometry import LineString
from shapely.ops import unary_union

from .text_engraver import Stroke


class StepVerificationError(ValueError):
    """Generated STEP motion failed the geometry-only verification gate."""


@dataclass(frozen=True)
class StepVerification:
    swept_area: float
    uncovered_area: float
    checked_strokes: int

    @property
    def passed(self) -> bool:
        return self.uncovered_area <= 1e-7


def verify_flat_clearing_paths(
    strokes: Iterable[Stroke],
    target_region,
    tool_radius: float,
    *,
    tolerance: float = 0.02,
) -> StepVerification:
    """Verify centerline containment and approximate cutter-swept coverage.

    This is intentionally a bounded 2D gate. It proves that clearing paths
    cover the tool-reachable (cutter-radius-eroded) portion of the requested
    planar region and that no centerline leaves that region. Sharp raw-region
    corner tips are not reachable by a cylindrical cutter centerline. Z-level
    collision simulation is a later, higher-fidelity stage; callers must not
    treat this as a substitute for machine-envelope validation.
    """
    if tool_radius <= 0 or not math.isfinite(tool_radius):
        raise StepVerificationError("Tool radius must be finite and greater than zero")
    if target_region.is_empty:
        raise StepVerificationError("Cannot verify an empty clearing region")
    paths = tuple(strokes)
    if not paths:
        raise StepVerificationError("Cannot verify an empty clearing path set")
    reachable_region = target_region.buffer(-tool_radius, join_style=2)
    if reachable_region.is_empty:
        raise StepVerificationError("The requested clearing region is too small for the selected tool")
    lines = []
    for stroke in paths:
        if len(stroke) < 2 or any(not all(math.isfinite(value) for value in point) for point in stroke):
            raise StepVerificationError("Clearing path contains an invalid point")
        line = LineString(stroke)
        if line.length <= 1e-7:
            raise StepVerificationError("Clearing path contains a zero-length stroke")
        if not reachable_region.buffer(tolerance).covers(line):
            raise StepVerificationError("Clearing centerline leaves the requested planar region")
        lines.append(line)
    swept = unary_union([line.buffer(tool_radius, cap_style=1, join_style=1) for line in lines])
    uncovered = reachable_region.difference(swept).area
    allowed = max(0.05, reachable_region.area * 0.005)
    if uncovered > allowed:
        raise StepVerificationError(
            f"Clearing paths leave {uncovered:.3f} mm² of planar material outside the verification tolerance"
        )
    return StepVerification(float(swept.area), float(uncovered), len(paths))
