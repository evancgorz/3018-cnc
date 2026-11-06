"""Build the offline V-bit detail leg of the Hawkeye two-bit review bundle.

This uses the approved black-and-white artwork as geometry. It never connects
to the CNC and emits a review-only shallow engraving file, not a cutout.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
import sys

from shapely.geometry import LineString, Point, box
from shapely.ops import unary_union
import shapely


ROOT = Path(__file__).resolve().parents[4]
OUT = Path(__file__).resolve().parent
SOURCE = ROOT / "artifacts" / "ornaments" / "hawkeye" / "approved-artwork-reference.png"
sys.path.insert(0, str(ROOT / "src"))

from ttc3018_control.gcode import (  # noqa: E402
    parse_gcode,
    validate_nonnegative_work_xy,
    validate_rapid_xy_clearance,
)
from ttc3018_control.ornament_cam import (  # noqa: E402
    ROUND_GUARD,
    OrnamentSettings,
    _motion_metrics,
    _polygons,
    optimize_engraving_paths,
    plan_engraving,
    raster_region,
)
from PIL import Image, ImageDraw  # noqa: E402
import numpy as np  # noqa: E402


STOCK = 110.0
STOCK_THICKNESS = 3.0
PART_DIAMETER = 100.0
PART_CENTER = (55.0, 55.0)
ART_DIAMETER = 90.0
STOCK_MARGIN = 5.0
PLACEMENT = (10.0, 10.0)
HOLE_CENTER = (55.0, 100.0)
HOLE_RADIUS = 2.0
HOLE_ENGRAVE_CLEARANCE = 1.0
HOLE_KEEPOUT_RADIUS = HOLE_RADIUS + HOLE_ENGRAVE_CLEARANCE

V_ANGLE = 60.0
TIP_DIAMETER = 0.05
COARSE_DEPTH = 0.45
COARSE_STEPOVER = 0.25
COARSE_STEPDOWN = 0.25
MIN_RESIDUAL_COMPONENT_AREA = 0.1
SKELETON_SCALE = 2
SKELETON_CLEARANCE = 0.015
SAFE_Z = 3.0
APPROACH_Z = 0.2
CUT_FEED = 300.0
PLUNGE_FEED = 80.0
THRESHOLD = 128


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def settings_for(image_size: tuple[int, int], *, depth: float, stepover: float,
                 stepdown: float) -> OrnamentSettings:
    return OrnamentSettings(
        crop=(0, 0, image_size[0], image_size[1]),
        outer_diameter=PART_DIAMETER,
        art_diameter=ART_DIAMETER,
        stock_thickness=STOCK_THICKNESS,
        stock_margin=STOCK_MARGIN,
        engraving_depth=depth,
        v_angle=V_ANGLE,
        tip_diameter=TIP_DIAMETER,
        stepover=stepover,
        max_stepdown=stepdown,
        safe_z=SAFE_Z,
        cut_feed=CUT_FEED,
        plunge_feed=PLUNGE_FEED,
        spindle_rpm=None,
        threshold=THRESHOLD,
        optimize_paths=True,
        approach_z=APPROACH_Z,
    )


def swept(paths, diameter: float, *, conservative: bool = False):
    radius = diameter / 2
    if conservative:
        # Matches the existing planner's emitted-coordinate containment check;
        # the plan inset itself already adds ROUND_GUARD before rounding paths.
        radius = radius / math.cos(math.pi / 128)
    pieces = [LineString(path).buffer(radius, quad_segs=32) for path in paths]
    if not pieces:
        raise ValueError("A detail stage produced no cutter sweep")
    return unary_union(pieces)


def plan_stage(region, settings: OrnamentSettings):
    initial, inset = plan_engraving(region, settings)
    optimized = optimize_engraving_paths(initial, inset, settings)
    initial_metrics = _motion_metrics(initial, settings)
    optimized_metrics = _motion_metrics(optimized, settings)
    if optimized_metrics["estimated_minutes"] < initial_metrics["estimated_minutes"]:
        return optimized, {
            "enabled": True,
            "applied": True,
            "initialPathCount": len(initial),
            "finalPathCount": len(optimized),
            "initialEstimatedMinutes": initial_metrics["estimated_minutes"],
            "finalEstimatedMinutes": optimized_metrics["estimated_minutes"],
        }
    return initial, {
        "enabled": True,
        "applied": False,
        "initialPathCount": len(initial),
        "finalPathCount": len(initial),
        "initialEstimatedMinutes": initial_metrics["estimated_minutes"],
        "finalEstimatedMinutes": initial_metrics["estimated_minutes"],
    }


def rasterize_for_skeleton(geometry, width: int, height: int, pixel_mm: float):
    """Rasterize a geometry on a fine grid for topology-preserving thinning."""
    image = Image.new("1", (width, height), 0)
    draw = ImageDraw.Draw(image)

    def ring_pixels(ring):
        return [((x - PLACEMENT[0]) / pixel_mm,
                 height - (y - PLACEMENT[1]) / pixel_mm)
                for x, y in ring.coords]

    for polygon in _polygons(geometry):
        draw.polygon(ring_pixels(polygon.exterior), fill=1)
        for interior in polygon.interiors:
            draw.polygon(ring_pixels(interior), fill=0)
    return np.asarray(image, dtype=bool)


def thin_skeleton(mask):
    """Zhang-Suen thinning; deterministic and dependency-free beyond NumPy."""
    work = mask.copy()
    while True:
        changed = False
        for phase in (0, 1):
            padded = np.pad(work, 1, constant_values=False)
            center = padded[1:-1, 1:-1]
            neighbors = (
                padded[:-2, 1:-1], padded[:-2, 2:], padded[1:-1, 2:],
                padded[2:, 2:], padded[2:, 1:-1], padded[2:, :-2],
                padded[1:-1, :-2], padded[:-2, :-2],
            )
            count = sum(neighbors)
            transitions = sum(
                (~neighbors[index] & neighbors[(index + 1) % 8])
                for index in range(8)
            )
            common = center & (count >= 2) & (count <= 6) & (transitions == 1)
            north, _, east, _, south, west, _, _ = neighbors
            if phase == 0:
                remove = common & ~(north & east & south) & ~(east & south & west)
            else:
                remove = common & ~(north & east & west) & ~(north & south & west)
            if remove.any():
                work[remove] = False
                changed = True
        if not changed:
            return work


def skeleton_paths(residual, source_region, image_size, source_pixel_size):
    """Trace residual medial axes and set V-bit depth from local stroke width."""
    width, height = image_size
    pixel_mm = source_pixel_size / SKELETON_SCALE
    mask = rasterize_for_skeleton(
        residual, width * SKELETON_SCALE, height * SKELETON_SCALE, pixel_mm
    )
    skeleton = thin_skeleton(mask)
    rows, cols = np.nonzero(skeleton)
    pixel_mm = source_pixel_size / SKELETON_SCALE
    physical_x = PLACEMENT[0] + (cols + 0.5) * pixel_mm
    physical_y = PLACEMENT[1] + (height*SKELETON_SCALE - rows - 0.5) * pixel_mm
    points = shapely.points(physical_x, physical_y)
    inside_residual = np.asarray(shapely.covers(residual, points), dtype=bool)
    rows, cols = rows[inside_residual], cols[inside_residual]
    points = points[inside_residual]
    exact_clearance = np.asarray(shapely.distance(points, source_region.boundary), dtype=float)
    usable = exact_clearance >= TIP_DIAMETER/2 + SKELETON_CLEARANCE + 0.0001
    omitted_narrow_nodes = int((~usable).sum())
    rows, cols = rows[usable], cols[usable]
    exact_clearance = exact_clearance[usable]
    pixels = set(zip(rows.tolist(), cols.tolist()))
    if not pixels:
        raise ValueError("Residual detail produced no medial-axis paths")

    adjacency = {}
    for row, col in pixels:
        neighbors = []
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                if not (dr or dc):
                    continue
                point = (row + dr, col + dc)
                if point not in pixels:
                    continue
                # Suppress a diagonal shortcut whenever an orthogonal route
                # already connects the same two pixels.
                if dr and dc and ((row + dr, col) in pixels or (row, col + dc) in pixels):
                    continue
                # Two diagonal residual cells that only touch at a corner do
                # not form a machinable corridor for even the assumed tip.
                if dr and dc and not (mask[row + dr, col] or mask[row, col + dc]):
                    continue
                neighbors.append(point)
        adjacency[(row, col)] = tuple(sorted(neighbors))

    unused = {
        tuple(sorted((point, neighbor)))
        for point, neighbors in adjacency.items() for neighbor in neighbors
    }
    remaining_degree = {point: len(neighbors) for point, neighbors in adjacency.items()}
    active = {point for point, degree in remaining_degree.items() if degree}
    active_odd = {point for point in active if remaining_degree[point] % 2}
    vertex_clearance = {
        (int(row), int(col)): float(clearance - SKELETON_CLEARANCE)
        for row, col, clearance in zip(rows, cols, exact_clearance)
    }

    def walk_edges(start):
        trail = [start]
        current = start
        previous = None
        while True:
            choices = [neighbor for neighbor in adjacency[current]
                       if tuple(sorted((current, neighbor))) in unused]
            if not choices:
                return trail
            if previous is None or len(choices) == 1:
                chosen = choices[0]
            else:
                in_angle = math.atan2(current[0]-previous[0], current[1]-previous[1])
                chosen = min(choices, key=lambda point: (
                    abs((math.atan2(point[0]-current[0], point[1]-current[1]) - in_angle + math.pi) % (2*math.pi) - math.pi),
                    point,
                ))
            edge = tuple(sorted((current, chosen)))
            unused.remove(edge)
            for point in edge:
                remaining_degree[point] -= 1
                if remaining_degree[point] == 0:
                    active.discard(point)
                    active_odd.discard(point)
                elif remaining_degree[point] % 2:
                    active_odd.add(point)
                else:
                    active_odd.discard(point)
            trail.append(chosen)
            previous, current = current, chosen

    trails = []
    while unused:
        start = min(active_odd) if active_odd else min(active)
        trail = walk_edges(start)
        if len(trail) < 2:
            raise ValueError("Medial-axis graph contains an untraceable edge")
        trails.append(trail)

    # Nearest-endpoint ordering reduces safe-Z XY travel between disconnected
    # strokes while retaining each exact graph edge and its local depth profile.
    xy_scale = source_pixel_size / SKELETON_SCALE
    origin_x, origin_y = PLACEMENT

    def physical(point):
        row, col = point
        return (origin_x + (col + 0.5) * xy_scale,
                origin_y + (height*SKELETON_SCALE - row - 0.5) * xy_scale)

    ordered = []
    current_xy = (0.0, 0.0)
    remaining = list(trails)
    while remaining:
        index, reverse = min(
            ((index, reverse) for index, trail in enumerate(remaining) for reverse in (False, True)),
            key=lambda item: (math.dist(current_xy, physical(remaining[item[0]][-1 if item[1] else 0])), item),
        )
        trail = remaining.pop(index)
        if reverse:
            trail.reverse()
        path = []
        for point in trail:
            clearance = vertex_clearance[point]
            depth = min(COARSE_DEPTH, (clearance - TIP_DIAMETER/2) / math.tan(math.radians(V_ANGLE/2)))
            depth = math.floor(max(depth, 0.0) * 10000) / 10000
            if depth < 0.0001:
                # An isolated undersized stroke cannot fit the assumed tip.
                depth = 0.0001
            path.append((*physical(point), depth))
        ordered.append(tuple(path))
        current_xy = path[-1][:2]
    if not ordered:
        raise ValueError("No centerline paths remained after planning")
    return tuple(ordered), {
        "method": "residual medial-axis centerlines with local V-bit width-to-depth mapping",
        "skeletonGridScale": SKELETON_SCALE,
        "skeletonNodeCount": len(pixels),
        "skeletonNodesOutsideResidualFiltered": int((~inside_residual).sum()),
        "skeletonNodesTooNarrowForTipFiltered": omitted_narrow_nodes,
        "pathCount": len(ordered),
        "maximumDepthMm": max(max(point[2] for point in path) for path in ordered),
        "minimumDepthMm": min(min(point[2] for point in path) for path in ordered),
        "clearanceGuardMm": SKELETON_CLEARANCE,
        "widthEstimate": "exact vector distance to the approved black-region boundary",
    }


def variable_depth_sweep(paths):
    """Conservative envelope of linear XY/Z V-bit moves for each medial path."""
    pieces = []
    tangent = math.tan(math.radians(V_ANGLE/2))
    for path in paths:
        for x, y, depth in path:
            radius = (TIP_DIAMETER + 2*depth*tangent) / 2
            radius = radius / math.cos(math.pi/128) + ROUND_GUARD
            pieces.append(Point(x, y).buffer(radius, quad_segs=32))
        for a, b in zip(path, path[1:]):
            ra = (TIP_DIAMETER + 2*a[2]*tangent) / 2
            rb = (TIP_DIAMETER + 2*b[2]*tangent) / 2
            ra = ra / math.cos(math.pi/128) + ROUND_GUARD
            rb = rb / math.cos(math.pi/128) + ROUND_GUARD
            # The convex hull of the endpoint disks bounds the complete linearly
            # varying-width sweep and stays conservative at output precision.
            pieces.append(unary_union((
                Point(a[0], a[1]).buffer(ra, quad_segs=32),
                Point(b[0], b[1]).buffer(rb, quad_segs=32),
            )).convex_hull)
    return unary_union(pieces)


def path_data(geometry) -> str:
    chunks = []
    for polygon in _polygons(geometry):
        for ring in (polygon.exterior, *polygon.interiors):
            coords = list(ring.coords)
            if len(coords) < 4:
                continue
            chunks.append(
                f"M {coords[0][0]:.4f} {coords[0][1]:.4f} "
                + " ".join(f"L {x:.4f} {y:.4f}" for x, y in coords[1:])
                + " Z"
            )
    return " ".join(chunks)


def polyline_elements(paths, color: str, width: float) -> str:
    return "\n".join(
        '<polyline points="' + " ".join(f"{point[0]:.4f},{point[1]:.4f}" for point in path)
        + f'" stroke="{color}" stroke-width="{width:.5f}"/>'
        for path in paths
    )


def variable_polyline_elements(paths, color: str) -> str:
    tangent = math.tan(math.radians(V_ANGLE/2))
    elements = []
    for path in paths:
        for a, b in zip(path, path[1:]):
            width = TIP_DIAMETER + (a[2] + b[2]) * tangent
            elements.append(
                f'<line x1="{a[0]:.4f}" y1="{a[1]:.4f}" '
                f'x2="{b[0]:.4f}" y2="{b[1]:.4f}" '
                f'stroke="{color}" stroke-width="{width:.5f}" '
                'stroke-linecap="round"/>'
            )
    return "\n".join(elements)


def write_preview(source_region, coarse_paths, fine_paths, coarse_diameter: float,
                  fine_diameter: float, source_sha: str) -> Path:
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="110mm" height="126mm" viewBox="0 0 110 126">
<title>Hawkeye approved artwork with actual two-depth V-bit toolpaths</title>
<desc>Gray is thresholded approved source artwork. Blue and amber strokes show the emitted V-bit centerline sweeps at the deepest depth of each stage. The red circle is the hanger no-engrave keepout; source black overlapping it is intentionally reserved and reported.</desc>
<rect width="110" height="126" fill="#fff"/>
<g transform="translate(0 110) scale(1 -1)">
<rect x="0" y="0" width="110" height="110" fill="#f5f0e6" stroke="#34495e" stroke-width="0.35"/>
<circle cx="55" cy="55" r="50" fill="none" stroke="#34495e" stroke-width="0.35"/>
<path d="{path_data(source_region)}" fill="#9aa2aa" fill-rule="evenodd" opacity="0.56"/>
<g fill="none" stroke="#176b91" stroke-linecap="round" stroke-linejoin="round">
{polyline_elements(coarse_paths, '#176b91', coarse_diameter)}
</g>
<g fill="none" stroke-linejoin="round">
{variable_polyline_elements(fine_paths, '#d28b16')}
</g>
<circle cx="{HOLE_CENTER[0]}" cy="{HOLE_CENTER[1]}" r="{HOLE_KEEPOUT_RADIUS}" fill="#fff" stroke="#bf3535" stroke-width="0.22" stroke-dasharray="0.7 0.45"/>
<circle cx="{HOLE_CENTER[0]}" cy="{HOLE_CENTER[1]}" r="{HOLE_RADIUS}" fill="none" stroke="#bf3535" stroke-width="0.2"/>
</g>
<g font-family="sans-serif" fill="#29333d">
<text x="2" y="114" font-size="1.9">Gray: approved thresholded artwork • Blue: broad fill, Z −{COARSE_DEPTH:g}, width {coarse_diameter:.3f} mm</text>
<text x="2" y="117" font-size="1.9">Amber: residual centerlines, V-bit depth follows stroke width (up to {COARSE_DEPTH:.2f} mm) • Red: 3 mm hanger keepout</text>
<text x="2" y="120" font-size="1.75">110 × 110 stock • 100 mm circle centered at X55 Y55 • shared XY origin lower-left</text>
<text x="2" y="123" font-size="1.55">Centerline sweeps from emitted G-code; dimensions and source hash are in detail-report.json</text>
</g>
</svg>'''
    path = OUT / "detail-preview-optimized-candidate.svg"
    path.write_text(svg, encoding="utf-8")
    return path


def program_lines(coarse_paths, fine_paths) -> str:
    lines = [
        "; OFFLINE REVIEW DRAFT ONLY - not verified or authorized for cutting",
        "; Source is approved-artwork-reference.png; black threshold cells only, no redraw",
        "; 60 degree V-bit; assumed 0.05 mm tip; actual tool/runout are unverified",
        "; Shallow engraving only; hanger hole and outer cutout are in separate 02 file",
        "; Work XY: 110 x 110 stock, lower-left origin; 100 mm disc centered X55 Y55",
        f"; Art resized proportionally to 90 mm; hanger no-engrave keepout radius {HOLE_KEEPOUT_RADIUS:g} mm",
        f"; Broad stage reaches Z-{COARSE_DEPTH:g} in <= {COARSE_STEPDOWN:g} mm passes; floor is scalloped",
        "; Fine stage follows residual medial axes; local V-bit depth matches each stroke width",
        f"; XY rapid safe Z{SAFE_Z:g}; illustrative vertical approach Z{APPROACH_Z:g}",
        "; Feeds are assumed; spindle startup intentionally omitted; no automatic tool change",
        "G21 G17 G90 G94 G54",
        "M5",
        f"G0 Z{SAFE_Z:.4f}",
        f"; STAGE 1: broad filled black regions, V-bit effective diameter at final depth {settings_for((1, 1), depth=COARSE_DEPTH, stepover=COARSE_STEPOVER, stepdown=COARSE_STEPDOWN).effective_diameter:.4f} mm",
    ]
    for depth in (0.25, COARSE_DEPTH):
        lines.append(f"; Broad pass to Z-{depth:.4f}")
        for path in coarse_paths:
            x, y = path[0]
            lines.extend((
                f"G0 Z{SAFE_Z:.4f}", f"G0 X{x:.4f} Y{y:.4f}",
                f"G0 Z{APPROACH_Z:.4f}", f"G1 Z{-depth:.4f} F{PLUNGE_FEED:.4f}",
            ))
            lines.extend(f"G1 X{x:.4f} Y{y:.4f} F{CUT_FEED:.4f}" for x, y in path[1:])
    lines.append("; STAGE 2: residual medial-axis detail, local-width V-bit carving")
    for path in fine_paths:
        passes = 2 if max(point[2] for point in path) > COARSE_STEPDOWN else 1
        for pass_index in range(passes):
            first = pass_index == 0
            x, y, target_depth = path[0]
            start_depth = min(target_depth, COARSE_STEPDOWN) if passes == 2 and first else target_depth
            lines.extend((
                f"G0 Z{SAFE_Z:.4f}", f"G0 X{x:.4f} Y{y:.4f}",
                f"G0 Z{APPROACH_Z:.4f}", f"G1 Z{-start_depth:.4f} F{PLUNGE_FEED:.4f}",
            ))
            for px, py, depth in path[1:]:
                pass_depth = min(depth, COARSE_STEPDOWN) if passes == 2 and first else depth
                lines.append(f"G1 X{px:.4f} Y{py:.4f} Z{-pass_depth:.4f} F{CUT_FEED:.4f}")
    lines.extend((f"G0 Z{SAFE_Z:.4f}", "M5", "M2"))
    return "\n".join(lines) + "\n"


def main() -> None:
    with Image.open(SOURCE) as image:
        image_size = image.size
    coarse = settings_for(image_size, depth=COARSE_DEPTH, stepover=COARSE_STEPOVER, stepdown=COARSE_STEPDOWN)
    source_region, pixel_size = raster_region(SOURCE, coarse)
    keepout = Point(*HOLE_CENTER).buffer(HOLE_KEEPOUT_RADIUS, quad_segs=256)
    clipped_by_hole = source_region.intersection(keepout)
    work_region = source_region.difference(keepout)
    if work_region.is_empty:
        raise ValueError("Hanger keepout removed all engravable artwork")

    coarse_paths, coarse_optimization = plan_stage(work_region, coarse)
    coarse_sweep = swept(coarse_paths, coarse.effective_diameter)
    # Conservative, quantized centerline envelopes must stay inside the original
    # approved black pixels and outside the hanger reserve.
    coarse_guard = swept(coarse_paths, coarse.effective_diameter, conservative=True)
    if not source_region.covers(coarse_guard) or not work_region.covers(coarse_guard):
        raise ValueError("Broad-stage quantized cutter footprint leaves approved black or enters hanger keepout")

    residual = work_region.difference(coarse_sweep)
    residual_components = list(_polygons(residual))
    dust = [part for part in residual_components if part.area < MIN_RESIDUAL_COMPONENT_AREA]
    if residual.is_empty:
        raise ValueError("No residual artwork remains for the required fine-detail stage")
    fine_paths, fine_planning = skeleton_paths(residual, work_region, image_size, pixel_size)
    fine_sweep = variable_depth_sweep(fine_paths)
    fine_guard = fine_sweep
    if not source_region.covers(fine_guard) or not work_region.covers(fine_guard):
        outside = fine_guard.difference(work_region)
        raise ValueError(
            f"Residual medial-axis sweep leaves approved black or enters hanger keepout "
            f"(outside={outside.area:.6f} mm2; bounds={outside.bounds})"
        )

    combined_sweep = unary_union((coarse_sweep, fine_sweep))
    omitted_work_art = work_region.difference(combined_sweep)
    total_uncovered = source_region.difference(combined_sweep)
    fine_target_uncovered = residual.difference(fine_sweep)

    gcode = program_lines(coarse_paths, fine_paths)
    nc_path = OUT / "01-detail-review-optimized-candidate.nc"
    nc_path.write_text(gcode, encoding="ascii", newline="\n")
    program = parse_gcode(gcode, nc_path)
    validate_nonnegative_work_xy(program)
    validate_rapid_xy_clearance(program, SAFE_Z)
    stock = box(0, 0, STOCK, STOCK)
    if not stock.buffer(0.001).covers(coarse_guard.union(fine_guard)):
        raise ValueError("Emitted V-bit cutter sweep leaves the declared stock envelope")
    executable = "\n".join(line for line in gcode.splitlines() if not line.lstrip().startswith(";"))
    if re.search(r"\bM\s*(?:3|6)\b", executable, re.IGNORECASE):
        raise ValueError("Detail draft unexpectedly starts spindle or changes tool")
    if executable.splitlines()[1] != "M5" or executable.splitlines()[-2:] != ["M5", "M2"]:
        raise ValueError("Detail draft must use initial/final M5 and one final M2")
    if len(re.findall(r"\bM\s*(?:2|30)\b", executable, re.IGNORECASE)) != 1:
        raise ValueError("Detail draft must have one program end")

    preview_path = write_preview(
        source_region, coarse_paths, fine_paths,
        coarse.effective_diameter,
        TIP_DIAMETER + 2*fine_planning["maximumDepthMm"]*math.tan(math.radians(V_ANGLE/2)),
        sha256(SOURCE),
    )
    report = {
        "schemaVersion": 1,
        "bundle": "hawkeye-two-bit-vbit-detail-review",
        "releaseStatus": "offline-review-only; not verified or authorized for cutting",
        "rebuildCommand": ".\\.venv\\Scripts\\python.exe artifacts/ornaments/hawkeye/two-bit/prepare-detail-optimized-candidate.py",
        "scope": "Approved-artwork shallow V-bit detail only; hanger-hole and outer cutout are separate endmill operation 02.",
        "source": {
            "path": "artifacts/ornaments/hawkeye/approved-artwork-reference.png",
            "sha256": sha256(SOURCE),
            "imageSizePx": list(image_size),
            "threshold": THRESHOLD,
            "pixelSizeMm": pixel_size,
            "method": "Thresholded source black pixels mapped proportionally to 90 mm; no redraw, contour reconstruction or generated artwork.",
        },
        "geometry": {
            "units": "mm",
            "stock": {"width": STOCK, "height": STOCK, "origin": "lower-left", "assumedThickness": STOCK_THICKNESS, "thicknessMeasured": False},
            "part": {"shape": "analytic 100 mm circle", "diameter": PART_DIAMETER, "centerWorkXY": list(PART_CENTER)},
            "artwork": {"diameter": ART_DIAMETER, "placementOriginWorkXY": list(PLACEMENT), "sameXYAsCutout": True, "outerRimClearanceMm": (PART_DIAMETER-ART_DIAMETER)/2},
            "hangerKeepout": {"holeCenterWorkXY": list(HOLE_CENTER), "assumedHoleRadiusMm": HOLE_RADIUS, "engravingClearanceMm": HOLE_ENGRAVE_CLEARANCE, "noEngraveRadiusMm": HOLE_KEEPOUT_RADIUS, "sourceBlackRemovedMm2": clipped_by_hole.area, "clippedBoundsWorkXY": list(clipped_by_hole.bounds) if not clipped_by_hole.is_empty else None, "warning": "Keepout trims source black near the top-center emblem; inspect preview for impact on the outer ring/title."},
        },
        "tool": {"type": "assumed 60 degree V-bit", "includedAngleDeg": V_ANGLE, "tipDiameterMm": TIP_DIAMETER, "tipDiameterVerified": False, "runoutVerified": False, "spindleStartupIncluded": False, "automaticToolchangeIncluded": False},
        "stages": [
            {"order": 1, "name": "broad filled black regions", "sourceTarget": "approved black regions reachable at max depth", "maximumDepthMm": COARSE_DEPTH, "depthPassesMm": [-0.25, -COARSE_DEPTH], "maximumStepdownMm": COARSE_STEPDOWN, "stepoverMm": COARSE_STEPOVER, "effectiveDiameterAtMaxDepthMm": coarse.effective_diameter, "pathCount": len(coarse_paths), "optimization": coarse_optimization, "floor": "V-shaped and scalloped; not a flat-bottom pocket"},
            {"order": 2, "name": "residual variable-depth centerlines", "sourceTarget": "all black residual after actual broad-stage cutter sweep; no residual-area threshold", "maximumDepthMm": fine_planning["maximumDepthMm"], "depthPassesMm": "local V-bit depth; paths above 0.25 mm use two passes, with each step <= 0.25 mm", "maximumStepdownMm": COARSE_STEPDOWN, "effectiveDiameterRangeMm": [TIP_DIAMETER, TIP_DIAMETER + 2*fine_planning["maximumDepthMm"]*math.tan(math.radians(V_ANGLE/2))], "pathCount": len(fine_paths), "planning": fine_planning, "normalCutterRadiusErosionApplied": False},
        ],
        "sweepReview": {
            "sourceBlackAreaBeforeHangerKeepoutMm2": source_region.area,
            "sourceBlackRemovedByHangerKeepoutMm2": clipped_by_hole.area,
            "availableSourceBlackAreaMm2": work_region.area,
            "broadActualSweepAreaMm2": coarse_sweep.area,
            "broadSweepInsideAvailableBlackMm2": work_region.intersection(coarse_sweep).area,
            "residualAfterBroadSweepMm2": residual.area,
            "residualComponentsBelow0_1Mm2": len(dust),
            "residualAreaIntentionallyDroppedBelow0_1Mm2": sum(part.area for part in dust),
            "residualComponentsRetainedForFinePlanning": len(residual_components),
            "fineTargetAfterBufferAndSourceClipMm2": residual.area,
            "fineActualSweepAreaMm2": fine_sweep.area,
            "fineSweepInsideAvailableBlackMm2": work_region.intersection(fine_sweep).area,
            "fineResidualNotCoveredByEmittedFineSweepMm2": fine_target_uncovered.area,
            "combinedSweepInsideAvailableBlackMm2": work_region.intersection(combined_sweep).area,
            "availableSourceBlackOmittedByBothStagesMm2": omitted_work_art.area,
            "availableSourceBlackOmittedPercent": 100 * omitted_work_art.area / work_region.area,
            "allSourceBlackNotSweptIncludingHangerKeepoutMm2": total_uncovered.area,
            "fineSweepOverlapWithBroadSweepMm2": fine_sweep.intersection(coarse_sweep).area,
            "conservativeQuantizedSweepContainedInOriginalBlack": True,
            "conservativeQuantizedSweepRespectsHangerKeepout": True,
            "coarseBufferMethod": "LineString cutter-radius sweep with 32 quadrant segments; containment verified using the planner's radius/cos(pi/128) envelope. The planner adds its 0.0002 mm inset guard before 0.0001 mm output quantization.",
            "fineResidualMethod": "Subtract broad-stage emitted sweep from thresholded source black, rasterize residual at 2x source resolution, Zhang-Suen thin it, trace graph paths, and set V-bit depth from each point's distance to the original approved-black boundary. Conservative swept envelopes of emitted linear XY/Z moves are verified inside the approved black region and outside the hanger keepout.",
        },
        "motionReview": {
            "approachZMm": APPROACH_Z,
            "safeZMm": SAFE_Z,
            "cutFeedMmPerMin": CUT_FEED,
            "plungeFeedMmPerMin": PLUNGE_FEED,
            "xyRapidsRemainAtSafeZ": True,
            "exactCombinedProgramEstimatedMinutes": program.estimated_seconds / 60,
            "estimateSource": "parse_gcode(complete emitted NC).estimated_seconds; linear distance/feed model, not measured cycle time.",
            "gcodeLineCount": len(gcode.splitlines()),
            "m5Count": len(re.findall(r"\bM\s*5\b", executable, re.IGNORECASE)),
            "m3Count": 0,
            "m6Count": 0,
            "programEndCount": 1,
        },
        "unknownsBlockingProduction": [
            "actual V-bit included angle, tip diameter, runout and condition",
            "measured stock thickness, flatness, finish and exact Z0",
            "validated spindle RPM, cut feed, plunge feed and V-bit depth limits",
            "fixture, clamp, spoilboard and full tool-clearance review",
            "manual two-tool change, XY preservation, re-probeZ and fresh authorization workflow",
            "physical coupon, fine-line fidelity, floor scalloping, tear-out and hanger-hole overlap review",
        ],
        "offlineChecks": {
            "gcodeParses": True,
            "nonnegativeWorkXY": True,
            "rapidXYAtSafeZ": True,
            "oneToolNoM3NoM6": True,
            "initialAndFinalM5": True,
            "oneFinalProgramEnd": True,
            "allSweepsInsideStock": True,
            "coarseAndFineSweepsInsideApprovedBlack": True,
            "holeKeepoutPreserved": True,
            "fineStageTargetIsDerivedFromCoarseResidual": True,
            "fineStageUsesLocalVBitDepth": True,
            "fineStageSweepsVerifiedAgainstApprovedBlack": True,
        },
        "artifacts": {
            "source": {"path": "artifacts/ornaments/hawkeye/two-bit/prepare-detail-optimized-candidate.py", "sha256": sha256(Path(__file__))},
            "gcode": {"path": "artifacts/ornaments/hawkeye/two-bit/01-detail-review-optimized-candidate.nc", "sha256": sha256(nc_path)},
            "preview": {"path": "artifacts/ornaments/hawkeye/two-bit/detail-preview-optimized-candidate.svg", "sha256": sha256(preview_path)},
        },
    }
    (OUT / "detail-report-optimized-candidate.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "nc": str(nc_path),
        "preview": str(preview_path),
        "broadPaths": len(coarse_paths),
        "finePaths": len(fine_paths),
        "estimatedMinutes": report["motionReview"]["exactCombinedProgramEstimatedMinutes"],
        "omittedBlackMm2": omitted_work_art.area,
        "hangerKeepoutClippedMm2": clipped_by_hole.area,
    }, indent=2))


if __name__ == "__main__":
    main()
