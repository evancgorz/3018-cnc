"""Build the offline single-endmill cutout leg of the Hawkeye two-bit job.

This script emits a review draft only. It does not communicate with the CNC.
Run from the repository root with the project virtual environment:

    .\\.venv\\Scripts\\python.exe artifacts/ornaments/hawkeye/two-bit/c045-stock-3p25/prepare-cutout.py
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
import sys
from typing import Iterable

from shapely.geometry import GeometryCollection, LineString, Point, Polygon, box
from shapely.ops import unary_union


REPO_ROOT = Path(__file__).resolve().parents[5]
OUT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from ttc3018_control.gcode import (  # noqa: E402
    parse_gcode,
    validate_nonnegative_work_xy,
    validate_rapid_xy_clearance,
)
from ttc3018_control.step_engraver import generate_step_gcode  # noqa: E402
from ttc3018_control.step_geometry import PlanarLoop, Point2D, StepPlanarModel  # noqa: E402


STOCK_WIDTH = 110.0
STOCK_HEIGHT = 110.0
PART_DIAMETER = 100.0
PART_CENTER_LOCAL = (50.0, 50.0)
PLACEMENT = (5.0, 5.0)
PART_CENTER_WORK = (55.0, 55.0)
TOOL_DIAMETER = 3.175  # Assumed only; the SPMS200 cutting diameter is unverified.
TOOL_RADIUS = TOOL_DIAMETER / 2
STOCK_THICKNESS = 3.25  # User-reported measured plywood thickness; local flatness is unverified.
BREAKTHROUGH = 0.15
TARGET_DEPTH = -(STOCK_THICKNESS + BREAKTHROUGH)
SAFE_Z = 3.0
CUT_FEED = 300.0
PLUNGE_FEED = 80.0
TAB_COUNT = 4
TAB_WIDTH = 4.0
TAB_HEIGHT = 0.8
MAX_STEPDOWN = 0.5
HOLE_CENTER_WORK = (55.0, 100.0)
HOLE_DIAMETER = 4.0
SPINDLE_RPM = 1000  # User confirmed a previously successful saved setting.
SPINDLE_DWELL_SECONDS = 2.0  # Candidate startup allowance; not measured on this spindle.


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def closed_circle(center: tuple[float, float], radius: float, count: int = 144):
    return tuple(
        (center[0] + radius * math.cos(math.tau * index / count),
         center[1] + radius * math.sin(math.tau * index / count))
        for index in range(count)
    )


def model_loops() -> tuple[PlanarLoop, ...]:
    # Preserve the frozen one-bit task's analytic geometry and work transform:
    # a 100 mm circle, hanger center at local (50,95), both shifted by (5,5).
    return (
        PlanarLoop(tuple(Point2D(x, y) for x, y in closed_circle((50.0, 50.0), 50.0))),
        PlanarLoop(tuple(Point2D(x, y) for x, y in closed_circle((50.0, 95.0), 2.0, 96))),
    )


def planar_model(loops: tuple[PlanarLoop, ...]) -> StepPlanarModel:
    return StepPlanarModel(
        Path("hawkeye-100mm-cutout"), loops, 0.0, STOCK_THICKNESS,
        (0.0, 0.0, 0.0, PART_DIAMETER, PART_DIAMETER, STOCK_THICKNESS),
        face_plane="XY",
    )


def body_lines(gcode: str) -> list[str]:
    lines = gcode.splitlines()
    try:
        start = lines.index("G94") + 1
    except ValueError as exc:
        raise ValueError("STEP component lacks its expected G94 setup") from exc
    if lines[-4:] != ["G0 Z3", "G0 X0 Y0", "M5", "M2"]:
        raise ValueError("STEP component has an unexpected program-end sequence")
    body = lines[start:-4]
    if any(line in {"M2", "M30"} for line in body):
        raise ValueError("Intermediate operation contains a program-end marker")
    return body


def split_in_material_z_descents(gcode: str) -> tuple[str, int]:
    """Bound feed descents that begin below the top surface to 0.5 mm."""
    output: list[str] = []
    current_z = 0.0
    motion = 0
    feed = PLUNGE_FEED
    inserted = 0
    for raw in gcode.splitlines():
        code = raw.split(";", 1)[0].strip()
        if not code:
            output.append(raw)
            continue
        words = {
            match.group(1).upper(): float(match.group(2))
            for match in re.finditer(
                r"([A-Z])\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))", code, re.IGNORECASE
            )
        }
        if "F" in words:
            feed = words["F"]
        if "G" in words and words["G"] in (0.0, 1.0):
            motion = int(words["G"])
        if "Z" in words:
            target_z = words["Z"]
            if motion == 1 and current_z < -1e-6 and target_z < current_z - MAX_STEPDOWN - 1e-9:
                while current_z - target_z > MAX_STEPDOWN + 1e-9:
                    current_z = round(current_z - MAX_STEPDOWN, 4)
                    output.append(f"G1 Z{current_z:.4f} F{feed:g}")
                    inserted += 1
            current_z = target_z
        output.append(raw)
    return "\n".join(output) + "\n", inserted


def sweep(lines: Iterable[tuple[tuple[float, float], tuple[float, float]]]):
    paths = [
        LineString(line).buffer(TOOL_RADIUS, cap_style=1, join_style=1, quad_segs=8)
        for line in lines
        if math.dist(line[0], line[1]) > 1e-9
    ]
    return unary_union(paths) if paths else GeometryCollection()


def polygon_parts(geometry):
    if geometry.geom_type == "Polygon":
        return [geometry]
    return [part for part in getattr(geometry, "geoms", ()) if part.geom_type == "Polygon"]


def path_data(geometry) -> str:
    fragments: list[str] = []
    for item in polygon_parts(geometry):
        for ring in (item.exterior, *item.interiors):
            points = list(ring.coords)
            if len(points) < 4:
                continue
            fragments.append(
                "M " + " L ".join(f"{x:.4f},{STOCK_HEIGHT - y:.4f}" for x, y in points) + " Z"
            )
    return " ".join(fragments)


def write_preview(hole_sweep, full_depth_sweep, tab_sweep) -> Path:
    # This is the exact parsed XY cutter sweep of the emitted file. Amber shows
    # the same contour where the final pass is raised to retain the tabs.
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="-2 -18 114 132" width="760" height="880">
<title>Hawkeye 100 mm endmill cutout review preview for measured 3.25 mm stock</title>
<desc>Exact XY cutter-sweep polygons parsed from 02-cutout-review.nc. Blue is the hanger-hole cut; red is the full-depth outside cut; amber is the outside contour at the tab floor. Stock is 110 by 110 mm, lower-left work origin. The program uses a user-reported measured thickness of 3.25 mm.</desc>
<rect x="0" y="0" width="110" height="110" fill="#f5f0e5" stroke="#48515a" stroke-width="0.35"/>
<circle cx="55" cy="55" r="50" transform="translate(0 110) scale(1 -1)" fill="none" stroke="#303840" stroke-width="0.35" stroke-dasharray="1.2 1"/>
<path d="{path_data(full_depth_sweep)}" fill="#c94f40" fill-rule="evenodd" opacity="0.92"/>
<path d="{path_data(tab_sweep)}" fill="#edb43e" fill-rule="evenodd" opacity="0.98"/>
<path d="{path_data(hole_sweep)}" fill="#397da8" fill-rule="evenodd" opacity="0.94"/>
<circle cx="55" cy="10" r="2" fill="none" stroke="#1d4f70" stroke-width="0.35"/>
<text x="0" y="-7" font-family="sans-serif" font-size="2.5" fill="#263238">100 mm nominal profile • assumed 3.175 mm endmill</text>
<text x="0" y="-3.5" font-family="sans-serif" font-size="2.2" fill="#263238">3.25 mm stock • blue: hole • red: through contour • amber: tabs at Z −2.45</text>
<text x="0" y="114" font-family="sans-serif" font-size="2.2" fill="#263238">Offline review only; cutter, feeds, breakthrough and local stock flatness remain unverified.</text>
</svg>'''
    path = OUT_DIR / "cutout-preview.svg"
    path.write_text(svg, encoding="utf-8", newline="\n")
    return path


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    model = planar_model(model_loops())
    common = dict(
        orientation="Top (XY)", stock_width=STOCK_WIDTH, stock_height=STOCK_HEIGHT,
        zero_location="Lower-left", tool_diameter=TOOL_DIAMETER,
        depth=TARGET_DEPTH, passes=1, max_stepdown=MAX_STEPDOWN,
        safe_z=SAFE_Z, cut_feed=CUT_FEED, plunge_feed=PLUNGE_FEED,
        spindle_rpm=None, stock_thickness=STOCK_THICKNESS,
        breakthrough=BREAKTHROUGH, _placement_offset=PLACEMENT,
    )
    hole_job = generate_step_gcode(model, mode="Hole", **common)
    outside_job = generate_step_gcode(
        model, mode="Profile cutout", tab_count=TAB_COUNT,
        tab_width=TAB_WIDTH, tab_height=TAB_HEIGHT,
        _profile_outer_only=True, **common,
    )
    if hole_job.passes != 7 or outside_job.passes != 7:
        raise ValueError("Hanger hole and outside contour must each use seven depth passes")

    combined = [
        "; OFFLINE REVIEW DRAFT ONLY - not authorized or verified for cutting",
        "; C-045 offline review: hole and outside profile with one assumed flat endmill",
        "; Tool: assumed 3.175 mm SPMS200 cutting diameter; actual diameter/flute length unverified",
        "; Stock thickness: 3.25 mm user-reported measured plywood; local flatness unverified",
        "; Breakthrough: provisional 0.15 mm below measured thickness; spoilboard clearance unverified",
        "; Shared XY frame: stock 110 x 110 mm; lower-left work zero; part center X55 Y55",
        "; Feeds 300/80 mm/min and safe Z3 mm are illustrative; spindle start omitted",
        "; Seven depth levels, max in-stock descent 0.5 mm; four nominal 4 mm tabs, 0.8 mm high",
        "G21", "G17", "G90", "G94", "M5", f"G0 Z{SAFE_Z:g}",
        "; OPERATION 1: complete 4 mm hanger-hole passes",
        *body_lines(hole_job.gcode),
        "; OPERATION 2: tabbed 100 mm outside contour after the hole is complete",
        *body_lines(outside_job.gcode),
        f"G0 Z{SAFE_Z:g}", "G0 X0 Y0", "M5", "M2",
    ]
    gcode, inserted_tab_moves = split_in_material_z_descents("\n".join(combined) + "\n")
    nc_path = OUT_DIR / "02-cutout-review.nc"
    nc_path.write_text(gcode, encoding="ascii", newline="\n")

    program = parse_gcode(gcode, nc_path)
    validate_nonnegative_work_xy(program)
    validate_rapid_xy_clearance(program, SAFE_Z)
    executable = "\n".join(line for line in gcode.splitlines() if not line.lstrip().startswith(";"))
    if re.search(r"\bM\s*(?:3|6)\b", executable, re.IGNORECASE):
        raise ValueError("Cutout draft must omit spindle start and automatic toolchange")
    if len(re.findall(r"\bM\s*(?:2|30)\b", executable, re.IGNORECASE)) != 1 or not gcode.rstrip().endswith("M2"):
        raise ValueError("Combined cutout file must have exactly one final program-end marker")
    m5_count = len(re.findall(r"\bM\s*5\b", executable, re.IGNORECASE))
    if m5_count != 2:
        raise ValueError("Combined cutout file must have one initial and one final M5")

    hole_segments = []
    outside_segments = []
    vertical_descents = []
    for index, segment in enumerate(program.segments):
        start_xy = (segment.start.x, segment.start.y)
        end_xy = (segment.end.x, segment.end.y)
        xy_length = math.dist(start_xy, end_xy)
        radius = math.dist(
            ((segment.start.x + segment.end.x) / 2, (segment.start.y + segment.end.y) / 2),
            PART_CENTER_WORK,
        )
        if not segment.rapid and xy_length > 1e-8 and segment.end.z < -1e-6:
            item = (index, start_xy, end_xy, (segment.start.z + segment.end.z) / 2)
            if radius < 48:
                hole_segments.append(item)
            elif radius > 48:
                outside_segments.append(item)
        if (
            not segment.rapid and xy_length <= 1e-8
            and segment.start.z < -1e-6 and segment.end.z < segment.start.z - 1e-6
        ):
            vertical_descents.append(segment.start.z - segment.end.z)
    if not hole_segments or not outside_segments:
        raise ValueError("Combined parser view is missing the hanger-hole or outside contour")
    if max(item[0] for item in hole_segments) >= min(item[0] for item in outside_segments):
        raise ValueError("A hanger-hole cutting move occurs after the outside contour begins")

    hole_sweep = sweep((item[1], item[2]) for item in hole_segments)
    outer_deep = [item for item in outside_segments if item[3] < -(STOCK_THICKNESS - TAB_HEIGHT) + 0.002]
    outer_tabs = [item for item in outside_segments if math.isclose(item[3], -(STOCK_THICKNESS - TAB_HEIGHT), abs_tol=0.002)]
    outer_sweep = sweep((item[1], item[2]) for item in outer_deep)
    tab_sweep = sweep((item[1], item[2]) for item in outer_tabs)
    full_outer_sweep = sweep((item[1], item[2]) for item in outside_segments)
    tab_span_lines: dict[int, list[LineString]] = {}
    for _, start_xy, end_xy, _ in outer_tabs:
        midpoint = ((start_xy[0] + end_xy[0]) / 2, (start_xy[1] + end_xy[1]) / 2)
        angle = math.degrees(math.atan2(
            midpoint[1] - PART_CENTER_WORK[1], midpoint[0] - PART_CENTER_WORK[0],
        )) % 360
        cardinal = int(round(angle / 90)) % 4
        tab_span_lines.setdefault(cardinal, []).append(LineString((start_xy, end_xy)))
    tab_span_lengths = {
        key: round(unary_union(lines).length, 4)
        for key, lines in sorted(tab_span_lines.items())
    }
    if len(tab_span_lengths) != TAB_COUNT or any(
        abs(length - TAB_WIDTH) > 0.05 for length in tab_span_lengths.values()
    ):
        raise ValueError("Parsed profile must retain four 4 mm tab intervals")
    all_sweeps = unary_union((hole_sweep, full_outer_sweep))
    if not box(0, 0, STOCK_WIDTH, STOCK_HEIGHT).buffer(0.001).covers(all_sweeps):
        raise ValueError("The exact parsed cutter sweep leaves the declared stock envelope")

    profile_levels = sorted({
        round(-item[3], 3)
        for item in [*hole_segments, *outside_segments]
        if not math.isclose(item[3], -(STOCK_THICKNESS - TAB_HEIGHT), abs_tol=0.002)
    })
    stepdowns = [profile_levels[0], *(
        following - previous for previous, following in zip(profile_levels, profile_levels[1:])
    )]
    measured_max_stepdown = max([*stepdowns, *vertical_descents])
    if len(profile_levels) != 7 or measured_max_stepdown > MAX_STEPDOWN + 0.001:
        raise ValueError("Parsed pass levels or actual in-stock Z descents exceed the 0.5 mm/7-pass limit")
    if len(outer_tabs) == 0 or inserted_tab_moves < 1:
        raise ValueError("Expected tab sweeps and bounded tab-exit descent moves are missing")
    preview_path = write_preview(hole_sweep, outer_sweep, tab_sweep)

    candidate_lines = list(gcode.splitlines())
    candidate_lines[0] = "; OFFLINE JOB-READY CANDIDATE - not loaded or run; physical/tool assumptions remain"
    candidate_lines[candidate_lines.index(
        "; Feeds 300/80 mm/min and safe Z3 mm are illustrative; spindle start omitted",
    )] = "; Feeds 300/80 mm/min and safe Z3 mm are illustrative; candidate spindle is 1000 RPM"
    safe_start = candidate_lines.index(f"G0 Z{SAFE_Z:g}")
    candidate_lines[safe_start + 1:safe_start + 1] = [
        f"; User-confirmed prior successful saved spindle setting: {SPINDLE_RPM} RPM",
        f"; Assumed startup dwell: {SPINDLE_DWELL_SECONDS:g} seconds",
        f"M3 S{SPINDLE_RPM}", f"G4 P{SPINDLE_DWELL_SECONDS:g}",
    ]
    candidate_gcode = "\n".join(candidate_lines) + "\n"
    candidate_path = OUT_DIR / "02-cutout-candidate-1000rpm.nc"
    candidate_path.write_text(candidate_gcode, encoding="ascii", newline="\n")
    candidate_program = parse_gcode(candidate_gcode, candidate_path)
    validate_nonnegative_work_xy(candidate_program)
    validate_rapid_xy_clearance(candidate_program, SAFE_Z)
    if candidate_program.segments != program.segments:
        raise ValueError("Spindle-enabled candidate must retain identical parsed motion geometry")
    candidate_executable = "\n".join(
        line for line in candidate_gcode.splitlines() if not line.lstrip().startswith(";")
    )
    candidate_m3_count = len(re.findall(r"\bM\s*3\b", candidate_executable, re.IGNORECASE))
    candidate_m5_count = len(re.findall(r"\bM\s*5\b", candidate_executable, re.IGNORECASE))
    candidate_m6_count = len(re.findall(r"\bM\s*6\b", candidate_executable, re.IGNORECASE))
    candidate_g4_count = len(re.findall(r"\bG\s*4\b", candidate_executable, re.IGNORECASE))
    if (candidate_m3_count != 1 or candidate_m5_count != 2 or candidate_m6_count != 0
            or candidate_g4_count != 1
            or not candidate_executable.rstrip().endswith("M2")
            or candidate_executable.splitlines()[-2:] != ["M5", "M2"]):
        raise ValueError("Spindle candidate must have one M3, one dwell, two M5s, and final M5/M2")
    if not math.isclose(
        candidate_program.estimated_seconds - program.estimated_seconds,
        SPINDLE_DWELL_SECONDS,
        abs_tol=0.001,
    ):
        raise ValueError("Spindle candidate dwell is missing from its parsed runtime estimate")

    nominal_hole_area = math.pi * (HOLE_DIAMETER / 2) ** 2
    hole_centerline_diameter = 2 * max(
        math.dist(point, HOLE_CENTER_WORK)
        for item in hole_segments for point in (item[1], item[2])
    )
    hole_sweep_diameter = hole_centerline_diameter + TOOL_DIAMETER
    outer_centerline_radius = max(
        math.dist(point, PART_CENTER_WORK)
        for item in outside_segments for point in (item[1], item[2])
    )
    nc_path_final = nc_path
    report = {
        "schemaVersion": 1,
        "bundle": "hawkeye-two-bit-endmill-cutout-review-stock-3p25",
        "releaseStatus": "offline-review-only; not verified or authorized for cutting",
        "rebuildCommand": ".\\.venv\\Scripts\\python.exe artifacts/ornaments/hawkeye/two-bit/c045-stock-3p25/prepare-cutout.py",
        "scope": "Endmill cutout leg only; shallow V-bit artwork engraving is a separate job and is not included in this file.",
        "geometrySourceReference": {
            "path": "artifacts/ornaments/hawkeye/single-bit/prepare.py",
            "sha256": sha256(REPO_ROOT / "artifacts" / "ornaments" / "hawkeye" / "single-bit" / "prepare.py"),
            "note": "Reuses the frozen analytic circle/hanger-loop profile geometry and shared XY placement; art-pocket generation is excluded.",
        },
        "geometry": {
            "units": "mm",
            "stock": {"width": STOCK_WIDTH, "height": STOCK_HEIGHT, "origin": "lower-left", "thicknessMm": STOCK_THICKNESS, "thicknessMeasured": True, "thicknessMeasurementSource": "user-reported measured plywood thickness"},
            "part": {"shape": "analytic circle", "nominalDiameter": PART_DIAMETER, "centerWorkXY": list(PART_CENTER_WORK)},
            "hangerHole": {
                "centerWorkXY": list(HOLE_CENTER_WORK), "nominalDiameter": HOLE_DIAMETER,
                "outerRimWebMm": 3.0, "toolCenterlineDiameterMm": round(hole_centerline_diameter, 4),
                "toolSweepDiameterMm": round(hole_sweep_diameter, 4),
                "toolSweepDeviationFromNominalMm": round(hole_sweep_diameter - HOLE_DIAMETER, 4),
                "nominalAreaMm2": round(nominal_hole_area, 4),
            },
            "outerContour": {
                "nominalDiameter": PART_DIAMETER,
                "toolCenterlineRadiusWorkMm": round(outer_centerline_radius, 4),
                "fullDepthSweepBoundsWorkXY": [round(value, 4) for value in full_outer_sweep.bounds],
                "tabs": {"count": TAB_COUNT, "widthMm": TAB_WIDTH, "heightMm": TAB_HEIGHT},
            },
            "sharedPlacement": {
                "modelOffsetXY": list(PLACEMENT), "holeAndOuterUseSameOffset": True,
                "partCenterTransform": "local(50,50) + (5,5) = work(55,55)",
            },
        },
        "tool": {
            "type": "assumed flat endmill", "reportedModel": "SHARPRO SPMS200-2ES-1/8",
            "cuttingDiameterMm": TOOL_DIAMETER, "diameterVerified": False,
            "fluteLengthVerified": False,
        },
        "operations": [
            {"order": 1, "kind": "hanger hole", "diameterMm": HOLE_DIAMETER, "passes": hole_job.passes, "targetDepthMm": TARGET_DEPTH, "maxStepdownMm": MAX_STEPDOWN},
            {"order": 2, "kind": "tabbed outside profile", "nominalDiameterMm": PART_DIAMETER, "passes": outside_job.passes, "targetDepthMm": TARGET_DEPTH, "tabFloorMm": -(STOCK_THICKNESS - TAB_HEIGHT), "maxStepdownMm": MAX_STEPDOWN, "tabs": {"count": TAB_COUNT, "widthMm": TAB_WIDTH, "heightMm": TAB_HEIGHT}},
        ],
        "toolpathReview": {
            "stockWorkBoundsMm": [0.0, 0.0, STOCK_WIDTH, STOCK_HEIGHT],
            "safeZMm": SAFE_Z,
            "cutFeedMmPerMin": CUT_FEED,
            "plungeFeedMmPerMin": PLUNGE_FEED,
            "spindleStartIncluded": False,
            "automaticToolchangeIncluded": False,
            "feedDepthLevelsMm": [-value for value in profile_levels],
            "measuredMaxStepdownIncludingVerticalMovesMm": round(measured_max_stepdown, 4),
            "inStockVerticalDescentCount": len(vertical_descents),
            "largestInStockVerticalDescentMm": round(max(vertical_descents, default=0.0), 4),
            "insertedTabExitStepdownMoves": inserted_tab_moves,
            "holePassesCompleteBeforeOuterContour": True,
            "tabLiftFeedSegmentCount": len(outer_tabs),
            "tabIntervalsVerified": len(tab_span_lengths),
            "tabCenterlineSpanLengthsMm": list(tab_span_lengths.values()),
            "holeCutterSweepAreaMm2": round(hole_sweep.area, 4),
            "outerFullDepthCutterSweepAreaMm2": round(outer_sweep.area, 4),
            "exactCombinedProgramEstimatedMinutes": round(program.estimated_seconds / 60, 3),
            "estimateSource": "parse_gcode(complete combined file).estimated_seconds; linear distance/feed model, not an observed cycle time",
            "gcodeLineCount": len(gcode.splitlines()),
            "m5Count": m5_count,
            "initialM5": executable.splitlines()[4] == "M5",
            "finalM5BeforeM2": executable.splitlines()[-2:] == ["M5", "M2"],
            "m3Count": len(re.findall(r"\bM\s*3\b", executable, re.IGNORECASE)),
            "m6Count": len(re.findall(r"\bM\s*6\b", executable, re.IGNORECASE)),
            "programEndCount": len(re.findall(r"\bM\s*(?:2|30)\b", executable, re.IGNORECASE)),
        },
        "unknownsBlockingProduction": [
            "actual SPMS200 cutting diameter, runout and flute length",
            "local stock flatness, thickness variation, veneer and spoilboard condition",
            "validated feed, plunge and cut-depth settings for this machine/material; 1000 RPM was previously successful per user but was not re-tested here",
            "fixture, clamp, spoilboard and full tool-clearance review",
            "physical coupon, hole size, retained tabs and breakout results",
        ],
        "offlineChecks": {
            "gcodeParses": True,
            "nonnegativeWorkXY": True,
            "rapidXYAtSafeZ": True,
            "oneToolNoM3NoM6": True,
            "oneFinalProgramEnd": True,
            "allEmittedCutterSweepsInsideStock": True,
            "holeFinishesBeforeOuterStarts": True,
            "sevenDepthLevelsAndMaxStepdownIncludingTabReentry": True,
            "fourNominalTabIntervals": True,
        },
        "artifacts": {
            "source": {"path": "artifacts/ornaments/hawkeye/two-bit/c045-stock-3p25/prepare-cutout.py", "sha256": sha256(Path(__file__))},
            "gcode": {"path": "artifacts/ornaments/hawkeye/two-bit/c045-stock-3p25/02-cutout-review.nc", "sha256": sha256(nc_path_final)},
            "preview": {"path": "artifacts/ornaments/hawkeye/two-bit/c045-stock-3p25/cutout-preview.svg", "sha256": sha256(preview_path)},
        },
    }
    (OUT_DIR / "cutout-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    candidate_report = json.loads(json.dumps(report))
    candidate_report.update({
        "bundle": "hawkeye-two-bit-endmill-cutout-candidate-1000rpm-stock-3p25",
        "releaseStatus": "offline job-ready candidate; not loaded or run; remaining physical/tool assumptions still require review",
        "candidateAssumptions": {
            "spindleRpm": SPINDLE_RPM,
            "basis": "User confirmed this saved 1000 RPM setting was successful on a prior job.",
            "startupDwellSeconds": SPINDLE_DWELL_SECONDS,
            "dwellCommand": f"G4 P{SPINDLE_DWELL_SECONDS:g}",
            "dwellBasis": "The project parser accepts G4 P seconds; standard GRBL v1.1 lists G4 as a supported dwell. The installed controller firmware/version was not checked.",
            "grblDocumentation": "https://github.com/gnea/grbl/blob/master/README.md?plain=1",
        },
    })
    candidate_report["toolpathReview"].update({
        "spindleStartIncluded": True,
        "spindleRpm": SPINDLE_RPM,
        "spindleDwellSeconds": SPINDLE_DWELL_SECONDS,
        "exactCombinedProgramEstimatedMinutes": round(candidate_program.estimated_seconds / 60, 3),
        "estimateSource": "parse_gcode(complete combined candidate).estimated_seconds; linear distance/feed plus explicit G4 dwell, not an observed cycle time",
        "gcodeLineCount": len(candidate_gcode.splitlines()),
        "m5Count": candidate_m5_count,
        "initialM5": candidate_executable.splitlines()[4] == "M5",
        "finalM5BeforeM2": candidate_executable.splitlines()[-2:] == ["M5", "M2"],
        "m3Count": candidate_m3_count,
        "m6Count": candidate_m6_count,
        "programEndCount": len(re.findall(r"\bM\s*(?:2|30)\b", candidate_executable, re.IGNORECASE)),
    })
    candidate_report["offlineChecks"].pop("oneToolNoM3NoM6", None)
    candidate_report["offlineChecks"].update({
        "oneM3S1000": candidate_m3_count == 1 and f"M3 S{SPINDLE_RPM}" in candidate_executable.splitlines(),
        "oneG4StartupDwellAcceptedByParser": candidate_g4_count == 1,
        "twoM5WithFinalStopBeforeM2": candidate_m5_count == 2 and candidate_executable.splitlines()[-2:] == ["M5", "M2"],
        "candidateMotionEqualsSpindleOffReview": candidate_program.segments == program.segments,
    })
    candidate_report["artifacts"]["gcode"] = {
        "path": "artifacts/ornaments/hawkeye/two-bit/c045-stock-3p25/02-cutout-candidate-1000rpm.nc",
        "sha256": sha256(candidate_path),
    }
    candidate_report["artifacts"]["spindleOffReviewGcode"] = {
        "path": "artifacts/ornaments/hawkeye/two-bit/c045-stock-3p25/02-cutout-review.nc",
        "sha256": sha256(nc_path_final),
    }
    candidate_report["artifacts"]["report"] = {
        "path": "artifacts/ornaments/hawkeye/two-bit/c045-stock-3p25/cutout-candidate-report.json",
    }
    (OUT_DIR / "cutout-candidate-report.json").write_text(
        json.dumps(candidate_report, indent=2) + "\n", encoding="utf-8",
    )
    print(json.dumps({
        "nc": str(nc_path),
        "estimatedMinutes": report["toolpathReview"]["exactCombinedProgramEstimatedMinutes"],
        "candidateNc": str(candidate_path),
        "candidateEstimatedMinutes": candidate_report["toolpathReview"]["exactCombinedProgramEstimatedMinutes"],
        "candidateSpindleRpm": SPINDLE_RPM,
        "candidateDwellSeconds": SPINDLE_DWELL_SECONDS,
        "depthLevels": report["toolpathReview"]["feedDepthLevelsMm"],
        "maxStepdownMm": report["toolpathReview"]["measuredMaxStepdownIncludingVerticalMovesMm"],
        "insertedTabExitMoves": inserted_tab_moves,
        "holeBeforeOuter": True,
        "gcodeLines": len(gcode.splitlines()),
    }, indent=2))


if __name__ == "__main__":
    main()
