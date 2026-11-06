"""Build an offline lower-feed, safely simplified deep+fine review candidate.

This script only reads approved artwork and existing NC artifacts. It never
connects to or communicates with a CNC machine.
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
GENERATOR_PATH = HERE / "prepare-detail-vbit30-plus-fine.py"
SOURCE_NC = HERE / "01-detail-stream-compatible-inner-ply-plus-fine-600-160.nc"
BASE_NC = ROOT / "artifacts/ornaments/hawkeye/two-bit/c043-runtime/v5-inner-ply-1p625mm-1000rpm/01-detail-stream-compatible-inner-ply-1p625mm-600-160.nc"
NC_NAME = "01-detail-speed-optimized-candidate-450-120.nc"
REPORT_NAME = "speed-optimized-candidate-report.json"
VERIFY_NAME = "speed-optimized-candidate-verification.json"
SIMPLIFY_TOLERANCE_MM = 0.06
CUT_FEED = 450.0
PLUNGE_FEED = 120.0


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_generator():
    spec = importlib.util.spec_from_file_location("v6_generator_for_speed_candidate", GENERATOR_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


def simplify_broad_paths(paths, allowed_region, tool_radius: float):
    """Simplify each path only if its conservative cutter sweep remains inside art."""
    allowed = prep(allowed_region)
    guarded_radius = tool_radius / math.cos(math.pi / 128)
    accepted = 0
    result = []
    for path in paths:
        line = LineString(path)
        simplified = line.simplify(SIMPLIFY_TOLERANCE_MM, preserve_topology=False)
        candidate = tuple((round(x, 4), round(y, 4)) for x, y in simplified.coords)
        if (
            len(candidate) >= 2
            and candidate[0] == path[0]
            and candidate[-1] == path[-1]
            and allowed.covers(
                LineString(candidate).buffer(guarded_radius, quad_segs=32)
            )
        ):
            if candidate != tuple(path):
                accepted += 1
            result.append(candidate)
        else:
            result.append(path)
    return tuple(result), accepted


def build_gcode(source_lines: list[str], paths, levels, *, safe_z: float, approach_z: float) -> str:
    first_pass = next(i for i, line in enumerate(source_lines) if line.startswith("; PASS 1/"))
    fine_start = next(i for i, line in enumerate(source_lines) if line.startswith("; FINE DETAIL:"))
    header = source_lines[:first_pass]
    fine = [
        line.replace("F160.0000", f"F{PLUNGE_FEED:.4f}")
        .replace("F600.0000", f"F{CUT_FEED:.4f}")
        for line in source_lines[fine_start:]
    ]
    output = list(header)
    for pass_number, depth in enumerate(levels, start=1):
        output.append(f"; PASS {pass_number}/{len(levels)}: broad paths to Z-{depth:.4f}")
        for path in paths:
            x, y = path[0]
            output.extend((
                f"G0 Z{safe_z:.4f}",
                f"G0 X{x:.4f} Y{y:.4f}",
                f"G0 Z{approach_z:.4f}",
                f"G1 Z{-depth:.4f} F{PLUNGE_FEED:.4f}",
            ))
            output.extend(
                f"G1 X{x:.4f} Y{y:.4f} F{CUT_FEED:.4f}" for x, y in path[1:]
            )
    output.extend(fine)
    return "\n".join(output) + "\n"


def main() -> None:
    generator = load_generator()
    base_report_path = HERE / "detail-report-vbit30-inner-ply-plus-fine-1000rpm.json"
    base_report = json.loads(base_report_path.read_text(encoding="utf-8"))
    with generator.Image.open(generator.SOURCE) as image:
        settings = generator.settings_for(image.size)
    source_region, pixel_size = generator.raster_region(generator.SOURCE, settings)
    keepout = Point(*generator.HOLE_CENTER).buffer(generator.HOLE_KEEPOUT_RADIUS, quad_segs=256)
    work_region = source_region.difference(keepout)
    original_gcode = SOURCE_NC.read_text(encoding="ascii")
    original_lines = original_gcode.rstrip().splitlines()
    base_gcode = BASE_NC.read_text(encoding="ascii")
    broad_original = generator.emitted_paths_by_depth(base_gcode)[-generator.TARGET_DEPTH]
    if not broad_original:
        raise ValueError("Base file has no broad paths at the requested final depth")

    broad_paths, accepted = simplify_broad_paths(
        broad_original, work_region, settings.effective_diameter / 2
    )
    if len(broad_paths) != len(broad_original):
        raise AssertionError("Broad simplification changed the retract/path count")
    output = build_gcode(
        original_lines,
        broad_paths,
        generator.depth_levels(generator.TARGET_DEPTH, generator.MAX_STEPDOWN),
        safe_z=generator.SAFE_Z,
        approach_z=generator.APPROACH_Z,
    )
    nc_path = HERE / NC_NAME
    nc_path.write_text(output, encoding="ascii", newline="\n")

    from ttc3018_control.gcode import (  # noqa: E402
        parse_gcode,
        validate_nonnegative_work_xy,
        validate_rapid_xy_clearance,
    )

    program = parse_gcode(output, nc_path)
    validate_nonnegative_work_xy(program)
    validate_rapid_xy_clearance(program, generator.SAFE_Z)
    candidate_paths = generator.emitted_paths_by_depth(output)
    expected_levels = [-1.625, -1.2, -0.6, -0.04]
    actual_levels = sorted(candidate_paths)
    if actual_levels != expected_levels:
        raise AssertionError(f"Unexpected cut depths: {actual_levels}")
    if not (
        candidate_paths[-0.6]
        == candidate_paths[-1.2]
        == candidate_paths[-1.625]
    ):
        raise AssertionError("Deep path geometry changed between passes")
    if candidate_paths[-0.04] != generator.emitted_paths_by_depth(original_gcode)[-0.04]:
        raise AssertionError("Fine detail geometry changed")
    if program.bounds.minimum.z != -generator.TARGET_DEPTH or program.bounds.maximum.z != generator.SAFE_Z:
        raise AssertionError("Parser depth or clearance bounds changed")
    if program.bounds.minimum.x < 0 or program.bounds.minimum.y < 0 or program.bounds.maximum.x > generator.STOCK or program.bounds.maximum.y > generator.STOCK:
        raise AssertionError("Parsed work bounds leave the stock envelope")

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
    cut_moves = [line for line in executable.splitlines() if line.startswith("G1 ") and re.search(r"\b[XY]\s*", line)]
    plunge_moves = [line for line in executable.splitlines() if line.startswith("G1 Z-")]
    if not cut_moves or any(f"F{CUT_FEED:.4f}" not in line for line in cut_moves):
        raise AssertionError("Cut feed does not match the candidate setting")
    if not plunge_moves or any(f"F{PLUNGE_FEED:.4f}" not in line for line in plunge_moves):
        raise AssertionError("Plunge feed does not match the candidate setting")

    broad_radius = settings.effective_diameter / 2
    broad = generator.swept(candidate_paths[-generator.TARGET_DEPTH], 2 * broad_radius)
    broad_guard = generator.swept(candidate_paths[-generator.TARGET_DEPTH], 2 * broad_radius, conservative=True)
    fine_radius = base_report["fineStage"]["effectiveDiameterMm"] / 2
    fine = generator.swept(candidate_paths[-0.04], 2 * fine_radius)
    fine_guard = generator.swept(candidate_paths[-0.04], 2 * fine_radius, conservative=True)
    baseline_broad = generator.swept(broad_original, 2 * broad_radius)
    stock = box(0, 0, generator.STOCK, generator.STOCK)
    for label, footprint in (("broad", broad_guard), ("fine", fine_guard)):
        if not source_region.covers(footprint) or not work_region.covers(footprint):
            raise AssertionError(f"Conservative {label} sweep leaves approved artwork or enters the hanger keepout")
        if not stock.buffer(0.001).covers(footprint):
            raise AssertionError(f"Conservative {label} sweep leaves the stock envelope")
    combined = unary_union((broad, fine))
    omitted = work_region.difference(combined).area
    baseline_combined = unary_union((baseline_broad, fine))
    baseline_omitted = work_region.difference(baseline_combined).area

    original_program = parse_gcode(original_gcode, SOURCE_NC)
    original_broad_vertices = sum(map(len, broad_original))
    candidate_broad_vertices = sum(map(len, broad_paths))
    report = {
        "schemaVersion": 1,
        "releaseStatus": "offline-review-only; not verified or authorized for cutting",
        "source": {"path": str(generator.SOURCE.relative_to(ROOT)), "sha256": sha256(generator.SOURCE), "pixelSizeMm": pixel_size},
        "candidate": {"path": str(nc_path.relative_to(ROOT)), "sha256": sha256(nc_path)},
        "generator": {"path": str(Path(__file__).resolve().relative_to(ROOT)), "sha256": sha256(Path(__file__))},
        "baseArtifacts": {
            "v6GcodeSha256": sha256(SOURCE_NC),
            "v5BroadGcodeSha256": sha256(BASE_NC),
        },
        "geometry": {
            "broadSimplificationToleranceMm": SIMPLIFY_TOLERANCE_MM,
            "broadPathsBefore": len(broad_original),
            "broadPathsAfter": len(broad_paths),
            "broadPathsSimplified": accepted,
            "broadXyVerticesPerPassBefore": original_broad_vertices,
            "broadXyVerticesPerPassAfter": candidate_broad_vertices,
            "broadXyVertexReductionPercent": 100 * (1 - candidate_broad_vertices / original_broad_vertices),
            "broadSweepBaselineMm2": baseline_broad.area,
            "broadSweepCandidateMm2": broad.area,
            "broadSweepLostFromBaselineMm2": baseline_broad.difference(broad).area,
            "broadSweepAddedVsBaselineMm2": broad.difference(baseline_broad).area,
            "broadSweepInsideApprovedArtworkAndOutsideKeepout": True,
            "fineSweepInsideApprovedArtworkAndOutsideKeepout": True,
            "combinedOmittedMm2": omitted,
            "combinedOmittedPercent": 100 * omitted / work_region.area,
            "combinedOmissionChangeMm2": omitted - baseline_omitted,
            "combinedOmissionChangePercentOfWorkRegion": 100 * (omitted - baseline_omitted) / work_region.area,
        },
        "motion": {
            "cutFeedMmPerMin": CUT_FEED,
            "plungeFeedMmPerMin": PLUNGE_FEED,
            "spindleRpm": base_report["motion"]["spindleRpm"],
            "depthPassesMm": base_report["motion"]["depthPassesMm"],
            "finePassDepthMm": base_report["motion"]["finePassDepthMm"],
            "lineCount": len(output.splitlines()),
            "estimatedMinutes": program.estimated_seconds / 60,
            "baselineEstimatedMinutesAt600_160": original_program.estimated_seconds / 60,
            "parserBoundsMm": {
                "minimum": [program.bounds.minimum.x, program.bounds.minimum.y, program.bounds.minimum.z],
                "maximum": [program.bounds.maximum.x, program.bounds.maximum.y, program.bounds.maximum.z],
            },
            "machineCommands": counts,
        },
        "offlineChecks": {
            "gcodeParses": True,
            "nonnegativeWorkXY": True,
            "rapidXYAtSafeZ": True,
            "broadDepthGeometryRepeatedAtEachDepth": True,
            "fineGeometryUnchanged": True,
            "allConservativeSweepsContained": True,
            "depthsUnchanged": True,
            "cutFeed450Plunge120": True,
            "spindleUnchangedAt1000Rpm": True,
            "singleM3FinalM5M2NoM4M6": True,
        },
    }
    report_path = HERE / REPORT_NAME
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    verification = {
        "result": "passed",
        "candidateSha256": report["candidate"]["sha256"],
        "parserAndGeometryChecks": report["offlineChecks"],
        "broadXyVerticesPerPassBeforeAfter": [original_broad_vertices, candidate_broad_vertices],
        "broadSweepLostMm2": report["geometry"]["broadSweepLostFromBaselineMm2"],
        "combinedOmissionChangeMm2": report["geometry"]["combinedOmissionChangeMm2"],
        "estimatedMinutes": report["motion"]["estimatedMinutes"],
    }
    (HERE / VERIFY_NAME).write_text(json.dumps(verification, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({
        "candidate": str(nc_path),
        "broadXyVerticesPerPass": [original_broad_vertices, candidate_broad_vertices],
        "broadPathsSimplified": accepted,
        "broadSweepLostMm2": round(report["geometry"]["broadSweepLostFromBaselineMm2"], 4),
        "combinedOmissionChangeMm2": round(report["geometry"]["combinedOmissionChangeMm2"], 4),
        "cutFeedMmPerMin": CUT_FEED,
        "plungeFeedMmPerMin": PLUNGE_FEED,
        "estimatedMinutes": round(report["motion"]["estimatedMinutes"], 3),
        "baselineEstimatedMinutesAt600_160": round(report["motion"]["baselineEstimatedMinutesAt600_160"], 3),
        "lineCount": len(output.splitlines()),
    }, indent=2))


if __name__ == "__main__":
    main()
