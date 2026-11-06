"""Offline fixed-depth raster engraving CAM; never connects to a machine.

Black pixels describe shallow removed areas, not through cuts. This module is a
bounded first CAM route, not a variable-depth V-carver or a commissioning tool.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
import math
from itertools import islice
from pathlib import Path

from PIL import Image
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union
from shapely.strtree import STRtree
from shapely.prepared import prep

from .gcode import parse_gcode, validate_nonnegative_work_xy, validate_rapid_xy_clearance
from .job_analysis import analyze_program

MAX_PIXELS = 4_000_000
MAX_RUNS = 100_000
MAX_PATHS = 100_000
MAX_POINTS = 250_000
MAX_CONCENTRIC_RINGS_PER_COMPONENT = 32
ROUND_GUARD = 0.0002


@dataclass(frozen=True)
class OrnamentSettings:
    # All dimensions in mm, positive depths below face Z0, feeds in mm/min.
    crop: tuple[int, int, int, int]
    outer_diameter: float
    art_diameter: float
    stock_thickness: float
    stock_margin: float
    engraving_depth: float
    v_angle: float
    tip_diameter: float
    stepover: float
    max_stepdown: float
    safe_z: float
    cut_feed: float
    plunge_feed: float
    spindle_rpm: int | None
    threshold: int
    optimize_paths: bool = True
    approach_z: float | None = None

    def validate(self) -> None:
        if self.approach_z is not None:
            value = self.approach_z
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0.01:
                raise ValueError("approach_z must be null or a finite clearance >= 0.01 mm")
            if value > self.safe_z or not math.isclose(value, round(value, 4), rel_tol=0, abs_tol=1e-10):
                raise ValueError("approach_z must be <= safe_z and representable to 0.0001 mm")
        if not isinstance(self.optimize_paths, bool):
            raise ValueError("optimize_paths must be a boolean")
        positive = ("outer_diameter", "art_diameter", "stock_thickness", "stock_margin",
                    "engraving_depth", "stepover", "max_stepdown", "safe_z", "cut_feed", "plunge_feed")
        for name in positive:
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive")
        for name in ("tip_diameter", "v_angle"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"{name} must be finite")
        if self.tip_diameter < 0 or self.tip_diameter > 50 or not 0 < self.v_angle < 180:
            raise ValueError("Invalid V-bit tip diameter or included angle")
        if self.art_diameter >= self.outer_diameter:
            raise ValueError("art_diameter must be smaller than outer_diameter to retain a wood rim")
        if self.engraving_depth >= self.stock_thickness:
            raise ValueError("engraving_depth must be less than stock_thickness; this exporter does not cut through")
        if self.outer_diameter > 1000 or self.stock_margin > 1000 or self.stock_thickness > 100 or self.safe_z > 100 or max(self.cut_feed, self.plunge_feed) > 10000:
            raise ValueError("Settings exceed offline exporter resource/dimension limits")
        if self.safe_z < 0.01 or min(self.engraving_depth, self.stepover, self.max_stepdown, self.cut_feed, self.plunge_feed) < 0.001:
            raise ValueError("Settings are below output precision: safe_z >= 0.01; depths, stepover and feeds >= 0.001")
        for name in ("engraving_depth", "max_stepdown", "safe_z"):
            value = getattr(self, name)
            if not math.isclose(value, round(value, 4), rel_tol=0, abs_tol=1e-10):
                raise ValueError(f"{name} must be representable to 0.0001 mm output precision")
        if not math.isfinite(self.effective_diameter) or not 0.001 <= self.effective_diameter <= self.outer_diameter:
            raise ValueError("Effective tool diameter must be finite, >= 0.001 and no larger than the ornament")
        if math.ceil(self.engraving_depth / self.max_stepdown) > 100:
            raise ValueError("Too many depth passes (maximum 100)")
        if self.stepover > self.effective_diameter * 0.8:
            raise ValueError("stepover must not exceed 80% of effective V-bit diameter")
        if not isinstance(self.threshold, int) or isinstance(self.threshold, bool) or not 1 <= self.threshold <= 254:
            raise ValueError("threshold must be an integer from 1 to 254")
        if self.spindle_rpm is not None and (isinstance(self.spindle_rpm, bool) or not isinstance(self.spindle_rpm, int) or not 1 <= self.spindle_rpm <= 120000):
            raise ValueError("spindle_rpm must be null or an explicit positive integer <= 120000")
        if not isinstance(self.crop, (tuple, list)) or len(self.crop) != 4 or any(isinstance(v, bool) or not isinstance(v, int) for v in self.crop):
            raise ValueError("crop must be four integer pixel coordinates [left, top, right, bottom]")
        left, top, right, bottom = self.crop
        if left < 0 or top < 0 or right <= left or bottom <= top or right-left != bottom-top:
            raise ValueError("crop must be a positive square within the image; aspect ratio is never stretched")
        if (right-left) * (bottom-top) > MAX_PIXELS:
            raise ValueError("Crop exceeds pixel limit")

    @property
    def approach_clearance(self) -> float:
        return self.safe_z if self.approach_z is None else self.approach_z

    @property
    def effective_diameter(self) -> float:
        return self.tip_diameter + 2 * self.engraving_depth * math.tan(math.radians(self.v_angle / 2))


def _lines(geometry):
    if isinstance(geometry, LineString):
        yield geometry
    elif hasattr(geometry, "geoms"):
        for item in geometry.geoms:
            yield from _lines(item)


def _polygons(geometry):
    if isinstance(geometry, Polygon):
        yield geometry
    elif hasattr(geometry, "geoms"):
        for item in geometry.geoms:
            yield from _polygons(item)


def raster_region(image_path: Path, settings: OrnamentSettings):
    """Turn thresholded pixel cells into physical polygons, with image Y flipped."""
    settings.validate()
    with Image.open(image_path) as image:
        if image.width * image.height > MAX_PIXELS:
            raise ValueError("Image exceeds pixel limit")
        left, top, right, bottom = settings.crop
        if right > image.width or bottom > image.height:
            raise ValueError("crop exceeds image bounds")
        # Alpha is composited on white rather than interpreted as black material.
        rgba = image.convert("RGBA")
        background = Image.new("RGBA", rgba.size, "white")
        background.alpha_composite(rgba)
        gray = background.convert("L").crop(tuple(settings.crop))
        width, height = gray.size
        values = gray.load()
        if any(values[x, y] < settings.threshold for x in range(width) for y in (0, height-1)) or any(values[x, y] < settings.threshold for y in range(height) for x in (0, width-1)):
            raise ValueError("Black artwork touches crop edge; include a white border")
        scale = settings.art_diameter / width
        origin = settings.stock_margin + (settings.outer_diameter - settings.art_diameter) / 2
        runs = []
        for y in range(height):
            start = None
            for x in range(width + 1):
                black = x < width and values[x, y] < settings.threshold
                if black and start is None:
                    start = x
                elif not black and start is not None:
                    runs.append(box(origin + start*scale, origin + (height-y-1)*scale,
                                    origin + x*scale, origin + (height-y)*scale))
                    start = None
                    if len(runs) > MAX_RUNS:
                        raise ValueError("Artwork exceeds raster run limit")
    if not runs:
        raise ValueError("No black artwork in crop")
    region = unary_union(runs)
    center = settings.stock_margin + settings.outer_diameter/2
    # Inscribed polygon with generous resolution: rejects square-corner artwork.
    allowed = Point(center, center).buffer(settings.outer_diameter/2, quad_segs=256)
    if not allowed.covers(region):
        raise ValueError("Artwork lies outside physical ornament circle")
    return region, scale


def plan_engraving(region, settings: OrnamentSettings):
    """Plan independent scanlines and boundary finishes inside tool-radius inset."""
    settings.validate()
    radius = settings.effective_diameter/2
    # Conservative polygonal circle envelope plus emitted-coordinate roundoff.
    guarded_radius = radius / math.cos(math.pi/128) + ROUND_GUARD
    inset = region.buffer(-guarded_radius, join_style="mitre")
    if inset.is_empty:
        raise ValueError("Artwork is narrower than the tool footprint at this depth")
    paths = []
    point_count = 0
    # Finish boundaries, including counters. Retract between all independent loops.
    for polygon in _polygons(inset):
        for ring in (polygon.exterior, *polygon.interiors):
            coords = tuple((round(x, 4), round(y, 4)) for x, y in ring.coords)
            point_count += len(coords)
            if point_count > MAX_POINTS:
                raise ValueError("Artwork exceeds toolpath point limit")
            paths.append(coords)
    minx, miny, maxx, maxy = inset.bounds
    rows = math.ceil((maxy - miny) / settings.stepover)
    if rows > MAX_PATHS:
        raise ValueError("Too many engraving scanlines")
    for row in range(rows + 1):
        y = miny + row*settings.stepover
        if y > maxy:
            break
        segments = sorted(_lines(inset.intersection(LineString([(minx-1, y), (maxx+1, y)]))), key=lambda line: line.bounds[0])
        if row % 2:
            segments.reverse()
        for segment in segments:
            coords = tuple((round(x, 4), round(yy, 4)) for x, yy in segment.coords)
            if len(coords) < 2 or segment.length < 0.0002:
                continue
            paths.append(coords[::-1] if row % 2 else coords)
            point_count += len(coords)
            if len(paths) > MAX_PATHS or point_count > MAX_POINTS:
                raise ValueError("Artwork exceeds toolpath resource limit")
    if not paths:
        raise ValueError("No engraving paths generated")
    # Verify quantized paths, not just the unrounded planning geometry. The
    # inflated 32-segment circular buffer conservatively contains the real cutter.
    verification_radius = radius / math.cos(math.pi/128)
    for path in paths:
        sweep = LineString(path).buffer(verification_radius, quad_segs=32)
        if not region.covers(sweep):
            raise ValueError("Emitted cutter footprint exceeds black artwork")
    return tuple(paths), inset


def _rounded_ring_paths(geometry):
    """Return closed quantized perimeter paths for one compensated region."""
    paths = []
    for polygon in _polygons(geometry):
        for ring in (polygon.exterior, *polygon.interiors):
            coords = tuple((round(x, 4), round(y, 4)) for x, y in ring.coords)
            if len(coords) >= 4:
                paths.append(coords)
    return paths


def _component_scanline_paths(component, settings: OrnamentSettings):
    """Return one component's boundary and alternating scanline fill paths."""
    paths = _rounded_ring_paths(component)
    minx, miny, maxx, maxy = component.bounds
    rows = math.ceil((maxy - miny) / settings.stepover)
    if rows > MAX_PATHS:
        raise ValueError("Too many engraving scanlines")
    for row in range(rows + 1):
        y = miny + row * settings.stepover
        if y > maxy:
            break
        spans = sorted(_lines(component.intersection(LineString(((minx - 1, y), (maxx + 1, y))))),
                       key=lambda line: line.bounds[0])
        if row % 2:
            spans.reverse()
        for span in spans:
            coords = tuple((round(x, 4), round(yy, 4)) for x, yy in span.coords)
            if len(coords) >= 2 and span.length >= 0.0002:
                paths.append(coords[::-1] if row % 2 else coords)
    return paths


