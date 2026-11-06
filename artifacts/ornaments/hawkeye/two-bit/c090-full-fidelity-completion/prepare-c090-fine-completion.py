"""Generate the aligned fine-residual completion after the C-084 broad pass.

Offline only.  This companion restores the approved Hawkeye detail omitted by
the broad-only speed pass; it never connects to Pine or loads/starts a job.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sys

from shapely.geometry import Point
from shapely.ops import unary_union

HERE = Path(__file__).resolve().parent
ROOT = Path(__file__).resolve().parents[5]
C084 = ROOT / "artifacts" / "ornaments" / "hawkeye" / "two-bit" / "c084-runtime-45m" / "01-detail-c084-broad-only-008-review-only.nc"
C069_DIR = ROOT / "artifacts" / "ornaments" / "hawkeye" / "two-bit" / "c069-flow"
C069 = C069_DIR / "01-detail-c069-flow-675-120-review-only.nc"
OUTPUT = HERE / "02-detail-c090-fine-residual-completion-review-only.nc"
REPORT = HERE / "c090-full-fidelity-completion-report.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    sys.path.insert(0, str(ROOT / "src"))
    from ttc3018_control.gcode import parse_gcode, validate_nonnegative_work_xy, validate_rapid_xy_clearance
    from ttc3018_control.job_analysis import analyze_program

    c069 = load_module(C069_DIR / "prepare-c069-flow.py", "c090_c069")
    generator = c069.load_module(c069.SOURCE_SCRIPT, "c090_generator").load_generator()
    source = C069.read_text(encoding="ascii")
    lines = source.rstrip().splitlines()
    first_pass = next(index for index, line in enumerate(lines) if line.startswith("; PASS 1/"))
    fine_start = next(index for index, line in enumerate(lines) if line.startswith("; FINE DETAIL:"))
    if lines[-3:] != [f"G0 Z{generator.SAFE_Z:.4f}", "M5", "M2"]:
        raise AssertionError("C-069 terminal controls changed")
    output = lines[:first_pass]
    output.extend((
        "; C-090 full-fidelity completion after C-084 broad-only sequence",
        "; Run only after the exact matching C-084 0.08 broad pass has completed in this work frame.",
        "; This restores the shallow residual detail; it does not repeat the broad passes.",
    ))
    output.extend(lines[fine_start:])
    text = "\n".join(output) + "\n"
    OUTPUT.write_text(text, encoding="ascii", newline="\n")

    program = parse_gcode(text, OUTPUT)
    validate_nonnegative_work_xy(program)
    validate_rapid_xy_clearance(program, generator.SAFE_Z)
    emitted = generator.emitted_paths_by_depth(text)
    if sorted(emitted) != [-0.04]:
        raise AssertionError(f"Completion must have only the shallow fine pass: {sorted(emitted)}")

    c084_program = parse_gcode(C084.read_text(encoding="ascii"), C084)
    c084_paths = generator.emitted_paths_by_depth(C084.read_text(encoding="ascii"))
    with generator.Image.open(generator.SOURCE) as image:
        image_size = image.size
    approved, _ = generator.raster_region(generator.SOURCE, generator.settings_for(image_size))
    approved = approved.difference(Point(*generator.HOLE_CENTER).buffer(generator.HOLE_KEEPOUT_RADIUS, quad_segs=256))
    broad_diameter = generator.settings_for(image_size).effective_diameter
    fine_diameter = generator.settings_for(image_size, depth=generator.FINE_DEPTH,
                                            stepover=generator.FINE_STEPOVER,
                                            stepdown=generator.FINE_DEPTH).effective_diameter
    broad_sweep = generator.swept(c084_paths[-generator.TARGET_DEPTH], broad_diameter)
    fine_sweep = generator.swept(emitted[-generator.FINE_DEPTH], fine_diameter)
    combined = unary_union((broad_sweep, fine_sweep))
    if not approved.covers(combined):
        raise AssertionError("Combined broad/fine cutter sweep leaves approved artwork")
    report = {
        "schemaVersion": 1,
        "releaseStatus": "offline-review-only; no machine action performed",
        "sequence": {
            "requiredPriorProgram": str(C084.relative_to(ROOT)),
            "requiredPriorSha256": sha256(C084),
            "completionFile": OUTPUT.name,
            "completionSha256": sha256(OUTPUT),
            "sameWorkFrame": "110 mm stock; 100 mm ornament; lower-left XY origin; unchanged 30 degree 0.1 mm V-bit",
        },
        "completion": {
            "commands": len(program.commands),
            "feedBasedEstimateMinutes": program.estimated_seconds / 60,
            "motion": analyze_program(program),
            "depthsMm": sorted(emitted),
            "effectiveFineDiameterMm": fine_diameter,
        },
        "combinedC084BroadPlusC090Fine": {
            "omittedApprovedArtworkMm2": approved.difference(combined).area,
            "omittedApprovedArtworkFraction": approved.difference(combined).area / approved.area,
            "fullDiameterSweepContainedInApprovedArtwork": True,
        },
        "checks": {"parsesExactOutput": True, "nonnegativeWorkXY": True,
                   "rapidXYAtSafeZ": True, "fineOnly": True,
                   "combinedSweepContained": True},
        "limitations": ["Physical execution requires matching completed broad pass, same tool and confirmed work zero.",
                        "Nominal time excludes acceleration, connection, setup and material effects."],
    }
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(report["completion"], indent=2))


if __name__ == "__main__":
    main()
