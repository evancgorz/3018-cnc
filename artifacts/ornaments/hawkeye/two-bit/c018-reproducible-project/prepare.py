"""Rebuild the offline, review-only Hawkeye ornament project bundle."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import sys

from shapely import maximum_inscribed_circle
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union


ROOT = Path(__file__).resolve().parents[5]
OUT = Path(__file__).resolve().parent
SOURCE = ROOT / "artifacts" / "ornaments" / "hawkeye" / "approved-artwork-reference.png"
VBIT_SETUP = ROOT / "examples" / "hardware-setups" / "plywood-vbit-engraving.json"
ENDMILL_SETUP = ROOT / "examples" / "hardware-setups" / "plywood-endmill-profile.json"
sys.path.insert(0, str(ROOT / "src"))

from ttc3018_control.gcode import (  # noqa: E402
    parse_gcode,
    validate_nonnegative_work_xy,
    validate_rapid_xy_clearance,
)
from ttc3018_control.ornament_cam import (  # noqa: E402
    OrnamentSettings,
    _polygons,
    _motion_metrics,
    optimize_engraving_paths,
    plan_engraving,
    raster_region,
)
from ttc3018_control.step_engraver import generate_step_gcode  # noqa: E402
from ttc3018_control.step_geometry import (  # noqa: E402
    PlanarLoop,
    Point2D,
    StepPlanarModel,
)
from ttc3018_control.step_simulation import simulate_profile_paths  # noqa: E402
from PIL import Image  # noqa: E402


PART_DIAMETER_MM = 100.0
ART_DIAMETER_MM = 90.0
STOCK_MARGIN_MM = 5.0
STOCK_SIZE_MM = 110.0
PART_CENTER = (55.0, 55.0)
HOLE_CENTER = (55.0, 100.0)
HOLE_DIAMETER_MM = 4.0
HANGER_ENGRAVE_KEEPOUT_MM = 3.0
STOCK_THICKNESS_MM = 3.25
VBIT_ANGLE_DEG = 30.0
VBIT_TIP_MM = 0.1
ENGRAVING_DEPTH_MM = 0.25
ENGRAVING_STEPOVER_MM = 0.12
ENGRAVING_MAX_STEPDOWN_MM = 0.125
SAFE_Z_MM = 3.0
VBIT_FEED_MM_MIN = 300.0
VBIT_PLUNGE_MM_MIN = 80.0
ENDMILL_DIAMETER_MM = 3.175
PROFILE_FEED_MM_MIN = 180.0
PROFILE_PLUNGE_MM_MIN = 65.0
PROFILE_BREAKTHROUGH_MM = 0.2
TAB_COUNT = 4
TAB_WIDTH_MM = 3.0
TAB_HEIGHT_MM = 0.7
THRESHOLD = 128


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def settings(image_size: tuple[int, int]) -> OrnamentSettings:
    return OrnamentSettings(
        crop=(0, 0, image_size[0], image_size[1]),
        outer_diameter=PART_DIAMETER_MM,
        art_diameter=ART_DIAMETER_MM,
        stock_thickness=STOCK_THICKNESS_MM,
        stock_margin=STOCK_MARGIN_MM,
        engraving_depth=ENGRAVING_DEPTH_MM,
        v_angle=VBIT_ANGLE_DEG,
        tip_diameter=VBIT_TIP_MM,
        stepover=ENGRAVING_STEPOVER_MM,
        max_stepdown=ENGRAVING_MAX_STEPDOWN_MM,
        safe_z=SAFE_Z_MM,
        cut_feed=VBIT_FEED_MM_MIN,
        plunge_feed=VBIT_PLUNGE_MM_MIN,
        spindle_rpm=None,
        threshold=THRESHOLD,
        optimize_paths=True,
        approach_z=None,
    )


def circular_loop(center: tuple[float, float], radius: float, segments: int = 1024) -> PlanarLoop:
    return PlanarLoop(tuple(
        Point2D(
            center[0] + radius * math.cos(index * math.tau / segments),
            center[1] + radius * math.sin(index * math.tau / segments),
        )
        for index in range(segments)
    ))


def vector_svg(region, size: float) -> str:
    paths = []
    for polygon in _polygons(region):
        for ring in (polygon.exterior, *polygon.interiors):
            coordinates = list(ring.coords)
            if len(coordinates) < 4:
                continue
            paths.append(
                f"M {coordinates[0][0]:.6f} {coordinates[0][1]:.6f} "
                + " ".join(f"L {x:.6f} {y:.6f}" for x, y in coordinates[1:])
                + " Z"
            )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size:g}mm" '
        f'height="{size:g}mm" viewBox="0 0 {size:g} {size:g}">\n'
        "<title>Thresholded approved artwork in the 110 mm stock XY frame</title>\n"
        "<desc>Black paths are the exact thresholded source pixels mapped to 90 mm; "
        "red is the 100 mm part boundary; gray is the hanger no-engrave keepout. "
        "This is vectorized raster geometry, not independently authored vector art.</desc>\n"
        '<g transform="translate(0 110) scale(1 -1)" fill="#111" fill-rule="evenodd">\n'
        f'<path d="{" ".join(paths)}"/>\n</g>\n'
        f'<circle cx="{PART_CENTER[0]}" cy="{PART_CENTER[1]}" r="{PART_DIAMETER_MM / 2:g}" '
        'fill="none" stroke="#b22" stroke-width="0.08"/>\n'
        f'<circle cx="{HOLE_CENTER[0]}" cy="{STOCK_SIZE_MM - HOLE_CENTER[1]}" r="{HOLE_DIAMETER_MM / 2 + HANGER_ENGRAVE_KEEPOUT_MM:g}" '
        'fill="#ddd" fill-opacity="0.7" stroke="#a22" stroke-dasharray="0.4 0.25" stroke-width="0.08"/>\n'
        f'<circle cx="{HOLE_CENTER[0]}" cy="{STOCK_SIZE_MM - HOLE_CENTER[1]}" r="{HOLE_DIAMETER_MM / 2:g}" '
        'fill="none" stroke="#a22" stroke-width="0.08"/>\n'
        "</svg>\n"
    )


def svg_path(geometry) -> str:
    paths = []
    if isinstance(geometry, LineString):
        lines = [geometry]
    elif geometry.geom_type == "MultiLineString":
        lines = list(geometry.geoms)
    else:
        lines = []
    for line in lines:
        coordinates = list(line.coords)
        if len(coordinates) >= 2:
            paths.append(
                f"M {coordinates[0][0]:.6f} {coordinates[0][1]:.6f} "
                + " ".join(f"L {x:.6f} {y:.6f}" for x, y in coordinates[1:])
            )
    for polygon in _polygons(geometry):
        for ring in (polygon.exterior, *polygon.interiors):
            coordinates = list(ring.coords)
            if len(coordinates) < 4:
                continue
            paths.append(
                f"M {coordinates[0][0]:.6f} {coordinates[0][1]:.6f} "
                + " ".join(f"L {x:.6f} {y:.6f}" for x, y in coordinates[1:])
                + " Z"
            )
    return " ".join(paths)


def profile_preview(profile_gcode: str, all_sweeps) -> str:
    program = parse_gcode(profile_gcode)
    radius = ENDMILL_DIAMETER_MM / 2
    through_parts = []
    tab_parts = []
    for segment in program.segments:
        if segment.rapid or math.dist(
            (segment.start.x, segment.start.y),
            (segment.end.x, segment.end.y),
        ) <= 1e-8:
            continue
        depth = max(0.0, -min(segment.start.z, segment.end.z))
        line = LineString(((segment.start.x, segment.start.y), (segment.end.x, segment.end.y)))
        swept = line.buffer(radius / math.cos(math.pi / 128), quad_segs=32)
        if depth >= STOCK_THICKNESS_MM + PROFILE_BREAKTHROUGH_MM - 1e-4:
            through_parts.append(swept)
        elif math.isclose(depth, STOCK_THICKNESS_MM - TAB_HEIGHT_MM, abs_tol=1e-4):
            tab_parts.append(line)
    if not through_parts or not tab_parts:
        raise ValueError("Exact profile output is missing through-cut or tab-floor geometry")
    through_sweep = unary_union(through_parts)
    tabs = unary_union(tab_parts)
    return "\n".join((
        '<svg xmlns="http://www.w3.org/2000/svg" width="110mm" height="110mm" viewBox="0 0 110 110">',
        "<title>Exact emitted disc and hole profile sweep, including tab retention</title>",
        "<desc>Blue is the full-depth endmill sweep parsed from the exact profile NC. Orange marks exact emitted tab-floor path segments retained at Z-2.55. Frame is a candidate 110 mm stock, not a measured setup.</desc>",
        '<rect width="110" height="110" fill="#faf8f2"/>',
        '<g transform="translate(0 110) scale(1 -1)">',
        f'<path d="{svg_path(all_sweeps)}" fill="#176b91" fill-opacity="0.22" stroke="none"/>',
        f'<path d="{svg_path(through_sweep)}" fill="#176b91" fill-opacity="0.48" stroke="none"/>',
        f'<path d="{svg_path(tabs)}" fill="none" stroke="#d28b16" stroke-width="{ENDMILL_DIAMETER_MM:g}" stroke-linecap="round"/>',
        f'<circle cx="{PART_CENTER[0]}" cy="{PART_CENTER[1]}" r="{PART_DIAMETER_MM / 2:g}" fill="none" stroke="#29333d" stroke-width="0.12"/>',
        f'<circle cx="{HOLE_CENTER[0]}" cy="{HOLE_CENTER[1]}" r="{HOLE_DIAMETER_MM / 2:g}" fill="none" stroke="#a22" stroke-width="0.16"/>',
        "</g>",
        '<g font-family="sans-serif" font-size="1.7" fill="#29333d">',
        '<text x="2" y="106">Blue: exact full-depth cutter sweep; orange: outer tabs retained to Z-2.55</text>',
        '<text x="2" y="108">110 x 110 mm candidate stock; 100 mm disc, 4 mm hole; review only</text>',
        "</g>",
        "</svg>",
        "",
    ))


def path_sweep(program, tool_radius_at_depth):
    shapes = []
    for segment in program.segments:
        if segment.rapid or math.dist(
            (segment.start.x, segment.start.y),
            (segment.end.x, segment.end.y),
        ) <= 1e-8:
            continue
        depth = max(0.0, -min(segment.start.z, segment.end.z))
        if depth <= 1e-8:
            continue
        radius = tool_radius_at_depth(depth)
        shapes.append(
            LineString(
                ((segment.start.x, segment.start.y), (segment.end.x, segment.end.y))
            ).buffer(radius / math.cos(math.pi / 128), quad_segs=32)
        )
    if not shapes:
        raise ValueError("No exact emitted XY cutting moves were found")
    return unary_union(shapes)


def max_circle_diameter(geometry) -> float:
    line = maximum_inscribed_circle(geometry)
    coordinates = list(line.coords)
    return 2 * math.dist(coordinates[0], coordinates[-1]) if len(coordinates) >= 2 else 0.0


def engraving_for_region(region, engraving_settings: OrnamentSettings):
    initial_paths, inset = plan_engraving(region, engraving_settings)
    paths = optimize_engraving_paths(initial_paths, inset, engraving_settings)
    metrics = _motion_metrics(paths, engraving_settings)
    depth_units = round(engraving_settings.engraving_depth * 10000)
    step_units = round(engraving_settings.max_stepdown * 10000)
    passes = (depth_units + step_units - 1) // step_units
    lines = [
        "; OFFLINE REVIEW DRAFT ONLY - not verified or authorized for cutting",
        "; Toolpath geometry was clipped to the explicit hanger no-engrave keepout",
        "G21 G17 G90 G94 G54",
        "M5",
        f"G0 Z{engraving_settings.safe_z:.4f}",
        "(No spindle startup: spindle configuration is unknown)",
    ]
    for pass_index in range(1, passes + 1):
        depth = min(pass_index * step_units, depth_units) / 10000
        lines.append(f"(Engraving pass {pass_index} of {passes})")
        for path in paths:
            x, y = path[0]
            lines.extend((
                f"G0 Z{engraving_settings.safe_z:.4f}",
                f"G0 X{x:.4f} Y{y:.4f}",
                f"G1 Z{-depth:.4f} F{engraving_settings.plunge_feed:.4f}",
            ))
            lines.extend(
                f"G1 X{x:.4f} Y{y:.4f} F{engraving_settings.cut_feed:.4f}"
                for x, y in path[1:]
            )
    lines.extend((f"G0 Z{engraving_settings.safe_z:.4f}", "M5", "M2"))
    return "\n".join(lines) + "\n", metrics, paths


def analyze_artwork(source_region, work_region, source_size, engraving_gcode: str, engraving_settings: OrnamentSettings):
    program = parse_gcode(engraving_gcode)
    validate_nonnegative_work_xy(program)
    validate_rapid_xy_clearance(program, engraving_settings.safe_z)
    swept = path_sweep(
        program,
        lambda depth: (
            engraving_settings.tip_diameter
            + 2 * depth * math.tan(math.radians(engraving_settings.v_angle / 2))
        ) / 2,
    )
    hole_keepout = Point(*HOLE_CENTER).buffer(
        HOLE_DIAMETER_MM / 2 + HANGER_ENGRAVE_KEEPOUT_MM,
        quad_segs=256,
    )
    part = Point(*PART_CENTER).buffer(PART_DIAMETER_MM / 2, quad_segs=512)
    stock_region = box(0.0, 0.0, STOCK_SIZE_MM, STOCK_SIZE_MM)
    if not part.covers(source_region):
        raise ValueError("Thresholded artwork is not contained in the 100 mm part")
    if not work_region.buffer(1e-8).covers(swept):
        raise ValueError("Exact emitted V-bit cutter sweep escapes the approved artwork")
    if swept.intersects(hole_keepout):
        raise ValueError("Exact emitted V-bit cutter sweep enters the hanger keepout")
    if not stock_region.covers(swept):
        raise ValueError("Exact emitted V-bit cutter sweep leaves candidate stock bounds")
    inaccessible = source_region.difference(swept)
    black_components = list(_polygons(source_region))
    component_diameters = [
        max_circle_diameter(component)
        for component in black_components
    ]
    counter_widths = [
        max_circle_diameter(Polygon(interior))
        for polygon in black_components
        for interior in polygon.interiors
        if Polygon(interior).area >= 0.01
    ]
    component_gaps = [
        first.distance(second)
        for index, first in enumerate(black_components)
        for second in black_components[index + 1:]
    ]
    pixel_mm = ART_DIAMETER_MM / source_size[0]
    return {
        "source_black_area_mm2": source_region.area,
        "exact_emitted_sweep_area_mm2": swept.area,
        "exact_emitted_sweep_bounds_xy_mm": list(swept.bounds),
        "unengraved_black_area_mm2": inaccessible.area,
        "unengraved_black_fraction": inaccessible.area / source_region.area,
        "hanger_keepout_black_area_mm2": source_region.intersection(hole_keepout).area,
        "cutter_inaccessible_black_area_outside_keepout_mm2": source_region.difference(
            swept.union(hole_keepout)
        ).area,
        "source_connected_black_components": len(black_components),
        "minimum_connected_black_component_max_inscribed_diameter_mm": min(component_diameters),
        "black_components_with_no_tool-center_at_final_depth": sum(
            diameter < engraving_settings.effective_diameter
            for diameter in component_diameters
        ),
        "minimum_gap_between_distinct_black_components_mm": min(component_gaps, default=None),
        "smallest_source_counter_max_inscribed_diameter_mm": min(counter_widths) if counter_widths else None,
        "source_counter_count_measured": len(counter_widths),
        "source_counters_narrower_than_final_cutter_mm": sum(
            width < engraving_settings.effective_diameter for width in counter_widths
        ),
        "feature_spacing_method": (
            "Raster-vector connected-component maximum-inscribed-circle diameter, minimum "
            "separation between disconnected black components, and minimum enclosed-counter "
            "maximum-inscribed-circle diameter. These are geometric proxies; exact emitted "
            "sweep/unengraved-area checks remain the machining reachability result."
        ),
        "resolution_mm_per_pixel": pixel_mm,
        "tool_diameter_at_final_depth_mm": engraving_settings.effective_diameter,
        "feature_floor": (
            "The 0.234 mm V-bit footprint is the minimum full-width cutting feature "
            "at the selected depth. Exact emitted sweeps preserve all white counters; "
            "unengraved black area is measured and is not silently discarded."
        ),
        "hanger": {
            "hole_center_stock_xy_mm": list(HOLE_CENTER),
            "hole_diameter_mm": HOLE_DIAMETER_MM,
            "engraving_keepout_radius_mm": HOLE_DIAMETER_MM / 2 + HANGER_ENGRAVE_KEEPOUT_MM,
            "nearest_part_edge_wood_ligament_mm": (
                PART_DIAMETER_MM / 2
                - math.dist(PART_CENTER, HOLE_CENTER)
                - HOLE_DIAMETER_MM / 2
            ),
            "minimum_blank_edge_ligament_mm": (
                STOCK_SIZE_MM - (HOLE_CENTER[1] + HOLE_DIAMETER_MM / 2)
            ),
            "cut_sweep_clear_of_hanger_keepout": not swept.intersects(hole_keepout),
        },
        "exact_sweep_within_candidate_110mm_stock": stock_region.covers(swept),
        "part": {
            "diameter_mm": PART_DIAMETER_MM,
            "center_stock_xy_mm": list(PART_CENTER),
            "source_artwork_diameter_mm": ART_DIAMETER_MM,
            "artwork_circular_margin_mm": (PART_DIAMETER_MM - ART_DIAMETER_MM) / 2,
            "within_100_mm_stock_example": False,
            "stock_geometry_note": (
                "The example setup records a 100 x 100 mm blank, which is not large "
                "enough for a 100 mm finished disc plus outside-cutter clearance. "
                "This review bundle uses a distinct, explicitly unverified 110 x 110 mm "
                "blank; do not treat it as the recorded setup."
            ),
        },
    }


def build_profile_program():
    model = StepPlanarModel(
        path=SOURCE,
        loops=(
            circular_loop(PART_CENTER, PART_DIAMETER_MM / 2),
            circular_loop(HOLE_CENTER, HOLE_DIAMETER_MM / 2),
        ),
        top_z=STOCK_THICKNESS_MM,
        thickness=STOCK_THICKNESS_MM,
        source_bounds=(0, 0, STOCK_SIZE_MM, STOCK_SIZE_MM, 0, STOCK_THICKNESS_MM),
        loop_parents=(),
    )
    job = generate_step_gcode(
        model,
        mode="Profile cutout",
        stock_width=STOCK_SIZE_MM,
        stock_height=STOCK_SIZE_MM,
        zero_location="Lower-left",
        tool_diameter=ENDMILL_DIAMETER_MM,
        max_stepdown=0.8,
        safe_z=SAFE_Z_MM,
        cut_feed=PROFILE_FEED_MM_MIN,
        plunge_feed=PROFILE_PLUNGE_MM_MIN,
        spindle_rpm=None,
        stock_thickness=STOCK_THICKNESS_MM,
        breakthrough=PROFILE_BREAKTHROUGH_MM,
        tab_count=TAB_COUNT,
        tab_width=TAB_WIDTH_MM,
        tab_height=TAB_HEIGHT_MM,
    )
    parsed = parse_gcode(job.gcode)
    validate_nonnegative_work_xy(parsed)
    validate_rapid_xy_clearance(parsed, SAFE_Z_MM)
    if not job.profile_simulation or not job.profile_simulation.passed:
        raise ValueError("STEP profile simulation did not verify the cutout")
    if len(job.strokes) != 2:
        raise ValueError("Expected exactly one compensated hole path and one outer path")
    if [operation.operation_id for operation in job.operations] != [
        "internal-through",
        "outer-profile",
    ]:
        raise ValueError("Profile operation plan must cut the hole before the outside contour")
    if "depends on internal-through" not in job.gcode:
        raise ValueError("Outer profile is not explicitly dependent on the hole")
    tab_floor_moves = sum(
        line.startswith(f"G1 Z{-(STOCK_THICKNESS_MM - TAB_HEIGHT_MM):g} ")
        for line in job.gcode.splitlines()
    )
    if tab_floor_moves != TAB_COUNT * 2:
        raise ValueError(
            "The exact profile output does not contain four outer tabs in each of the "
            "two deepest passes"
        )

    radius = ENDMILL_DIAMETER_MM / 2
    exact_sweep = path_sweep(parsed, lambda _depth: radius)
    stock = box(0, 0, STOCK_SIZE_MM, STOCK_SIZE_MM)
    if not stock.covers(exact_sweep):
        raise ValueError("Exact emitted endmill sweep leaves the candidate stock bounds")
    hole_centerline_radius = HOLE_DIAMETER_MM / 2 - radius
    outside_centerline_radius = PART_DIAMETER_MM / 2 + radius
    contour_gauges = []
    for label, stroke, center, expected_radius in (
        ("hanger-hole", job.strokes[0], HOLE_CENTER, hole_centerline_radius),
        ("outside-profile", job.strokes[1], PART_CENTER, outside_centerline_radius),
    ):
        radii = [math.dist(point, center) for point in stroke]
        mean_radius = sum(radii) / len(radii)
        if max(abs(value - expected_radius) for value in radii) > 0.02:
            raise ValueError(f"{label} compensated path is not on its intended radius")
        contour_gauges.append({
            "id": label,
            "center_stock_xy_mm": list(center),
            "expected_centerline_radius_mm": expected_radius,
            "emitted_centerline_radius_min_mm": min(radii),
            "emitted_centerline_radius_max_mm": max(radii),
            "emitted_centerline_radius_mean_mm": mean_radius,
        })
    expected_xy_frame = {
        "stock_dimensions_mm": [STOCK_SIZE_MM, STOCK_SIZE_MM],
        "origin": "lower-left stock corner (candidate frame; fixture not verified)",
        "work_coordinate_system": "G54 P1 (named setup slot; physical zero not verified)",
        "part_center_mm": list(PART_CENTER),
        "hole_center_mm": list(HOLE_CENTER),
    }
    stats = {
        "tool_id": "endmill-3p175",
        "tool_diameter_mm": ENDMILL_DIAMETER_MM,
        "operation_depth_mm": abs(job.depth),
        "stock_dimensions_mm": [STOCK_SIZE_MM, STOCK_SIZE_MM],
        "stock_thickness_mm": STOCK_THICKNESS_MM,
        "breakthrough_mm": PROFILE_BREAKTHROUGH_MM,
        "safe_z_mm": SAFE_Z_MM,
        "cut_feed_mm_min": PROFILE_FEED_MM_MIN,
        "plunge_feed_mm_min": PROFILE_PLUNGE_MM_MIN,
        "spindle_rpm": None,
        "bounds_mm": {
            "min": [parsed.bounds.minimum.x, parsed.bounds.minimum.y, parsed.bounds.minimum.z],
            "max": [parsed.bounds.maximum.x, parsed.bounds.maximum.y, parsed.bounds.maximum.z],
        },
        "exact_tool_sweep_bounds_xy_mm": list(exact_sweep.bounds),
        "exact_sweep_within_candidate_110mm_stock": True,
        "inner_cut_count": sum(
            operation.operation_id == "internal-through" for operation in job.operations
        ),
        "outer_cut_count": sum(
            operation.operation_id == "outer-profile" for operation in job.operations
        ),
        "compensated_contours": contour_gauges,
        "simulation": {
            "passed": job.profile_simulation.passed,
            "swept_area_mm2": job.profile_simulation.swept_area,
            "retained_gouge_area_mm2": job.profile_simulation.gouged_area,
            "allowed_gouge_area_mm2": job.profile_simulation.allowed_gouged_area,
            "checked_paths": job.profile_simulation.checked_paths,
            "cutting_segments": job.profile_simulation.cutting_segments,
            "depth_passes": job.profile_simulation.passes,
        },
        "tabs": {
            "count": TAB_COUNT,
            "width_mm": TAB_WIDTH_MM,
            "height_mm": TAB_HEIGHT_MM,
            "only_outer_profile": True,
            "tab_floor_z_mm": -(STOCK_THICKNESS_MM - TAB_HEIGHT_MM),
            "tab_floor_transition_count_in_exact_nc": tab_floor_moves,
            "tabbed_deep_passes": 2,
        },
        "operation_order": [operation.operation_id for operation in job.operations],
        "xy_frame": expected_xy_frame,
        "runtime": {
            "nominal_estimated_minutes": job.estimated_minutes,
            "cutting_distance_mm": job.cutting_distance,
            "rapid_xy_distance_mm": job.rapid_xy_distance,
            "retract_count": job.retract_count,
            "assumption": "Feed-based projection only; excludes acceleration, junction slowing, material response and physical setup.",
        },
    }
    return job, stats, exact_sweep


def main() -> None:
    with Image.open(SOURCE) as image:
        image_size = image.size
    engraving_settings = settings(image_size)
    source_region, pixel_size = raster_region(SOURCE, engraving_settings)
    source_keepout = Point(*HOLE_CENTER).buffer(
        HOLE_DIAMETER_MM / 2 + HANGER_ENGRAVE_KEEPOUT_MM,
        quad_segs=256,
    )
    work_region = source_region.difference(source_keepout)
    if work_region.is_empty:
        raise ValueError("Hanger keepout removed all engravable approved artwork")
    engraving_gcode, engraving_metrics, engraving_paths = engraving_for_region(
        work_region,
        engraving_settings,
    )
    profile, profile_report, profile_sweep = build_profile_program()
    artwork_report = analyze_artwork(
        source_region,
        work_region,
        image_size,
        engraving_gcode,
        engraving_settings,
    )

    engraving_header = (
        "; Project: Hawkeye 100 mm ornament, retained approved artwork\n"
        "; Operation: shallow filled engraving; fixed-depth V-bit raster\n"
        "; Tool identity: vbit-30deg-0p1 from plywood-vbit-engraving setup\n"
        "; XY: candidate 110 x 110 mm stock, lower-left origin; part center X55 Y55\n"
        "; Artwork: 90 mm mapped source raster; exact source hash in review-report.json\n"
        "; Depth: 0.25 mm provisional; angle 30 deg and tip 0.1 mm per setup record\n"
        "; Feeds and safe Z are illustrative, unverified values; spindle start omitted\n"
        "; REVIEW ONLY: recorded setup stock is 100 x 100 mm; candidate frame is not that setup\n"
    )
    engraving_gcode = engraving_header + engraving_gcode
    profile_header = (
        "; Project: Hawkeye 100 mm ornament, retained approved artwork\n"
        "; Operation: one 4 mm hanger through-hole, then tabbed 100 mm outside profile\n"
        "; Tool identity: endmill-3p175 from plywood-endmill-profile setup\n"
        "; XY: candidate 110 x 110 mm stock, G54 P1 lower-left origin; same frame as engraving file\n"
        "; Through depth: 3.25 mm stock + 0.2 mm provisional breakthrough\n"
        "; Feeds and safe Z are illustrative, unverified values; spindle start omitted\n"
        "; REVIEW ONLY: endmill flute length, fixture clearance and 110 mm stock are unknown\n"
        "G54\n"
    )
    profile_gcode = profile_header + profile.gcode
    profile_preview_svg = profile_preview(profile_gcode, profile_sweep)

    final_width = engraving_settings.effective_diameter
    preview_lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{STOCK_SIZE_MM:g}mm" '
        f'height="{STOCK_SIZE_MM:g}mm" viewBox="0 0 {STOCK_SIZE_MM:g} {STOCK_SIZE_MM:g}">',
        "<title>Exact emitted V-bit engraving paths; offline review only</title>",
        '<rect width="110" height="110" fill="#faf8f2"/>',
        '<g transform="translate(0 110) scale(1 -1)" fill="none" stroke="#176b91" '
        f'stroke-width="{final_width:.6f}" stroke-linecap="round" stroke-linejoin="round">',
    ]
    preview_lines.extend(
        '<polyline points="' + " ".join(f"{x:.4f},{y:.4f}" for x, y in path) + '"/>'
        for path in engraving_paths
    )
    preview_lines.extend((
        "</g>",
        f'<circle cx="{PART_CENTER[0]}" cy="{PART_CENTER[1]}" r="{PART_DIAMETER_MM / 2:g}" '
        'fill="none" stroke="#b22" stroke-width="0.08"/>',
        f'<circle cx="{HOLE_CENTER[0]}" cy="{STOCK_SIZE_MM - HOLE_CENTER[1]}" '
        f'r="{HOLE_DIAMETER_MM / 2 + HANGER_ENGRAVE_KEEPOUT_MM:g}" '
        'fill="#ddd" fill-opacity="0.7" stroke="#a22" stroke-dasharray="0.4 0.25" stroke-width="0.08"/>',
        "</svg>",
        "",
    ))
    preview = "\n".join(preview_lines)
    for name, value in (
        ("approved-artwork-geometry.svg", vector_svg(source_region, STOCK_SIZE_MM)),
        ("engraving-review.nc", engraving_gcode),
        ("disc-hole-profile-review.nc", profile_gcode),
        ("engraving-preview.svg", preview),
        ("profile-preview.svg", profile_preview_svg),
    ):
        (OUT / name).write_text(value, encoding="utf-8")

    profile_program = parse_gcode(profile_gcode)
    validate_nonnegative_work_xy(profile_program)
    validate_rapid_xy_clearance(profile_program, SAFE_Z_MM)
    engraving_program = parse_gcode(engraving_gcode)
    validate_nonnegative_work_xy(engraving_program)
    validate_rapid_xy_clearance(engraving_program, SAFE_Z_MM)

    input_hashes = {
        "approved_artwork_reference_png": sha256_file(SOURCE),
        "vbit_setup_json": sha256_file(VBIT_SETUP),
        "endmill_setup_json": sha256_file(ENDMILL_SETUP),
        "vectorized_artwork_svg": sha256_file(OUT / "approved-artwork-geometry.svg"),
    }
    output_hashes = {
        name: sha256_file(OUT / name)
        for name in (
            "engraving-review.nc",
            "disc-hole-profile-review.nc",
            "engraving-preview.svg",
            "profile-preview.svg",
        )
    }
    provisional = {
        "candidate_stock_dimensions_mm": [STOCK_SIZE_MM, STOCK_SIZE_MM],
        "engraving_depth_mm": ENGRAVING_DEPTH_MM,
        "engraving_stepover_mm": ENGRAVING_STEPOVER_MM,
        "engraving_max_stepdown_mm": ENGRAVING_MAX_STEPDOWN_MM,
        "safe_z_mm": SAFE_Z_MM,
        "vbit_cut_feed_mm_min": VBIT_FEED_MM_MIN,
        "vbit_plunge_feed_mm_min": VBIT_PLUNGE_MM_MIN,
        "endmill_cut_feed_mm_min": PROFILE_FEED_MM_MIN,
        "endmill_plunge_feed_mm_min": PROFILE_PLUNGE_MM_MIN,
        "profile_breakthrough_mm": PROFILE_BREAKTHROUGH_MM,
        "tab_count": TAB_COUNT,
        "tab_width_mm": TAB_WIDTH_MM,
        "tab_height_mm": TAB_HEIGHT_MM,
    }
    blocked = [
        "The named setup records 100 x 100 mm stock; the candidate 100 mm disc needs a distinct 110 x 110 mm blank to retain cutter clearance.",
        "The actual fixture/clamp layout and safe Z clearance are unknown.",
        "The endmill flute length, usable cutting length, and holder clearance are unknown.",
        "Feeds, plunge feeds, spindle speed, actual material response, breakthrough, tab retention and plywood flatness are unverified.",
        "The setup provenance describes measured/reported inputs but does not independently verify them in this run.",
        "The retained artwork is a thresholded raster conversion; the report quantifies sweep-inaccessible black detail and makes no aesthetic approval claim.",
    ]
    project = {
        "schema_version": 1,
        "project_id": "hawkeye-approved-100mm-ornament",
        "status": "offline_review_only_not_released",
        "artwork": {
            "source_path": "artifacts/ornaments/hawkeye/approved-artwork-reference.png",
            "sha256": input_hashes["approved_artwork_reference_png"],
            "retained_source": True,
            "threshold": THRESHOLD,
            "source_pixel_dimensions": list(image_size),
            "mapped_artwork_diameter_mm": ART_DIAMETER_MM,
            "vector_geometry": "approved-artwork-geometry.svg",
            "units": "mm",
            "stock_xy_transform": {
                "crop": [0, 0, image_size[0], image_size[1]],
                "physical_scale_mm_per_pixel": pixel_size,
                "image_y_axis": "flipped into Cartesian stock coordinates",
                "translation_mm": [10.0, 10.0],
            },
        },
        "part_geometry": {
            "shape": "disc",
            "diameter_mm": PART_DIAMETER_MM,
            "center_stock_xy_mm": list(PART_CENTER),
            "hanger_hole_center_stock_xy_mm": list(HOLE_CENTER),
            "hanger_hole_diameter_mm": HOLE_DIAMETER_MM,
        },
        "stock": {
            "shape": "square",
            "dimensions_mm": [STOCK_SIZE_MM, STOCK_SIZE_MM],
            "recorded_setup_dimensions_mm": {
                "width": 100.0,
                "height": 100.0,
                "thickness": STOCK_THICKNESS_MM,
                "provenance": "Named setup records: width/height measured with calipers; thickness measured with digital calipers; not re-measured here.",
            },
            "material": "birch plywood (user-reported package label)",
            "thickness_mm": STOCK_THICKNESS_MM,
            "thickness_provenance": "measured in named setup record; not re-measured here",
            "candidate_dimensions_provenance": "unverified candidate; differs from named 100 x 100 mm setups",
        },
        "units": "mm",
        "origin": "lower-left candidate stock corner; XY frame shared by both programs",
        "work_coordinate_system": "G54 P1; named setup slot, physical zero not verified",
        "fixture_provenance": {
            "xy_datum": "Lower-left stock corner, user-reported fixture fence reference",
            "z_datum": "Planed stock top surface, user-reported setup reference",
            "wcs_slot": 1,
            "machine_x_mm": None,
            "machine_y_mm": None,
            "actual_fixture_and_clamp_clearance": "unknown",
        },
        "process_provenance": {
            "safe_z_mm": "unknown in named setup; 3.0 mm used only as provisional review value",
            "cut_feed_mm_min": "unknown in named setup; listed candidate feeds are illustrative",
            "plunge_feed_mm_min": "unknown in named setup; listed candidate feeds are illustrative",
            "spindle_rpm": "unknown in named setup; no spindle-start command emitted",
        },
        "setup_inputs": {
            "engraving": {
                "setup_id": "plywood-vbit-engraving",
                "source_path": "examples/hardware-setups/plywood-vbit-engraving.json",
                "sha256": input_hashes["vbit_setup_json"],
            },
            "profile": {
                "setup_id": "plywood-endmill-profile",
                "source_path": "examples/hardware-setups/plywood-endmill-profile.json",
                "sha256": input_hashes["endmill_setup_json"],
            },
        },
        "tools": [
            {
                "id": "vbit-30deg-0p1",
                "kind": "v-bit",
                "included_angle_deg": VBIT_ANGLE_DEG,
                "tip_diameter_mm": VBIT_TIP_MM,
                "setup_provenance": "30 degree user-reported packaging angle; 0.1 mm measured per tool specification in setup record",
                "effective_diameter_at_depth_mm": {
                    "depth_mm": ENGRAVING_DEPTH_MM,
                    "diameter_mm": engraving_settings.effective_diameter,
                },
                "release_state": "not independently verified",
            },
            {
                "id": "endmill-3p175",
                "kind": "flat-endmill",
                "diameter_mm": ENDMILL_DIAMETER_MM,
                "diameter_provenance": "measured in named setup record; not re-measured here",
                "flute_length_mm": None,
                "release_state": "blocked until flute/usable cutting length and holder clearance are measured",
            },
        ],
        "operations": [
            {
                "id": "engrave-approved-artwork",
                "tool_id": "vbit-30deg-0p1",
                "file": "engraving-review.nc",
                "depth_mm": ENGRAVING_DEPTH_MM,
                "strategy": "fixed-depth raster clearing from thresholded black source pixels",
                "status": "review only",
            },
            {
                "id": "hanger-hole-through",
                "tool_id": "endmill-3p175",
                "file": "disc-hole-profile-review.nc",
                "depth_mm": STOCK_THICKNESS_MM + PROFILE_BREAKTHROUGH_MM,
                "depends_on": [],
                "status": "review only; emitted before outer profile",
            },
            {
                "id": "tabbed-outside-through",
                "tool_id": "endmill-3p175",
                "file": "disc-hole-profile-review.nc",
                "depth_mm": STOCK_THICKNESS_MM + PROFILE_BREAKTHROUGH_MM,
                "depends_on": ["hanger-hole-through"],
                "status": "review only; four outer tabs",
            },
        ],
        "rebuild": {
            "command": ".venv\\Scripts\\python.exe artifacts\\ornaments\\hawkeye\\two-bit\\c018-reproducible-project\\prepare.py",
            "requirements": "repository .venv and source checkout; no backend, GUI, or hardware",
            "compatibility": "Uses existing ornament_cam raster clearing, gcode parser/validators, step_engraver profile compensation and tab simulation.",
        },
        "inputs_sha256": input_hashes,
        "outputs_sha256": output_hashes,
        "provisional_settings": provisional,
        "production_release_blockers": blocked,
    }
    report = {
        "schema_version": 1,
        "status": "review_only_candidate_not_production_released",
        "project_id": project["project_id"],
        "inputs_sha256": input_hashes,
        "outputs_sha256": output_hashes,
        "engraving": {
            "operation_id": "engrave-approved-artwork",
            "tool_id": "vbit-30deg-0p1",
            "target_depth_mm": ENGRAVING_DEPTH_MM,
            "stock_dimensions_mm": [STOCK_SIZE_MM, STOCK_SIZE_MM],
            "stock_thickness_mm": STOCK_THICKNESS_MM,
            "stock_xy_origin": "lower-left; candidate 110 x 110 mm frame",
            "motion_metrics": engraving_metrics,
            "runtime_assumption": (
                "Feed-based projection only; assumes 3000 mm/min rapid and excludes acceleration, "
                "junction slowing, material response and physical setup."
            ),
            "placement_and_features": artwork_report,
            "exact_emitted_bounds_mm": {
                "min": [
                    engraving_program.bounds.minimum.x,
                    engraving_program.bounds.minimum.y,
                    engraving_program.bounds.minimum.z,
                ],
                "max": [
                    engraving_program.bounds.maximum.x,
                    engraving_program.bounds.maximum.y,
                    engraving_program.bounds.maximum.z,
                ],
            },
            "checks": {
                "parse": True,
                "nonnegative_work_xy": True,
                "rapid_xy_at_safe_z": True,
                "exact_vbit_sweep_inside_art": True,
                "exact_vbit_sweep_outside_hanger_keepout": True,
            },
        },
        "profile": profile_report,
        "tools": [
            {
                "id": "vbit-30deg-0p1",
                "setup_id": "plywood-vbit-engraving",
                "angle_deg": VBIT_ANGLE_DEG,
                "tip_diameter_mm": VBIT_TIP_MM,
            },
            {
                "id": "endmill-3p175",
                "setup_id": "plywood-endmill-profile",
                "diameter_mm": ENDMILL_DIAMETER_MM,
                "flute_length_mm": None,
            },
        ],
        "operations": project["operations"],
        "shared_xy_frame": project["origin"],
        "provisional_settings": provisional,
        "production_release_blockers": blocked,
    }
    (OUT / "ornament-project.json").write_text(
        json.dumps(project, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (OUT / "review-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({
        "status": report["status"],
        "program_hashes": output_hashes,
        "blocked_release_reasons": blocked,
        "artwork": artwork_report,
        "profile": profile_report,
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
