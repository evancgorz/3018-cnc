"""Recheck the offline C-039 V-bit review bundle without touching hardware."""
from __future__ import annotations

import hashlib
import json
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
    report_path = HERE / "detail-report-vbit30-simplified.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    artifact_paths = {
        "source": ROOT / report["artifacts"]["source"]["path"],
        "gcode": ROOT / report["artifacts"]["gcode"]["path"],
        "preview": ROOT / report["artifacts"]["preview"]["path"],
    }
    for key, path in artifact_paths.items():
        expected = report["artifacts"][key]["sha256"]
        actual = sha256(path)
        if actual != expected:
            raise AssertionError(f"{key} SHA-256 mismatch: {actual} != {expected}")

    nc_path = artifact_paths["gcode"]
    gcode = nc_path.read_text(encoding="ascii")
    program = parse_gcode(gcode, nc_path)
    validate_nonnegative_work_xy(program)
    validate_rapid_xy_clearance(program, report["motionReview"]["safeZMm"])
    executable = "\n".join(line.split(";", 1)[0] for line in gcode.splitlines())
    counts = {
        "m5": len(re.findall(r"\bM\s*5\b", executable, re.IGNORECASE)),
        "m3": len(re.findall(r"\bM\s*3\b", executable, re.IGNORECASE)),
        "m6": len(re.findall(r"\bM\s*6\b", executable, re.IGNORECASE)),
        "program_end": len(re.findall(r"\bM\s*(?:2|30)\b", executable, re.IGNORECASE)),
    }
    if counts != {"m5": 2, "m3": 0, "m6": 0, "program_end": 1}:
        raise AssertionError(f"Unexpected machine-control commands: {counts}")
    if not all(report["offlineChecks"].values()):
        raise AssertionError("Generator report has a failed offline check")
    estimated_minutes = program.estimated_seconds / 60
    if abs(estimated_minutes - report["motionReview"]["exactCombinedProgramEstimatedMinutes"]) > 1e-6:
        raise AssertionError("Parser estimate differs from the recorded estimate")

    verification = {
        "result": "passed",
        "scope": "offline artifact integrity, G-code parse, coordinate and command checks",
        "tool": report["tool"],
        "releaseStatus": report["releaseStatus"],
        "commands": {
            "rebuild": report["rebuildCommand"],
            "verify": ".\\.venv\\Scripts\\python.exe artifacts/ornaments/hawkeye/two-bit/c043-runtime/v2-simplified/verify-review.py",
        },
        "gcodeSha256": report["artifacts"]["gcode"]["sha256"],
        "previewSvgSha256": report["artifacts"]["preview"]["sha256"],
        "sourceSha256": report["source"]["sha256"],
        "gcodeParses": True,
        "nonnegativeWorkXY": True,
        "rapidXYClearanceMm": report["motionReview"]["safeZMm"],
        "controlCommands": counts,
        "lineCount": len(gcode.splitlines()),
        "estimatedMinutes": round(estimated_minutes, 3),
        "availableBlackOmittedPercent": round(
            report["sweepReview"]["availableSourceBlackOmittedPercent"], 3
        ),
        "hashesVerified": list(artifact_paths),
        "generatorOfflineChecks": report["offlineChecks"],
    }
    (HERE / "independent-verification.json").write_text(
        json.dumps(verification, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({
        "gcodeParses": True,
        "nonnegativeWorkXY": True,
        "rapidXYClearanceMm": report["motionReview"]["safeZMm"],
        "controlCommands": counts,
        "lineCount": len(gcode.splitlines()),
        "estimatedMinutes": round(estimated_minutes, 3),
        "availableBlackOmittedPercent": round(
            report["sweepReview"]["availableSourceBlackOmittedPercent"], 3
        ),
        "hashesVerified": list(artifact_paths),
    }, indent=2))


if __name__ == "__main__":
    main()
