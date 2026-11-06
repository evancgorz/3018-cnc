"""Prepare an offline, broad-only inner-ply depth candidate; never connects to CNC."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
import sys

from PIL import Image
from shapely.geometry import LineString, Point, box
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parents[6]
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

STOCK = 110.0
STOCK_THICKNESS = 3.25
PART_DIAMETER = 100.0
PART_CENTER = (55.0, 55.0)
ART_DIAMETER = 90.0
STOCK_MARGIN = 5.0
PLACEMENT = (10.0, 10.0)
HOLE_CENTER = (55.0, 100.0)
HOLE_RADIUS = 2.0
HOLE_ENGRAVE_CLEARANCE = 1.0
HOLE_KEEPOUT_RADIUS = HOLE_RADIUS + HOLE_ENGRAVE_CLEARANCE
V_ANGLE = 30.0
TIP_DIAMETER = 0.1
TARGET_DEPTH = 1.625
MAX_STEPDOWN = 0.6
STEPOVER = 0.27
SAFE_Z = 3.0
APPROACH_Z = 0.2
CUT_FEED = 600.0
PLUNGE_FEED = 160.0
THRESHOLD = 128
SPINDLE_RPM = 1000
SPINDLE_DWELL_SECONDS = 2.0
NC_NAME = "01-detail-stream-compatible-inner-ply-1p625mm-600-160.nc"
REPORT_NAME = "detail-report-vbit30-inner-ply-1p625mm-1000rpm.json"
PREVIEW_NAME = "detail-preview-vbit30-inner-ply-1p625mm-1000rpm.svg"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def depth_levels(target: float, maximum_stepdown: float) -> tuple[float, ...]:
    count = math.ceil(target / maximum_stepdown)
    levels = tuple(round(min((index + 1) * maximum_stepdown, target), 4) for index in range(count))
    if not levels or levels[-1] != target or any(b <= a for a, b in zip((0.0, *levels[:-1]), levels)):
        raise ValueError("Depth levels must increase monotonically to the target")
    return levels


def settings_for(image_size: tuple[int, int]) -> OrnamentSettings:
    return OrnamentSettings(
        crop=(0, 0, image_size[0], image_size[1]),
        outer_diameter=PART_DIAMETER,
        art_diameter=ART_DIAMETER,
        stock_thickness=STOCK_THICKNESS,
        stock_margin=STOCK_MARGIN,
        engraving_depth=TARGET_DEPTH,
        v_angle=V_ANGLE,
        tip_diameter=TIP_DIAMETER,
        stepover=STEPOVER,
        max_stepdown=MAX_STEPDOWN,
        safe_z=SAFE_Z,
        cut_feed=CUT_FEED,
        plunge_feed=PLUNGE_FEED,
        spindle_rpm=SPINDLE_RPM,
        threshold=THRESHOLD,
        optimize_paths=True,
        approach_z=APPROACH_Z,
    )


def swept(paths, diameter: float, *, conservative: bool = False):
    radius = diameter / 2
    if conservative:
        radius = radius / math.cos(math.pi / 128)
    pieces = [LineString(path).buffer(radius, quad_segs=32) for path in paths]
    if not pieces:
        raise ValueError("Broad stage produced no cutter sweep")
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


def polyline_elements(paths, width: float) -> str:
    return "\n".join(
        '<polyline points="' + " ".join(f"{x:.4f},{y:.4f}" for x, y in path)
        + f'" stroke="#176b91" stroke-width="{width:.5f}"/>'
        for path in paths
    )


def write_preview(source_region, paths, diameter: float) -> Path:
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="110mm" height="126mm" viewBox="0 0 110 126">
<title>Hawkeye broad V-bit sweep at 1.625 mm depth</title>
<desc>Gray is approved thresholded black artwork. Blue is the broad V-bit path sweep at final depth. Fine detail is intentionally omitted. Red marks the hanger keepout; interface depth is unknown.</desc>
<rect width="110" height="126" fill="#fff"/>
<g transform="translate(0 110) scale(1 -1)">
<rect x="0" y="0" width="110" height="110" fill="#f5f0e6" stroke="#34495e" stroke-width="0.35"/>
<circle cx="55" cy="55" r="50" fill="none" stroke="#34495e" stroke-width="0.35"/>
<path d="{path_data(source_region)}" fill="#9aa2aa" fill-rule="evenodd" opacity="0.56"/>
<g fill="none" stroke="#176b91" stroke-linecap="round" stroke-linejoin="round">
{polyline_elements(paths, diameter)}
</g>
<circle cx="55" cy="100" r="3" fill="#fff" stroke="#bf3535" stroke-width="0.22" stroke-dasharray="0.7 0.45"/>
</g>
<g font-family="sans-serif" fill="#29333d">
<text x="2" y="114" font-size="1.9">Blue: broad fill, Z −{TARGET_DEPTH:g}, modeled width {diameter:.3f} mm</text>
<text x="2" y="117" font-size="1.8">Three passes: {', '.join(f'{z:g}' for z in depth_levels(TARGET_DEPTH, MAX_STEPDOWN))} mm • 0.27 mm stepover</text>
<text x="2" y="120" font-size="1.75">110 × 110 stock • 100 mm circle centered at X55 Y55 • XY origin lower-left</text>
<text x="2" y="123" font-size="1.6">Broad-only; fine marks omitted. 3.25 mm nominal thickness; actual ply boundary unknown.</text>
</g>
</svg>'''
    path = OUT / PREVIEW_NAME
    path.write_text(svg, encoding="utf-8", newline="\n")
    return path


def build_gcode(paths, diameter: float) -> str:
    levels = depth_levels(TARGET_DEPTH, MAX_STEPDOWN)
    lines = [
        "; OFFLINE REVIEW ONLY - not verified or authorized for cutting",
        "; Approved thresholded artwork only; broad-only, fine detail intentionally omitted",
        "; Assumed 30 degree included-angle V-bit with 0.1 mm tip; actual tool/runout unverified",
        "; Nominal stock thickness 3.25 mm; target is half-thickness, actual ply boundary unknown",
        "; 110 x 110 stock, 100 mm disc centered X55 Y55; shared lower-left XY origin",
        f"; Target Z-{TARGET_DEPTH:g}; modeled effective cutter width {diameter:.4f} mm at target depth",
        f"; Three incremental full-path passes; maximum stepdown {MAX_STEPDOWN:g} mm",
        f"; XY rapid safe Z{SAFE_Z:g}; illustrative vertical approach Z{APPROACH_Z:g}",
        f"; Spindle S{SPINDLE_RPM} was previously reported successful; physical state is unverified",
        f"; Assumed spindle startup dwell {SPINDLE_DWELL_SECONDS:g} seconds",
        "G21 G17 G90 G94 G54",
        f"G0 Z{SAFE_Z:.4f}",
        f"M3 S{SPINDLE_RPM}",
        f"G4 P{SPINDLE_DWELL_SECONDS:.3f}",
        f"; Broad sweep final tool diameter {diameter:.4f} mm; step-over {STEPOVER:.4f} mm",
    ]
    for pass_number, depth in enumerate(levels, start=1):
        lines.append(f"; PASS {pass_number}/{len(levels)}: broad paths to Z-{depth:.4f}")
        for path in paths:
            x, y = path[0]
            lines.extend((
                f"G0 Z{SAFE_Z:.4f}",
                f"G0 X{x:.4f} Y{y:.4f}",
                f"G0 Z{APPROACH_Z:.4f}",
                f"G1 Z{-depth:.4f} F{PLUNGE_FEED:.4f}",
            ))
            lines.extend(f"G1 X{x:.4f} Y{y:.4f} F{CUT_FEED:.4f}" for x, y in path[1:])
    lines.extend((f"G0 Z{SAFE_Z:.4f}", "M5", "M2"))
    return "\n".join(lines) + "\n"


def main() -> None:
    with Image.open(SOURCE) as image:
        image_size = image.size
    settings = settings_for(image_size)
    levels = depth_levels(TARGET_DEPTH, MAX_STEPDOWN)
    pass_diameters = [TIP_DIAMETER + 2 * depth * math.tan(math.radians(V_ANGLE / 2)) for depth in levels]
    if any(STEPOVER > diameter * 0.8 for diameter in pass_diameters):
        raise ValueError("Stepover exceeds 80% of a pass-depth effective diameter")

    source_region, pixel_size = raster_region(SOURCE, settings)
    keepout = Point(*HOLE_CENTER).buffer(HOLE_KEEPOUT_RADIUS, quad_segs=256)
    clipped_by_hole = source_region.intersection(keepout)
    work_region = source_region.difference(keepout)
    if work_region.is_empty:
        raise ValueError("Hanger keepout removed all engravable artwork")

    initial_paths, inset = plan_engraving(work_region, settings)
    optimized_paths = optimize_engraving_paths(initial_paths, inset, settings)
    initial_minutes = _motion_metrics(initial_paths, settings)["estimated_minutes"]
    optimized_minutes = _motion_metrics(optimized_paths, settings)["estimated_minutes"]
    paths = optimized_paths if optimized_minutes < initial_minutes else initial_paths
    optimization = {
        "enabled": True,
        "applied": paths is optimized_paths,
        "initialPathCount": len(initial_paths),
        "finalPathCount": len(paths),
        "initialEstimatedMinutes": initial_minutes,
        "finalEstimatedMinutes": min(initial_minutes, optimized_minutes),
    }

    diameter = settings.effective_diameter
    broad_sweep = swept(paths, diameter)
    broad_guard = swept(paths, diameter, conservative=True)
    if not source_region.covers(broad_guard) or not work_region.covers(broad_guard):
        raise ValueError("Quantized broad cutter sweep leaves approved black or enters hanger keepout")
    stock = box(0, 0, STOCK, STOCK)
    if not stock.buffer(0.001).covers(broad_guard):
        raise ValueError("Broad cutter sweep leaves declared stock envelope")
    omitted_work_art = work_region.difference(broad_sweep)
    total_uncovered = source_region.difference(broad_sweep)

    gcode = build_gcode(paths, diameter)
    nc_path = OUT / NC_NAME
    nc_path.write_text(gcode, encoding="ascii", newline="\n")
    program = parse_gcode(gcode, nc_path)
    validate_nonnegative_work_xy(program)
    validate_rapid_xy_clearance(program, SAFE_Z)
    if (program.bounds.minimum.z != -TARGET_DEPTH or program.bounds.maximum.z != SAFE_Z
            or program.bounds.minimum.x < -0.001 or program.bounds.minimum.y < -0.001
            or program.bounds.maximum.x > STOCK + 0.001 or program.bounds.maximum.y > STOCK + 0.001):
        raise ValueError("Parsed work bounds differ from target depth or stock envelope")

    executable = "\n".join(line for line in gcode.splitlines() if not line.lstrip().startswith(";"))
    counts = {
        "m5": len(re.findall(r"\bM\s*5\b", executable, re.IGNORECASE)),
        "m3": len(re.findall(r"\bM\s*3\b", executable, re.IGNORECASE)),
        "m6": len(re.findall(r"\bM\s*6\b", executable, re.IGNORECASE)),
        "program_end": len(re.findall(r"\bM\s*(?:2|30)\b", executable, re.IGNORECASE)),
    }
    if counts != {"m5": 1, "m3": 1, "m6": 0, "program_end": 1}:
        raise ValueError(f"Unexpected machine-control commands: {counts}")
    if executable.splitlines()[:3] != ["G21 G17 G90 G94 G54", f"G0 Z{SAFE_Z:.4f}", f"M3 S{SPINDLE_RPM}"]:
        raise ValueError("Stream-compatible start must move to safe Z before spindle start")
    if executable.splitlines()[-2:] != ["M5", "M2"] or f"G4 P{SPINDLE_DWELL_SECONDS:.3f}" not in executable:
        raise ValueError("Final M5/M2 or spindle dwell is missing")
    g1_lines = [line for line in executable.splitlines() if line.startswith("G1 ")]
    if any(f"F{PLUNGE_FEED:.4f}" not in line for line in g1_lines if re.search(r"\bZ\s*-", line)):
        raise ValueError("Unexpected plunge feed")
    if any(f"F{CUT_FEED:.4f}" not in line for line in g1_lines if re.search(r"\b[XY]\s*", line)):
        raise ValueError("Unexpected cut feed")

    preview_path = write_preview(source_region, paths, diameter)
    report = {
        "schemaVersion": 1,
        "bundle": "hawkeye-two-bit-vbit30-inner-ply-1p625mm-broad-only-review",
        "releaseStatus": "offline-review-only; not verified or authorized for cutting",
        "scope": "Broad-only V-bit engraving to nominal half-thickness. No fine stage, hanger hole or outside cut is included.",
        "depthAssumption": "Target depth 1.625 mm is half the nominal 3.25 mm sheet thickness; actual contrasting-ply boundary is unknown.",
        "source": {
            "path": "artifacts/ornaments/hawkeye/approved-artwork-reference.png",
            "sha256": sha256(SOURCE),
            "imageSizePx": list(image_size),
            "threshold": THRESHOLD,
            "pixelSizeMm": pixel_size,
            "method": "Thresholded approved source black pixels mapped proportionally to 90 mm; no redraw.",
        },
        "geometry": {
            "units": "mm",
            "stock": {"width": STOCK, "height": STOCK, "assumedThickness": STOCK_THICKNESS, "thicknessMeasured": False, "origin": "lower-left"},
            "part": {"diameter": PART_DIAMETER, "centerWorkXY": list(PART_CENTER)},
            "artwork": {"diameter": ART_DIAMETER, "placementOriginWorkXY": list(PLACEMENT)},
            "hangerKeepout": {"holeCenterWorkXY": list(HOLE_CENTER), "noEngraveRadiusMm": HOLE_KEEPOUT_RADIUS, "sourceBlackRemovedMm2": clipped_by_hole.area},
        },
        "tool": {
            "type": "assumed 30 degree included-angle V-bit with 0.1 mm flat tip",
            "includedAngleDeg": V_ANGLE,
            "tipDiameterMm": TIP_DIAMETER,
            "tipDiameterVerified": False,
            "runoutVerified": False,
            "spindleRpm": SPINDLE_RPM,
            "spindleCurrentlyVerified": False,
            "spindleStartupDwellSeconds": SPINDLE_DWELL_SECONDS,
            "dwellDurationAssumed": True,
        },
        "broadStage": {
            "targetDepthMm": TARGET_DEPTH,
            "depthPassesMm": [-depth for depth in levels],
            "maximumStepdownMm": MAX_STEPDOWN,
            "effectiveDiameterAtFinalDepthMm": diameter,
            "stepoverMm": STEPOVER,
            "stepoverWithin80PercentAtEveryPass": True,
            "pathCount": len(paths),
            "optimization": optimization,
            "fineDetailPassIncluded": False,
        },
        "coverage": {
            "availableApprovedBlackMm2": work_region.area,
            "broadSweepMm2": broad_sweep.area,
            "broadSweepInsideApprovedBlackMm2": work_region.intersection(broad_sweep).area,
            "approvedBlackOmittedMm2": omitted_work_art.area,
            "approvedBlackOmittedPercent": 100 * omitted_work_art.area / work_region.area,
            "allSourceBlackNotSweptIncludingHangerKeepoutMm2": total_uncovered.area,
            "conservativeQuantizedSweepContainedInApprovedBlack": True,
            "conservativeQuantizedSweepRespectsHangerKeepout": True,
            "note": "Fine detail is intentionally omitted; the reported omitted area is left uncut by this broad-only file.",
        },
        "motion": {
            "spindleRpm": SPINDLE_RPM,
            "spindleStartupDwellSeconds": SPINDLE_DWELL_SECONDS,
            "cutFeedMmPerMin": CUT_FEED,
            "plungeFeedMmPerMin": PLUNGE_FEED,
            "safeZMm": SAFE_Z,
            "approachZMm": APPROACH_Z,
            "depthPassesMm": [-depth for depth in levels],
            "measuredMaximumStepdownMm": max([levels[0], *(b - a for a, b in zip(levels, levels[1:]))]),
            "parserBoundsMm": {
                "minimum": [program.bounds.minimum.x, program.bounds.minimum.y, program.bounds.minimum.z],
                "maximum": [program.bounds.maximum.x, program.bounds.maximum.y, program.bounds.maximum.z],
            },
            "xyRapidsAtSafeZ": True,
            "estimatedMinutes": program.estimated_seconds / 60,
            "estimateSource": "Complete NC parsed by parse_gcode; linear distance/feed estimate with rapid feed 3000 mm/min and dwell, not observed cycle time.",
            "gcodeLineCount": len(gcode.splitlines()),
            "machineCommands": counts,
        },
        "offlineChecks": {
            "gcodeParses": True,
            "nonnegativeWorkXY": True,
            "rapidXYAtSafeZ": True,
            "parserBoundsWithinStockAndTargetDepth": True,
            "allSweepsInsideApprovedBlackAndOutsideHangerKeepout": True,
            "allSweepsInsideStock": True,
            "threeIncrementalPassesAtOrBelow0p6mm": len(levels) == 3 and max([levels[0], *(b - a for a, b in zip(levels, levels[1:]))]) <= MAX_STEPDOWN,
            "oneM3At1000RpmNoM6": True,
            "finalM5AndM2": True,
            "spindleDwellParses": True,
            "cutFeed600Plunge160": True,
            "fineDetailPassIntentionallyOmitted": True,
        },
        "unknownsBlockingProduction": [
            "actual plywood ply interface and contrast boundary",
            "measured stock thickness, flatness and exact Z0",
            "actual V-bit geometry, tip, runout and condition",
            "validated 600/160 mm/min feeds, 0.6 mm pass depth and 1.625 mm total depth",
            "fixture, workholding, spindle state and coupon result",
        ],
        "artifacts": {
            "gcode": {"path": f"artifacts/ornaments/hawkeye/two-bit/c043-runtime/v5-inner-ply-1p625mm-1000rpm/{NC_NAME}", "sha256": sha256(nc_path)},
            "preview": {"path": f"artifacts/ornaments/hawkeye/two-bit/c043-runtime/v5-inner-ply-1p625mm-1000rpm/{PREVIEW_NAME}", "sha256": sha256(preview_path)},
            "generator": {"path": "artifacts/ornaments/hawkeye/two-bit/c043-runtime/v5-inner-ply-1p625mm-1000rpm/prepare-detail-vbit30-inner-ply-1p625mm.py", "sha256": sha256(Path(__file__))},
        },
        "rebuildCommand": ".\\.venv\\Scripts\\python.exe artifacts/ornaments/hawkeye/two-bit/c043-runtime/v5-inner-ply-1p625mm-1000rpm/prepare-detail-vbit30-inner-ply-1p625mm.py",
        "verifyCommand": ".\\.venv\\Scripts\\python.exe artifacts/ornaments/hawkeye/two-bit/c043-runtime/v5-inner-ply-1p625mm-1000rpm/verify-review.py",
    }
    report_path = OUT / REPORT_NAME
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({
        "nc": str(nc_path),
        "depthPassesMm": report["broadStage"]["depthPassesMm"],
        "effectiveDiameterMm": diameter,
        "stepoverMm": STEPOVER,
        "pathCount": len(paths),
        "estimatedMinutes": report["motion"]["estimatedMinutes"],
        "availableBlackOmittedPercent": report["coverage"]["approvedBlackOmittedPercent"],
        "lineCount": report["motion"]["gcodeLineCount"],
        "machineCommands": counts,
    }, indent=2))


if __name__ == "__main__":
    main()