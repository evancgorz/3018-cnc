"""Offline, reusable analysis of a parsed CNC job; never connects to hardware."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

from .gcode import load_gcode
from .performance_budget import estimate_runtime_with_calibration


def analyze_program(program) -> dict:
    """Summarize parsed motion, separating XY cutting from vertical feed moves.

    Cutting-segment and junction statistics include XY feed moves only when
    both endpoints are below work Z0. Rapid transfers, plunges, and depth
    changes end the current cut path. This is a geometry report, not a machine
    readiness check or a measured runtime.
    """
    cut_lengths: list[float] = []
    turns: list[float] = []
    previous_xy: tuple[float, float] | None = None
    cut_distance = feed_distance = plunge_distance = 0.0
    rapid_distance = rapid_xy_distance = rapid_z_distance = 0.0
    rapid_segments = retract_count = 0

    for segment in program.segments:
        dx = segment.end.x - segment.start.x
        dy = segment.end.y - segment.start.y
        dz = segment.end.z - segment.start.z
        xy_distance = math.hypot(dx, dy)
        if segment.rapid:
            rapid_segments += 1
            rapid_distance += math.sqrt(dx * dx + dy * dy + dz * dz)
            rapid_xy_distance += xy_distance
            rapid_z_distance += abs(dz)
            if dz > 1e-9 and segment.start.z < 0 and segment.end.z >= 0:
                retract_count += 1
            previous_xy = None
            continue

        feed_distance += math.sqrt(dx * dx + dy * dy + dz * dz)
        if dz < -1e-9 and xy_distance <= 1e-9:
            plunge_distance += abs(dz)
        if xy_distance <= 1e-9 or segment.start.z >= 0 or segment.end.z >= 0:
            previous_xy = None
            continue

        cut_distance += xy_distance
        cut_lengths.append(xy_distance)
        vector = (dx, dy)
        if previous_xy is not None:
            cosine = sum(a * b for a, b in zip(previous_xy, vector)) / (math.hypot(*previous_xy) * xy_distance)
            turns.append(math.degrees(math.acos(max(-1.0, min(1.0, cosine)))))
        previous_xy = vector

    cut_lengths.sort()
    median = cut_lengths[len(cut_lengths) // 2] if cut_lengths else None
    percentile = lambda values, ratio: values[min(len(values) - 1, int(ratio * len(values)))] if values else None
    short_0_1 = sum(length <= 0.1 for length in cut_lengths)
    short_0_25 = sum(length <= 0.25 for length in cut_lengths)
    sharp_90 = sum(turn >= 89.999 for turn in turns)
    sharp_135 = sum(turn >= 134.999 for turn in turns)
    return {
        "commands": len(program.commands),
        "bounds_mm": {"min": vars(program.bounds.minimum), "max": vars(program.bounds.maximum)},
        "feed_based_seconds": program.estimated_seconds,
        "estimate_limits": "Excludes acceleration and junction slowing; rapid feed assumed 3000 mm/min.",
        "cut_distance_mm": cut_distance,
        "feed_distance_mm": feed_distance,
        "plunge_distance_mm": plunge_distance,
        "rapid_distance_mm": rapid_distance,
        "rapid_xy_distance_mm": rapid_xy_distance,
        "rapid_z_distance_mm": rapid_z_distance,
        "rapid_segments": rapid_segments,
        "retract_count": retract_count,
        "nonzero_cut_segments": len(cut_lengths),
        "median_cut_segment_mm": median,
        "p95_cut_segment_mm": percentile(cut_lengths, 0.95),
        "cut_segments_at_most_0_1mm": short_0_1,
        "cut_segments_at_most_0_1mm_percent": 100.0 * short_0_1 / len(cut_lengths) if cut_lengths else 0.0,
        "cut_segments_at_most_0_25mm": short_0_25,
        "cut_segments_at_most_0_25mm_percent": 100.0 * short_0_25 / len(cut_lengths) if cut_lengths else 0.0,
        "cut_junctions": len(turns),
        "cut_junctions_at_least_90_degrees": sharp_90,
        "cut_junctions_at_least_90_degrees_percent": 100.0 * sharp_90 / len(turns) if turns else 0.0,
        "cut_junctions_at_least_135_degrees": sharp_135,
        "cut_junctions_at_least_135_degrees_percent": 100.0 * sharp_135 / len(turns) if turns else 0.0,
        "retracts_per_1000_commands": 1000.0 * retract_count / len(program.commands) if program.commands else 0.0,
    }


def analyze(path: Path, *, target_minutes: float | None = None,
            machine_profile_key: str = "", calibration_path: Path | None = None) -> dict:
    program = load_gcode(path)
    report = {
        "path": str(path.resolve()),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        **analyze_program(program),
    }
    if target_minutes is not None or calibration_path is not None:
        if not machine_profile_key.strip():
            raise ValueError("--machine-profile-key is required for runtime estimates")
        calibration = None
        if calibration_path is not None:
            calibration = json.loads(calibration_path.read_text(encoding="utf-8"))
            if not isinstance(calibration, dict):
                raise ValueError("runtime calibration JSON must contain an object")
        report["runtime_estimate"] = estimate_runtime_with_calibration(
            report["feed_based_seconds"], target_minutes=target_minutes,
            machine_profile_key=machine_profile_key, calibration=calibration,
        )
    elif machine_profile_key:
        raise ValueError("--machine-profile-key requires --target-minutes or --calibration-json")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("gcode", type=Path)
    parser.add_argument("--target-minutes", type=float,
                        help="include an informational comparison between calibrated projection and target")
    parser.add_argument("--machine-profile-key", default="",
                        help="stable key for the exact machine/tool/material/CAM motion profile")
    parser.add_argument("--calibration-json", type=Path,
                        help="JSON file of completed comparable runs (see AGENT_CNC_JOB_WORKFLOW.md)")
    args = parser.parse_args()
    try:
        if (args.target_minutes is not None or args.calibration_json is not None) and not args.machine_profile_key:
            parser.error("--target-minutes requires --machine-profile-key")
        print(json.dumps(analyze(
            args.gcode, target_minutes=args.target_minutes,
            machine_profile_key=args.machine_profile_key,
            calibration_path=args.calibration_json,
        ), indent=2))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
