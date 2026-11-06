"""Generate a review-only fidelity/runtime ladder for the Hawkeye fine pass.

The exact C-084 0.08 mm broad passes are held fixed. Only the shallow C-069
fine-residual vectors are simplified, and every changed cutter footprint is
checked against the approved artwork before exact G-code is emitted.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sys

from shapely.geometry import LineString, Point, box
from shapely.ops import unary_union

HERE = Path(__file__).resolve().parent
ROOT = Path(__file__).resolve().parents[5]
TWO_BIT = ROOT / "artifacts" / "ornaments" / "hawkeye" / "two-bit"
C069_DIR = TWO_BIT / "c069-flow"
C069_NC = C069_DIR / "01-detail-c069-flow-675-120-review-only.nc"
C084_DIR = TWO_BIT / "c084-runtime-45m"
C084_NC = C084_DIR / "01-detail-c084-broad-only-008-review-only.nc"
RUNTIME_PROFILE_KEY = "cnc3018-stock-spindle-vbit30-0.1-plywood3.25-cut675-plunge120-s1000"
ASPIRATIONAL_RUNTIME_MINUTES = 45.0
FINE_TOLERANCES_MM = (0.04, 0.08, 0.12, 0.20, 0.32)


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


def write_preview(path: Path, art, sweep, omitted, tolerance: float) -> None:
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="110mm" height="110mm" viewBox="0 0 110 110">
<title>C-088 fine-pass fidelity ladder, {tolerance:.2f} mm chord tolerance</title>
<desc>Physical scale 110 mm stock. Dark gray is approved artwork; blue is the emitted combined C-084 broad and C-088 fine cutter sweep; amber is artwork omitted at full depth; red circle is the hanger keepout.</desc>
<rect width="110" height="110" fill="#fff"/>
<g transform="translate(0 110) scale(1 -1)">
<path d="{geometry_path(art)}" fill="#303640" fill-rule="evenodd"/>
<path d="{geometry_path(omitted)}" fill="#E5A02E" fill-rule="evenodd" opacity="0.95"/>
<path d="{geometry_path(sweep)}" fill="#4E8CF7" fill-rule="evenodd" opacity="0.95"/>
<circle cx="55" cy="100" r="3" fill="none" stroke="#D84A4A" stroke-width="0.15"/>
</g>
<text x="2" y="4" font-size="1.8">C-088 review only · fixed C-084 broad + fine residual · {tolerance:.2f} mm chord tolerance</text>
<text x="2" y="108" font-size="1.8">Blue: emitted full-width sweep · amber: omitted artwork · scale: 110 mm</text>
</svg>'''
    path.write_text(svg, encoding="utf-8", newline="\n")


def candidate_name(index: int, tolerance: float) -> str:
    return f"{index:02d}-fine-tolerance-{int(round(tolerance * 1000)):03d}-review-only.nc"


def build_candidate(c069, source_lines, broad_paths, fine_paths, levels, safe_z, approach_z,
                   tolerance: float) -> str:
    text = c069.build_gcode(source_lines, broad_paths, fine_paths, levels, safe_z, approach_z)
    text = text.replace(
        "; C-069 guarded-vector feed comparison candidate",
        f"; C-088 fixed-broad fine-residual candidate; {tolerance:.2f} mm guarded chord tolerance",
    )
    return text


def main() -> None:
    sys.path.insert(0, str(ROOT / "src"))
    from ttc3018_control.gcode import (
        parse_gcode,
        validate_nonnegative_work_xy,
        validate_rapid_xy_clearance,
    )
    from ttc3018_control.job_analysis import analyze_program
    from ttc3018_control.performance_budget import estimate_runtime_with_calibration

    c069 = load_module(C069_DIR / "prepare-c069-flow.py", "c088_c069")
    generator = c069.load_module(c069.SOURCE_SCRIPT, "c088_source").load_generator()
    c069_text = C069_NC.read_text(encoding="ascii")
    c084_text = C084_NC.read_text(encoding="ascii")
    c069_lines = c069_text.rstrip().splitlines()
    c069_paths = generator.emitted_paths_by_depth(c069_text)
    c084_paths = generator.emitted_paths_by_depth(c084_text)
    levels = generator.depth_levels(generator.TARGET_DEPTH, generator.MAX_STEPDOWN)
    expected_depths = sorted([-value for value in levels] + [-generator.FINE_DEPTH])
    if sorted(c069_paths) != expected_depths:
        raise AssertionError(f"Unexpected C-069 depth set: {sorted(c069_paths)}")
    if sorted(c084_paths) != sorted(-value for value in levels):
        raise AssertionError(f"Unexpected C-084 depth set: {sorted(c084_paths)}")

    broad_paths = c084_paths[-generator.TARGET_DEPTH]
    fine_source = c069_paths[-generator.FINE_DEPTH]
    if any(tuple(c084_paths[-depth]) != tuple(broad_paths) for depth in levels):
        raise AssertionError("C-084 broad geometry differs between depth passes")

    with generator.Image.open(generator.SOURCE) as image:
        image_size = image.size
    art, pixel_size = generator.raster_region(
        generator.SOURCE, generator.settings_for(image_size)
    )
    keepout = Point(*generator.HOLE_CENTER).buffer(
        generator.HOLE_KEEPOUT_RADIUS, quad_segs=256
    )
    approved = art.difference(keepout)
    stock = box(0, 0, generator.STOCK, generator.STOCK)
    broad_diameter = generator.settings_for(image_size).effective_diameter
    fine_diameter = generator.settings_for(
        image_size,
        depth=generator.FINE_DEPTH,
        stepover=generator.FINE_STEPOVER,
        stepdown=generator.FINE_DEPTH,
    ).effective_diameter
    broad_sweep = generator.swept(broad_paths, broad_diameter)
    broad_guard = generator.swept(broad_paths, broad_diameter, conservative=True)
    if not approved.covers(broad_guard) or not stock.covers(broad_guard):
        raise AssertionError("Exact C-084 broad sweep is outside approved art or stock")

    baseline_fine_sweep = generator.swept(fine_source, fine_diameter)
    baseline_combined = unary_union((broad_sweep, baseline_fine_sweep))
    if not approved.covers(generator.swept(fine_source, fine_diameter, conservative=True)):
        raise AssertionError("Baseline C-069 fine sweep is outside approved artwork")

    baseline_text = build_candidate(
        c069, c069_lines, broad_paths, fine_source, levels,
        generator.SAFE_Z, generator.APPROACH_Z, FINE_TOLERANCES_MM[0],
    )
    baseline_program = parse_gcode(baseline_text)
    baseline_motion = analyze_program(baseline_program)
    variants = []

    for index, tolerance in enumerate(FINE_TOLERANCES_MM, start=1):
        fine_paths = (
            tuple(fine_source)
            if index == 1
            else c069.simplify_paths(fine_source, tolerance, approved, fine_diameter)
        )
        text = build_candidate(
            c069, c069_lines, broad_paths, fine_paths, levels,
            generator.SAFE_Z, generator.APPROACH_Z, tolerance,
        )
        nc_path = HERE / candidate_name(index, tolerance)
        nc_path.write_text(text, encoding="ascii", newline="\n")
        program = parse_gcode(text, nc_path)
        validate_nonnegative_work_xy(program)
        validate_rapid_xy_clearance(program, generator.SAFE_Z)
        emitted = generator.emitted_paths_by_depth(text)
        if sorted(emitted) != expected_depths:
            raise AssertionError(f"Unexpected candidate depth set: {sorted(emitted)}")
        if any(tuple(emitted[-depth]) != tuple(broad_paths) for depth in levels):
            raise AssertionError("Candidate changed the exact C-084 broad paths")
        if tuple(emitted[-generator.FINE_DEPTH]) != tuple(fine_paths):
            raise AssertionError("Fine G-code does not match the candidate geometry")
        if text.rstrip().splitlines()[-3:] != [
            f"G0 Z{generator.SAFE_Z:.4f}", "M5", "M2"
        ]:
            raise AssertionError("Candidate terminal commands changed")

        fine_sweep = generator.swept(fine_paths, fine_diameter)
        fine_guard = generator.swept(fine_paths, fine_diameter, conservative=True)
        combined = unary_union((broad_sweep, fine_sweep))
        combined_guard = unary_union((broad_guard, fine_guard))
        if not approved.covers(combined_guard):
            raise AssertionError("Full-width candidate sweep leaves approved artwork/keepout")
        if not stock.covers(combined_guard):
            raise AssertionError("Full-width candidate sweep leaves stock")
        omitted = approved.difference(combined)
        motion = analyze_program(program)
        runtime = estimate_runtime_with_calibration(
            program.estimated_seconds,
            machine_profile_key=RUNTIME_PROFILE_KEY,
            calibration=None,
            target_minutes=ASPIRATIONAL_RUNTIME_MINUTES,
        )
        preview_path = HERE / f"fine-tolerance-{int(round(tolerance * 1000)):03d}.svg"
        write_preview(preview_path, approved, combined, omitted, tolerance)
        candidate = {
            "file": nc_path.name,
            "sha256": sha256(nc_path),
            "preview": {"file": preview_path.name, "sha256": sha256(preview_path)},
            "fineChordToleranceMm": tolerance,
            "tool": {
                "angleDeg": 30.0,
                "tipDiameterMm": 0.1,
                "broadEffectiveDiameterAtFinalDepthMm": broad_diameter,
                "fineEffectiveDiameterMm": fine_diameter,
                "physicalToolConditionVerified": False,
            },
            "depthPassesMm": expected_depths,
            "motion": {
                "commands": motion["commands"],
                "feedBasedEstimateMinutes": program.estimated_seconds / 60,
                "nominalRuntimeEstimate": runtime,
                "cutSegments": motion["nonzero_cut_segments"],
                "cutDistanceMm": motion["cut_distance_mm"],
                "medianCutSegmentMm": motion["median_cut_segment_mm"],
                "p95CutSegmentMm": motion["p95_cut_segment_mm"],
                "cutSegmentsAtMost0p1Mm": motion["cut_segments_at_most_0_1mm"],
                "cutSegmentsAtMost0p1MmPercent": motion["cut_segments_at_most_0_1mm_percent"],
                "cutJunctions": motion["cut_junctions"],
                "cutJunctionsAtLeast90Deg": motion["cut_junctions_at_least_90_degrees"],
                "cutJunctionsAtLeast90DegPercent": motion["cut_junctions_at_least_90_degrees_percent"],
                "cutJunctionsAtLeast135Deg": motion["cut_junctions_at_least_135_degrees"],
                "retractCount": motion["retract_count"],
                "rapidXYDistanceMm": motion["rapid_xy_distance_mm"],
                "estimateLimit": motion["estimate_limits"],
            },
            "coverage": {
                "availableArtworkMm2": approved.area,
                "fullDiameterCombinedSweepMm2": combined.area,
                "omittedArtworkMm2": omitted.area,
                "omittedArtworkFraction": omitted.area / approved.area if approved.area else 0.0,
                "omittedIncreaseVersusFullFidelityMm2": baseline_combined.difference(combined).area,
                "additionalSweepVersusFullFidelityMm2": combined.difference(baseline_combined).area,
                "combinedSweepSymmetricDifferenceVersusFullFidelityMm2": combined.symmetric_difference(baseline_combined).area,
                "conservativeFullWidthSweepContainedInApprovedArtAndStock": True,
            },
            "deltaVersusFullFidelity": {
                "commands": motion["commands"] - baseline_motion["commands"],
                "feedBasedEstimateMinutes": program.estimated_seconds / 60 - baseline_program.estimated_seconds / 60,
                "cutSegments": motion["nonzero_cut_segments"] - baseline_motion["nonzero_cut_segments"],
                "cutJunctions": motion["cut_junctions"] - baseline_motion["cut_junctions"],
                "retracts": motion["retract_count"] - baseline_motion["retract_count"],
            },
            "checks": {
                "exactFileParses": True,
                "nonnegativeWorkXY": True,
                "rapidXYAtSafeZ": True,
                "C084BroadPassGeometryUnchangedAtEveryDepth": True,
                "finePassMatchesReportedCandidateGeometry": True,
                "conservativeFullWidthSweepContained": True,
                "stockBoundsContained": True,
                "terminalM5AndM2Preserved": True,
            },
        }
        variants.append(candidate)

    report_path = HERE / "c088-fine-fidelity-ladder-report.json"
    report = {
        "schemaVersion": 1,
        "releaseStatus": "offline-review-only; no machine interaction or cutting authorization",
        "inputs": {
            "fullFidelityFineSource": str(C069_NC.relative_to(ROOT)),
            "fullFidelityFineSourceSha256": sha256(C069_NC),
            "fixedBroadProgram": str(C084_NC.relative_to(ROOT)),
            "fixedBroadProgramSha256": sha256(C084_NC),
            "sourceArtworkSha256": sha256(generator.SOURCE),
            "sourcePixelSizeMm": pixel_size,
        },
        "fixedSetup": {
            "stockMm": [generator.STOCK, generator.STOCK],
            "measuredThicknessMm": 3.25,
            "ornamentDiameterMm": 100.0,
            "workOrigin": "lower-left; same C-069/C-084 110 mm stock frame",
            "tool": {"includedAngleDeg": 30.0, "tipDiameterMm": 0.1, "conditionVerified": False},
            "spindleCommandRpm": 1000,
            "cutFeedMmPerMin": c069.CUT_FEED,
            "plungeFeedMmPerMin": c069.PLUNGE_FEED,
            "fixedBroadPassesMm": expected_depths[:-1],
            "fineDepthMm": -generator.FINE_DEPTH,
        },
        "method": {
            "changedParameter": "fine-path guarded chord simplification tolerance only",
            "tolerancesMm": list(FINE_TOLERANCES_MM),
            "broadGeometry": "Exact emitted C-084 0.08 mm broad paths reused at all three depths",
            "fineGeometry": "The 0.04 mm rung reuses the exact C-069 residual path; later rungs apply greater chord simplification with full-width conservative cutter containment in approved thresholded art",
            "coverageMetric": "Exact parsed-path full-diameter sweeps; omissions and sweep differences are relative to the 0.04 mm full-fidelity reference",
            "runtimeTargetMinutes": ASPIRATIONAL_RUNTIME_MINUTES,
            "runtimeCaveat": "Nominal feed-based estimates exclude acceleration, junction slowing, controller streaming, setup, material and physical calibration; 45 minutes is aspirational only.",
        },
        "variants": variants,
    }
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")

    rows = []
    for item in variants:
        motion = item["motion"]
        rows.append(
            f"| {item['fineChordToleranceMm']:.2f} | `{item['file']}` | "
            f"{motion['commands']:,} | {motion['feedBasedEstimateMinutes']:.2f} | "
            f"{motion['cutSegments']:,} | {motion['cutJunctionsAtLeast90DegPercent']:.1f}% | "
            f"{motion['retractCount']:,} | {item['coverage']['omittedArtworkMm2']:.2f} | "
            f"{item['coverage']['omittedIncreaseVersusFullFidelityMm2']:.2f} | "
            f"[SVG]({item['preview']['file']}) |"
        )
    readme = f"""# C-088 Hawkeye fine-residual fidelity/runtime ladder

