"""Independently recheck the offline deep-engraving candidate; no hardware access."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
import sys

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


def main() -> None:
    report_path = HERE / "detail-report-vbit30-inner-ply-1p625mm-1000rpm.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    artifact_paths = {
        key: ROOT / entry["path"]
        for key, entry in report["artifacts"].items()
    }
    for key, path in artifact_paths.items():
        expected = report["artifacts"][key]["sha256"]
        actual = sha256(path)
        if actual != expected:
            raise AssertionError(f"{key} SHA-256 mismatch")

    nc_path = artifact_paths["gcode"]
    gcode = nc_path.read_text(encoding="ascii")
    program = parse_gcode(gcode, nc_path)
    validate_nonnegative_work_xy(program)
    validate_rapid_xy_clearance(program, report["motion"]["safeZMm"])
    executable = [line.split(";", 1)[0].strip() for line in gcode.splitlines() if line.strip() and not line.lstrip().startswith(";")]
    counts = {
        "m5": len(re.findall(r"\bM\s*5\b", "\n".join(executable), re.IGNORECASE)),
        "m3": len(re.findall(r"\bM\s*3\b", "\n".join(executable), re.IGNORECASE)),
        "m6": len(re.findall(r"\bM\s*6\b", "\n".join(executable), re.IGNORECASE)),
        "program_end": len(re.findall(r"\bM\s*(?:2|30)\b", "\n".join(executable), re.IGNORECASE)),
    }
    if counts != {"m5": 1, "m3": 1, "m6": 0, "program_end": 1}:
        raise AssertionError(f"Unexpected machine-control commands: {counts}")
    if executable[:3] != ["G21 G17 G90 G94 G54", "G0 Z3.0000", "M3 S1000"] or executable[-2:] != ["M5", "M2"]:
        raise AssertionError("Stream-compatible opening or final safety commands changed")
    if "G4 P2.000" not in executable:
        raise AssertionError("Spindle startup dwell is missing")

    expected_passes = [0.6, 1.2, 1.625]
    plunge_lines = [line for line in executable if line.startswith("G1 Z-")]
    actual_passes = sorted({round(abs(float(re.search(r"Z(-?[0-9]+\.[0-9]+)", line).group(1))), 4) for line in plunge_lines})
    if actual_passes != expected_passes:
        raise AssertionError(f"Unexpected depth pass levels: {actual_passes}")
    if any("F160.0000" not in line for line in plunge_lines):
        raise AssertionError("Plunge feed differs from 160 mm/min")
    xy_cut_lines = [line for line in executable if line.startswith("G1 ") and re.search(r"\b[XY]\s*", line)]
    if not xy_cut_lines or any("F600.0000" not in line for line in xy_cut_lines):
        raise AssertionError("XY cut feed differs from 600 mm/min")
    max_stepdown = max(b - a for a, b in zip([0.0, *expected_passes[:-1]], expected_passes))
    if max_stepdown > 0.6 + 1e-9:
        raise AssertionError("A broad depth increment exceeds 0.6 mm")
    pass_diameters = [0.1 + 2 * depth * math.tan(math.radians(15.0)) for depth in expected_passes]
    if any(0.27 > diameter * 0.8 for diameter in pass_diameters):
        raise AssertionError("Stepover exceeds 80% of an incremental-pass cutter diameter")

    motion = report["motion"]
    bounds = motion["parserBoundsMm"]
    expected_bounds = (
        [program.bounds.minimum.x, program.bounds.minimum.y, program.bounds.minimum.z],
        [program.bounds.maximum.x, program.bounds.maximum.y, program.bounds.maximum.z],
    )
    if any(abs(actual - expected) > 1e-8 for actual_row, expected_row in zip((bounds["minimum"], bounds["maximum"]), expected_bounds) for actual, expected in zip(actual_row, expected_row)):
        raise AssertionError("Parser bounds differ from the report")
    if program.bounds.minimum.z != -1.625 or program.bounds.maximum.z != 3.0:
        raise AssertionError("Unexpected Z bounds")
    if program.bounds.maximum.x > 110.001 or program.bounds.maximum.y > 110.001:
        raise AssertionError("XY bounds leave 110 x 110 stock")
    if len(gcode.splitlines()) != motion["gcodeLineCount"]:
        raise AssertionError("Line count differs from the report")
    estimated_minutes = program.estimated_seconds / 60
    if abs(estimated_minutes - motion["estimatedMinutes"]) > 1e-8:
        raise AssertionError("Parser timing differs from the report")
    if not all(report["offlineChecks"].values()):
        raise AssertionError("Generator report includes a failed offline check")

    verification = {
        "result": "passed",
        "scope": "offline artifact hashes, parser, bounds, feeds, pass depths, timing and safety commands",
        "releaseStatus": report["releaseStatus"],
        "gcodeSha256": report["artifacts"]["gcode"]["sha256"],
        "previewSvgSha256": report["artifacts"]["preview"]["sha256"],
        "generatorSha256": report["artifacts"]["generator"]["sha256"],
        "gcodeParses": True,
        "nonnegativeWorkXY": True,
        "rapidXYClearanceMm": motion["safeZMm"],
        "parserBoundsMm": bounds,
        "depthPassesMm": [-depth for depth in expected_passes],
        "cutFeedMmPerMin": 600,
        "plungeFeedMmPerMin": 160,
        "controlCommands": counts,
        "lineCount": len(gcode.splitlines()),
        "estimatedMinutes": round(estimated_minutes, 3),
        "availableBlackOmittedPercent": round(report["coverage"]["approvedBlackOmittedPercent"], 3),
        "hashesVerified": list(artifact_paths),
    }
    (HERE / "independent-verification.json").write_text(json.dumps(verification, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(verification, indent=2))


if __name__ == "__main__":
    main()