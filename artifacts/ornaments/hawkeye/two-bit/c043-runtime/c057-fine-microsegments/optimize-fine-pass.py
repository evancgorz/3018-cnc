"""Create an offline fine-path simplification candidate from the C-043 speed file.

This script reads artwork and NC artifacts only. It does not connect to a CNC
controller or interact with the running application.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import sys

from shapely.geometry import LineString, Point, box
from shapely.ops import unary_union
from shapely.prepared import prep

HERE = Path(__file__).resolve().parent
ROOT = Path(__file__).resolve().parents[6]
V6_DIR = HERE.parent / "v6-inner-ply-plus-fine-1000rpm"
SOURCE_NC = V6_DIR / "01-detail-stream-compatible-inner-ply-plus-fine-600-160.nc"
SPEED_NC = V6_DIR / "01-detail-speed-optimized-candidate-450-120.nc"
SPEED_REPORT = V6_DIR / "speed-optimized-candidate-report.json"
V6_REPORT = V6_DIR / "detail-report-vbit30-inner-ply-plus-fine-1000rpm.json"
NC_NAME = "01-detail-speed-fine-simplified-450-120-review-only.nc"
REPORT_NAME = "fine-microsegment-optimization-report.json"
VERIFY_NAME = "fine-microsegment-optimization-verification.json"
SIMPLIFY_TOLERANCE_MM = 0.0015
CUT_FEED = 450.0
PLUNGE_FEED = 120.0

sys.path.insert(0, str(ROOT / "src"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_generator():
    generator_path = V6_DIR / "prepare-detail-vbit30-plus-fine.py"
    spec = importlib.util.spec_from_file_location("c057_v6_generator", generator_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


def simplify_paths(paths, work_region, stock):
    """Simplify at subpixel tolerance, retaining any path that fails a full-width guard."""
    allowed = prep(work_region)
    stock_allowed = prep(stock.buffer(0.001))
    fine_diameter = 0.1 + 2 * 0.04 * math.tan(math.radians(15.0))
    guard_radius = (fine_diameter / 2) / math.cos(math.pi / 128)
    optimized = []
    changed = 0
    fallback = 0
    before_vertices = 0
    after_vertices = 0
    maximum_hausdorff_mm = 0.0

    for path in paths:
        original = tuple((round(x, 4), round(y, 4)) for x, y in path)
        line = LineString(original)
        reduced = tuple(
            (round(x, 4), round(y, 4))
            for x, y in line.simplify(SIMPLIFY_TOLERANCE_MM, preserve_topology=False).coords
        )
        if len(reduced) < 2 or reduced[0] != original[0] or reduced[-1] != original[-1]:
            reduced = original

        if reduced != original:
            guarded = LineString(reduced).buffer(guard_radius, quad_segs=32)
            if not allowed.covers(guarded) or not stock_allowed.covers(guarded):
                reduced = original
                fallback += 1

        chosen = LineString(reduced)
        if reduced != original:
            changed += 1
            maximum_hausdorff_mm = max(maximum_hausdorff_mm, line.hausdorff_distance(chosen))
        before_vertices += len(original)
        after_vertices += len(reduced)
        optimized.append(reduced)

    return optimized, {
        "pathsBefore": len(paths),
        "pathsAfter": len(optimized),
        "pathsSimplified": changed,
        "pathsKeptForFullDiameterContainment": fallback,
        "xyVerticesBefore": before_vertices,
        "xyVerticesAfter": after_vertices,
        "xyMoveSegmentsBefore": before_vertices - len(paths),
        "xyMoveSegmentsAfter": after_vertices - len(optimized),
        "xyMoveReductionPercent": 100 * (1 - (after_vertices - len(optimized)) / (before_vertices - len(paths))),
        "xyVertexReductionPercent": 100 * (1 - after_vertices / before_vertices),
        "simplificationToleranceMm": SIMPLIFY_TOLERANCE_MM,
        "maximumEmittedCenterlineHausdorffMm": maximum_hausdorff_mm,
    }


def write_candidate(speed_lines: list[str], fine_paths, fine_marker: str, safe_z: float, approach_z: float) -> str:
    fine_start = next(i for i, line in enumerate(speed_lines) if line.startswith("; FINE DETAIL:"))
    if speed_lines[-3:] != [f"G0 Z{safe_z:.4f}", "M5", "M2"]:
        raise ValueError("Speed candidate has unexpected safe final commands")
    output = speed_lines[:fine_start]
    output.append(fine_marker)
    for path in fine_paths:
        x, y = path[0]
        output.extend((
            f"G0 Z{safe_z:.4f}",
            f"G0 X{x:.4f} Y{y:.4f}",
            f"G0 Z{approach_z:.4f}",
            f"G1 Z-0.0400 F{PLUNGE_FEED:.4f}",
        ))
        output.extend(f"G1 X{x:.4f} Y{y:.4f} F{CUT_FEED:.4f}" for x, y in path[1:])
    output.extend(speed_lines[-3:])
    return "\n".join(output) + "\n"


def main() -> None:
    from ttc3018_control.gcode import (
        parse_gcode,
        validate_nonnegative_work_xy,
        validate_rapid_xy_clearance,
    )

    generator = load_generator()
    speed_report = json.loads(SPEED_REPORT.read_text(encoding="utf-8"))
    v6_report = json.loads(V6_REPORT.read_text(encoding="utf-8"))
    source_hash = sha256(SOURCE_NC)
    speed_hash = sha256(SPEED_NC)
    if speed_hash != speed_report["candidate"]["sha256"]:
        raise ValueError("Speed candidate hash differs from its report")
    if source_hash != speed_report["baseArtifacts"]["v6GcodeSha256"]:
        raise ValueError("The C-043 v6 source NC hash differs from the speed report")

    with generator.Image.open(generator.SOURCE) as image:
        image_size = image.size
    source_region, pixel_size = generator.raster_region(generator.SOURCE, generator.settings_for(image_size))
    keepout = Point(*generator.HOLE_CENTER).buffer(generator.HOLE_KEEPOUT_RADIUS, quad_segs=256)
    work_region = source_region.difference(keepout)
    stock = box(0, 0, generator.STOCK, generator.STOCK)

    source_gcode = SOURCE_NC.read_text(encoding="ascii")
    speed_gcode = SPEED_NC.read_text(encoding="ascii")
    source_paths = generator.emitted_paths_by_depth(source_gcode)
    speed_paths = generator.emitted_paths_by_depth(speed_gcode)
    original_fine = source_paths[-generator.FINE_DEPTH]
    speed_fine = speed_paths[-generator.FINE_DEPTH]
    if speed_fine != original_fine:
        raise ValueError("Speed candidate fine geometry differs from the C-043 v6 source")

    fine_settings = generator.settings_for(
        image_size,
        depth=generator.FINE_DEPTH,
        stepover=generator.FINE_STEPOVER,
        stepdown=generator.FINE_DEPTH,
    )
    fine_diameter = fine_settings.effective_diameter
    if abs(fine_diameter - v6_report["fineStage"]["effectiveDiameterMm"]) > 1e-10:
        raise ValueError("Computed fine cutter diameter differs from the v6 report")
    broad_diameter = generator.settings_for(image_size).effective_diameter

    optimized_fine, metrics = simplify_paths(speed_fine, work_region, stock)
    fine_marker = next(line for line in speed_gcode.splitlines() if line.startswith("; FINE DETAIL:"))
    output = write_candidate(
        speed_gcode.rstrip().splitlines(),
        optimized_fine,
        fine_marker,
        generator.SAFE_Z,
        generator.APPROACH_Z,
    )
    candidate_path = HERE / NC_NAME
    candidate_path.write_text(output, encoding="ascii", newline="\n")

    program = parse_gcode(output, candidate_path)
    validate_nonnegative_work_xy(program)
    validate_rapid_xy_clearance(program, generator.SAFE_Z)
    candidate_paths = generator.emitted_paths_by_depth(output)
    expected_depths = [-1.625, -1.2, -0.6, -0.04]
    if sorted(candidate_paths) != expected_depths:
        raise AssertionError(f"Unexpected emitted cut depths: {sorted(candidate_paths)}")
    for depth in (-0.6, -1.2, -1.625):
        if candidate_paths[depth] != speed_paths[depth]:
            raise AssertionError(f"Broad paths changed at depth {depth}")
    if candidate_paths[-0.04] != optimized_fine:
        raise AssertionError("Emitted fine centerlines differ from the simplified paths")
    if program.bounds.minimum.z != -generator.TARGET_DEPTH or program.bounds.maximum.z != generator.SAFE_Z:
        raise AssertionError("Parsed depth or safe-Z bounds changed")
    if program.bounds.minimum.x < 0 or program.bounds.minimum.y < 0 or program.bounds.maximum.x > generator.STOCK or program.bounds.maximum.y > generator.STOCK:
        raise AssertionError("Parsed work bounds leave stock")

    executable = "\n".join(line.split(";", 1)[0] for line in output.splitlines())
    counts = {
        "m5": len(re.findall(r"\bM\s*5\b", executable, re.IGNORECASE)),
        "m3": len(re.findall(r"\bM\s*3\b", executable, re.IGNORECASE)),
        "m4": len(re.findall(r"\bM\s*4\b", executable, re.IGNORECASE)),
        "m6": len(re.findall(r"\bM\s*6\b", executable, re.IGNORECASE)),
        "program_end": len(re.findall(r"\bM\s*(?:2|30)\b", executable, re.IGNORECASE)),
    }
    if counts != {"m5": 1, "m3": 1, "m4": 0, "m6": 0, "program_end": 1}:
        raise AssertionError(f"Unexpected machine-control commands: {counts}")
    cut_lines = [line for line in executable.splitlines() if line.startswith("G1 ") and re.search(r"\b[XY]\s*", line)]
    plunge_lines = [line for line in executable.splitlines() if line.startswith("G1 Z-")]
    if not cut_lines or any(f"F{CUT_FEED:.4f}" not in line for line in cut_lines):
        raise AssertionError("One or more XY cutting moves do not use F450")
    if not plunge_lines or any(f"F{PLUNGE_FEED:.4f}" not in line for line in plunge_lines):
        raise AssertionError("One or more Z plunge moves do not use F120")

    # Buffer at half of the stated full effective diameter; this conservative
    # radius checks the cutter disk against black artwork and the hanger reserve.
    fine_radius = fine_diameter / 2
    guard_radius = fine_radius / math.cos(math.pi / 128)
    allowed = prep(work_region)
    stock_allowed = prep(stock.buffer(0.001))
    for index, path in enumerate(candidate_paths[-0.04]):
        guarded_path = LineString(path).buffer(guard_radius, quad_segs=32)
        if not allowed.covers(guarded_path):
            raise AssertionError(f"Full-diameter conservative fine sweep leaves artwork or enters keepout at path {index}")
        if not stock_allowed.covers(guarded_path):
            raise AssertionError(f"Full-diameter conservative fine sweep leaves stock at path {index}")

    baseline_fine_sweep = generator.swept(speed_fine, fine_diameter)
    optimized_fine_sweep = generator.swept(candidate_paths[-0.04], fine_diameter)
    fine_lost = baseline_fine_sweep.difference(optimized_fine_sweep).area
    fine_added = optimized_fine_sweep.difference(baseline_fine_sweep).area
    fine_symmetric_difference = fine_lost + fine_added
    broad_sweep = generator.swept(candidate_paths[-generator.TARGET_DEPTH], broad_diameter)
    baseline_combined = unary_union((broad_sweep, baseline_fine_sweep))
    optimized_combined = unary_union((broad_sweep, optimized_fine_sweep))
    baseline_omitted = work_region.difference(baseline_combined).area
    optimized_omitted = work_region.difference(optimized_combined).area
    omission_delta = optimized_omitted - baseline_omitted
    fine_difference_percent = 100 * fine_symmetric_difference / baseline_fine_sweep.area

    # Tight acceptance limits are relative to the exact emitted full-diameter sweep.
    if fine_symmetric_difference > 0.75:
        raise AssertionError(f"Fine sweep symmetric difference is too large: {fine_symmetric_difference:.6f} mm2")
    if abs(omission_delta) > 0.10:
        raise AssertionError(f"Combined approved-black coverage changed by {omission_delta:.6f} mm2")
    if metrics["xyMoveReductionPercent"] < 30:
        raise AssertionError("The candidate did not materially reduce XY move count")

    report = {
        "schemaVersion": 1,
        "releaseStatus": "offline-review-only; not verified or authorized for cutting",
        "source": {
            "artPath": str(generator.SOURCE.relative_to(ROOT)),
            "artSha256": sha256(generator.SOURCE),
            "v6NcPath": str(SOURCE_NC.relative_to(ROOT)),
            "v6NcSha256": source_hash,
            "speedCandidatePath": str(SPEED_NC.relative_to(ROOT)),
            "speedCandidateSha256": speed_hash,
            "pixelSizeMm": pixel_size,
        },
        "candidate": {"path": str(candidate_path.relative_to(ROOT)), "sha256": sha256(candidate_path)},
        "generator": {"path": str(Path(__file__).resolve().relative_to(ROOT)), "sha256": sha256(Path(__file__))},
        "geometry": {
            **metrics,
            "fineDepthMm": -generator.FINE_DEPTH,
            "fineEffectiveDiameterMm": fine_diameter,
            "fineBufferRadiusMm": fine_radius,
            "fullDiameterConservativeGuardRadiusMm": guard_radius,
            "fineSweepBaselineMm2": baseline_fine_sweep.area,
            "fineSweepCandidateMm2": optimized_fine_sweep.area,
            "fineSweepLostFromBaselineMm2": fine_lost,
            "fineSweepAddedVsBaselineMm2": fine_added,
            "fineSweepSymmetricDifferenceMm2": fine_symmetric_difference,
            "fineSweepSymmetricDifferencePercent": fine_difference_percent,
            "combinedApprovedBlackOmittedBaselineMm2": baseline_omitted,
            "combinedApprovedBlackOmittedCandidateMm2": optimized_omitted,
            "combinedApprovedBlackOmissionChangeMm2": omission_delta,
            "fullDiameterConservativeSweepInsideApprovedArtworkAndOutsideKeepout": True,
            "fullDiameterConservativeSweepInsideStock": True,
        },
        "motion": {
            "cutFeedMmPerMin": CUT_FEED,
            "plungeFeedMmPerMin": PLUNGE_FEED,
            "spindleRpm": 1000,
            "depthPassesMm": [-0.6, -1.2, -1.625],
            "finePassDepthMm": -0.04,
            "cuttingXyMoveCount": len(cut_lines),
            "lineCount": len(output.splitlines()),
            "estimatedMinutes": program.estimated_seconds / 60,
            "speedCandidateEstimatedMinutes": speed_report["motion"]["estimatedMinutes"],
            "parserBoundsMm": {
                "minimum": [program.bounds.minimum.x, program.bounds.minimum.y, program.bounds.minimum.z],
                "maximum": [program.bounds.maximum.x, program.bounds.maximum.y, program.bounds.maximum.z],
            },
            "machineCommands": counts,
        },
        "offlineChecks": {
            "v6AndSpeedCandidateHashesMatchReports": True,
            "speedCandidateFineGeometryMatchesV6": True,
            "broadGeometryUnchangedAtEveryDepth": True,
            "gcodeParses": True,
            "nonnegativeWorkXY": True,
            "rapidXYAtSafeZ": True,
            "fullDiameterFineSweepContainedInArtworkOutsideKeepoutAndStock": True,
            "fullDiameterSweepComparedByExactSymmetricDifference": True,
            "combinedApprovedBlackOmissionChangeWithin0p10Mm2": True,
            "cutFeed450Plunge120": True,
            "spindleUnchangedAt1000Rpm": True,
            "singleM3FinalM5M2NoM4M6": True,
        },
    }
    (HERE / REPORT_NAME).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    verification = {
        "result": "passed",
        "candidateSha256": report["candidate"]["sha256"],
        "xyMoveSegmentsBeforeAfter": [metrics["xyMoveSegmentsBefore"], metrics["xyMoveSegmentsAfter"]],
        "xyMoveReductionPercent": round(metrics["xyMoveReductionPercent"], 4),
        "fullFineEffectiveDiameterMm": fine_diameter,
        "fineSweepLostAddedMm2": [fine_lost, fine_added],
        "fineSweepSymmetricDifferenceMm2": fine_symmetric_difference,
        "combinedApprovedBlackOmissionChangeMm2": omission_delta,
        "estimatedMinutes": program.estimated_seconds / 60,
        "offlineChecks": report["offlineChecks"],
    }
    (HERE / VERIFY_NAME).write_text(json.dumps(verification, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(verification, indent=2))


if __name__ == "__main__":
    main()