This reproducible, offline review ladder preserves the exact C-084 0.08 mm
broad-pass geometry at Z−0.6, −1.2 and −1.625 mm, and progressively simplifies
only the C-069 shallow residual pass at Z−0.04 mm. All five rungs use the same
approved artwork, 110 mm stock frame, 100 mm ornament, 30°/0.1 mm V-bit,
675/120 mm/min feeds and 1000 RPM spindle command. Each exact combined G-code
file is review-only; no machine was contacted and no candidate is approved for
cutting.

| Fine chord tolerance (mm) | Exact file | Commands | Nominal min | Cut segments | ≥90° junctions | Retracts | Omitted art (mm²) | Additional omission vs full detail (mm²) | Sweep preview |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---|
{chr(10).join(rows)}

`omitted art` is the area of approved artwork not reached by the combined
full-diameter C-084 broad plus candidate fine sweep. `Additional omission`
measures only the full-fidelity sweep not covered by that candidate; the
separate symmetric-difference fields in the JSON report also show any new
sweep area. The guard checks use conservative full-width cutter buffers and
reject any rung that leaves the approved art, hanger keepout, or stock.

Command counts, cutting-segment/junction statistics, retracts, rapid distance,
exact output SHA-256 values and nominal projections are in
[`c088-fine-fidelity-ladder-report.json`](c088-fine-fidelity-ladder-report.json).
The nominal runtime excludes acceleration, corner slowing, streaming, setup
and material effects. The 45-minute target is aspirational, not a measured ETA.
The physical condition of the V-bit has not been verified.

Regenerate all exact candidates, previews and the report from the repository
root:

```powershell
.\\.venv\\Scripts\\python.exe artifacts\\ornaments\\hawkeye\\two-bit\\c088-detail-ladder\\prepare-c088-fine-ladder.py
```

The script imports the reviewed C-069 path simplifier, checks every emitted
file after serialization, verifies that all broad paths are identical to the
C-084 input at each broad depth, and verifies conservative full-width sweep
containment. It does not load or start a job.
"""
    (HERE / "README.md").write_text(readme, encoding="utf-8", newline="\n")
    print(json.dumps({
        "report": str(report_path.relative_to(ROOT)),
        "variants": [
            {
                "file": item["file"],
                "sha256": item["sha256"],
                "commands": item["motion"]["commands"],
                "nominalMinutes": item["motion"]["feedBasedEstimateMinutes"],
                "omittedArtworkMm2": item["coverage"]["omittedArtworkMm2"],
                "additionalOmissionMm2": item["coverage"]["omittedIncreaseVersusFullFidelityMm2"],
            }
            for item in variants
        ],
    }, indent=2))


if __name__ == "__main__":
    main()