def _component_offset_paths(component, settings: OrnamentSettings):
    """Return nested inward offset rings for one component, if they cover it.

    The centreline region is already cutter-radius compensated.  We retain all
    counters, stop when erosion removes the component, and only accept this
    strategy after verifying its rounded cutter sweep covers that component.
    """
    current = component
    paths = []
    ring_count = 0
    while not current.is_empty:
        ring_count += 1
        # Dense artwork can turn repeated polygon offsets into an unbounded
        # planning cost.  Its local scanline fallback remains exact and keeps
        # planning bounded; small isolated regions still receive concentric
        # machining.
        if ring_count > MAX_CONCENTRIC_RINGS_PER_COMPONENT:
            return []
        ring_paths = _rounded_ring_paths(current)
        if not ring_paths:
            break
        paths.extend(ring_paths)
        if len(paths) > MAX_PATHS or sum(map(len, paths)) > MAX_POINTS:
            raise ValueError("Artwork exceeds concentric engraving resource limit")
        next_region = current.buffer(-settings.stepover, join_style="mitre")
        if next_region.is_empty or next_region.equals(current):
            break
        current = next_region
    return paths


def plan_adaptive_region_engraving(region, settings: OrnamentSettings):
    """Plan localized engraving: concentric offsets per component when valid.

    Each connected compensated component is completed before the next.  A
    rounded full-cutter sweep proves both containment and coverage.  Fragmented
    or under-covering offset rings fall back to that component's connected
    scanlines rather than silently losing artwork.
    """
    settings.validate()
    radius = settings.effective_diameter / 2
    guarded_radius = radius / math.cos(math.pi / 128) + ROUND_GUARD
    inset = region.buffer(-guarded_radius, join_style="mitre")
    if inset.is_empty:
        raise ValueError("Artwork is narrower than the tool footprint at this depth")
    verification_radius = radius / math.cos(math.pi / 128)
    paths = []
    metrics = {"concentric_components": 0, "scanline_fallback_components": 0,
               "component_local_stay_down_links": 0}
    remaining = list(_polygons(inset))
    current = Point(0, 0)
    while remaining:
        # Nearest-next component ordering preserves the user's desired local
        # completion rule without incurring arbitrary left-to-right air moves.
        index, component = min(enumerate(remaining),
                               key=lambda item: (item[1].distance(current), item[1].bounds, item[0]))
        del remaining[index]
        offsets = _component_offset_paths(component, settings)
        # Successive offset boundaries are separated by at most one cutter
        # diameter and continue until erosion vanishes.  That proves coverage
        # without a potentially enormous polygon union; each rounded ring's
        # full cutter sweep is still checked below.
        if offsets and settings.stepover <= 2 * verification_radius:
            selected = offsets
            metrics["concentric_components"] += 1
        else:
            selected = _component_scanline_paths(component, settings)
            metrics["scanline_fallback_components"] += 1
        if not selected:
            continue
        # Safe links and path orientation may be optimized inside this one
        # component only: never interleave two engraving areas.
        local, local_metrics = _schedule_engraving_paths(tuple(selected), component, settings)
        paths.extend(local)
        metrics["component_local_stay_down_links"] += local_metrics["stay_down_link_count"]
        current = Point(local[-1][-1])
        if len(paths) > MAX_PATHS or sum(map(len, paths)) > MAX_POINTS:
            raise ValueError("Artwork exceeds engraving toolpath resource limit")
    if not paths:
        raise ValueError("No engraving paths generated")
    for path in paths:
        sweep = LineString(path).buffer(verification_radius, quad_segs=32)
        if not region.covers(sweep):
            raise ValueError("Adaptive emitted cutter footprint exceeds black artwork")
    metrics["components"] = metrics["concentric_components"] + metrics["scanline_fallback_components"]
    return tuple(paths), inset, metrics



