"""Generate offline broad-only runtime candidates for the Hawkeye engraving.

This script removes the shallow fine-residual operation, then prepares two
guarded chord-tolerance variants for the existing deep broad passes. It never
connects to a machine. The output is review-only and explicitly trades artwork
coverage for fewer controller commands.
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
ROOT = Path(__file__).resolve().parents[5]
SOURCE_DIR = ROOT / "artifacts" / "ornaments" / "hawkeye" / "two-bit" / "c069-flow"
SOURCE_NC = SOURCE_DIR / "01-detail-c069-flow-675-120-review-only.nc"
REPORT = HERE / "c084-runtime-report.json"
SETTINGS = HERE / "c084-settings.json"
PREVIEW_008 = HERE / "c084-broad-only-tolerance-008.svg"
PREVIEW_050 = HERE / "c084-broad-only-tolerance-050.svg"

# These telemetry samples bracketed the prior live continuation's command rate.
# The rate is accepted-command throughput, not a calibrated physical ETA.
OBSERVED_ACCEPTED_COMMANDS_PER_MINUTE = (3310 / 31.4, 7626 / 68.8)
RUNTIME_PROFILE_KEY = "cnc3018-stock-spindle-vbit30-0.1-plywood3.25-cut675-plunge120-s1000"
ASPIRATIONAL_RUNTIME_MINUTES = 45.0


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def geometry_path(geometry) -> str:
    polygons = [geometry] if geometry.geom_type == "Polygon" else list(geometry.geoms)
    chunks = []
    for polygon in polygons:
        for ring in (polygon.exterior, *polygon.interiors):
            coordinates = list(ring.coords)
            chunks.append(
                "M " + " L ".join(f"{x:.4f} {y:.4f}" for x, y in coordinates) + " Z"
            )
    return " ".join(chunks)


def write_preview(path: Path, art, cut_sweep, residual, *, tolerance: float) -> None:
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="110mm" height="110mm" viewBox="0 0 110 110">
<title>C-084 broad-only cutter sweep, chord tolerance {tolerance:.2f} mm</title>
<desc>Physical scale 110 mm stock. Dark gray is available approved artwork; blue is broad-pass V-bit sweep; amber is artwork left uncut by the broad-only candidate; red circle is the hanger keepout.</desc>
<rect width="110" height="110" fill="#fff"/>
<g transform="translate(0 110) scale(1 -1)">
<path d="{geometry_path(art)}" fill="#303640" fill-rule="evenodd"/>
<path d="{geometry_path(residual)}" fill="#E5A02E" fill-rule="evenodd" opacity="0.95"/>
<path d="{geometry_path(cut_sweep)}" fill="#4E8CF7" fill-rule="evenodd" opacity="0.95"/>
<circle cx="55" cy="100" r="3" fill="none" stroke="#D84A4A" stroke-width="0.15"/>
</g>
<text x="2" y="4" font-size="1.8">C-084 review only · broad-only · {tolerance:.2f} mm chord tolerance</text>
<text x="2" y="108" font-size="1.8">Blue: emitted sweep · amber: omitted artwork · scale: 110 mm</text>
</svg>'''
    path.write_text(svg, encoding="utf-8", newline="\n")


def max_economic_link_mm(cut_feed: float, plunge_feed: float, depth: float,
                         safe_z: float, approach_z: float, rapid_feed: float = 3000.0) -> float:
    """Distance below which a safe stay-down link beats retract/rapid/plunge nominally."""
    overhead = (safe_z - depth + safe_z - approach_z) / rapid_feed
    overhead += (approach_z + depth) / plunge_feed
    extra_cut_per_mm = 1 / cut_feed - 1 / rapid_feed
    return overhead / extra_cut_per_mm if extra_cut_per_mm > 0 else 0.0


def link_safe_paths(paths, allowed_art, diameter: float, max_link: float):
    """Link short endpoint pairs only when the complete cutter footprint is safe."""
    allowed = prep(allowed_art)
    radius = diameter / 2 / math.cos(math.pi / 128)
    remaining = set(range(len(paths)))
    chains: list[list[tuple[float, float]]] = []
    link_lengths: list[float] = []
    reversed_paths = 0

    while remaining:
        if not chains:
            index = min(remaining, key=lambda i: (math.dist((0.0, 0.0), paths[i][0]), i))
            reverse = math.dist((0.0, 0.0), paths[index][-1]) < math.dist((0.0, 0.0), paths[index][0])
            oriented = list(paths[index][::-1] if reverse else paths[index])
            chains.append(oriented)
            reversed_paths += int(reverse)
            remaining.remove(index)
            continue

        current = chains[-1][-1]
        candidates = []
        for index in remaining:
            for reverse in (False, True):
                oriented = paths[index][::-1] if reverse else paths[index]
                start = oriented[0]
                distance = math.dist(current, start)
                if distance <= max_link:
                    candidates.append((distance, index, reverse, start))
        candidates.sort()

        selected = None
        for distance, index, reverse, start in candidates:
            if allowed.covers(LineString((current, start)).buffer(radius, quad_segs=64)):
                selected = (distance, index, reverse, start)
                break

        if selected is None:
            # No profitable full-width-safe connector exists. Keep the nearest
            # transition as an ordinary retract and XY rapid.
            choices = []
            for index in remaining:
                for reverse in (False, True):
                    oriented = paths[index][::-1] if reverse else paths[index]
                    choices.append((math.dist(current, oriented[0]), index, reverse))
            _, index, reverse = min(choices)
            chains.append(list(paths[index][::-1] if reverse else paths[index]))
            reversed_paths += int(reverse)
            remaining.remove(index)
            continue

        distance, index, reverse, start = selected
        oriented = list(paths[index][::-1] if reverse else paths[index])
        if current != start:
            chains[-1].append(start)  # Emitted as a G1 at the current cut depth.
            link_lengths.append(distance)
        chains[-1].extend(oriented[1:])
        reversed_paths += int(reverse)
        remaining.remove(index)

    # Recheck the rounded, continuous emitted chain at the maximum cutter width.
    for chain in chains:
        if not allowed_art.covers(LineString(chain).buffer(radius, quad_segs=64)):
            raise AssertionError("Linked chain full cutter sweep leaves approved artwork")
    return tuple(tuple(chain) for chain in chains), {
        "primitivePathsBefore": len(paths),
        "emittedChainsPerPass": len(chains),
        "safeStayDownLinksPerPass": len(link_lengths),
        "safeStayDownLinkDistanceMmPerPass": sum(link_lengths),
        "maximumSafeStayDownLinkMm": max_link,
        "longestSafeStayDownLinkMm": max(link_lengths, default=0.0),
        "reversedPrimitivePaths": reversed_paths,
    }


def candidate_gcode(c069, source_lines, broad_paths, tolerance: float, levels,
                   safe_z: float, approach_z: float) -> str:
    first_pass = next(i for i, line in enumerate(source_lines) if line.startswith("; PASS 1/"))
    output = source_lines[:first_pass]
    output.extend((
        f"; C-084 broad-only candidate; guarded chord tolerance {tolerance:.2f} mm",
        "; The fine residual stage is omitted to reduce command count; artwork loss is quantified in c084-runtime-report.json",
        "; Short stay-down connectors were added only after full-width cutter-sweep containment checks",
    ))
    for index, depth in enumerate(levels, start=1):
        output.append(f"; PASS {index}/{len(levels)}: broad paths to Z{-depth:.4f}")
        for path in broad_paths:
            c069.emit_path(output, path, -depth, safe_z, approach_z)
    output.extend(source_lines[-3:])
    return "\n".join(output) + "\n"


def main() -> None:
    sys.path.insert(0, str(ROOT / "src"))
    from ttc3018_control.gcode import parse_gcode, validate_nonnegative_work_xy, validate_rapid_xy_clearance
    from ttc3018_control.job_analysis import analyze_program
    from ttc3018_control.performance_budget import estimate_runtime_with_calibration

    c069 = load_module(SOURCE_DIR / "prepare-c069-flow.py", "c084_c069")
    generator = c069.load_module(c069.SOURCE_SCRIPT, "c084_c058").load_generator()
    source_text = SOURCE_NC.read_text(encoding="ascii")
    source_lines = source_text.rstrip().splitlines()
    baseline_program = parse_gcode(source_text, SOURCE_NC)
    source_groups = generator.emitted_paths_by_depth(source_text)
    levels = generator.depth_levels(generator.TARGET_DEPTH, generator.MAX_STEPDOWN)
    broad_source = source_groups[-generator.TARGET_DEPTH]
    fine_source = source_groups[-generator.FINE_DEPTH]

    with generator.Image.open(generator.SOURCE) as image:
        image_size = image.size
    art, pixel_size = generator.raster_region(generator.SOURCE, generator.settings_for(image_size))
    keepout = Point(*generator.HOLE_CENTER).buffer(generator.HOLE_KEEPOUT_RADIUS, quad_segs=256)
    available_art = art.difference(keepout)
    stock = box(0, 0, generator.STOCK, generator.STOCK)
    broad_diameter = generator.settings_for(image_size).effective_diameter
    fine_diameter = generator.settings_for(
        image_size, depth=generator.FINE_DEPTH,
        stepover=generator.FINE_STEPOVER, stepdown=generator.FINE_DEPTH,
    ).effective_diameter

    baseline_broad_sweep = generator.swept(broad_source, broad_diameter)
    baseline_fine_sweep = generator.swept(fine_source, fine_diameter)
    baseline_combined = unary_union((baseline_broad_sweep, baseline_fine_sweep))
    baseline_omission = available_art.difference(baseline_combined).area
    broad_only_omission = available_art.difference(baseline_broad_sweep).area

    variants = []
    for tolerance, nc_name, svg_path in (
        (0.08, "01-detail-c084-broad-only-008-review-only.nc", PREVIEW_008),
        (0.50, "02-detail-c084-broad-only-050-review-only.nc", PREVIEW_050),
    ):
        broad = c069.simplify_paths(broad_source, tolerance, available_art, broad_diameter)
        max_link = max_economic_link_mm(c069.CUT_FEED, c069.PLUNGE_FEED,
                                        generator.TARGET_DEPTH, generator.SAFE_Z,
                                        generator.APPROACH_Z)
        linked, linking = link_safe_paths(broad, available_art, broad_diameter, max_link)
        text = candidate_gcode(c069, source_lines, linked, tolerance, levels,
                               generator.SAFE_Z, generator.APPROACH_Z)
        nc_path = HERE / nc_name
        nc_path.write_text(text, encoding="ascii", newline="\n")

        program = parse_gcode(text, nc_path)
        validate_nonnegative_work_xy(program)
        validate_rapid_xy_clearance(program, generator.SAFE_Z)
        emitted = generator.emitted_paths_by_depth(text)
        if sorted(emitted) != [-1.625, -1.2, -0.6]:
            raise AssertionError(f"Unexpected candidate depth set: {sorted(emitted)}")
        if any(tuple(emitted[-depth]) != tuple(linked) for depth in levels):
            raise AssertionError("Broad geometry differs across depth passes")
        if program.bounds.minimum.x < 0 or program.bounds.minimum.y < 0:
            raise AssertionError("Candidate leaves nonnegative XY work coordinates")
        if program.bounds.maximum.x > generator.STOCK or program.bounds.maximum.y > generator.STOCK:
            raise AssertionError("Candidate leaves stock bounds")

        broad_sweep = generator.swept(linked, broad_diameter)
        if not available_art.covers(broad_sweep):
            raise AssertionError("Full-diameter candidate sweep leaves approved artwork/keepout")
        if not stock.covers(broad_sweep):
            raise AssertionError("Full-diameter candidate sweep leaves stock")
        residual = available_art.difference(broad_sweep)
        write_preview(svg_path, available_art, broad_sweep, residual, tolerance=tolerance)

        rapid = [segment for segment in program.segments if segment.rapid]
        cut = [segment for segment in program.segments if not segment.rapid]
        rapid_distance = sum(math.dist((s.start.x, s.start.y, s.start.z),
                                       (s.end.x, s.end.y, s.end.z)) for s in rapid)
        cut_distance = sum(math.dist((s.start.x, s.start.y, s.start.z),
                                     (s.end.x, s.end.y, s.end.z)) for s in cut)
        omission = available_art.difference(broad_sweep).area
        count = len(program.commands)
        generic_motion = analyze_program(program)
        runtime_estimate = estimate_runtime_with_calibration(
            program.estimated_seconds,
            machine_profile_key=RUNTIME_PROFILE_KEY,
            calibration=None,
            target_minutes=ASPIRATIONAL_RUNTIME_MINUTES,
        )
        observed_projection = {
            "acceptedCommandsPerMinuteObserved": [
                OBSERVED_ACCEPTED_COMMANDS_PER_MINUTE[0], OBSERVED_ACCEPTED_COMMANDS_PER_MINUTE[1]
            ],
            "minutesAtObservedAcceptedCommandRate": [
                count / OBSERVED_ACCEPTED_COMMANDS_PER_MINUTE[1],
                count / OBSERVED_ACCEPTED_COMMANDS_PER_MINUTE[0],
            ],
            "interpretation": "Historical acknowledged-command pacing projection, not measured physical cycle time; accepted commands do not prove completed motion or the candidate's exact pace.",
        }
        variant = {
            "file": nc_name,
            "sha256": sha256(nc_path),
            "preview": {"file": svg_path.name, "sha256": sha256(svg_path)},
            "chordToleranceMm": tolerance,
            "tool": {"angleDeg": 30.0, "tipDiameterMm": 0.1,
                     "effectiveDiameterAtFinalDepthMm": broad_diameter,
                     "physicalToolConditionVerified": False},
            "depthPassesMm": [-value for value in levels],
            "feedMmPerMin": {"cut": c069.CUT_FEED, "plunge": c069.PLUNGE_FEED},
            "spindleCommandRpm": 1000,
            "boundsMm": {
                "min": {"x": program.bounds.minimum.x, "y": program.bounds.minimum.y, "z": program.bounds.minimum.z},
                "max": {"x": program.bounds.maximum.x, "y": program.bounds.maximum.y, "z": program.bounds.maximum.z},
            },
            "motion": {
                "commands": count,
                "motionSegments": len(program.segments),
                "cutSegments": len(cut),
                "rapidSegments": len(rapid),
                "genericParsedMotionAnalysis": generic_motion,
                "runtimeEstimate": runtime_estimate,
                "cutDistanceMm3d": cut_distance,
                "rapidDistanceMm3d": rapid_distance,
                "retracts": max(0, sum(1 for line in text.splitlines() if line == f"G0 Z{generator.SAFE_Z:.4f}") - 2),
                "pathLinking": linking,
                "feedBasedEstimateMinutes": program.estimated_seconds / 60,
                "estimateAssumptions": "Parser uses commanded feed and 3000 mm/min rapid; excludes acceleration, junction slowdown, controller streaming delay, setup and physical verification.",
                "observedThroughputProjection": observed_projection,
            },
            "coverage": {
                "availableBlackAreaMm2": available_art.area,
                "fullDiameterSweepMm2": broad_sweep.area,
                "omittedAvailableBlackMm2": omission,
                "omittedFraction": omission / available_art.area,
                "omissionIncreaseVersusFullC069Mm2": omission - baseline_omission,
                "sweepSymmetricDifferenceVsCurrentBroadMm2": baseline_broad_sweep.symmetric_difference(broad_sweep).area,
                "fullDiameterContainedInApprovedArtAndOutsideHangerKeepout": True,
            },
            "checks": {
                "parses": True,
                "rapidXYAtSafeZ": True,
                "depthPassesUnchanged": True,
                "broadPathIdenticalAcrossPasses": True,
                "safePathLinksVerifiedAtFullFinalDepthCutterWidth": True,
                "toolSweepContained": True,
                "stockBoundsContained": True,
                "fineResidualStageOmitted": True,
            },
        }
        variants.append(variant)

    settings = {
        "status": "offline review only; no machine interaction or cutting authorization",
        "sourceFile": str(SOURCE_NC.relative_to(ROOT)),
        "sourceSha256": sha256(SOURCE_NC),
        "sourcePixelSizeMm": pixel_size,
        "stock": {"sizeMm": [110.0, 110.0], "measuredThicknessMm": 3.25,
                  "workOrigin": "lower-left; saved 100 mm ornament frame is unchanged"},
        "ornament": {"diameterMm": 100.0, "centerWorkXY": [55.0, 55.0]},
        "tool": {"includedAngleDeg": 30.0, "tipDiameterMm": 0.1,
                 "physicalConditionVerified": False},
        "spindleCommandRpm": 1000,
        "cutFeedMmPerMin": c069.CUT_FEED,
        "plungeFeedMmPerMin": c069.PLUNGE_FEED,
        "safeZMm": generator.SAFE_Z,
        "approachZMm": generator.APPROACH_Z,
        "broadDepthPassesMm": [-value for value in levels],
        "deliberateTradeoff": "Shallow residual fine-detail stage omitted. V-bit remains at the same broad depths, including 1.625 mm final depth.",
        "runtimeProfileKey": RUNTIME_PROFILE_KEY,
        "aspirationalRuntimeMinutes": ASPIRATIONAL_RUNTIME_MINUTES,
        "timeGoal": "45 minutes is an aspiration. Report nominal and historical-throughput projections, but do not reject a candidate solely for exceeding either projection.",
        "observedAcceptedCommandPace": OBSERVED_ACCEPTED_COMMANDS_PER_MINUTE,
        "candidateVariants": [
            {"file": item["file"], "toleranceMm": item["chordToleranceMm"]} for item in variants
        ],
    }
    SETTINGS.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8", newline="\n")
    report = {
        "schemaVersion": 1,
        "releaseStatus": "offline-review-only; not authorized or verified for cutting",
        "source": {"file": str(SOURCE_NC.relative_to(ROOT)), "sha256": sha256(SOURCE_NC)},
        "generator": {"file": str(Path(__file__).resolve().relative_to(ROOT)), "sha256": sha256(Path(__file__))},
        "settingsFile": {"file": SETTINGS.name, "sha256": sha256(SETTINGS)},
        "comparison": {
            "currentC069Commands": len(parse_gcode(source_text).commands),
            "currentC069EstimateMinutes": parse_gcode(source_text).estimated_seconds / 60,
            "currentC069GenericParsedMotionAnalysis": analyze_program(baseline_program),
            "currentC069AvailableBlackOmittedMm2": baseline_omission,
            "broadOnlyAtCurrentToleranceOmittedMm2": broad_only_omission,
            "fineStagePaths": len(fine_source),
            "fineStageCutSegments": sum(len(path) - 1 for path in fine_source),
            "sameWorkFrameToolAndBroadDepths": True,
            "observedThroughput": {
                "referenceJob": "C-083 continuation telemetry before the operator stop",
                "samples": [
                    {"acceptedCommands": 3310, "elapsedMinutes": 31.4},
                    {"acceptedCommands": 7626, "elapsedMinutes": 68.8},
                ],
                "estimatedCommandsPerMinute": list(OBSERVED_ACCEPTED_COMMANDS_PER_MINUTE),
                "caveat": "Accepted commands are not a calibrated physical position or precise executed-motion measure; use only as a warning that the parser estimate is optimistic.",
            },
        },
        "variants": variants,
    }
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"report": str(REPORT.relative_to(ROOT)), "variants": variants}, indent=2))


if __name__ == "__main__":
    main()
