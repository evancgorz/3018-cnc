"""Reusable tapered C-095 sunburst geometry (offline review helper)."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

from shapely.geometry import LineString, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union


@dataclass(frozen=True)
class RayLayout:
    """Unclipped nominal ray polygons and their source centerlines, in mm."""

    centerlines: tuple[LineString, ...]
    polygons: tuple[Polygon, ...]

    @property
    def geometry(self) -> BaseGeometry:
        return unary_union(self.polygons)


def c095_ray_centerlines(
    *,
    center: tuple[float, float] = (55.0, 62.0),
    angles_deg: Iterable[float] = (30, 45, 60, 75, 90, 105, 120, 135, 150),
    start_radius_mm: float = 11.0,
    end_radius_mm: float = 27.0,
) -> tuple[LineString, ...]:
    """Return rays at the original C-095 positions and radial extents."""
    if start_radius_mm < 0 or end_radius_mm <= start_radius_mm:
        raise ValueError("Require 0 <= start radius < end radius")
    cx, cy = center
    return tuple(
        LineString((
            (cx + start_radius_mm * math.cos(math.radians(angle)),
             cy + start_radius_mm * math.sin(math.radians(angle))),
            (cx + end_radius_mm * math.cos(math.radians(angle)),
             cy + end_radius_mm * math.sin(math.radians(angle))),
        ))
        for angle in angles_deg
    )


def make_tapered_ray_layout(
    *,
    center: tuple[float, float] = (55.0, 62.0),
    angles_deg: Iterable[float] = (30, 45, 60, 75, 90, 105, 120, 135, 150),
    start_radius_mm: float = 11.0,
    end_radius_mm: float = 27.0,
    inner_width_mm: float = 0.8,
    outer_width_mm: float = 3.3,
) -> RayLayout:
    """Build straight-sided tapered rays, preserving original C-095 axes.

    Widths are full cross-sectional widths at each centerline endpoint. The
    polygons are intentionally sharp-ended; downstream sky clipping sets the
    actual endpoints at the aircraft and sky boundaries.
    """
    if inner_width_mm <= 0 or outer_width_mm <= 0:
        raise ValueError("Ray widths must be positive")
    centerlines = c095_ray_centerlines(
        center=center, angles_deg=angles_deg,
        start_radius_mm=start_radius_mm, end_radius_mm=end_radius_mm,
    )
    polygons = []
    for line in centerlines:
        (ax, ay), (bx, by) = line.coords
        dx, dy = bx - ax, by - ay
        length = math.hypot(dx, dy)
        nx, ny = -dy / length, dx / length
        r0, r1 = inner_width_mm / 2, outer_width_mm / 2
        polygons.append(Polygon((
            (ax + nx * r0, ay + ny * r0),
            (bx + nx * r1, by + ny * r1),
            (bx - nx * r1, by - ny * r1),
            (ax - nx * r0, ay - ny * r0),
        )))
    return RayLayout(centerlines=centerlines, polygons=tuple(polygons))


def clip_rays_to_sky(layout: RayLayout, sky_zone: BaseGeometry) -> BaseGeometry:
    """Clip rays to the caller-provided C-095 sky zone/aircraft exclusion."""
    return layout.geometry.intersection(sky_zone)
