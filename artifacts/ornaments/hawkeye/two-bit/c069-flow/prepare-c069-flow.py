"""Replace raster stair-steps with guarded longer vectors, entirely offline."""
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
C057_DIR = HERE.parent / "c043-runtime" / "c057-fine-microsegments"
SOURCE_NC = C057_DIR / "01-detail-speed-fine-simplified-450-120-review-only.nc"
SOURCE_SCRIPT = C057_DIR / "optimize-fine-pass.py"
OUTPUT_NC = HERE / "01-detail-c069-flow-675-120-review-only.nc"
REPORT = HERE / "c069-flow-report.json"
VERIFY = HERE / "c069-flow-verification.json"

# One physical artwork pixel is 0.0717703 mm.  A one-pixel tolerance removes
# raster stair-steps while the full cutter-disk containment test below retains
# any corner that cannot be safely replaced by a chord.
BROAD_TOLERANCE_MM = 0.08
FINE_TOLERANCE_MM = 0.04
CUT_FEED = 675.0
PLUNGE_FEED = 120.0

sys.path.insert(0, str(ROOT / "src"))


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def point_segment_distance(point, start, end) -> float:
    dx, dy = end[0] - start[0], end[1] - start[1]
    if dx == 0 and dy == 0:
        return math.dist(point, start)
    ratio = ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / (dx * dx + dy * dy)
    ratio = max(0.0, min(1.0, ratio))
    projection = (start[0] + ratio * dx, start[1] + ratio * dy)
    return math.dist(point, projection)


def simplify_open(points, tolerance: float, allowed, guard_radius: float):
    """RDP reduction that accepts a chord only when its cutter disk is safe."""
    if len(points) <= 2:
        return [points[0], points[-1]]
    distances = [point_segment_distance(point, points[0], points[-1]) for point in points[1:-1]]
    maximum = max(distances)
    split = distances.index(maximum) + 1
    chord = LineString((points[0], points[-1]))
    if maximum <= tolerance and allowed.covers(chord.buffer(guard_radius, quad_segs=32)):
        return [points[0], points[-1]]
    if maximum < 1e-12:
        split = len(points) // 2
    before = simplify_open(points[: split + 1], tolerance, allowed, guard_radius)
    after = simplify_open(points[split:], tolerance, allowed, guard_radius)
    return before[:-1] + after


def simplify_path(path, tolerance: float, allowed, guard_radius: float):
    points = list(path)
    if len(points) <= 2:
        # A two-point degenerate path is an intentional plunge-only dot.  Keep
        # its repeated endpoint so sweep accounting includes the cutter disk.
        return tuple(points)
    if points[0] == points[-1]:
        split = len(points) // 2
        before = simplify_open(points[: split + 1], tolerance, allowed, guard_radius)
        after = simplify_open(points[split:], tolerance, allowed, guard_radius)
        result = before[:-1] + after
    else:
        result = simplify_open(points, tolerance, allowed, guard_radius)
    rounded = [(round(x, 4), round(y, 4)) for x, y in result]
    deduplicated = [rounded[0]]
    for point in rounded[1:]:
        if point != deduplicated[-1]:
            deduplicated.append(point)
    return tuple(deduplicated)


def simplify_paths(paths, tolerance: float, allowed_region, diameter: float):
    allowed = prep(allowed_region)
    guard_radius = diameter / 2 / math.cos(math.pi / 128)
    result = tuple(simplify_path(path, tolerance, allowed, guard_radius) for path in paths)
    for index, path in enumerate(result):
        source = paths[index]
        if path[0] != source[0] or path[-1] != source[-1]:
            raise AssertionError(f"Path {index} endpoints changed")
        if not allowed.covers(LineString(path).buffer(guard_radius, quad_segs=32)):
            raise AssertionError(f"Path {index} cutter disk leaves approved artwork")
    return result


def emit_path(lines: list[str], path, depth: float, safe_z: float, approach_z: float) -> None:
    x, y = path[0]
    lines.extend((
        f"G0 Z{safe_z:.4f}",
        f"G0 X{x:.4f} Y{y:.4f}",
        f"G0 Z{approach_z:.4f}",
        f"G1 Z{depth:.4f} F{PLUNGE_FEED:.4f}",
    ))
    lines.extend(f"G1 X{x:.4f} Y{y:.4f} F{CUT_FEED:.4f}" for x, y in path[1:])


