"""Build a review-only continuation at the first safe boundary after command 4000."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import sys
import xml.sax.saxutils as xml

HERE = Path(__file__).resolve().parent
ROOT = Path(__file__).resolve().parents[5]
SOURCE = ROOT / "artifacts/ornaments/hawkeye/two-bit/c069-flow/01-detail-c069-flow-675-120-review-only.nc"
OUTPUT = HERE / "01-detail-c083-continuation-after-4000-review-only.nc"
REPORT = HERE / "c083-continuation-report.json"
PREVIEW = HERE / "c083-continuation-preview.svg"
REQUESTED_COMMAND = 4000
SOURCE_SHA256 = "f38e959b21c83df37ca339e011a7d347516e2d3acccf41299060352bd2fa730b"
SAFE_Z = 3.0
SPINDLE_RPM = 1000

sys.path.insert(0, str(ROOT / "src"))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def command_records(lines: list[str]) -> list[tuple[int, str]]:
    """Return executable source lines with their zero-based physical line indexes."""
    return [
        (index, line.strip())
        for index, line in enumerate(lines)
        if line.strip() and not line.lstrip().startswith(";")
    ]


def is_safe_stroke_start(commands: list[str], index: int) -> bool:
    """Require retract, XY rapid, approach, and a fresh plunge in the source."""
    if index + 3 >= len(commands):
        return False
    return (
        commands[index] == "G0 Z3.0000"
        and re.fullmatch(r"G0 X[+-]?(?:\d+(?:\.\d*)?|\.\d+) Y[+-]?(?:\d+(?:\.\d*)?|\.\d+)", commands[index + 1]) is not None
        and commands[index + 2] == "G0 Z0.2000"
        and re.fullmatch(r"G1 Z-[0-9.]+ F120\.0000", commands[index + 3]) is not None
    )


def write_preview(program) -> None:
    """Write a physical-size centerline preview; it is not a cutter-sweep model."""
    groups: dict[str, list[str]] = {"cut": [], "rapid": []}
    previous = {"cut": None, "rapid": None}
    for segment in program.segments:
        kind = "rapid" if segment.rapid else "cut"
        if abs(segment.start.x - segment.end.x) + abs(segment.start.y - segment.end.y) < 1e-9:
            previous[kind] = None
            continue
        start = (segment.start.x, segment.start.y, segment.start.z)
        end = (segment.end.x, segment.end.y, segment.end.z)
        prior = previous[kind]
        if prior is not None and all(abs(a - b) < 1e-6 for a, b in zip(prior, start)):
            groups[kind].append(f"L{end[0]:.4f},{end[1]:.4f}")
        else:
            groups[kind].extend((f"M{start[0]:.4f},{start[1]:.4f}", f"L{end[0]:.4f},{end[1]:.4f}"))
        previous[kind] = end

    cut_path = " ".join(groups["cut"])
    rapid_path = " ".join(groups["rapid"])
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="110mm" height="110mm" viewBox="0 0 110 110">
<title>C-083 continuation after command {REQUESTED_COMMAND}, centerline preview</title>
<desc>110 mm stock frame. Brown: cutting centerlines. Blue dashed: XY rapid centerlines. Tool sweep width is not shown.</desc>
<rect x="0" y="0" width="110" height="110" fill="#f7f4ed" stroke="#333" stroke-width="0.25"/>
<g transform="translate(0 110) scale(1 -1)" fill="none" stroke-linecap="round" stroke-linejoin="round">
<path id="rapid" d="{xml.escape(rapid_path)}" stroke="#4186b5" stroke-width="0.08" stroke-dasharray="0.35 0.3"/>
<path id="cut" d="{xml.escape(cut_path)}" stroke="#5a3326" stroke-width="0.12"/>
</g>
<g font-family="sans-serif" font-size="1.6" fill="#222">
<text x="2" y="4">C-083 continuation · after executable command {REQUESTED_COMMAND}</text>
<text x="2" y="107">Centerline view only — not a cutter-sweep preview</text>
</g>
</svg>\n'''
    PREVIEW.write_text(svg, encoding="utf-8", newline="\n")


def main() -> None:
    from ttc3018_control.gcode import parse_gcode, validate_nonnegative_work_xy, validate_rapid_xy_clearance

    raw = SOURCE.read_bytes()
    source_sha = sha256_bytes(raw)
    if source_sha != SOURCE_SHA256:
        raise SystemExit(f"Source SHA mismatch: expected {SOURCE_SHA256}, got {source_sha}")
    source_text = raw.decode("ascii")
    lines = source_text.splitlines()
    records = command_records(lines)
    commands = [line for _, line in records]
    if len(commands) != 107517:
        raise SystemExit(f"Unexpected source executable-command count: {len(commands)}")

    # Find the first complete stroke start strictly after the requested command.
    start_index = next(
        index for index in range(REQUESTED_COMMAND, len(commands))
        if is_safe_stroke_start(commands, index)
    )
    start_ordinal = start_index + 1
    if start_ordinal <= REQUESTED_COMMAND:
        raise AssertionError("Selected boundary did not advance past requested command")

    physical_line_index = records[start_index][0]
    suffix_lines = lines[physical_line_index:]
    prologue = [
        "; OFFLINE REVIEW ONLY - generated continuation, not approved for cutting",
        "; C-083 resumes after source executable command 4000 at a complete safe-Z stroke boundary",
        f"; Source SHA-256: {source_sha}",
        f"; First included source command: {start_ordinal} ({commands[start_index]})",
        "; Restore the same verified G54 work zero before this candidate is run",
        "; Assumed tool: 30 degree included-angle V-bit, 0.1 mm tip; physically unverified",
        "G21 G17 G90 G94 G54",
        "G0 Z3.0000",
        f"M3 S{SPINDLE_RPM}",
        "G4 P2.000",
    ]
    output_text = "\n".join(prologue + suffix_lines).rstrip() + "\n"
    OUTPUT.write_text(output_text, encoding="ascii", newline="\n")

    source_program = parse_gcode(source_text, SOURCE, source_sha256=source_sha)
    program = parse_gcode(output_text, OUTPUT)
    validate_nonnegative_work_xy(program)
    validate_rapid_xy_clearance(program, SAFE_Z)
    if program.commands[4:] != source_program.commands[start_index:]:
        raise AssertionError("Candidate does not contain the exact original executable suffix")
    if program.commands[:4] != ("G21 G17 G90 G94 G54", "G0 Z3.0000", "M3 S1000", "G4 P2.000"):
        raise AssertionError("Modal/spindle prologue changed")
    if program.commands[-2:] != ("M5", "M2"):
        raise AssertionError("Candidate does not retain source terminal spindle-off/program-end")
    m3_count = sum("M3" in command.split() for command in program.commands)
    m6_count = sum("M6" in command.split() for command in program.commands)
    if m3_count != 1 or m6_count:
        raise AssertionError(f"Unexpected spindle/tool-change commands: M3={m3_count}, M6={m6_count}")
    depths = sorted({round(point.z, 4) for segment in program.segments for point in (segment.start, segment.end) if point.z < -1e-9})
    expected_depths = [-1.625, -1.2, -0.6, -0.04]
    if depths != expected_depths:
        raise AssertionError(f"Unexpected retained cutting-depth set: {depths}")
    if commands[start_index:start_index + 4] != [
        "G0 Z3.0000", commands[start_index + 1], "G0 Z0.2000", "G1 Z-0.6000 F120.0000"
    ]:
        raise AssertionError("Selected boundary is not a safe-Z/XY/approach/plunge sequence")
    write_preview(program)

    report = {
        "schemaVersion": 1,
        "releaseStatus": "offline review only; no machine interaction",
        "source": {
            "path": str(SOURCE.relative_to(ROOT)).replace("/", "\\"),
            "sha256": source_sha,
            "executableCommands": len(commands),
        },
        "candidate": {
            "path": str(OUTPUT.relative_to(ROOT)).replace("/", "\\"),
            "sha256": sha256_bytes(OUTPUT.read_bytes()),
            "executableCommands": len(program.commands),
        },
        "generator": {
            "path": str(Path(__file__).relative_to(ROOT)).replace("/", "\\"),
            "sha256": sha256_bytes(Path(__file__).read_bytes()),
            "command": ".\\.venv\\Scripts\\python.exe artifacts\\ornaments\\hawkeye\\two-bit\\c083-recovery-at-4000\\prepare-c083-continuation.py",
        },
        "requestedSkipThroughCommand": REQUESTED_COMMAND,
        "selectedSafeBoundary": {
            "firstIncludedSourceExecutableCommand": start_ordinal,
            "sourcePhysicalLine": physical_line_index + 1,
            "sourceCommandsOmitted": start_ordinal - 1,
            "boundaryCommands": commands[start_index:start_index + 4],
            "reason": "First next complete stroke boundary after command 4000; the preceding stroke is finished before retract and restart.",
        },
        "setup": {
            "workFrame": "G54; original shared lower-left XY work origin",
            "stockFrameMm": [110.0, 110.0],
            "ornamentDiameterMm": 100.0,
            "tool": "30 degree included-angle V-bit, 0.1 mm tip (assumption; physical cutter unverified)",
            "spindleCommandRpm": SPINDLE_RPM,
            "safeZMm": SAFE_Z,
            "approachZMm": 0.2,
            "depthsMm": expected_depths,
            "prologue": prologue[-4:],
            "terminalCommands": ["M5", "M2"],
        },
        "parsedBoundsMm": {
            "minimum": {"x": program.bounds.minimum.x, "y": program.bounds.minimum.y, "z": program.bounds.minimum.z},
            "maximum": {"x": program.bounds.maximum.x, "y": program.bounds.maximum.y, "z": program.bounds.maximum.z},
        },
        "nominalEstimateMinutes": program.estimated_seconds / 60,
        "checks": {
            "sourceHashMatchesReleasedC069": True,
            "selectedStartIsRetractXYRapidApproachPlunge": True,
            "freshMetricAbsoluteG54Prologue": True,
            "exactOriginalExecutableSuffixPreserved": True,
            "gcodeParses": True,
            "nonnegativeWorkXY": True,
            "rapidXYAtSafeZ": True,
            "depthsRetained": True,
            "singleM3FinalM5M2NoM6": True,
        },
        "limitations": [
            "The continuation omits source commands 1 through the command preceding the selected boundary; their physical completion is not proven by a command count.",
            "This is a full suffix from a safe source boundary, not a controller position bookmark. Recut overlap may occur where physical motion was buffered or uncertain.",
            "The SVG is a physical-size XY centerline preview and does not show the V-bit's depth-dependent cutter sweep.",
            "The modeled work zero, cutter, spindle speed and material boundary are not physically verified by this offline generator.",
            "Never jog from an arbitrary location into the first move; restore the saved G54 work zero so the opening G0 Z3 move has the intended surface reference.",
        ],
    }
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({
        "candidate": str(OUTPUT.relative_to(ROOT)),
        "candidateSha256": report["candidate"]["sha256"],
        "firstIncludedSourceCommand": start_ordinal,
        "omittedSourceCommands": start_ordinal - 1,
        "candidateCommands": len(program.commands),
        "bounds": report["parsedBoundsMm"],
        "nominalEstimateMinutes": report["nominalEstimateMinutes"],
        "checks": report["checks"],
    }, indent=2))


if __name__ == "__main__":
    main()