def _schedule_engraving_paths(paths, inset, settings: OrnamentSettings):
    """Bounded deterministic endpoint scheduling, with proven stay-down links.

    All original paths are retained. Spatial buckets examine at most 64 endpoint
    candidates per step, with at most eight surrounding cell rings. No global
    quadratic nearest-neighbor search is performed.
    """
    polygons = list(_polygons(inset))
    tree = STRtree(polygons)
    grouped = {}
    for index, path in enumerate(paths):
        component = int(tree.nearest(Point(path[0])))
        grouped.setdefault(component, []).append(index)
    cell_size = max(settings.stepover * 4, settings.effective_diameter)
    def cell(point):
        return math.floor(point[0]/cell_size), math.floor(point[1]/cell_size)
    # A slightly larger safe region than the planning inset absorbs coordinate
    # quantization, while retaining a conservative full-cutter clearance.
    safe_centers = prep(inset.buffer(ROUND_GUARD/2, join_style="mitre"))
    # Link only when cutting the connector is cheaper than retract/rapid/plunge.
    overhead = (2*settings.safe_z - settings.approach_clearance)/3000 + settings.approach_clearance/settings.plunge_feed
    denominator = 1/settings.cut_feed - 1/3000
    max_link = overhead/denominator if denominator > 0 else float('inf')
    chains = []
    scheduled_indices = []
    reversed_count = 0
    stay_down_link_distances = []
    current = (0.0, 0.0)
    for component in sorted(grouped, key=lambda i: (cell((polygons[i].bounds[0], polygons[i].bounds[1])), i)):
        active = dict.fromkeys(grouped[component])
        buckets = {}
        for index in active:
            for reverse in (False, True):
                endpoint = paths[index][-1 if reverse else 0]
                buckets.setdefault(cell(endpoint), {})[(index, reverse)] = None
        while active:
            cx, cy = cell(current)
            candidates = []
            for ring in range(9):
                cells = ((cx+dx, cy+dy) for dy in range(-ring, ring+1) for dx in range(-ring, ring+1)
                         if max(abs(dx), abs(dy)) == ring)
                for key in cells:
                    for index, reverse in islice(buckets.get(key, {}), max(0, 64-len(candidates))):
                        start = paths[index][-1 if reverse else 0]
                        candidates.append((math.dist(current, start), index, reverse))
                    if len(candidates) >= 64:
                        break
                if len(candidates) >= 64:
                    break
            if not candidates:
                index = next(iter(active))
                candidates = [(math.dist(current, paths[index][0]), index, False),
                              (math.dist(current, paths[index][-1]), index, True)]
            ordered = sorted(candidates)
            chosen = ordered[0]
            linked = False
            if chains:
                for candidate in ordered:
                    distance, index, reverse = candidate
                    start = paths[index][-1 if reverse else 0]
                    if distance <= max_link and (current == start or safe_centers.covers(LineString([current, start]))):
                        chosen = candidate
                        linked = True
                        break
            _, index, reverse = chosen
            scheduled_indices.append(index)
            reversed_count += int(reverse)
            path = paths[index][::-1] if reverse else paths[index]
            if linked:
                stay_down_link_distances.append(math.dist(current, path[0]))
                chains[-1].extend(path[1:] if current == path[0] else path)
            else:
                chains.append(list(path))
            current = path[-1]
            del active[index]
            for reverse_endpoint in (False, True):
                endpoint = paths[index][-1 if reverse_endpoint else 0]
                del buckets[cell(endpoint)][(index, reverse_endpoint)]
    result = tuple(tuple(chain) for chain in chains)
    # Recheck full quantized geometry, including every inserted connector.
    quantized_centers = prep(inset.buffer(ROUND_GUARD, join_style="mitre"))
    for path in result:
        if not quantized_centers.covers(LineString(path)):
            raise ValueError("Optimized path exceeds compensated engraving region")
    schedule_metrics = {
        "primitive_paths_before": len(paths),
        "scheduled_chains_per_pass": len(result),
        "reversed_primitive_paths": reversed_count,
        "stay_down_link_count": len(stay_down_link_distances),
        "stay_down_link_distance_mm": sum(stay_down_link_distances),
        "stay_down_link_max_mm": max(stay_down_link_distances, default=0.0),
        "scheduled_order_changed": tuple(scheduled_indices) != tuple(range(len(paths))),
    }
    return result, schedule_metrics