def build_gcode(source_lines, broad_paths, fine_paths, levels, safe_z, approach_z) -> str:
    first_pass = next(i for i, line in enumerate(source_lines) if line.startswith("; PASS 1/"))
    fine_marker = next(line for line in source_lines if line.startswith("; FINE DETAIL:"))
    if source_lines[-3:] != [f"G0 Z{safe_z:.4f}", "M5", "M2"]:
        raise ValueError("Source has unexpected terminal commands")
    output = [
        "; Approved thresholded artwork; broad and fine paths use guarded controller-efficient vectors"
        if line.startswith("; Approved thresholded artwork; deep broad passes copied unchanged")
        else line
        for line in source_lines[:first_pass]
    ]
    output.append("; C-069 guarded-vector feed comparison candidate")
    for number, depth in enumerate(levels, start=1):
        output.append(f"; PASS {number}/{len(levels)}: broad paths to Z{-depth:.4f}")
        for path in broad_paths:
            emit_path(output, path, -depth, safe_z, approach_z)
    output.append(fine_marker)
    for path in fine_paths:
        emit_path(output, path, -0.04, safe_z, approach_z)
    output.extend(source_lines[-3:])
    return "\n".join(output) + "\n"


def motion_stats(paths):
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
    turns.sort()
    percentile = lambda values, ratio: values[min(len(values) - 1, int(ratio * len(values)))] if values else 0.0
    return {
        "segments": len(lengths),
        "distanceMm": sum(lengths),
        "medianSegmentMm": percentile(lengths, 0.5),
        "p95SegmentMm": percentile(lengths, 0.95),
        "segmentsAtMost0p1Mm": sum(value <= 0.1 for value in lengths),
        "junctions": len(turns),
        "junctionsAtLeast90Deg": sum(value >= 89.999 for value in turns),
    }


