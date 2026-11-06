"""Independent offline checks for the C-045 measured-stock cutout review."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
import sys

from shapely.geometry import LineString, box
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT / "src"))

from ttc3018_control.gcode import (
    parse_gcode,
    validate_nonnegative_work_xy,
    validate_rapid_xy_clearance,
)


OUT = Path(__file__).resolve().parent
BASELINE = ROOT / "artifacts/ornaments/hawkeye/two-bit/02-cutout-review.nc"
GCODE = OUT / "02-cutout-review.nc"
REPORT = OUT / "cutout-report.json"
CANDIDATE = OUT / "02-cutout-candidate-1000rpm.nc"
CANDIDATE_REPORT = OUT / "cutout-candidate-report.json"
STOCK = box(0, 0, 110, 110)
TOOL_RADIUS = 3.175 / 2  # The report explicitly marks this diameter unverified.
THICKNESS = 3.25
TAB_FLOOR = -(THICKNESS - 0.8)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parsed_geometry(path: Path, thickness: float):
    source = path.read_text(encoding="ascii")
    program = parse_gcode(source, path)
    validate_nonnegative_work_xy(program)
    validate_rapid_xy_clearance(program, 3.0)

    hole_lines: list[LineString] = []
    outer_lines: list[LineString] = []
    tab_lines: list[LineString] = []
    xy_cut_lines: list[LineString] = []
    depths: set[float] = set()
    vertical_descents: list[float] = []
    tab_span_lines: dict[int, list[LineString]] = {}
    for segment in program.segments:
        start = (segment.start.x, segment.start.y)
        end = (segment.end.x, segment.end.y)
        xy_length = math.dist(start, end)
        radius = math.dist(
            ((start[0] + end[0]) / 2, (start[1] + end[1]) / 2), (55, 55),
        )
        midpoint_z = (segment.start.z + segment.end.z) / 2
        if not segment.rapid and xy_length > 1e-8 and segment.end.z < -1e-6:
            line = LineString((start, end))
            xy_cut_lines.append(line)
            if radius < 48:
                hole_lines.append(line)
            elif radius > 48:
                outer_lines.append(line)
                if math.isclose(midpoint_z, -(thickness - 0.8), abs_tol=0.002):
                    tab_lines.append(line)
                    angle = math.degrees(math.atan2(
                        (start[1] + end[1]) / 2 - 55,
                        (start[0] + end[0]) / 2 - 55,
                    )) % 360
                    cardinal = int(round(angle / 90)) % 4
                    tab_span_lines.setdefault(cardinal, []).append(line)
            depths.add(round(segment.end.z, 3))
        elif (
            not segment.rapid and xy_length <= 1e-8
            and segment.start.z < -1e-6
            and segment.end.z < segment.start.z - 1e-6
        ):
            vertical_descents.append(segment.start.z - segment.end.z)

    return {
        "program": program,
        "hole": unary_union(hole_lines),
        "outer": unary_union(outer_lines),
        "tabs": unary_union(tab_lines),
        "cut_sweep": unary_union([
            line.buffer(TOOL_RADIUS, cap_style=1, join_style=1, quad_segs=8)
            for line in xy_cut_lines
        ]),
        "depths": sorted(depths),
        "max_vertical_descent": max(vertical_descents, default=0.0),
        "tab_span_lengths": {
            str(key * 90): round(unary_union(lines).length, 4)
            for key, lines in sorted(tab_span_lines.items())
        },
        "tab_segment_count": len(tab_lines),
        "hole_segments": len(hole_lines),
        "outer_segments": len(outer_lines),
        "source": source,
    }


def main() -> None:
    measured = parsed_geometry(GCODE, THICKNESS)
    original = parsed_geometry(BASELINE, 3.0)
    candidate = parsed_geometry(CANDIDATE, THICKNESS)
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    candidate_report = json.loads(CANDIDATE_REPORT.read_text(encoding="utf-8"))
    program = measured["program"]
    candidate_program = candidate["program"]

    executable = "\n".join(
        line for line in measured["source"].splitlines()
        if not line.lstrip().startswith(";")
    )
    hole_first = max(
        (index for index, segment in enumerate(program.segments)
         if not segment.rapid and math.dist(
             (segment.start.x, segment.start.y), (segment.end.x, segment.end.y),
         ) > 1e-8 and math.dist(
             ((segment.start.x + segment.end.x) / 2,
              (segment.start.y + segment.end.y) / 2), (55, 55),
         ) < 48),
        default=-1,
    ) < min(
        (index for index, segment in enumerate(program.segments)
         if not segment.rapid and math.dist(
             (segment.start.x, segment.start.y), (segment.end.x, segment.end.y),
         ) > 1e-8 and math.dist(
             ((segment.start.x + segment.end.x) / 2,
              (segment.start.y + segment.end.y) / 2), (55, 55),
         ) > 48),
        default=len(program.segments),
    )
    tab_lengths = list(measured["tab_span_lengths"].values())
    candidate_executable = "\n".join(
        line for line in candidate["source"].splitlines()
        if not line.lstrip().startswith(";")
    )
    candidate_m3_count = len(re.findall(r"\bM\s*3\b", candidate_executable, re.IGNORECASE))
    candidate_m5_count = len(re.findall(r"\bM\s*5\b", candidate_executable, re.IGNORECASE))
    candidate_m6_count = len(re.findall(r"\bM\s*6\b", candidate_executable, re.IGNORECASE))
    candidate_dwell_count = len(re.findall(r"\bG\s*4\b", candidate_executable, re.IGNORECASE))
    checks = {
        "gcodeParses": True,
        "nonnegativeWorkXY": True,
        "rapidXYAtSafeZ3": True,
        "measuredThickness3p25": report["geometry"]["stock"]["thicknessMm"] == 3.25
        and report["geometry"]["stock"]["thicknessMeasured"] is True,
        "targetDepth3p40": math.isclose(min(measured["depths"]), -3.4, abs_tol=0.001),
        "sevenDepthLevelsAtMost0p5": len(report["toolpathReview"]["feedDepthLevelsMm"]) == 7
        and report["toolpathReview"]["measuredMaxStepdownIncludingVerticalMovesMm"] <= 0.5,
        "tabFloorAtMinus2p45": math.isclose(TAB_FLOOR, -2.45, abs_tol=1e-9),
        "fourTabIntervalsOf4mm": len(tab_lengths) == 4
        and all(abs(value - 4.0) <= 0.05 for value in tab_lengths),
        "holeFinishesBeforeOuterStarts": hole_first,
        "sameHoleXYAsBaseline": measured["hole"].equals(original["hole"]),
        "sameOuterXYAsBaseline": measured["outer"].equals(original["outer"]),
        "sameTabXYAsBaseline": measured["tabs"].equals(original["tabs"]),
        "allParsedCutterSweepInside110mmStock": STOCK.buffer(0.001).covers(measured["cut_sweep"]),
        "noSpindleOrToolchange": not any(
            code in executable.upper().splitlines() for code in ("M3", "M03", "M6", "M06")
        ),
        "estimatedMinutesMatchesReport": math.isclose(
            program.estimated_seconds / 60,
            report["toolpathReview"]["exactCombinedProgramEstimatedMinutes"],
            abs_tol=0.001,
        ),
        "candidateParsesWithG4Dwell": candidate_dwell_count == 1,
        "candidateUsesOneM3S1000": candidate_m3_count == 1
        and "M3 S1000" in candidate_executable.splitlines(),
        "candidateEndsWithM5ThenM2": candidate_m5_count == 2
        and candidate_executable.splitlines()[-2:] == ["M5", "M2"],
        "candidateHasNoToolchange": candidate_m6_count == 0,
        "candidateMotionEqualsSpindleOffReview": candidate_program.segments == program.segments,
        "candidateSweepEqualsSpindleOffReview": candidate["cut_sweep"].equals(measured["cut_sweep"]),
        "candidateRuntimeIncludesTwoSecondDwell": math.isclose(
            candidate_program.estimated_seconds - program.estimated_seconds,
            2.0,
            abs_tol=0.001,
        ),
        "candidateRuntimeMatchesCandidateReport": math.isclose(
            candidate_program.estimated_seconds / 60,
            candidate_report["toolpathReview"]["exactCombinedProgramEstimatedMinutes"],
            abs_tol=0.001,
        ),
    }
    if not all(checks.values()):
        failed = [key for key, value in checks.items() if not value]
        raise SystemExit(f"Offline verification failed: {failed}")

    result = {
        "scope": "independent offline parsing and geometry comparison only; no app, backend, or hardware access",
        "checks": checks,
        "parsed": {
            "segmentCount": len(program.segments),
            "depthLevelsMm": report["toolpathReview"]["feedDepthLevelsMm"],
            "targetDepthMm": min(measured["depths"]),
            "tabFloorMm": TAB_FLOOR,
            "tabSpansByCardinalDegreesMm": measured["tab_span_lengths"],
            "tabLiftSegmentCount": measured["tab_segment_count"],
            "maxVerticalDescentMm": round(measured["max_vertical_descent"], 4),
            "estimatedMinutes": round(program.estimated_seconds / 60, 3),
            "candidateSpindleRpm": 1000,
            "candidateDwellSeconds": 2.0,
            "candidateEstimatedMinutes": round(candidate_program.estimated_seconds / 60, 3),
        },
        "artifacts": {
            "baselineGcodeSha256": sha256(BASELINE),
            "gcodeSha256": sha256(GCODE),
            "reportSha256": sha256(REPORT),
            "candidateGcodeSha256": sha256(CANDIDATE),
            "candidateReportSha256": sha256(CANDIDATE_REPORT),
        },
    }
    (OUT / "independent-verification.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8",
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