def optimize_engraving_paths(paths, inset, settings: OrnamentSettings):
    """Public geometry-only wrapper for the bounded endpoint scheduler."""
    return _schedule_engraving_paths(paths, inset, settings)[0]


def _path_motion_stats(paths):
    lengths = []
    turns = []
    for path in paths:
        vectors = []
        for start, end in zip(path, path[1:]):
            dx, dy = end[0] - start[0], end[1] - start[1]
            length = math.hypot(dx, dy)
            if length > 1e-9:
                lengths.append(length)
                vectors.append((dx, dy, length))
        for first, second in zip(vectors, vectors[1:]):
            cosine = (first[0] * second[0] + first[1] * second[1]) / (first[2] * second[2])
            turns.append(math.degrees(math.acos(max(-1.0, min(1.0, cosine)))))
    lengths.sort()
    percentile = lambda ratio: lengths[min(len(lengths) - 1, int(ratio * len(lengths)))] if lengths else None
    return {
        "nonzero_cut_segments": len(lengths),
        "median_cut_segment_mm": percentile(0.5),
        "p95_cut_segment_mm": percentile(0.95),
        "cut_segments_at_most_0_1mm": sum(length <= 0.1 for length in lengths),
        "cut_segments_at_most_0_25mm": sum(length <= 0.25 for length in lengths),
        "cut_junctions": len(turns),
        "cut_junctions_at_least_90_degrees": sum(turn >= 89.999 for turn in turns),
        "cut_junctions_at_least_135_degrees": sum(turn >= 134.999 for turn in turns),
    }


