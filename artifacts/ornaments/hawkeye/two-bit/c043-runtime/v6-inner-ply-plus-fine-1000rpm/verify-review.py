"""Independent offline checks for the deep-plus-fine review candidate."""
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

HERE = Path(__file__).resolve().parent
ROOT = Path(__file__).resolve().parents[6]
sys.path.insert(0, str(ROOT / "src"))
from ttc3018_control.gcode import (  # noqa: E402
    parse_gcode,
    validate_nonnegative_work_xy,
    validate_rapid_xy_clearance,
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def actual_sweeps(gcode: str):
    """Recover the emitted XY paths at each cutting Z from the NC stream."""
    x = y = z = 0.0
    active_depth = None
    active_path = []
    paths_by_depth: dict[float, list[tuple[tuple[float, float], ...]]] = {}

    def close_path():
        nonlocal active_path
        if active_depth is not None and len(active_path) > 1:
            paths_by_depth.setdefault(round(active_depth, 4), []).append(tuple(active_path))
        active_path = []

    for raw in gcode.splitlines():
        line = raw.split(";", 1)[0].strip().upper()
        if not line:
            continue
        motion = line.split(maxsplit=1)[0]
        coords = {axis: float(value) for axis, value in re.findall(r"\b([XYZ])\s*(-?\d+(?:\.\d+)?)", line)}
        if motion == "G0":
            close_path()
            if "X" in coords:
                x = coords["X"]
            if "Y" in coords:
                y = coords["Y"]
            if "Z" in coords:
                z = coords["Z"]
            active_depth = None
        elif motion == "G1":
            if "Z" in coords:
                close_path()
                z = coords["Z"]
                active_depth = round(z, 4) if z < 0 else None
                if active_depth is not None:
                    active_path = [(x, y)]
            if "X" in coords or "Y" in coords:
                if active_depth is not None:
                    nx, ny = coords.get("X", x), coords.get("Y", y)
                    active_path.append((nx, ny))
                if "X" in coords:
                    x = coords["X"]
                if "Y" in coords:
                    y = coords["Y"]
    close_path()
    return paths_by_depth


def sweep(paths, radius: float):
    pieces = [LineString(path).buffer(radius, quad_segs=32) for path in paths]
    if not pieces:
        raise AssertionError("No emitted cutting paths found at the expected depth")
    return unary_union(pieces)


def main() -> None:
    report_path = HERE / "detail-report-vbit30-inner-ply-plus-fine-1000rpm.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    artifact_paths = {key: ROOT / entry["path"] for key, entry in report["artifacts"].items()}
    for key, path in artifact_paths.items():
        if sha256(path) != report["artifacts"][key]["sha256"]:
            raise AssertionError(f"{key} SHA-256 mismatch")

    gcode = artifact_paths["gcode"].read_text(encoding="ascii")
    base_gcode = artifact_paths["baseCandidate"].read_text(encoding="ascii")
    base_lines = base_gcode.rstrip().splitlines()
    candidate_lines = gcode.rstrip().splitlines()
    expected_prefix = base_lines[:-3]
    expected_prefix = [
        "; Approved thresholded artwork; deep broad passes copied unchanged from v5, followed by shallow residual detail"
        if line == "; Approved thresholded artwork only; broad-only, fine detail intentionally omitted"
        else line
        for line in expected_prefix
    ]
    if candidate_lines[:len(expected_prefix)] != expected_prefix:
        raise AssertionError("Deep broad NC prefix differs from the loaded v5 candidate")
    program = parse_gcode(gcode, artifact_paths["gcode"])
    validate_nonnegative_work_xy(program)
    validate_rapid_xy_clearance(program, report["motion"]["safeZMm"])
    executable = "\n".join(line.split(";", 1)[0] for line in gcode.splitlines())
    counts = {
        "m5": len(re.findall(r"\bM\s*5\b", executable, re.IGNORECASE)),
        "m3": len(re.findall(r"\bM\s*3\b", executable, re.IGNORECASE)),
        "m6": len(re.findall(r"\bM\s*6\b", executable, re.IGNORECASE)),
        "program_end": len(re.findall(r"\bM\s*(?:2|30)\b", executable, re.IGNORECASE)),
    }
    expected_commands = {"m5": 1, "m3": 1, "m6": 0, "program_end": 1}
    if counts != expected_commands:
        raise AssertionError(f"Unexpected machine-control commands: {counts}")
    executable_lines = [line.strip() for line in executable.splitlines() if line.strip()]
    if executable_lines[:3] != ["G21 G17 G90 G94 G54", "G0 Z3.0000", "M3 S1000"]:
        raise AssertionError("Stream-compatible opening changed")
    if executable_lines[-2:] != ["M5", "M2"] or "G4 P2.000" not in executable_lines:
        raise AssertionError("Spindle dwell or final safety commands are missing")
    plunge_lines = [line for line in executable_lines if line.startswith("G1 Z-")]
    actual_passes = sorted({round(abs(float(re.search(r"Z(-?\d+\.\d+)", line).group(1))), 4) for line in plunge_lines})
    expected_passes = [0.04, 0.6, 1.2, 1.625]
    if actual_passes != expected_passes:
        raise AssertionError(f"Unexpected broad/fine depth levels: {actual_passes}")
    if any("F160.0000" not in line for line in plunge_lines):
        raise AssertionError("Plunge feed differs from 160 mm/min")
    xy_cut_lines = [line for line in executable_lines if line.startswith("G1 ") and re.search(r"\b[XY]\s*", line)]
    if not xy_cut_lines or any("F600.0000" not in line for line in xy_cut_lines):
        raise AssertionError("Cut feed differs from 600 mm/min")
    if program.bounds.minimum.z != -1.625 or program.bounds.maximum.z != 3.0:
        raise AssertionError("Parser depth or clearance bounds differ from the candidate")
    if program.bounds.minimum.x < 0 or program.bounds.minimum.y < 0 or program.bounds.maximum.x > 110.001 or program.bounds.maximum.y > 110.001:
        raise AssertionError("Parsed work bounds leave the 110 x 110 stock")
    motion = report["motion"]
    bounds = motion["parserBoundsMm"]
    actual_bounds = (
        [program.bounds.minimum.x, program.bounds.minimum.y, program.bounds.minimum.z],
        [program.bounds.maximum.x, program.bounds.maximum.y, program.bounds.maximum.z],
    )
    if any(abs(a - b) > 1e-8 for row, expected in zip(actual_bounds, (bounds["minimum"], bounds["maximum"])) for a, b in zip(row, expected)):
        raise AssertionError("Parser bounds differ from the report")
    if len(gcode.splitlines()) != motion["gcodeLineCount"]:
        raise AssertionError("G-code line count differs from the report")
    estimated_minutes = program.estimated_seconds / 60
    if abs(estimated_minutes - motion["estimatedMinutes"]) > 1e-8:
        raise AssertionError("Parser timing differs from the report")

    preview = artifact_paths["preview"].read_text(encoding="utf-8")
    if '#176b91' not in preview or '#d28b16' not in preview or "0.04" not in preview:
        raise AssertionError("SVG preview does not display both broad and fine passes")

    # Check the paths actually emitted in the NC against the approved source,
    # including a conservative envelope for endpoint quantization.
    generator_path = artifact_paths["generator"]
    spec = importlib.util.spec_from_file_location("v6_generator", generator_path)
    generator = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(generator)
    image_size = tuple(report["source"]["imageSizePx"])
    settings = generator.settings_for(image_size)
    source_region, _ = generator.raster_region(generator.SOURCE, settings)
    keepout = Point(*generator.HOLE_CENTER).buffer(generator.HOLE_KEEPOUT_RADIUS, quad_segs=256)
    work_region = source_region.difference(keepout)
    paths_by_depth = actual_sweeps(gcode)
    broad_diameter = report["broadStage"]["effectiveDiameterAtFinalDepthMm"]
    fine_diameter = report["fineStage"]["effectiveDiameterMm"]
    guard = 1 / math.cos(math.pi / 128)
    broad_sweep = sweep(paths_by_depth[-1.625], broad_diameter / 2)
    fine_sweep = sweep(paths_by_depth[-0.04], fine_diameter / 2)
    broad_guard = sweep(paths_by_depth[-1.625], (broad_diameter / 2) * guard)
    fine_guard = sweep(paths_by_depth[-0.04], (fine_diameter / 2) * guard)
    combined = unary_union((broad_sweep, fine_sweep))
    stock = box(0, 0, 110, 110)
    for label, footprint in (("broad", broad_guard), ("fine", fine_guard)):
        if not source_region.covers(footprint) or not work_region.covers(footprint):
            raise AssertionError(f"Actual emitted {label} sweep leaves approved art or enters the hanger keepout")
        if not stock.buffer(0.001).covers(footprint):
            raise AssertionError(f"Actual emitted {label} sweep leaves stock")
    omitted = work_region.difference(combined).area
    omitted_percent = 100 * omitted / work_region.area
    if abs(omitted - report["coverage"]["approvedBlackOmittedMm2"]) > 0.1:
        raise AssertionError(
            f"Recomputed combined sweep omission differs from the report: "
            f"actual={omitted:.6f}, reported={report['coverage']['approvedBlackOmittedMm2']:.6f}, "
            f"pathCounts={len(paths_by_depth[-1.625])}/{len(paths_by_depth[-0.04])}"
        )
    if not all(report["offlineChecks"].values()):
        raise AssertionError("Generator report includes a failed offline check")

    verification = {
        "result": "passed",
        "scope": "NC hashes, emitted sweep coverage, app parser, bounds, feeds, depths, spindle commands, SVG preview and estimated timing",
        "releaseStatus": report["releaseStatus"],
        "gcodeSha256": report["artifacts"]["gcode"]["sha256"],
        "previewSvgSha256": report["artifacts"]["preview"]["sha256"],
        "generatorSha256": report["artifacts"]["generator"]["sha256"],
        "depthPassesMm": [-0.6, -1.2, -1.625, -0.04],
        "cutFeedMmPerMin": 600,
        "plungeFeedMmPerMin": 160,
        "spindleRpm": 1000,
        "controlCommands": counts,
        "lineCount": len(gcode.splitlines()),
        "estimatedMinutes": round(estimated_minutes, 3),
        "availableBlackOmittedMm2Recomputed": round(omitted, 4),
        "availableBlackOmittedPercentRecomputed": round(omitted_percent, 3),
        "streamSweepsContainedInApprovedArt": True,
        "rapidXYClearanceMm": motion["safeZMm"],
        "parserBoundsMm": bounds,
        "hashesVerified": list(artifact_paths),
    }
    (HERE / "independent-verification.json").write_text(json.dumps(verification, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(verification, indent=2))


if __name__ == "__main__":
    main()
