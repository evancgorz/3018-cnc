"""Generate and compare bounded raster CAM fidelity/runtime candidates."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil
import tempfile

from shapely.geometry import LineString
from shapely.ops import unary_union

from .build import build
from ..application.job_provenance import read_review_bundle
from ..gcode import GCodeProgram, load_gcode
from ..job_analysis import analyze_program
from ..ornament_cam import OrnamentSettings, raster_region


_PROGRAM = "candidate-review-only.nc"
_MAX_SWEEP_SEGMENTS = 250_000
_CHANGED_SETTING = "stepover"


def _read_bundle(report_path: Path) -> tuple[dict, GCodeProgram, dict, Path, str]:
    report_path = report_path.resolve()
    if report_path.name != "report.json" or report_path.is_symlink():
        raise ValueError("Choose a local Pine CAM report.json")
    program, report, _ = read_review_bundle(report_path)
    if report.get("kind") != "raster":
        raise ValueError("Fidelity ladders currently support raster engraving bundles")
    try:
        design = json.loads((report_path.parent / "design.json").read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Could not read the bundle's design.json") from exc
    if not isinstance(design, dict) or design.get("kind") != "raster" or not isinstance(design.get("settings"), dict):
        raise ValueError("Review bundle has an invalid raster design spec")
    source_files = [name for name in report.get("sha256", {}) if name.startswith("source.")]
    if len(source_files) != 1:
        raise ValueError("Raster bundle must contain one hash-verified source file")
    source_path = report_path.parent / source_files[0]
    source_sha = hashlib.sha256(source_path.read_bytes()).hexdigest()
    if source_sha != (report.get("cam") or {}).get("source_sha256"):
        raise ValueError("Raster source hash does not match the CAM report")
    return report, program, design, source_path, source_sha


def _compare_inputs(baseline: dict, candidate: dict, baseline_source_sha: str,
                    candidate_source_sha: str) -> tuple[dict, dict]:
    if baseline_source_sha != candidate_source_sha:
        raise ValueError("Candidates use different source artwork")
    if baseline.get("concept") != candidate.get("concept"):
        raise ValueError("Candidates describe different concepts")
    base_settings = baseline["settings"]
    new_settings = candidate["settings"]
    if base_settings.keys() != new_settings.keys():
        raise ValueError("Candidates use different raster setting fields")
    for key in base_settings:
        if key != _CHANGED_SETTING and base_settings[key] != new_settings[key]:
            raise ValueError(f"Candidates must hold {key} fixed")
    base_stepover, new_stepover = base_settings.get(_CHANGED_SETTING), new_settings.get(_CHANGED_SETTING)
    if (type(base_stepover) not in (int, float) or type(new_stepover) not in (int, float)
            or not math.isfinite(base_stepover) or not math.isfinite(new_stepover)
            or new_stepover <= base_stepover):
        raise ValueError("Candidate stepover must be finite and greater than the baseline")
    return base_settings, new_settings


def _surface_sweep(program: GCodeProgram, settings: dict):
    config = OrnamentSettings(**settings)
    final_z = -config.engraving_depth
    radius = config.effective_diameter / 2
    segments = [segment for segment in program.segments
                if not segment.rapid and segment.start.z == final_z and segment.end.z == final_z
                and (segment.start.x != segment.end.x or segment.start.y != segment.end.y)]
    if not segments:
        raise ValueError("Exact G-code has no cutting moves at its declared final depth")
    if len(segments) > _MAX_SWEEP_SEGMENTS:
        raise ValueError("Exact G-code exceeds the bounded raster sweep comparison limit")
    paths = [LineString([(item.start.x, item.start.y), (item.end.x, item.end.y)])
             for item in segments]
    centerlines = unary_union(paths)
    return (centerlines.buffer(radius, quad_segs=32),
            centerlines.buffer(radius / math.cos(math.pi / 128), quad_segs=32))


def _coverage(program: GCodeProgram, source: Path, settings: dict) -> dict:
    config = OrnamentSettings(**settings)
    artwork, _ = raster_region(source, config)
    swept, envelope = _surface_sweep(program, settings)
    omitted = artwork.difference(swept).area
    excessive = envelope.difference(artwork).area
    return {
        "source_artwork_mm2": artwork.area,
        "omitted_artwork_mm2": omitted,
        "omitted_artwork_fraction": omitted / artwork.area if artwork.area else 0.0,
        "excess_sweep_mm2": excessive,
        "swept_area_mm2": swept.area,
        "verified_final_depth_surface_sweep": True,
    }


def compare_raster_candidates(baseline_report_path: Path, candidate_report_path: Path,
                              *, max_omission_fraction: float | None = None) -> dict:
    """Compare exact v1 raster bundles while changing only stepover."""
    if max_omission_fraction is not None and (
        isinstance(max_omission_fraction, bool) or not math.isfinite(max_omission_fraction)
        or not 0 <= max_omission_fraction <= 1
    ):
        raise ValueError("Maximum omission fraction must be between 0 and 1")
    baseline, baseline_program, base_design, base_source, source_sha = _read_bundle(baseline_report_path)
    candidate, candidate_program, candidate_design, candidate_source, candidate_source_sha = _read_bundle(candidate_report_path)
    base_settings, candidate_settings = _compare_inputs(base_design, candidate_design, source_sha, candidate_source_sha)
    baseline_coverage = _coverage(baseline_program, base_source, base_settings)
    candidate_coverage = _coverage(candidate_program, candidate_source, candidate_settings)
    baseline_motion = analyze_program(baseline_program)
    candidate_motion = analyze_program(candidate_program)
    time_a = baseline_motion["feed_based_seconds"]
    time_b = candidate_motion["feed_based_seconds"]
    omission_fraction = candidate_coverage["omitted_artwork_fraction"]
    return {
        "schema_version": 1,
        "status": "review-only",
        "changed_setting": _CHANGED_SETTING,
        "fixed_inputs": {"source_sha256": source_sha,
                         "tool": {"type": "V-bit", "included_angle_deg": base_settings["v_angle"],
                                  "tip_diameter_mm": base_settings["tip_diameter"]},
                         "stock_mm": baseline.get("stock_mm"),
                         "origin": baseline.get("origin"),
                         "depth_mm": base_settings["engraving_depth"],
                         "cut_feed_mm_min": base_settings["cut_feed"],
                         "plunge_feed_mm_min": base_settings["plunge_feed"]},
        "baseline": {"report": str(baseline_report_path.resolve()),
                     "gcode_sha256": baseline.get("sha256", {}).get(_PROGRAM),
                     "settings_sha256": baseline.get("sha256", {}).get("design.json"),
                     "stepover_mm": base_settings[_CHANGED_SETTING],
                     "coverage": baseline_coverage, "motion": baseline_motion},
        "candidate": {"report": str(candidate_report_path.resolve()),
                      "gcode_sha256": candidate.get("sha256", {}).get(_PROGRAM),
                      "settings_sha256": candidate.get("sha256", {}).get("design.json"),
                      "stepover_mm": candidate_settings[_CHANGED_SETTING],
                      "coverage": candidate_coverage, "motion": candidate_motion},
        "delta": {
            "commands": candidate_motion["commands"] - baseline_motion["commands"],
            "feed_based_seconds": time_b - time_a,
            "feed_based_percent": ((time_b - time_a) / time_a * 100) if time_a else 0,
            "cut_distance_mm": candidate_motion["cut_distance_mm"] - baseline_motion["cut_distance_mm"],
            "rapid_xy_distance_mm": candidate_motion["rapid_xy_distance_mm"] - baseline_motion["rapid_xy_distance_mm"],
            "rapid_z_distance_mm": candidate_motion["rapid_z_distance_mm"] - baseline_motion["rapid_z_distance_mm"],
            "retract_count": candidate_motion["retract_count"] - baseline_motion["retract_count"],
            "short_cut_segment_percent_points": (candidate_motion["cut_segments_at_most_0_1mm_percent"]
                                                  - baseline_motion["cut_segments_at_most_0_1mm_percent"]),
            "sharp_junction_percent_points": (candidate_motion["cut_junctions_at_least_90_degrees_percent"]
                                               - baseline_motion["cut_junctions_at_least_90_degrees_percent"]),
            "omitted_artwork_fraction": omission_fraction - baseline_coverage["omitted_artwork_fraction"],
        },
        "fidelity_limit": {
            "maximum_omission_fraction": max_omission_fraction,
            "candidate_within_limit": (None if max_omission_fraction is None
                                        else omission_fraction <= max_omission_fraction),
        },
        "runtime_limit": "Feed-based estimate only. Acceleration, junction slowing, and machine calibration are not included.",
    }


def generate_raster_ladder(baseline_report_path: Path, output_root: Path,
                           stepovers: list[float], *, max_omission_fraction: float) -> dict:
    """Generate immutable stepover candidates, preserving even rejected runs."""
    if output_root.exists():
        raise ValueError("Output directory already exists; choose a new ladder directory")
    if not stepovers or any(type(value) not in (int, float) or not math.isfinite(value) or value <= 0
                            for value in stepovers):
        raise ValueError("Provide one or more finite positive stepover values")
    if len(set(stepovers)) != len(stepovers):
        raise ValueError("Stepover values must be unique")
    baseline, _, base_design, base_source, source_sha = _read_bundle(baseline_report_path)
    base_stepover = base_design["settings"].get(_CHANGED_SETTING)
    if any(value <= base_stepover for value in stepovers):
        raise ValueError("Every ladder stepover must be greater than the baseline")
    if isinstance(max_omission_fraction, bool) or not math.isfinite(max_omission_fraction) or not 0 <= max_omission_fraction <= 1:
        raise ValueError("Maximum omission fraction must be between 0 and 1")

    output_root = output_root.absolute()
    output_root.parent.mkdir(parents=True, exist_ok=True)
    comparisons = []
    with tempfile.TemporaryDirectory(prefix="pine-cam-ladder-") as temporary:
        workspace = Path(temporary)
        source_name = base_source.name
        shutil.copyfile(base_source, workspace / source_name)
        staging = Path(tempfile.mkdtemp(prefix=f".{output_root.name}-", dir=output_root.parent))
        try:
            for stepover in sorted(stepovers):
                variant = dict(base_design)
                variant["source"] = source_name
                variant["settings"] = dict(base_design["settings"])
                variant["settings"][_CHANGED_SETTING] = stepover
                spec_path = workspace / f"stepover-{stepover:g}.json"
                spec_path.write_text(json.dumps(variant, indent=2) + "\n", encoding="utf-8")
                candidate_dir = staging / f"stepover-{stepover:g}"
                build(spec_path, candidate_dir)
                comparison = compare_raster_candidates(
                    baseline_report_path, candidate_dir / "report.json",
                    max_omission_fraction=max_omission_fraction,
                )
                comparison_dir = staging / "comparisons"
                comparison_dir.mkdir(exist_ok=True)
                (comparison_dir / f"stepover-{stepover:g}.json").write_text(
                    json.dumps(comparison, indent=2) + "\n", encoding="utf-8"
                )
                comparisons.append({
                    "candidate_directory": candidate_dir.name,
                    "comparison": f"comparisons/stepover-{stepover:g}.json",
                    "gcode_sha256": comparison["candidate"]["gcode_sha256"],
                    "stepover_mm": stepover,
                    "feed_based_seconds": comparison["candidate"]["motion"]["feed_based_seconds"],
                    "omitted_artwork_fraction": comparison["candidate"]["coverage"]["omitted_artwork_fraction"],
                    "fidelity_limit_met": comparison["fidelity_limit"]["candidate_within_limit"],
                })
            result = {"schema_version": 1, "status": "review-only", "baseline": str(baseline_report_path.resolve()),
                      "baseline_gcode_sha256": baseline.get("sha256", {}).get(_PROGRAM),
                      "source_sha256": source_sha, "max_omission_fraction": max_omission_fraction,
                      "candidates": comparisons,
                      "notice": "All candidates remain review-only. Select only a candidate whose fidelity limit is met."}
            (staging / "ladder.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
            staging.replace(output_root)
        except BaseException:
            shutil.rmtree(staging)
            raise
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    compare = sub.add_parser("compare", help="compare exact v1 raster bundle outputs")
    compare.add_argument("baseline", type=Path)
    compare.add_argument("candidate", type=Path)
    compare.add_argument("--max-omission-fraction", type=float)
    ladder = sub.add_parser("ladder", help="generate slower-to-faster stepover candidates")
    ladder.add_argument("baseline", type=Path)
    ladder.add_argument("output", type=Path)
    ladder.add_argument("--stepover-mm", type=float, nargs="+", required=True)
    ladder.add_argument("--max-omission-fraction", type=float, required=True)
    args = parser.parse_args(argv)
    try:
        result = (compare_raster_candidates(args.baseline, args.candidate,
                                            max_omission_fraction=args.max_omission_fraction)
                  if args.command == "compare" else
                  generate_raster_ladder(args.baseline, args.output, args.stepover_mm,
                                         max_omission_fraction=args.max_omission_fraction))
    except (OSError, ValueError, TypeError) as exc:
        parser.exit(2, f"CAM comparison rejected: {exc}\n")
    print(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