def _motion_metrics(paths, settings: OrnamentSettings, schedule_metrics=None):
    depth_units = round(settings.engraving_depth * 10000)
    step_units = round(settings.max_stepdown * 10000)
    passes = (depth_units + step_units - 1) // step_units
    cutting_distance = sum(sum(math.dist(a, b) for a, b in zip(path, path[1:])) for path in paths) * passes
    plunge_distance = 0.0
    rapid_z_distance = settings.safe_z
    rapid_xy_distance = 0.0
    previous = (0.0, 0.0)
    for pass_index in range(1, passes+1):
        depth = min(pass_index * step_units, depth_units) / 10000
        plunge_distance += len(paths) * (settings.approach_clearance + depth)
        rapid_z_distance += len(paths) * (2*settings.safe_z - settings.approach_clearance + depth)
        for path in paths:
            rapid_xy_distance += math.dist(previous, path[0])
            previous = path[-1]
    cutting_minutes = cutting_distance/settings.cut_feed
    plunge_minutes = plunge_distance/settings.plunge_feed
    rapid_minutes = (rapid_z_distance+rapid_xy_distance)/3000
    path_stats = _path_motion_stats(paths)
    for count_key in (
        "nonzero_cut_segments", "cut_segments_at_most_0_1mm", "cut_segments_at_most_0_25mm",
        "cut_junctions", "cut_junctions_at_least_90_degrees", "cut_junctions_at_least_135_degrees",
    ):
        path_stats[count_key] *= passes
    return {
        "cutting_minutes": cutting_minutes,
        "plunge_minutes": plunge_minutes,
        "rapid_minutes": rapid_minutes,
        "estimated_minutes": cutting_minutes + plunge_minutes + rapid_minutes,
        "cutting_distance_mm": cutting_distance,
        "rapid_xy_distance_mm": rapid_xy_distance,
        "rapid_z_distance_mm": rapid_z_distance,
        "rapid_distance_mm": rapid_xy_distance + rapid_z_distance,
        "plunge_distance_mm": plunge_distance,
        "retract_count": len(paths) * passes,
        "plunge_count": len(paths) * passes,
        "paths_per_pass": len(paths),
        "depth_passes": passes,
        **path_stats,
        **(schedule_metrics or {
            "primitive_paths_before": len(paths), "scheduled_chains_per_pass": len(paths),
            "reversed_primitive_paths": 0, "stay_down_link_count": 0,
            "stay_down_link_distance_mm": 0.0, "stay_down_link_max_mm": 0.0,
            "scheduled_order_changed": False,
        }),
    }

