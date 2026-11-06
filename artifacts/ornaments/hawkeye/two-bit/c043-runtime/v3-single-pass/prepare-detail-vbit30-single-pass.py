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
from PIL import Image  # noqa: E402


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

V_ANGLE = 30.0
TIP_DIAMETER = 0.1
COARSE_DEPTH = 0.45
COARSE_STEPOVER = 0.27
COARSE_STEPDOWN = 0.45
FINE_DEPTH = 0.04
FINE_STEPOVER = 0.097
FINE_STEPDOWN = 0.04
FINE_RESIDUAL_GROWTH = 0.08
MIN_RESIDUAL_COMPONENT_AREA = 0.1
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
        '<polyline points="' + " ".join(f"{x:.4f},{y:.4f}" for x, y in path)
        + f'" stroke="{color}" stroke-width="{width:.5f}"/>'
        for path in paths
    )


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
<g fill="none" stroke="#d28b16" stroke-linecap="round" stroke-linejoin="round">
{polyline_elements(fine_paths, '#d28b16', fine_diameter)}
</g>
<circle cx="{HOLE_CENTER[0]}" cy="{HOLE_CENTER[1]}" r="{HOLE_KEEPOUT_RADIUS}" fill="#fff" stroke="#bf3535" stroke-width="0.22" stroke-dasharray="0.7 0.45"/>
<circle cx="{HOLE_CENTER[0]}" cy="{HOLE_CENTER[1]}" r="{HOLE_RADIUS}" fill="none" stroke="#bf3535" stroke-width="0.2"/>
</g>
<g font-family="sans-serif" fill="#29333d">
<text x="2" y="114" font-size="1.9">Gray: approved thresholded artwork • Blue: broad fill, Z −{COARSE_DEPTH:g}, width {coarse_diameter:.3f} mm</text>
<text x="2" y="117" font-size="1.9">Amber: residual detail, Z −{FINE_DEPTH:g}, width {fine_diameter:.3f} mm • Red: 3 mm hanger keepout</text>
<text x="2" y="120" font-size="1.75">110 × 110 stock • 100 mm circle centered at X55 Y55 • shared XY origin lower-left</text>
<text x="2" y="123" font-size="1.55">Emitted cutter sweeps; dimensions and source hash are in detail-report-vbit30-single-pass.json</text>
</g>
</svg>'''
    path = OUT / "detail-preview-vbit30-single-pass.svg"
    path.write_text(svg, encoding="utf-8")
    return path


def program_lines(coarse_paths, fine_paths) -> str:
    lines = [
        "; OFFLINE REVIEW DRAFT ONLY - not verified or authorized for cutting",
        "; Source is approved-artwork-reference.png; black threshold cells only, no redraw",
        "; 30 degree included-angle V-bit; assumed 0.1 mm flat tip; actual tool/runout are unverified",
        "; Shallow engraving only; hanger hole and outer cutout are in separate 02 file",
        "; Work XY: 110 x 110 stock, lower-left origin; 100 mm disc centered X55 Y55",
        f"; Art resized proportionally to 90 mm; hanger no-engrave keepout radius {HOLE_KEEPOUT_RADIUS:g} mm",
        f"; Broad stage reaches Z-{COARSE_DEPTH:g} in <= {COARSE_STEPDOWN:g} mm passes; floor is scalloped",
        f"; Fine stage reaches Z-{FINE_DEPTH:g} only in buffered residual art; no full-area fine raster",
        f"; XY rapid safe Z{SAFE_Z:g}; illustrative vertical approach Z{APPROACH_Z:g}",
        "; Feeds are assumed; spindle startup intentionally omitted; no automatic tool change",
        "G21 G17 G90 G94 G54",
        "M5",
        f"G0 Z{SAFE_Z:.4f}",
        f"; STAGE 1: broad filled black regions, V-bit effective diameter at final depth {settings_for((1, 1), depth=COARSE_DEPTH, stepover=COARSE_STEPOVER, stepdown=COARSE_STEPDOWN).effective_diameter:.4f} mm",
    ]
    for depth in (COARSE_DEPTH,):
        lines.append(f"; Broad pass to Z-{depth:.4f}")
        for path in coarse_paths:
            x, y = path[0]
            lines.extend((
                f"G0 Z{SAFE_Z:.4f}", f"G0 X{x:.4f} Y{y:.4f}",
                f"G0 Z{APPROACH_Z:.4f}", f"G1 Z{-depth:.4f} F{PLUNGE_FEED:.4f}",
            ))
            lines.extend(f"G1 X{x:.4f} Y{y:.4f} F{CUT_FEED:.4f}" for x, y in path[1:])
    lines.append(f"; STAGE 2: residual-only fine detail, V-bit effective diameter {settings_for((1, 1), depth=FINE_DEPTH, stepover=FINE_STEPOVER, stepdown=FINE_STEPDOWN).effective_diameter:.4f} mm")
    lines.append(f"; Fine pass to Z-{FINE_DEPTH:.4f}")
    for path in fine_paths:
        x, y = path[0]
        lines.extend((
            f"G0 Z{SAFE_Z:.4f}", f"G0 X{x:.4f} Y{y:.4f}",
            f"G0 Z{APPROACH_Z:.4f}", f"G1 Z{-FINE_DEPTH:.4f} F{PLUNGE_FEED:.4f}",
        ))
        lines.extend(f"G1 X{x:.4f} Y{y:.4f} F{CUT_FEED:.4f}" for x, y in path[1:])
    lines.extend((f"G0 Z{SAFE_Z:.4f}", "M5", "M2"))
    return "\n".join(lines) + "\n"


def main() -> None:
    with Image.open(SOURCE) as image:
        image_size = image.size
    coarse = settings_for(image_size, depth=COARSE_DEPTH, stepover=COARSE_STEPOVER, stepdown=COARSE_STEPDOWN)
    fine = settings_for(image_size, depth=FINE_DEPTH, stepover=FINE_STEPOVER, stepdown=FINE_STEPDOWN)
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
    retained = [part for part in residual_components if part.area >= MIN_RESIDUAL_COMPONENT_AREA]
    if not retained:
        raise ValueError("No residual artwork remains for the required fine-detail stage")
    retained_residual = unary_union(retained)
    # Slightly widen residual centerline targets, then clip back to original
    # black pixels. plan_engraving applies its normal full-cutter-radius erosion.
    fine_target = retained_residual.buffer(FINE_RESIDUAL_GROWTH, join_style="round").intersection(work_region)
    if fine_target.is_empty:
        raise ValueError("Buffered residual detail target is empty")
    fine_paths, fine_optimization = plan_stage(fine_target, fine)
    fine_sweep = swept(fine_paths, fine.effective_diameter)
    fine_guard = swept(fine_paths, fine.effective_diameter, conservative=True)
    if not source_region.covers(fine_guard) or not work_region.covers(fine_guard):
        raise ValueError("Fine-stage quantized cutter footprint leaves approved black or enters hanger keepout")

    combined_sweep = unary_union((coarse_sweep, fine_sweep))
    omitted_work_art = work_region.difference(combined_sweep)
    total_uncovered = source_region.difference(combined_sweep)
    fine_target_uncovered = fine_target.difference(fine_sweep)

    gcode = program_lines(coarse_paths, fine_paths)
    nc_path = OUT / "01-detail-review-vbit30-single-pass.nc"
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
        coarse.effective_diameter, fine.effective_diameter, sha256(SOURCE),
    )
    report = {
        "schemaVersion": 1,
        "bundle": "hawkeye-two-bit-vbit30-single-pass-detail-review",
        "releaseStatus": "offline-review-only; not verified or authorized for cutting",
        "rebuildCommand": ".\\.venv\\Scripts\\python.exe artifacts/ornaments/hawkeye/two-bit/c043-runtime/v3-single-pass/prepare-detail-vbit30-single-pass.py",
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
        "tool": {"type": "assumed 30 degree included-angle V-bit with 0.1 mm flat tip", "includedAngleDeg": V_ANGLE, "tipDiameterMm": TIP_DIAMETER, "tipDiameterVerified": False, "runoutVerified": False, "spindleStartupIncluded": False, "automaticToolchangeIncluded": False},
        "stages": [
            {"order": 1, "name": "broad filled black regions", "sourceTarget": "approved black regions reachable at max depth", "maximumDepthMm": COARSE_DEPTH, "depthPassesMm": [-COARSE_DEPTH], "maximumStepdownMm": COARSE_STEPDOWN, "stepoverMm": COARSE_STEPOVER, "effectiveDiameterAtMaxDepthMm": coarse.effective_diameter, "pathCount": len(coarse_paths), "optimization": coarse_optimization, "floor": "V-shaped and scalloped; not a flat-bottom pocket"},
            {"order": 2, "name": "residual-only fine detail", "sourceTarget": "coarse-sweep residual components >= 0.1 mm2, buffered 0.08 mm and clipped to approved black pixels", "maximumDepthMm": FINE_DEPTH, "depthPassesMm": [-FINE_DEPTH], "maximumStepdownMm": FINE_STEPDOWN, "stepoverMm": FINE_STEPOVER, "effectiveDiameterAtMaxDepthMm": fine.effective_diameter, "pathCount": len(fine_paths), "optimization": fine_optimization, "normalCutterRadiusErosionApplied": True},
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
            "residualComponentsRetainedForFinePlanning": len(retained),
            "fineTargetAfterBufferAndSourceClipMm2": fine_target.area,
            "fineActualSweepAreaMm2": fine_sweep.area,
            "fineSweepInsideAvailableBlackMm2": work_region.intersection(fine_sweep).area,
            "fineTargetNotCoveredByEmittedFineSweepMm2": fine_target_uncovered.area,
            "combinedSweepInsideAvailableBlackMm2": work_region.intersection(combined_sweep).area,
            "availableSourceBlackOmittedByBothStagesMm2": omitted_work_art.area,
            "availableSourceBlackOmittedPercent": 100 * omitted_work_art.area / work_region.area,
            "allSourceBlackNotSweptIncludingHangerKeepoutMm2": total_uncovered.area,
            "fineSweepOverlapWithBroadSweepMm2": fine_sweep.intersection(coarse_sweep).area,
            "conservativeQuantizedSweepContainedInOriginalBlack": True,
            "conservativeQuantizedSweepRespectsHangerKeepout": True,
            "coarseBufferMethod": "LineString cutter-radius sweep with 32 quadrant segments; containment verified using the planner's radius/cos(pi/128) envelope. The planner adds its 0.0002 mm inset guard before 0.0001 mm output quantization.",
            "fineResidualMethod": "Subtract broad-stage emitted sweep from thresholded source black; report and drop residual components under 0.1 mm2; buffer retained residual by 0.08 mm, clip to original black, then apply normal fine-cutter erosion and path verification.",
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
            "single 0.45 mm broad-stage stepdown is an unverified cut-load assumption",
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
        },
        "artifacts": {
            "source": {"path": "artifacts/ornaments/hawkeye/two-bit/c043-runtime/v3-single-pass/prepare-detail-vbit30-single-pass.py", "sha256": sha256(Path(__file__))},
            "gcode": {"path": "artifacts/ornaments/hawkeye/two-bit/c043-runtime/v3-single-pass/01-detail-review-vbit30-single-pass.nc", "sha256": sha256(nc_path)},
            "preview": {"path": "artifacts/ornaments/hawkeye/two-bit/c043-runtime/v3-single-pass/detail-preview-vbit30-single-pass.svg", "sha256": sha256(preview_path)},
        },
    }
    (OUT / "detail-report-vbit30-single-pass.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
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
