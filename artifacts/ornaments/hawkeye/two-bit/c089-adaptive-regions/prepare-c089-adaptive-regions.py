"""Prepare an offline, component-local adaptive Hawkeye broad-pass candidate.

Every compensated engraving component is completed before the next.  The
planner prefers concentric offset rings when their rounded full-cutter sweep
covers the component; it falls back to local scanlines otherwise.  This script
never connects to Pine or changes a running job.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys
from dataclasses import replace

from shapely.geometry import Point, box
from shapely.ops import unary_union

HERE = Path(__file__).resolve().parent
ROOT = Path(__file__).resolve().parents[5]
C084_DIR = HERE.parent / "c084-runtime-45m"
C084_NC = C084_DIR / "01-detail-c084-broad-only-008-review-only.nc"
OUTPUT_NC = HERE / "01-detail-c089-adaptive-regions-review-only.nc"
REPORT = HERE / "c089-adaptive-regions-report.json"
PREVIEW = HERE / "c089-adaptive-regions-preview.svg"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    sys.path.insert(0, str(ROOT / "src"))
    from ttc3018_control.gcode import parse_gcode, validate_nonnegative_work_xy, validate_rapid_xy_clearance
    from ttc3018_control.job_analysis import analyze_program
    from ttc3018_control.ornament_cam import plan_adaptive_region_engraving

    c084 = load_module(C084_DIR / "prepare-c084-broad-only.py", "c089_c084")
    c069 = c084.load_module(c084.SOURCE_DIR / "prepare-c069-flow.py", "c089_c069")
    generator = c069.load_module(c069.SOURCE_SCRIPT, "c089_generator").load_generator()
    source_text = c084.SOURCE_NC.read_text(encoding="ascii")
    source_lines = source_text.rstrip().splitlines()
    baseline = parse_gcode(C084_NC.read_text(encoding="ascii"), C084_NC)

    with generator.Image.open(generator.SOURCE) as image:
        image_size = image.size
    source_settings = generator.settings_for(image_size)
    # Offset pockets need not use the source raster's very fine 0.27 mm lane
    # spacing.  This remains inside the exporter's 80%-of-tool-width coverage
    # limit, while making the topology comparison meaningful.
    radial_stepover = source_settings.effective_diameter * 0.75
    settings = replace(source_settings, stepover=radial_stepover)
    source_region, pixel_size = generator.raster_region(generator.SOURCE, settings)
    keepout = Point(*generator.HOLE_CENTER).buffer(generator.HOLE_KEEPOUT_RADIUS, quad_segs=256)
    approved = source_region.difference(keepout)
    stock = box(0, 0, generator.STOCK, generator.STOCK)
    raw_paths, _, strategy = plan_adaptive_region_engraving(approved, settings)
    # Offset rings inherit the image's pixel staircase.  Apply the same
    # full-cutter-contained chord simplifier used by C-069 before comparing
    # controller workload; it may never replace a ring segment with a chord
    # whose final-depth cutter footprint enters white artwork.
    paths = c069.simplify_paths(raw_paths, c069.BROAD_TOLERANCE_MM, approved,
                                settings.effective_diameter)
    strategy["raw_paths_before_guarded_chord_simplification"] = len(raw_paths)
    strategy["paths_after_guarded_chord_simplification"] = len(paths)
    levels = generator.depth_levels(generator.TARGET_DEPTH, generator.MAX_STEPDOWN)
    text = c084.candidate_gcode(c069, source_lines, paths, 0.0, levels,
                                generator.SAFE_Z, generator.APPROACH_Z)
    text = text.replace(
        "; C-084 broad-only candidate; guarded chord tolerance 0.00 mm",
        "; C-089 component-local adaptive candidate; concentric offsets with scanline fallback",
    ).replace(
        "; The fine residual stage is omitted to reduce command count; artwork loss is quantified in c084-runtime-report.json",
        "; Fine residual stage is omitted; this compares broad-pass path topology only.",
    )
    OUTPUT_NC.write_text(text, encoding="ascii", newline="\n")

    program = parse_gcode(text, OUTPUT_NC)
    validate_nonnegative_work_xy(program)
    validate_rapid_xy_clearance(program, generator.SAFE_Z)
    emitted = generator.emitted_paths_by_depth(text)
    if sorted(emitted) != [-1.625, -1.2, -0.6]:
        raise AssertionError(f"Unexpected depth set: {sorted(emitted)}")
    if not (tuple(emitted[-0.6]) == tuple(emitted[-1.2]) == tuple(emitted[-1.625]) == paths):
        raise AssertionError("Adaptive geometry differs across broad depth passes")
    diameter = settings.effective_diameter
    sweep = generator.swept(paths, diameter)
    if not approved.covers(sweep) or not stock.covers(sweep):
        raise AssertionError("Adaptive full-diameter sweep leaves approved artwork or stock")
    omission = approved.difference(sweep)
    c084.write_preview(PREVIEW, approved, sweep, omission, tolerance=0.0)

    candidate_analysis = analyze_program(program)
    baseline_analysis = analyze_program(baseline)
    report = {
        "schemaVersion": 1,
        "releaseStatus": "offline-review-only; not loaded or authorized for cutting",
        "strategy": {
            "componentOrder": "complete one connected compensated region before moving to the next",
            "preferred": "concentric inward offsets",
            "fallback": "boundary plus local alternating scanlines when rounded offset sweeps do not cover a component",
            **strategy,
        },
        "inputs": {
            "source": str(generator.SOURCE.relative_to(ROOT)),
            "sourceSha256": sha256(generator.SOURCE),
            "sourcePixelSizeMm": pixel_size,
            "baseline": str(C084_NC.relative_to(ROOT)),
            "baselineSha256": sha256(C084_NC),
            "stockMm": [generator.STOCK, generator.STOCK, 3.25],
            "tool": {"includedAngleDeg": 30.0, "tipDiameterMm": 0.1,
                     "effectiveDiameterAtFinalDepthMm": diameter},
            "adaptiveRadialStepoverMm": radial_stepover,
            "depthPassesMm": [-value for value in levels],
            "feedMmPerMin": {"cut": c069.CUT_FEED, "plunge": c069.PLUNGE_FEED},
            "spindleCommandRpm": 1000,
        },
        "candidate": {
            "file": OUTPUT_NC.name, "sha256": sha256(OUTPUT_NC),
            "preview": {"file": PREVIEW.name, "sha256": sha256(PREVIEW)},
            "commands": len(program.commands),
            "feedBasedEstimateMinutes": program.estimated_seconds / 60,
            "motion": candidate_analysis,
            "fullDiameterSweepMm2": sweep.area,
            "omittedApprovedArtworkMm2": omission.area,
            "omittedApprovedArtworkFraction": omission.area / approved.area,
        },
        "comparisonWithC084BroadOnly008": {
            "commands": {"baseline": len(baseline.commands), "candidate": len(program.commands),
                         "delta": len(program.commands) - len(baseline.commands)},
            "feedBasedMinutes": {"baseline": baseline.estimated_seconds / 60,
                                 "candidate": program.estimated_seconds / 60,
                                 "delta": program.estimated_seconds / 60 - baseline.estimated_seconds / 60},
            "motion": {"baseline": baseline_analysis, "candidate": candidate_analysis},
        },
        "checks": {
            "parsesExactOutput": True,
            "nonnegativeWorkXY": True,
            "rapidXYAtSafeZ": True,
            "sameThreeBroadDepths": True,
            "identicalGeometryEachBroadDepth": True,
            "fullDiameterSweepContainedInApprovedArtAndStock": True,
        },
        "limitations": [
            "This is a broad-only comparison: the shallow fine residual pass remains omitted.",
            "Nominal time excludes acceleration, corner slowdown, controller throughput and setup.",
            "No physical machine, backend, GUI or job state was changed.",
        ],
    }
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"candidate": report["candidate"], "strategy": report["strategy"],
                      "comparison": report["comparisonWithC084BroadOnly008"]["commands"]}, indent=2))


if __name__ == "__main__":
    main()