def generate_engraving(image_path: Path, settings: OrnamentSettings):
    region, pixel_size = raster_region(image_path, settings)
    paths, inset = plan_engraving(region, settings)
    baseline_paths = paths
    baseline_metrics = _motion_metrics(paths, settings)
    baseline_path_count = len(paths)
    schedule_metrics = None
    if settings.optimize_paths:
        paths, schedule_metrics = _schedule_engraving_paths(paths, inset, settings)
        verification_radius = settings.effective_diameter/2 / math.cos(math.pi/128)
        for path in paths:
            if not region.covers(LineString(path).buffer(verification_radius, quad_segs=32)):
                raise ValueError("Optimized emitted cutter footprint exceeds black artwork")
    metrics = _motion_metrics(paths, settings, schedule_metrics)
    optimization_applied = settings.optimize_paths
    if metrics["estimated_minutes"] > baseline_metrics["estimated_minutes"]:
        paths = baseline_paths
        metrics = baseline_metrics
        optimization_applied = False
    depth_units = round(settings.engraving_depth * 10000)
    step_units = round(settings.max_stepdown * 10000)
    passes = (depth_units + step_units - 1) // step_units
    approach_line = int(settings.approach_clearance < settings.safe_z)
    if sum(len(path) + 3 + approach_line for path in paths) * passes > 1_000_000:
        raise ValueError("Generated program would exceed one million lines")
    lines = ["(OFFLINE UNCOMMISSIONED - OPERATOR REVIEW REQUIRED)",
             "(Shallow engraving only - no through cuts or automatic tool changes)",
             "(XY origin: lower-left stock; Z0: measured top surface)",
             "G21 G90 G17 G94 G54", "M5", f"G0 Z{settings.safe_z:.4f}"]
    if settings.spindle_rpm is not None:
        lines.append(f"M3 S{settings.spindle_rpm}")
    else:
        lines.append("(No spindle startup requested - do not run without verified spindle setup)")
    for pass_index in range(1, passes+1):
        depth = min(pass_index * step_units, depth_units) / 10000
        lines.append(f"(Engraving pass {pass_index} of {passes})")
        for path in paths:
            x, y = path[0]
            lines.extend((f"G0 Z{settings.safe_z:.4f}", f"G0 X{x:.4f} Y{y:.4f}"))
            if settings.approach_clearance < settings.safe_z:
                lines.append(f"G0 Z{settings.approach_clearance:.4f}")
            lines.append(f"G1 Z{-depth:.4f} F{settings.plunge_feed:.4f}")
            lines.extend(f"G1 X{x:.4f} Y{y:.4f} F{settings.cut_feed:.4f}" for x, y in path[1:])
    lines.extend((f"G0 Z{settings.safe_z:.4f}", "M5", "M2"))
    gcode = "\n".join(lines) + "\n"
    program = parse_gcode(gcode)
    validate_nonnegative_work_xy(program)
    validate_rapid_xy_clearance(program, settings.safe_z)
    emitted_metrics = analyze_program(program)
    for planned_key, emitted_key in (
        ("cutting_distance_mm", "cut_distance_mm"),
        ("rapid_xy_distance_mm", "rapid_xy_distance_mm"),
        ("rapid_z_distance_mm", "rapid_z_distance_mm"),
        ("plunge_distance_mm", "plunge_distance_mm"),
        ("retract_count", "retract_count"),
        ("nonzero_cut_segments", "nonzero_cut_segments"),
        ("cut_junctions", "cut_junctions"),
    ):
        if not math.isclose(metrics[planned_key], emitted_metrics[emitted_key], rel_tol=1e-9, abs_tol=1e-7):
            raise ValueError(f"Planned {planned_key} differs from the exact emitted G-code")
    radius = settings.effective_diameter / 2
    if min(inset.bounds[:2]) < radius:
        raise ValueError("Cutter envelope crosses nonnegative work boundary")
    # Measures inaccessible black areas, not a claim of complete stock simulation.
    accessible = inset.buffer(radius, quad_segs=16)
    inaccessible = region.difference(accessible).area
    settings_bytes = json.dumps(asdict(settings), sort_keys=True, separators=(",", ":")).encode("utf-8")
    gcode_bytes = gcode.encode("ascii")
    report = {
        "schema": 1, "status": "offline_uncommissioned_operator_review_required",
        "operation": "fixed_depth_raster_engraving_only",
        "source_sha256": hashlib.sha256(image_path.read_bytes()).hexdigest(),
        "settings_sha256": hashlib.sha256(settings_bytes).hexdigest(),
        "output_gcode_sha256": hashlib.sha256(gcode_bytes).hexdigest(),
        "settings": asdict(settings), "effective_tool_diameter_mm": settings.effective_diameter,
        "pixel_size_mm": pixel_size, "passes": passes, "paths_per_pass": len(paths),
        "source_black_area_mm2": region.area,
        "inaccessible_black_area_mm2": inaccessible,
        "inaccessible_black_fraction": inaccessible / region.area,
        "fully_omitted_black_components": sum(not inset.intersects(polygon) for polygon in _polygons(region)),
        "estimated_minutes": program.estimated_seconds/60,
        "motion_metrics": metrics,
        "emitted_motion_metrics": emitted_metrics,
        "optimization": {"enabled": settings.optimize_paths, "applied": optimization_applied, "baseline_paths_per_pass": baseline_path_count,
                         "baseline_motion_metrics": baseline_metrics,
                         "saved_minutes": baseline_metrics["estimated_minutes"] - metrics["estimated_minutes"],
                         "original_primitives_retained": True,
                         "additional_stay_down_link_sweep_count": metrics["stay_down_link_count"]},
        "bounds": {"minimum": asdict(program.bounds.minimum), "maximum": asdict(program.bounds.maximum)},
        "warnings": ["Not physically commissioned; machine readiness is not evaluated.",
                     "Fixed-depth fill, not variable-depth V-carving; narrow detail and sharp corners can be omitted.",
                     "Preview shows top-surface cutter footprint, not floor finish, plywood tear-out or machining simulation.",
                     "V-bit raster floors are scalloped; this is not a flat-bottom pocketing operation.",
                     "No hanger or perimeter cutout is generated. Use separately reviewed compensated profile CAM.",
                     "Confirm tool angle/tip, stock flatness, feeds, spindle, clearances and work zero before machining."],
    }
    if settings.approach_clearance < settings.safe_z:
        report["warnings"].append("Reduced vertical approach clearance assumes verified stock flatness and no obstruction at cut starts; XY rapids still use safe_z.")
    if settings.spindle_rpm is None:
        report["warnings"].append("Spindle startup omitted because spindle_rpm is null.")
    size = settings.outer_diameter + 2*settings.stock_margin
    preview = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" width="{size}mm" height="{size}mm">',
               '<title>Offline engraving cutter footprint - not stock simulation</title>',
               f'<rect width="{size}" height="{size}" fill="white"/>',
               f'<g transform="translate(0 {size}) scale(1 -1)" fill="none" stroke="black" stroke-width="{settings.effective_diameter}" stroke-linecap="round" stroke-linejoin="round">']
    preview.extend('<polyline points="' + ' '.join(f'{x:.4f},{y:.4f}' for x, y in path) + '"/>' for path in paths)
    preview.extend(('</g>', '</svg>'))
    return gcode, report, "\n".join(preview)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    parser.add_argument("settings", type=Path, help="JSON containing every OrnamentSettings field")
    parser.add_argument("output", type=Path, help="New output directory; no existing files are overwritten")
    args = parser.parse_args(argv)
    try:
        if args.output.exists():
            raise ValueError("Output directory already exists; choose a new directory")
        data = json.loads(args.settings.read_text(encoding="utf-8"))
        settings = OrnamentSettings(**data)
        gcode, report, preview = generate_engraving(args.image, settings)
        args.output.mkdir(parents=True, exist_ok=False)
        (args.output / "engraving.nc").write_text(gcode, encoding="ascii")
        (args.output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        (args.output / "engraving-preview.svg").write_text(preview, encoding="utf-8")
    except (ValueError, TypeError, OSError, Image.DecompressionBombError) as exc:
        parser.exit(2, f"Ornament export rejected: {exc}\n")
    print(f"Offline engraving exported to {args.output}; read report.json before any machine use.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