def main() -> None:
    from ttc3018_control.gcode import parse_gcode, validate_nonnegative_work_xy, validate_rapid_xy_clearance

    c057 = load_module(SOURCE_SCRIPT, "c058_source")
    generator = c057.load_generator()
    source_text = SOURCE_NC.read_text(encoding="ascii")
    source_lines = source_text.rstrip().splitlines()
    source_paths = generator.emitted_paths_by_depth(source_text)
    broad_source = source_paths[-generator.TARGET_DEPTH]
    fine_source = source_paths[-generator.FINE_DEPTH]

    with generator.Image.open(generator.SOURCE) as image:
        image_size = image.size
    source_region, pixel_size = generator.raster_region(generator.SOURCE, generator.settings_for(image_size))
    keepout = Point(*generator.HOLE_CENTER).buffer(generator.HOLE_KEEPOUT_RADIUS, quad_segs=256)
    work_region = source_region.difference(keepout)
    stock = box(0, 0, generator.STOCK, generator.STOCK)
    broad_diameter = generator.settings_for(image_size).effective_diameter
    fine_diameter = generator.settings_for(
        image_size, depth=generator.FINE_DEPTH,
        stepover=generator.FINE_STEPOVER, stepdown=generator.FINE_DEPTH,
    ).effective_diameter

    broad = simplify_paths(broad_source, BROAD_TOLERANCE_MM, work_region, broad_diameter)
    fine = simplify_paths(fine_source, FINE_TOLERANCE_MM, work_region, fine_diameter)
    output = build_gcode(
        source_lines, broad, fine,
        generator.depth_levels(generator.TARGET_DEPTH, generator.MAX_STEPDOWN),
        generator.SAFE_Z, generator.APPROACH_Z,
    )
    HERE.mkdir(parents=True, exist_ok=True)
    OUTPUT_NC.write_text(output, encoding="ascii", newline="\n")

    program = parse_gcode(output, OUTPUT_NC)
    validate_nonnegative_work_xy(program)
    validate_rapid_xy_clearance(program, generator.SAFE_Z)
    emitted = generator.emitted_paths_by_depth(output)
    if sorted(emitted) != [-1.625, -1.2, -0.6, -0.04]:
        raise AssertionError(f"Unexpected depth set: {sorted(emitted)}")
    if not (
        tuple(emitted[-0.6]) == tuple(emitted[-1.2])
        == tuple(emitted[-1.625]) == broad
    ):
        raise AssertionError("Broad vector geometry differs between passes")
    if tuple(emitted[-0.04]) != fine:
        raise AssertionError("Fine emitted geometry differs from candidate")
    if not stock.buffer(0.001).covers(unary_union([LineString(path) for path in (*broad, *fine)])):
        raise AssertionError("Candidate centerline leaves stock")

    executable = "\n".join(line.split(";", 1)[0] for line in output.splitlines())
    controls = {
        "m3": len(re.findall(r"\bM\s*3\b", executable, re.I)),
        "m5": len(re.findall(r"\bM\s*5\b", executable, re.I)),
        "m6": len(re.findall(r"\bM\s*6\b", executable, re.I)),
        "end": len(re.findall(r"\bM\s*(?:2|30)\b", executable, re.I)),
    }
    if controls != {"m3": 1, "m5": 1, "m6": 0, "end": 1}:
        raise AssertionError(f"Unexpected controls: {controls}")

    baseline_broad_sweep = generator.swept(broad_source, broad_diameter)
    candidate_broad_sweep = generator.swept(broad, broad_diameter)
    baseline_fine_sweep = generator.swept(fine_source, fine_diameter)
    candidate_fine_sweep = generator.swept(fine, fine_diameter)
    baseline_combined = unary_union((baseline_broad_sweep, baseline_fine_sweep))
    candidate_combined = unary_union((candidate_broad_sweep, candidate_fine_sweep))
    baseline_omitted = work_region.difference(baseline_combined).area
    candidate_omitted = work_region.difference(candidate_combined).area
    baseline_stats = motion_stats((*broad_source, *broad_source, *broad_source, *fine_source))
    candidate_stats = motion_stats((*broad, *broad, *broad, *fine))
    segment_reduction = 100 * (1 - candidate_stats["segments"] / baseline_stats["segments"])
    omission_delta = candidate_omitted - baseline_omitted
    if segment_reduction < 40:
        raise AssertionError(f"Segment reduction is insufficient: {segment_reduction:.3f}%")
    if omission_delta > 10:
        raise AssertionError(f"Approved-art omission increased too much: {omission_delta:.6f} mm2")

    report = {
        "schemaVersion": 1,
        "releaseStatus": "offline-review-only; no machine interaction",
        "source": {"path": str(SOURCE_NC.relative_to(ROOT)), "sha256": sha256(SOURCE_NC), "pixelSizeMm": pixel_size},
        "candidate": {"path": str(OUTPUT_NC.relative_to(ROOT)), "sha256": sha256(OUTPUT_NC)},
        "generator": {"path": str(Path(__file__).resolve().relative_to(ROOT)), "sha256": sha256(Path(__file__))},
        "tolerancesMm": {"broad": BROAD_TOLERANCE_MM, "fine": FINE_TOLERANCE_MM},
        "toolDiametersMm": {"broadAtFinalDepth": broad_diameter, "fine": fine_diameter},
        "motion": {
            "cutFeedMmPerMin": CUT_FEED, "plungeFeedMmPerMin": PLUNGE_FEED, "spindleCommand": 1000,
            "baseline": baseline_stats, "candidate": candidate_stats,
            "segmentReductionPercent": segment_reduction,
            "estimatedMinutesIgnoringJunctionSlowdown": program.estimated_seconds / 60,
        },
        "geometry": {
            "broadPaths": len(broad), "finePaths": len(fine),
            "broadSegmentsBeforeAfterPerPass": [sum(len(path) - 1 for path in broad_source), sum(len(path) - 1 for path in broad)],
            "fineSegmentsBeforeAfter": [sum(len(path) - 1 for path in fine_source), sum(len(path) - 1 for path in fine)],
            "broadSweepSymmetricDifferenceMm2": baseline_broad_sweep.symmetric_difference(candidate_broad_sweep).area,
            "fineSweepSymmetricDifferenceMm2": baseline_fine_sweep.symmetric_difference(candidate_fine_sweep).area,
            "combinedApprovedBlackOmittedBeforeAfterMm2": [baseline_omitted, candidate_omitted],
            "combinedOmissionDeltaMm2": omission_delta,
            "fullDiameterChordContainment": True,
            "hangerKeepoutExcluded": True,
            "stockContained": True,
        },
        "checks": {
            "gcodeParses": True, "nonnegativeWorkXY": True, "rapidXYAtSafeZ": True,
            "depthsUnchanged": True, "broadRepeatedAtAllThreeDepths": True,
            "singleM3FinalM5M2NoM6": True,
        },
    }
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    verification = {
        "result": "passed",
        "candidateSha256": report["candidate"]["sha256"],
        "segmentsBeforeAfter": [baseline_stats["segments"], candidate_stats["segments"]],
        "segmentReductionPercent": report["motion"]["segmentReductionPercent"],
        "medianSegmentBeforeAfterMm": [baseline_stats["medianSegmentMm"], candidate_stats["medianSegmentMm"]],
        "junctionsAtLeast90DegBeforeAfter": [baseline_stats["junctionsAtLeast90Deg"], candidate_stats["junctionsAtLeast90Deg"]],
        "combinedOmissionDeltaMm2": report["geometry"]["combinedOmissionDeltaMm2"],
        "checks": report["checks"],
    }
    VERIFY.write_text(json.dumps(verification, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(verification, indent=2))


if __name__ == "__main__":
    main()
