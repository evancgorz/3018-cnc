"""Rebuild the offline one-bit Hawkeye ornament review bundle.

This script uses the repository's existing STEP pocket/profile engine.  It only
creates local vector/G-code review artifacts; it never connects to a machine.
Run from any directory with the repository virtual environment's Python:

    python artifacts/ornaments/hawkeye/single-bit/prepare.py
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
import sys
from typing import Iterable

from shapely.affinity import translate
from shapely.geometry import GeometryCollection, LineString, MultiPolygon, Point, Polygon, box
from shapely.ops import unary_union


REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT / "src"))

from ttc3018_control.gcode import parse_gcode, validate_nonnegative_work_xy, validate_rapid_xy_clearance  # noqa: E402
from ttc3018_control.step_engraver import generate_step_gcode  # noqa: E402
from ttc3018_control.step_geometry import PlanarLoop, Point2D, StepPlanarModel  # noqa: E402


OUT_DIR = Path(__file__).resolve().parent
REF_ART = REPO_ROOT / "artifacts" / "ornaments" / "hawkeye" / "approved-artwork-reference.png"
CONCEPT = Path(
    "C:/Users/Evan Gorczynski/.codex/generated_images/01a1973e-59f6-7913-babe-932570c6d115/"
    "exec-f73bdb31-af8a-4175-89fc-8faf34ffc33b.png"
)

STOCK = 110.0
PART_DIAMETER = 100.0
PART_CENTER_LOCAL = (50.0, 50.0)
PLACEMENT = (5.0, 5.0)
PART_CENTER_WORK = (55.0, 55.0)
TOOL_DIAMETER = 3.175  # Assumed only; actual SPMS200 cutting diameter is unverified.
TOOL_RADIUS = TOOL_DIAMETER / 2
STOCK_THICKNESS = 3.0  # Nominal only; sheet thickness and flatness are unmeasured.
BREAKTHROUGH = 0.15
POCKET_DEPTH = 0.4
SAFE_Z = 3.0
CUT_FEED = 300.0
PLUNGE_FEED = 80.0
TAB_COUNT = 4
TAB_WIDTH = 4.0
TAB_HEIGHT = 0.8
PROFILE_MAX_STEPDOWN = 0.5
STROKE_WIDTH = 3.5
STROKE_RADIUS = STROKE_WIDTH / 2
FONT_HEIGHT = 6.5


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def closed_circle(center: tuple[float, float], radius: float, count: int = 144) -> tuple[tuple[float, float], ...]:
    return tuple(
        (center[0] + radius * math.cos(math.tau * index / count),
         center[1] + radius * math.sin(math.tau * index / count))
        for index in range(count)
    )


def stroke(points: Iterable[tuple[float, float]], width: float = STROKE_WIDTH):
    coordinates = tuple(points)
    if len(coordinates) < 2:
        raise ValueError("A vector stroke needs at least two points")
    return LineString(coordinates).buffer(width / 2, cap_style=1, join_style=1, quad_segs=8)


def polygon(points: Iterable[tuple[float, float]]) -> Polygon:
    result = Polygon(tuple(points))
    if not result.is_valid or result.area <= 0:
        raise ValueError("Artwork contains an invalid or empty polygon")
    return result


# The letters are deliberately drawn as centerline paths then expanded to a
# 3.5 mm vector channel.  Counters in D/O/A/0 are widened to roughly the cutter
# diameter where geometry allows; the exact resulting openings are measured in
# the report, not assumed from this font definition.
def glyph(char: str) -> tuple[float, tuple[tuple[tuple[float, float], ...], ...]]:
    w_by_char = {
        "A": 10.5, "D": 7.0, "O": 7.0, "R": 7.0, "0": 7.0,
        "M": 3.6, "W": 3.2, "V": 2.6, "I": 2.0, "1": 2.0,
        "K": 2.8, "Y": 2.5, "E": 2.4, "S": 2.5, "T": 2.5,
        "2": 2.4, "-": 3.4,
    }
    width = w_by_char.get(char)
    if width is None:
        raise ValueError(f"Unsupported character in vector font: {char!r}")
    h = FONT_HEIGHT
    lines: list[tuple[tuple[float, float], ...]]

    def x(value: float) -> float:
        return width * value / 4.2

    mid = h / 2
    top = h
    if char in {"D", "O", "0"}:
        # Rounded by the cutter sweep; the intentionally wide path spacing
        # leaves a measurable negative counter after the 3.175 mm sweep.
        lines = [((x(0), 0), (x(0), top), (x(4.2), top), (x(4.2), 0), (x(0), 0))]
    elif char == "R":
        lines = [
            ((x(0), 0), (x(0), top), (x(4.2), top), (x(4.2), mid + 0.25), (x(0.55), mid + 0.25)),
            ((x(2.15), mid + 0.25), (x(4.2), 0)),
        ]
    elif char == "A":
        # Split-apex stencil A: the 3.8 mm opening is intentional and prevents
        # the assumed cutter from closing a triangular counter at the tip.
        apex_gap = 3.8
        left_apex = width / 2 - apex_gap / 2
        right_apex = width / 2 + apex_gap / 2
        bar_y = 2.4
        left_bar_x = width * bar_y / h
        right_bar_x = width - left_bar_x
        lines = [
            ((0, 0), (left_apex, top)),
            ((right_apex, top), (width, 0)),
            ((left_bar_x, bar_y), (right_bar_x, bar_y)),
        ]
    elif char == "M":
        lines = [((0, 0), (0, top), (width / 2, mid), (width, top), (width, 0))]
    elif char == "V":
        lines = [((0, top), (width / 2, 0), (width, top))]
    elif char == "W":
        lines = [((0, top), (width * 0.22, 0), (width / 2, mid), (width * 0.78, 0), (width, top))]
    elif char == "I":
        lines = [((width / 2, 0), (width / 2, top))]
    elif char == "1":
        # Open single-stroke one avoids a tiny serif pocket the assumed cutter
        # cannot clear while remaining legible in the narrow lettering band.
        lines = [((width * 0.2, top * 0.78), (width / 2, top), (width / 2, 0))]
    elif char == "K":
        lines = [((0, 0), (0, top)), ((width, top), (0, mid), (width, 0))]
    elif char == "Y":
        lines = [((0, top), (width / 2, mid), (width, top)), ((width / 2, mid), (width / 2, 0))]
    elif char == "E":
        lines = [((0, 0), (0, top), (width, top)), ((0, mid), (width * 0.82, mid)), ((0, 0), (width, 0))]
    elif char == "S":
        lines = [((width, top), (0, top), (0, mid), (width, mid), (width, 0), (0, 0))]
    elif char == "T":
        lines = [((0, top), (width, top)), ((width / 2, top), (width / 2, 0))]
    elif char == "2":
        lines = [((0, top), (width, top), (width, mid), (0, 0), (width, 0))]
    else:  # hyphen
        lines = [((0, mid), (width, mid))]
    return width, tuple(lines)


def text_on_arc(
    text: str,
    radius: float,
    *,
    top: bool,
    center=(50.0, 50.0),
    gap=0.8,
    word_space=4.0,
    center_offset=0.0,
):
    glyph_widths = [glyph(char)[0] + STROKE_WIDTH for char in text if char != " "]
    spaces = text.count(" ")
    word_letter_pairs = sum(
        1 for left, right in zip(text, text[1:]) if left != " " and right != " "
    )
    total = sum(glyph_widths) + gap * word_letter_pairs + word_space * spaces
    cursor = -total / 2 + center_offset
    geometries = []
    glyph_shapes = []
    for index, char in enumerate(text):
        if char == " ":
            cursor += word_space
            continue
        char_width, paths = glyph(char)
        physical_width = char_width + STROKE_WIDTH
        center_s = cursor + physical_width / 2
        theta = (math.pi / 2 - center_s / radius) if top else (3 * math.pi / 2 + center_s / radius)
        base = (center[0] + radius * math.cos(theta), center[1] + radius * math.sin(theta))
        if top:
            tangent = (math.sin(theta), -math.cos(theta))
            normal = (math.cos(theta), math.sin(theta))
        else:
            tangent = (-math.sin(theta), math.cos(theta))
            normal = (-math.cos(theta), -math.sin(theta))
        char_parts = []
        for path in paths:
            mapped = [
                (base[0] + (px - char_width / 2) * tangent[0] + (py - FONT_HEIGHT / 2) * normal[0],
                 base[1] + (px - char_width / 2) * tangent[1] + (py - FONT_HEIGHT / 2) * normal[1])
                for px, py in path
            ]
            char_parts.append(stroke(mapped))
        glyph_shape = unary_union(char_parts)
        geometries.append(glyph_shape)
        glyph_shapes.append(glyph_shape)
        cursor += physical_width
        if index + 1 < len(text) and text[index + 1] != " ":
            cursor += gap
    adjacent_gaps = [first.distance(second) for first, second in zip(glyph_shapes, glyph_shapes[1:])]
    return unary_union(geometries), float(total), min(adjacent_gaps, default=math.inf)


def rounded_box(x0: float, y0: float, x1: float, y1: float, radius: float):
    return box(x0 + radius, y0, x1 - radius, y1).union(
        box(x0, y0 + radius, x1, y1 - radius)
    ).union(
        unary_union([
            Point(x0 + radius, y0 + radius).buffer(radius, quad_segs=12),
            Point(x1 - radius, y0 + radius).buffer(radius, quad_segs=12),
            Point(x1 - radius, y1 - radius).buffer(radius, quad_segs=12),
            Point(x0 + radius, y1 - radius).buffer(radius, quad_segs=12),
        ])
    ).buffer(0)


def make_artwork():
    # Separate the two title words so their white gap sits at 12 o'clock under
    # the reserved hanger. All letter bands remain outside R34 and inside R44.
    dome, dome_length, dome_gap = text_on_arc("DOME", 39.0, top=True, gap=2.2)
    riders, riders_length, riders_gap = text_on_arc("RIDERS", 39.0, top=True, gap=2.2)
    upper_word_gap = 8.0
    dome_offset = -(dome_length / 2 + upper_word_gap / 2)
    riders_offset = riders_length / 2 + upper_word_gap / 2
    dome, dome_length, dome_gap = text_on_arc("DOME", 39.0, top=True, gap=2.2, center_offset=dome_offset)
    riders, riders_length, riders_gap = text_on_arc("RIDERS", 39.0, top=True, gap=2.2, center_offset=riders_offset)
    title = unary_union((dome, riders))
    title_arc_length = dome_length + riders_length + upper_word_gap
    bottom, bottom_arc_length, bottom_gap = text_on_arc(
        "VAW-120 KEY WEST", 39.1, top=False, gap=1.7, word_space=2.8
    )

    # E-2 side silhouette, kept broad and recognizable: pointed nose, tapered
    # fuselage, swept high wing, oval radar dome on a continuous stalk, paired
    # engine bulges and twin broad tail fins.
    fuselage = polygon([
        (24.5, 48.0), (28.0, 45.5), (59.0, 45.5), (67.0, 46.1),
        (73.0, 47.8), (67.5, 49.6), (31.0, 51.0), (27.0, 50.0),
    ])
    high_wing = polygon([
        (35.0, 46.7), (24.0, 51.0), (24.0, 54.0), (39.0, 50.1),
        (61.0, 50.1), (76.0, 54.0), (76.0, 51.0), (64.0, 46.5),
    ])
    tailplane = polygon([(63.0, 46.5), (73.0, 47.0), (77.0, 49.0), (68.0, 49.6)])
    tail_fins = unary_union((
        polygon([(65.8, 48.8), (69.8, 48.9), (69.6, 55.0), (67.0, 55.2)]),
        polygon([(70.4, 48.8), (74.4, 49.0), (74.4, 54.2), (71.0, 54.8)]),
    ))
    body_region = unary_union((fuselage, high_wing, tailplane, tail_fins))
    nacelles = unary_union((
        rounded_box(34.2, 46.4, 42.0, 50.0, 1.8),
        rounded_box(58.0, 46.4, 65.8, 50.0, 1.8),
    ))
    propeller_discs = unary_union(tuple(
        Polygon([
            (center_x + 2.0 * math.cos(2 * math.pi * index / 64),
             48.2 + 4.5 * math.sin(2 * math.pi * index / 64))
            for index in range(64)
        ])
        for center_x in (34.2, 65.8)
    ))
    # Keep nacelles joined to the fuselage/wing so the coarse, one-tool pocket
    # reads as a continuous E-2 silhouette instead of detached bars. Broad
    # propeller disks attach at the forward ends; no fine blades are implied.
    aircraft = unary_union((body_region, nacelles, propeller_discs))
    radar_dome = Polygon([
        (39.0, 56.0), (39.8, 54.7), (42.0, 53.8), (58.0, 53.8),
        (60.2, 54.7), (61.0, 56.0), (60.2, 57.3), (58.0, 58.2),
        (42.0, 58.2), (39.8, 57.3),
    ])
    radar_stalk = polygon([(48.2, 49.0), (51.8, 49.0), (51.8, 54.2), (48.2, 54.2)])
    aircraft = unary_union((aircraft, radar_dome, radar_stalk))

    # The sunburst has clear, separated rays in R16..R25; it cannot touch the
    # lettering band or the radar dome/aircraft silhouette.
    rays = []
    for angle_deg in (35, 52, 69, 86, 103, 120, 137, 145):
        angle = math.radians(angle_deg)
        start_r, end_r = 16.0, 22.0
        rays.append(stroke((
            (50 + start_r * math.cos(angle), 50 + start_r * math.sin(angle)),
            (50 + end_r * math.cos(angle), 50 + end_r * math.sin(angle)),
        )))
    sun = unary_union(rays)

    # Compact palm and sailboat remain separate from the plane, rays and both
    # letter bands. The palm fronds are broad curves, not thin trace lines.
    palm = unary_union((
        stroke([(29.0, 35.0), (29.0, 41.0)]),
        stroke([(29.0, 41.0), (25.0, 42.4)]),
        stroke([(29.0, 41.0), (25.5, 43.0)]),
        stroke([(29.0, 41.0), (27.0, 43.4)]),
        stroke([(29.0, 41.0), (30.0, 43.4)]),
        stroke([(29.0, 41.0), (32.5, 42.8)]),
        stroke([(29.0, 41.0), (33.0, 41.8)]),
    ))
    boat = unary_union((
        polygon([(74.0, 41.0), (74.0, 47.0), (78.0, 42.0)]),
        polygon([(75.0, 41.0), (75.0, 45.5), (72.0, 41.5)]),
        polygon([(71.0, 40.1), (80.0, 40.1), (78.2, 38.6), (73.0, 38.6)]),
    ))
    water = unary_union((
        stroke([(34.0, 39.0), (41.0, 39.4), (48.0, 39.0), (55.0, 39.5), (63.0, 39.1), (68.0, 39.3)]),
        stroke([(39.0, 35.0), (46.0, 35.3), (53.0, 35.0), (61.0, 35.4)]),
        stroke([(45.0, 31.8), (50.0, 32.0), (55.0, 31.8)]),
    ))

    motifs = unary_union((aircraft, sun, palm, boat, water)).buffer(0)
    pieces = (title, bottom, motifs)
    art = unary_union(pieces).buffer(0)
    if art.is_empty or not art.is_valid:
        raise ValueError("Generated artwork union is empty or invalid")
    # Full-vector envelope checks keep shallow art away from both the analytical
    # outside edge and the separately reserved hanger hole.
    disc = Point(*PART_CENTER_LOCAL).buffer(PART_DIAMETER / 2, quad_segs=256)
    hole = Point(50.0, 95.0).buffer(2.0, quad_segs=96)
    if art.distance(hole.boundary) < 1.0:
        raise ValueError("Artwork violates the hanger-hole reserve")
    glyph_gap = min(dome_gap, riders_gap, bottom_gap, dome.distance(riders))
    motif_text_gap = motifs.distance(unary_union((title, bottom)))
    radial = lambda geometry: (
        min(Point(*PART_CENTER_LOCAL).distance(part.boundary) for part in polygonal_parts(geometry)),
        max(math.dist(PART_CENTER_LOCAL, point) for part in polygonal_parts(geometry) for point in part.exterior.coords),
    )
    if glyph_gap < 0.8:
        raise ValueError(
            f"Artwork lettering loses the 0.8 mm retained gap ({glyph_gap:.3f} mm; "
            f"DOME {dome_gap:.3f}, RIDERS {riders_gap:.3f}, lower {bottom_gap:.3f}, "
            f"upper word gap {dome.distance(riders):.3f})"
        )
    if motif_text_gap < 1.0:
        raise ValueError(f"Motifs touch the lettering band ({motif_text_gap:.3f} mm gap)")
    motif_radial = radial(motifs)
    letter_radial = radial(unary_union((title, bottom)))
    if motif_radial[1] > 32.0 or letter_radial[0] < 33.5 or letter_radial[1] > 44.5:
        raise ValueError(
            f"Artwork bands violate the motif/letter layout (motifs {motif_radial}, letters {letter_radial})"
        )
    return (art, title, bottom, title_arc_length, bottom_arc_length, disc, hole,
            motifs, aircraft, glyph_gap, motif_text_gap, motif_radial, letter_radial, dome.distance(riders))


def loops_for(geometry) -> tuple[PlanarLoop, ...]:
    polygons = [geometry] if isinstance(geometry, Polygon) else list(geometry.geoms) if isinstance(geometry, MultiPolygon) else []
    loops: list[PlanarLoop] = []
    for item in polygons:
        if not isinstance(item, Polygon) or item.area <= 1e-8:
            continue
        for ring in (item.exterior, *item.interiors):
            points = tuple(Point2D(float(x), float(y)) for x, y in list(ring.coords)[:-1])
            if len(points) >= 3:
                loops.append(PlanarLoop(points))
    if not loops:
        raise ValueError("Generated geometry has no planar loops")
    return tuple(loops)


def planar_model(loops: tuple[PlanarLoop, ...], thickness: float, name: str) -> StepPlanarModel:
    return StepPlanarModel(
        Path(name), loops, 0.0, thickness, (0.0, 0.0, 0.0, 100.0, 100.0, thickness),
        face_plane="XY",
    )


def body_lines(gcode: str) -> list[str]:
    lines = gcode.splitlines()
    try:
        start = lines.index("G94") + 1
    except ValueError as exc:
        raise ValueError("STEP component lacks its expected G94 setup") from exc
    tail = ["G0 Z3", "G0 X0 Y0", "M5", "M2"]
    if lines[-4:] != tail:
        raise ValueError("STEP component has an unexpected program-end sequence")
    body = lines[start:-4]
    if any(line in {"M2", "M30"} for line in body):
        raise ValueError("Intermediate operation body contains a program-end marker")
    return body


def split_in_material_z_descents(gcode: str, maximum_stepdown: float) -> tuple[str, int]:
    """Split feed descents inside the stock into bounded Z increments.

    The STEP profile helper holds tabs at their configured floor. When its
    final pass leaves a tab, that feed descent can exceed the pass stepdown;
    this output-only adjustment inserts intermediate Z moves at the same XY.
    Approach plunges from nonnegative safe height are left intact.
    """
    if not math.isfinite(maximum_stepdown) or maximum_stepdown <= 0:
        raise ValueError("Maximum in-stock Z stepdown must be positive")
    output: list[str] = []
    current_z = 0.0
    modal_motion = 0
    modal_feed = PLUNGE_FEED
    inserted = 0
    for raw in gcode.splitlines():
        code = raw.split(";", 1)[0].strip()
        if not code:
            output.append(raw)
            continue
        words = {match.group(1).upper(): float(match.group(2)) for match in re.finditer(r"([A-Z])\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))", code, re.IGNORECASE)}
        if "F" in words:
            modal_feed = words["F"]
        if "G" in words and words["G"] in (0.0, 1.0):
            modal_motion = int(words["G"])
        if "Z" in words:
            target_z = words["Z"]
            if (
                modal_motion == 1
                and current_z < -1e-6
                and target_z < current_z - maximum_stepdown - 1e-9
            ):
                while current_z - target_z > maximum_stepdown + 1e-9:
                    current_z = round(current_z - maximum_stepdown, 4)
                    output.append(f"G1 Z{current_z:.4f} F{modal_feed:g}")
                    inserted += 1
            current_z = target_z
        output.append(raw)
    return "\n".join(output) + "\n", inserted


def linework_sweep(lines: Iterable, radius: float):
    geometries = []
    for line in lines:
        if math.dist(line[0], line[1]) > 1e-9:
            geometries.append(LineString(line).buffer(radius, cap_style=1, join_style=1, quad_segs=8))
    return unary_union(geometries) if geometries else GeometryCollection()


def motion_groups(program):
    shallow: list[tuple[tuple[float, float], tuple[float, float]]] = []
    through_hole: list[tuple[tuple[float, float], tuple[float, float]]] = []
    through_outer: list[tuple[tuple[float, float], tuple[float, float]]] = []
    tab_lift: list[tuple[tuple[float, float], tuple[float, float]]] = []
    profile_intermediate: list[tuple[tuple[float, float], tuple[float, float]]] = []
    ordered_profile: list[tuple[float, float, float]] = []
    for segment in program.segments:
        start = (segment.start.x, segment.start.y)
        end = (segment.end.x, segment.end.y)
        if segment.rapid or math.dist(start, end) <= 1e-8:
            continue
        z = (segment.start.z + segment.end.z) / 2
        midpoint_radius = math.dist(((start[0] + end[0]) / 2, (start[1] + end[1]) / 2), PART_CENTER_WORK)
        if math.isclose(z, -POCKET_DEPTH, abs_tol=0.002):
            shallow.append((start, end))
        elif z < -POCKET_DEPTH - 0.02:
            if midpoint_radius < 48:
                through_hole.append((start, end))
                ordered_profile.append((z, midpoint_radius, math.dist(start, end)))
            elif z <= -(STOCK_THICKNESS + BREAKTHROUGH) + 0.002:
                through_outer.append((start, end))
                ordered_profile.append((z, midpoint_radius, math.dist(start, end)))
            elif math.isclose(z, -(STOCK_THICKNESS - TAB_HEIGHT), abs_tol=0.002) and midpoint_radius > 48:
                tab_lift.append((start, end))
                ordered_profile.append((z, midpoint_radius, math.dist(start, end)))
            else:
                profile_intermediate.append((start, end))
                ordered_profile.append((z, midpoint_radius, math.dist(start, end)))
    if not shallow or not through_hole or not through_outer or not tab_lift:
        raise ValueError(
            "Combined G-code is missing a pocket, hole, outer or tab-lift sweep "
            f"(counts {len(shallow)}, {len(through_hole)}, {len(through_outer)}, {len(tab_lift)})"
        )
    first_profile_radius = ordered_profile[0][1]
    last_profile_radius = ordered_profile[-1][1]
    if first_profile_radius >= 48 or last_profile_radius < 48:
        raise ValueError("Combined profile order is not hole first and outside contour last")
    return shallow, through_hole, through_outer, tab_lift, profile_intermediate, ordered_profile


def polygonal_parts(geometry) -> list[Polygon]:
    if isinstance(geometry, Polygon):
        return [geometry]
    if isinstance(geometry, MultiPolygon):
        return list(geometry.geoms)
    return [item for item in getattr(geometry, "geoms", ()) if isinstance(item, Polygon)]


def path_d(geometry, *, y_max: float, offset=(0.0, 0.0)) -> str:
    bits = []
    for item in polygonal_parts(geometry):
        rings = [item.exterior, *item.interiors]
        for ring in rings:
            coords = list(ring.coords)
            if not coords:
                continue
            x0, y0 = coords[0]
            bits.append(f"M{x0 + offset[0]:.4f},{y_max - (y0 + offset[1]):.4f}")
            bits.extend(f"L{x + offset[0]:.4f},{y_max - (y + offset[1]):.4f}" for x, y in coords[1:])
            bits.append("Z")
    return " ".join(bits)


def write_artwork_svg(art, disc, hole) -> None:
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="110mm" height="110mm" viewBox="-5 -5 110 110">
<title>Hawkeye single-bit vector artwork reference</title>
<desc>Black shows the actual 3.5 mm vector pocket regions. This is a simplified line-art interpretation, not a raster conversion of the photographic mockup. The analytic 100 mm disc and 4 mm hanger hole are separate retained-part geometry.</desc>
<rect x="-5" y="-5" width="110" height="110" fill="#fff"/>
<path d="{path_d(disc.boundary.buffer(0.16), y_max=100)}" fill="none" stroke="#17202b" stroke-width="0.45"/>
<path d="{path_d(art, y_max=100)}" fill="#161616" fill-rule="evenodd"/>
<circle cx="50" cy="5" r="2" fill="#fff" stroke="#1b4b6b" stroke-width="0.45"/>
<text x="-3.8" y="-1.5" font-family="sans-serif" font-size="1.5" fill="#34495e">100 mm nominal part • artwork channels are 3.5 mm target width</text>
</svg>'''
    (OUT_DIR / "artwork-reference.svg").write_text(svg, encoding="utf-8")


def write_preview_svg(pocket_sweep, hole_sweep, outer_sweep, tab_sweep) -> None:
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="154mm" height="164mm" viewBox="-17 -8 144 153">
<title>G-code cutter-sweep review preview</title>
<desc>Exact XY line-segment sweeps from the emitted single-tool program. Brown is the shallow 0.4 mm pocket sweep; blue is the 4 mm hanger hole; red is the deep outside profile; amber is the same outside path at the tab-lift Z, retaining nominal 0.8 mm tabs. Stock XY is 110 by 110 mm.</desc>
<rect x="0" y="0" width="110" height="110" fill="#f1ead9" stroke="#3a4652" stroke-width="0.35"/>
<circle cx="55" cy="55" r="50" fill="none" stroke="#405364" stroke-width="0.35" stroke-dasharray="1 0.6"/>
<path d="{path_d(pocket_sweep, y_max=110)}" fill="#814f28" fill-rule="evenodd" opacity="0.80"/>
<path d="{path_d(hole_sweep, y_max=110)}" fill="#226b8e" fill-rule="evenodd" opacity="0.9"/>
<path d="{path_d(outer_sweep, y_max=110)}" fill="#a64235" fill-rule="evenodd" opacity="0.88"/>
<path d="{path_d(tab_sweep, y_max=110)}" fill="#efb43f" fill-rule="evenodd" opacity="0.96"/>
<text x="0" y="119" font-family="sans-serif" font-size="2.4" fill="#814f28">Brown: shallow pocket • Z -0.4</text>
<text x="0" y="123" font-family="sans-serif" font-size="2.4" fill="#226b8e">Blue: hanger hole • through</text>
<text x="0" y="127" font-family="sans-serif" font-size="2.4" fill="#a64235">Red: outside cut • through portions</text>
<text x="0" y="131" font-family="sans-serif" font-size="2.4" fill="#9b6710">Amber: tab spans at Z -2.2 • nominal 0.8 retained</text>
<text x="0" y="137" font-family="sans-serif" font-size="2.1" fill="#34495e">Exact XY sweeps; Z depth is encoded by color. Stock 110 × 110 mm, work origin lower left.</text>
</svg>'''
    (OUT_DIR / "cutter-sweep-preview.svg").write_text(svg, encoding="utf-8")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (art, title_art, bottom_art, title_arc_length, bottom_arc_length, disc, hole,
     motif_art, aircraft, glyph_gap, motif_text_gap, motif_radial, letter_radial,
     upper_word_gap_actual) = make_artwork()
    art_loops = loops_for(art)
    art_model = planar_model(art_loops, STOCK_THICKNESS, "single-bit-artwork")
    pocket = generate_step_gcode(
        art_model,
        mode="Pocket", orientation="Top (XY)", stock_width=STOCK, stock_height=STOCK,
        zero_location="Lower-left", tool_diameter=TOOL_DIAMETER, depth=-POCKET_DEPTH,
        passes=1, max_stepdown=POCKET_DEPTH, safe_z=SAFE_Z,
        cut_feed=CUT_FEED, plunge_feed=PLUNGE_FEED, spindle_rpm=None,
        stock_thickness=STOCK_THICKNESS, breakthrough=BREAKTHROUGH,
        _placement_offset=PLACEMENT,
    )

    # Profile input is analytic, not image-traced: the nominal 100 mm outer
    # circle and the hanger loop are concentric with the same local XY frame.
    profile_loops = (
        PlanarLoop(tuple(Point2D(x, y) for x, y in closed_circle((50.0, 50.0), 50.0))),
        PlanarLoop(tuple(Point2D(x, y) for x, y in closed_circle((50.0, 95.0), 2.0, 96))),
    )
    profile_model = planar_model(profile_loops, STOCK_THICKNESS, "single-bit-profile")
    hole_job = generate_step_gcode(
        profile_model,
        mode="Hole", orientation="Top (XY)", stock_width=STOCK, stock_height=STOCK,
        zero_location="Lower-left", tool_diameter=TOOL_DIAMETER,
        depth=-(STOCK_THICKNESS + BREAKTHROUGH), passes=1,
        max_stepdown=PROFILE_MAX_STEPDOWN, safe_z=SAFE_Z,
        cut_feed=CUT_FEED, plunge_feed=PLUNGE_FEED, spindle_rpm=None,
        stock_thickness=STOCK_THICKNESS, breakthrough=BREAKTHROUGH,
        _placement_offset=PLACEMENT,
    )
    outside_job = generate_step_gcode(
        profile_model,
        mode="Profile cutout", orientation="Top (XY)", stock_width=STOCK, stock_height=STOCK,
        zero_location="Lower-left", tool_diameter=TOOL_DIAMETER,
        depth=-(STOCK_THICKNESS + BREAKTHROUGH), passes=1,
        max_stepdown=PROFILE_MAX_STEPDOWN, safe_z=SAFE_Z,
        cut_feed=CUT_FEED, plunge_feed=PLUNGE_FEED, spindle_rpm=None,
        stock_thickness=STOCK_THICKNESS, breakthrough=BREAKTHROUGH,
        tab_count=TAB_COUNT, tab_width=TAB_WIDTH, tab_height=TAB_HEIGHT,
        _placement_offset=PLACEMENT, _profile_outer_only=True,
    )

    combined = [
        "; OFFLINE REVIEW DRAFT ONLY - not authorized or verified for cutting",
        "; One 3.175 mm endmill assumption for SPMS200; actual cutting diameter is unverified",
        "; Nominal plywood 3.0 mm, unmeasured; breakthrough 0.15 mm and tab geometry are provisional",
        "; Shallow pocket, then 4 mm hanger hole at all depth passes, then tabbed 100 mm outside profile",
        "; Shared frame: 110 x 110 mm stock, lower-left work zero, part center X55 Y55",
        "; 0.4 mm pocket depth, one pass; 300/80 mm/min feeds are illustrative and unverified",
        "; Through profile depth 3.15 mm is split into 7 passes with at most 0.5 mm stepdown",
        "; XY rapid clearance Z3 mm; spindle start is omitted; no automatic toolchange",
        "G21", "G17", "G90", "G94", "M5", f"G0 Z{SAFE_Z:g}",
        "; OPERATION 1: shallow artwork pocket",
        *body_lines(pocket.gcode),
        "; OPERATION 2: complete hanger-hole passes (max stepdown 0.5 mm)",
        *body_lines(hole_job.gcode),
        "; OPERATION 3: outside profile begins only after the hanger hole is complete",
        *body_lines(outside_job.gcode),
        f"G0 Z{SAFE_Z:g}", "G0 X0 Y0", "M5", "M2",
    ]
    gcode, inserted_depth_moves = split_in_material_z_descents(
        "\n".join(combined) + "\n", PROFILE_MAX_STEPDOWN
    )
    draft_path = OUT_DIR / "review-draft.nc"
    draft_path.write_text(gcode, encoding="ascii", newline="\n")
    program = parse_gcode(gcode, draft_path)
    validate_nonnegative_work_xy(program)
    validate_rapid_xy_clearance(program, SAFE_Z)
    executable_gcode = "\n".join(line for line in gcode.splitlines() if not line.lstrip().startswith(";"))
    if re.search(r"\bM\s*(?:3|6)\b", executable_gcode, re.IGNORECASE):
        raise ValueError("Draft unexpectedly contains spindle start or a tool change")
    if len(re.findall(r"\bM\s*(?:2|30)\b", gcode, re.IGNORECASE)) != 1 or not gcode.rstrip().endswith("M2"):
        raise ValueError("Draft must have exactly one final program-end marker")

    shallow_lines, hole_lines, outside_lines, tab_lines, intermediate_lines, ordered_profile = motion_groups(program)
    pocket_sweep = linework_sweep(shallow_lines, TOOL_RADIUS)
    hole_sweep = linework_sweep(hole_lines, TOOL_RADIUS)
    outside_sweep = linework_sweep(outside_lines, TOOL_RADIUS)
    tab_sweep = linework_sweep(tab_lines, TOOL_RADIUS)
    total_sweep = unary_union((pocket_sweep, hole_sweep, outside_sweep, tab_sweep))
    stock_region = box(0, 0, STOCK, STOCK)
    if not stock_region.buffer(0.001).covers(total_sweep):
        raise ValueError("Emitted cutter sweep leaves the declared 110 x 110 mm stock")

    world_art = translate(art, xoff=PLACEMENT[0], yoff=PLACEMENT[1])
    world_disc = Point(*PART_CENTER_WORK).buffer(PART_DIAMETER / 2, quad_segs=256)
    world_hole = Point(55.0, 100.0).buffer(2.0, quad_segs=96)
    art_hole_clearance = float(art.distance(hole.boundary))
    art_outer_clearance = float(art.distance(disc.boundary))
    counter_metrics = []
    for text_name, text_geom in (("title", title_art), ("bottom", bottom_art)):
        for item in polygonal_parts(text_geom):
            for interior in item.interiors:
                candidate = Polygon(interior)
                rectangle = candidate.minimum_rotated_rectangle
                coordinates = list(rectangle.exterior.coords)
                edge_lengths = [math.dist(coordinates[index], coordinates[index + 1]) for index in range(4)]
                counter_metrics.append({
                    "textGroup": text_name,
                    "areaMm2": round(candidate.area, 4),
                    "shortSideMm": round(min(edge_lengths), 4),
                    "longSideMm": round(max(edge_lengths), 4),
                })

    # Use exact component toolpaths and also check their compensations against
    # their analytic nominal dimensions in the common work frame.
    hole_area_nominal = math.pi * 2.0**2
    hole_centerline_diameter = 2 * max(math.dist((x, y), (55.0, 100.0)) for line in hole_lines for x, y in line)
    hole_sweep_diameter = hole_centerline_diameter + TOOL_DIAMETER
    profile_work_radius = max(math.dist((x, y), PART_CENTER_WORK) for line in outside_lines for x, y in line)
    profile_depths_positive = sorted({
        round(-z, 3) for z, _radius, _length in ordered_profile
        if not math.isclose(z, -(STOCK_THICKNESS - TAB_HEIGHT), abs_tol=0.002)
    })
    profile_pass_depths = [-depth for depth in profile_depths_positive]
    profile_stepdowns = [profile_depths_positive[0]] + [
        following - previous
        for previous, following in zip(profile_depths_positive, profile_depths_positive[1:])
    ]
    vertical_profile_descents = [
        segment.start.z - segment.end.z
        for segment in program.segments
        if (
            not segment.rapid
            and math.dist(
                (segment.start.x, segment.start.y),
                (segment.end.x, segment.end.y),
            ) <= 1e-8
            and segment.start.z < -1e-6
            and segment.end.z < segment.start.z - 1e-6
            and math.dist(
                ((segment.start.x + segment.end.x) / 2,
                 (segment.start.y + segment.end.y) / 2),
                PART_CENTER_WORK,
            ) > 48
        )
    ]
    max_profile_stepdown = max([*profile_stepdowns, *vertical_profile_descents])
    if hole_job.passes != 7 or outside_job.passes != 7 or len(profile_pass_depths) != 7:
        raise ValueError("Both through operations must use seven depth passes")
    if max_profile_stepdown > PROFILE_MAX_STEPDOWN + 0.001:
        raise ValueError(f"Profile pass schedule exceeds its {PROFILE_MAX_STEPDOWN:g} mm maximum stepdown")
    actual_svg = OUT_DIR / "artwork-reference.svg"
    write_artwork_svg(art, disc, hole)
    write_preview_svg(pocket_sweep, hole_sweep, outside_sweep, tab_sweep)
    world_title_art = translate(title_art, xoff=PLACEMENT[0], yoff=PLACEMENT[1])
    world_bottom_art = translate(bottom_art, xoff=PLACEMENT[0], yoff=PLACEMENT[1])
    title_uncut = float(world_title_art.difference(pocket_sweep).area)
    bottom_uncut = float(world_bottom_art.difference(pocket_sweep).area)

    source_refs = {
        "approvedArtwork": {
            "pathFromRepositoryRoot": str(REF_ART.relative_to(REPO_ROOT)).replace("\\", "/"),
            "sha256": sha256(REF_ART),
            "role": "fine-line visual reference; not raster-converted into toolpaths",
        },
        "approvedWoodMockup": {
            "filename": CONCEPT.name,
            "path": str(CONCEPT),
            "sha256": sha256(CONCEPT) if CONCEPT.exists() else "not-present-at-rebuild-time",
            "role": "appearance reference only; never converted to machining geometry",
        },
    }
    report = {
        "schemaVersion": 1,
        "bundle": "hawkeye-single-bit-review-draft",
        "rebuildCommand": ".\\.venv\\Scripts\\python.exe artifacts/ornaments/hawkeye/single-bit/prepare.py",
        "releaseStatus": "offline-review-only; not verified or authorized for cutting",
        "sourceReferences": source_refs,
        "simplification": {
            "strategy": "hand-built vector silhouette and monoline letters, processed by the existing STEP pocket and tabbed profile generators",
            "retainedLetteringExact": ["DOME RIDERS", "VAW-120 KEY WEST"],
            "letteringRenderCase": "uppercase",
            "includedMotifs": ["connected E-2 Hawkeye side silhouette", "radar dome and joined stalk", "paired engine bulges", "two broad propeller disks without blade detail", "seven sun rays", "water", "palm", "sailboat"],
            "removedReferenceDetails": ["curved filled display lettering", "fine aircraft panel/window lines", "fine palm fronds", "small water streaks", "thin circle border"],
            "notes": "This is a vector-native, one-tool redraw. It does not reproduce the photograph's carved shading or the approved line-art's fine contours. Closed counters are retained wood; their size is listed for visual/wood-web review and does not need cutter clearance.",
            "titleArcLengthMm": round(title_arc_length, 3),
            "bottomArcLengthMm": round(bottom_arc_length, 3),
            "measuredMinimumGlyphGapMm": round(glyph_gap, 4),
            "upperWordGapAtTwelveOclockMm": round(upper_word_gap_actual, 4),
            "minimumMotifToLetterClearanceMm": round(motif_text_gap, 4),
            "motifRadialBoundsMm": [round(value, 4) for value in motif_radial],
            "letteringRadialBoundsMm": [round(value, 4) for value in letter_radial],
            "aircraftSilhouette": {
                "connectedComponentCount": len(polygonal_parts(aircraft)),
                "boundsLocalXYMm": [round(value, 4) for value in aircraft.bounds],
                "nacellesJoinedToBody": True,
                "propellerDisks": 2,
                "propellerDiskSizeMm": [4.0, 9.0],
                "propellerBladesDetailed": False,
                "radarStalkJoinsWing": True,
                "tailFinMinimumBoundingWidthMm": 4.0,
            },
        },
        "geometry": {
            "units": "mm",
            "stock": {"width": STOCK, "height": STOCK, "origin": "lower-left", "assumedThickness": STOCK_THICKNESS, "thicknessMeasured": False},
            "part": {"shape": "analytic circle", "nominalDiameter": PART_DIAMETER, "centerWorkXY": list(PART_CENTER_WORK)},
            "hangerHole": {"centerWorkXY": [55.0, 100.0], "nominalDiameter": 4.0, "outerEdgeWebMm": 3.0, "toolSweepDiameterMm": round(hole_sweep_diameter, 4), "artworkToHoleEdgeClearanceMm": round(art_hole_clearance, 4)},
            "sharedPlacement": {"modelOffsetXY": list(PLACEMENT), "pocketAndProfileUseSameOffset": True, "partCenterTransform": "local(50,50) + (5,5) = work(55,55)"},
            "artworkRimClearanceMm": round(art_outer_clearance, 4),
            "letteringFitReview": {
                "status": "Closed counters remain as retained wood; review visible sizes in SVG. Split-apex A uses an open stencil form.",
                "counterCount": len(counter_metrics),
                "toolDiameterMm": TOOL_DIAMETER,
                "counterChecks": counter_metrics,
                "smallestCounterShortSideMm": min((item["shortSideMm"] for item in counter_metrics), default=None),
                "counterClearanceIsNotACutterAccessRequirement": True,
                "titleTargetAreaMm2": round(title_art.area, 4),
                "titleAreaUncutByEmittedSweepMm2": round(title_uncut, 4),
                "titleAreaUncutPercent": round(100 * title_uncut / title_art.area, 3),
                "bottomTextTargetAreaMm2": round(bottom_art.area, 4),
                "bottomTextAreaUncutByEmittedSweepMm2": round(bottom_uncut, 4),
                "bottomTextAreaUncutPercent": round(100 * bottom_uncut / bottom_art.area, 3),
                "allLetteringTargetAreaUncutPercent": round(100 * (title_uncut + bottom_uncut) / (title_art.area + bottom_art.area), 3),
            },
        },
        "tool": {"type": "assumed flat endmill", "reportedModel": "SHARPRO SPMS200-2ES-1/8", "cuttingDiameterMm": TOOL_DIAMETER, "diameterVerified": False, "fluteLengthVerified": False},
        "operations": [
            {"order": 1, "kind": "shallow pockets", "targetDepthMm": -POCKET_DEPTH, "passes": 1, "feedMmPerMin": CUT_FEED, "plungeMmPerMin": PLUNGE_FEED, "spindleStart": False},
            {"order": 2, "kind": "hanger hole", "targetDepthMm": -(STOCK_THICKNESS + BREAKTHROUGH), "cutoutDiameterMm": 4.0, "passes": hole_job.passes, "maxStepdownMm": PROFILE_MAX_STEPDOWN},
            {"order": 3, "kind": "outer profile", "targetDepthMm": -(STOCK_THICKNESS + BREAKTHROUGH), "nominalDiameterMm": PART_DIAMETER, "passes": outside_job.passes, "maxStepdownMm": PROFILE_MAX_STEPDOWN, "tabs": {"count": TAB_COUNT, "widthMm": TAB_WIDTH, "heightMm": TAB_HEIGHT}},
        ],
        "toolpathReview": {
            "xyRapidSafeZMm": SAFE_Z,
            "stockEnvelopeContainsAllEmittedCutterSweeps": True,
            "maxWorkXyMm": [round(program.bounds.maximum.x, 4), round(program.bounds.maximum.y, 4)],
            "minWorkXyMm": [round(program.bounds.minimum.x, 4), round(program.bounds.minimum.y, 4)],
            "pocketSweepAreaMm2": round(pocket_sweep.area, 4),
            "shallowTargetToolReachableAreaMm2": round(pocket.simulation.reachable_area, 4) if pocket.simulation else None,
            "shallowToolReachableAreaUncoveredMm2": round(pocket.simulation.uncovered_area, 4) if pocket.simulation else None,
            "shallowTargetCenterlineInaccessibleAreaMm2": round(pocket.simulation.unreachable_area, 4) if pocket.simulation else None,
            "shallowTargetAreaMm2": round(world_art.area, 4),
            "shallowTargetAreaUncutByEmittedSweepMm2": round(world_art.difference(pocket_sweep).area, 4),
            "shallowTargetAreaUncutPercent": round(100 * world_art.difference(pocket_sweep).area / world_art.area, 3),
            "profileHoleCenterlineDiameterMm": round(hole_centerline_diameter, 4),
            "profileHoleSweptDiameterMm": round(hole_sweep_diameter, 4),
            "outerProfileCenterlineSweepRadiusMm": round(profile_work_radius, 4),
            "exactCutterSweepBoundsWorkXY": [round(value, 4) for value in total_sweep.bounds],
            "profileFeedDepthLevelsMm": profile_pass_depths,
            "profileMaxStepdownMm": PROFILE_MAX_STEPDOWN,
            "profileMeasuredMaxStepdownMm": round(max_profile_stepdown, 4),
            "profileVerticalInStockDescentCount": len(vertical_profile_descents),
            "profileMaxVerticalInStockDescentMm": round(max(vertical_profile_descents, default=0.0), 4),
            "insertedStepdownMovesAtTabExits": inserted_depth_moves,
            "holeDepthPasses": hole_job.passes,
            "outerProfileDepthPasses": outside_job.passes,
            "holePassesAllCompleteBeforeOuterProfile": True,
            "tabLiftFeedSegments": len(tab_lines),
            "holeFirstOuterLast": ordered_profile[0][1] < 48 and ordered_profile[-1][1] > 48,
            "tabLiftSegments": len(tab_lines),
            "estimatedMinutes": round(pocket.estimated_minutes + hole_job.estimated_minutes + outside_job.estimated_minutes, 3),
            "estimateAssumptions": "3000 mm/min rapid model; excludes spindle start, acceleration, real GRBL limits and wood/material effects",
            "gcodeLineCount": len(gcode.splitlines()),
            "m3Count": len(re.findall(r"\bM\s*3\b", gcode, re.IGNORECASE)),
            "m6Count": len(re.findall(r"\bM\s*6\b", gcode, re.IGNORECASE)),
            "m5Count": len(re.findall(r"\bM\s*5\b", executable_gcode, re.IGNORECASE)),
            "finalProgramEndCount": len(re.findall(r"\bM\s*(?:2|30)\b", gcode, re.IGNORECASE)),
        },
        "unknownsBlockingProduction": [
            "actual endmill cutting diameter and flute length",
            "measured plywood thickness, flatness and veneer quality",
            "verified cut and plunge feeds, RPM and depth limits",
            "stock/clamp/spoilboard placement and clearance",
            "physical coupon results, tab retention and wood tear-out",
        ],
        "artifacts": {
            "source": {"path": "artifacts/ornaments/hawkeye/single-bit/prepare.py", "sha256": sha256(Path(__file__))},
            "artworkSvg": {"path": "artifacts/ornaments/hawkeye/single-bit/artwork-reference.svg", "sha256": sha256(actual_svg)},
            "gcode": {"path": "artifacts/ornaments/hawkeye/single-bit/review-draft.nc", "sha256": sha256(draft_path)},
            "sweepPreviewSvg": {"path": "artifacts/ornaments/hawkeye/single-bit/cutter-sweep-preview.svg", "sha256": sha256(OUT_DIR / "cutter-sweep-preview.svg")},
        },
        "offlineChecks": {
            "gcodeParses": True,
            "nonnegativeWorkXY": True,
            "rapidXYAtSafeZ": True,
            "oneToolNoM3NoM6": True,
            "oneFinalProgramEnd": True,
            "allEmittedCutterSweepsInsideStock": True,
            "profileAllInStockZDescentsWithinMaxStepdown": max_profile_stepdown <= PROFILE_MAX_STEPDOWN + 0.001,
        },
    }
    (OUT_DIR / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "gcode": str(draft_path), "lineCount": len(gcode.splitlines()),
        "pocketStrokes": pocket.stroke_count, "holeStrokes": hole_job.stroke_count,
        "outerProfileStrokes": outside_job.stroke_count,
        "pocketMinutes": round(pocket.estimated_minutes, 3),
        "profileMinutes": round(hole_job.estimated_minutes + outside_job.estimated_minutes, 3),
        "uncutPercent": report["toolpathReview"]["shallowTargetAreaUncutPercent"],
        "artHoleClearanceMm": report["geometry"]["hangerHole"]["artworkToHoleEdgeClearanceMm"],
        "minimumCounterShortSideMm": report["geometry"]["letteringFitReview"]["smallestCounterShortSideMm"],
        "holeSweepDiameterMm": report["geometry"]["hangerHole"]["toolSweepDiameterMm"],
        "holeFirstOuterLast": report["toolpathReview"]["holeFirstOuterLast"],
    }, indent=2))


if __name__ == "__main__":
    main()
