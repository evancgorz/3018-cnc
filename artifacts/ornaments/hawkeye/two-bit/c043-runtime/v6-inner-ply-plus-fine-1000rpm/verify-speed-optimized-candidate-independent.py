"""Independently verify the exact offline speed-optimized engraving NC.

This verifier reads files and uses a dummy in-memory sender only. It never
connects to an application, controller, or machine. Cutter coverage is rebuilt
from emitted G-code paths using explicit full tool diameters.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
import sys
from typing import Any

from shapely.geometry import LineString, Point, box
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parents[6]
HERE = Path(__file__).resolve().parent
SOURCE_IMAGE = ROOT / "artifacts/ornaments/hawkeye/approved-artwork-reference.png"
V6_NC = HERE / "01-detail-stream-compatible-inner-ply-plus-fine-600-160.nc"
BASE_450_NC = HERE / "01-detail-review-450-120.nc"
CANDIDATE_NC = HERE / "01-detail-speed-optimized-candidate-450-120.nc"
V6_REPORT = HERE / "detail-report-vbit30-inner-ply-plus-fine-1000rpm.json"
CANDIDATE_REPORT = HERE / "speed-optimized-candidate-report.json"
BUILDER = HERE / "prepare-speed-optimized-candidate.py"
OUTPUT = HERE / "speed-optimized-candidate-independent-verification.json"

STOCK_MM = 110.0
SAFE_Z_MM = 3.0
TARGET_DEPTH_MM = 1.625
FINE_DEPTH_MM = 0.04
V_ANGLE_DEGREES = 30.0
TIP_DIAMETER_MM = 0.1
HOLE_CENTER = (55.0, 100.0)
HOLE_KEEPOUT_RADIUS_MM = 3.0
GRBL_DEFAULT_RX_CAPACITY_BYTES = 127

sys.path.insert(0, str(ROOT / "src"))
from ttc3018_control.application.job_service import JobService  # noqa: E402
from ttc3018_control.gcode import (  # noqa: E402
    parse_gcode,
    validate_nonnegative_work_xy,
    validate_rapid_xy_clearance,
)
from ttc3018_control.job import JobStreamer  # noqa: E402
from ttc3018_control.ornament_cam import OrnamentSettings, raster_region  # noqa: E402


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def file_text(path: Path) -> str:
    return path.read_text(encoding="ascii")


def effective_diameter(depth_mm: float) -> float:
    return TIP_DIAMETER_MM + 2 * depth_mm * math.tan(math.radians(V_ANGLE_DEGREES / 2))


def read_emitted_paths(text: str) -> dict[float, tuple[tuple[tuple[float, float], ...], ...]]:
    """Recover absolute XY cutting paths directly from NC motion blocks."""
    x = y = z = 0.0
    active_depth: float | None = None
    active_path: list[tuple[float, float]] = []
    grouped: dict[float, list[tuple[tuple[float, float], ...]]] = {}

    def close_path() -> None:
        nonlocal active_path
        if active_depth is not None and len(active_path) > 1:
            grouped.setdefault(round(active_depth, 4), []).append(tuple(active_path))
        active_path = []

    for line_number, raw in enumerate(text.splitlines(), start=1):
        line = raw.split(";", 1)[0].strip().upper()
        if not line:
            continue
        words = {
            axis: float(value)
            for axis, value in re.findall(r"\b([XYZ])\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))", line)
        }
        motion_match = re.match(r"^G\s*(\d+)", line)
        if motion_match is None:
            continue
        motion = int(motion_match.group(1))
        if motion not in {0, 1}:
            if any(axis in words for axis in "XYZ"):
                raise AssertionError(f"line {line_number}: unsupported axis motion G{motion}")
            continue
        if motion == 0:
            close_path()
            x, y, z = words.get("X", x), words.get("Y", y), words.get("Z", z)
            active_depth = None
        elif motion == 1:
            if "Z" in words:
                close_path()
                z = words["Z"]
                active_depth = round(z, 4) if z < 0 else None
                if active_depth is not None:
                    active_path = [(x, y)]
            if "X" in words or "Y" in words:
                nx, ny = words.get("X", x), words.get("Y", y)
                if active_depth is not None:
                    active_path.append((nx, ny))
                x, y = nx, ny
        else:
            raise AssertionError(f"line {line_number}: expected only G0/G1 motion, got G{motion}")
    close_path()
    return {depth: tuple(paths) for depth, paths in grouped.items()}


def full_diameter_sweep(paths, diameter_mm: float, *, conservative: bool = False):
    """Buffer emitted centerlines at radius D/2, guarding polygonal circles."""
    radius_mm = diameter_mm / 2
    if conservative:
        # Shapely's 32-segment quadrant buffer is inscribed. Inflate by the
        # exact polygon sagitta factor so this polygon encloses the circular
        # cutter. Paths are parsed from the emitted 0.0001 mm NC coordinates;
        # there is no second coordinate-rounding step here.
        radius_mm = radius_mm / math.cos(math.pi / 128)
    pieces = [LineString(path).buffer(radius_mm, quad_segs=32) for path in paths]
    if not pieces:
        raise AssertionError("Expected cutting paths but found none")
    return unary_union(pieces)


def program_control_counts(text: str) -> dict[str, int]:
    executable = "\n".join(line.split(";", 1)[0] for line in text.splitlines())
    return {
        "m3": len(re.findall(r"\bM\s*3\b", executable, re.IGNORECASE)),
        "m4": len(re.findall(r"\bM\s*4\b", executable, re.IGNORECASE)),
        "m5": len(re.findall(r"\bM\s*5\b", executable, re.IGNORECASE)),
        "m6": len(re.findall(r"\bM\s*6\b", executable, re.IGNORECASE)),
        "m2": len(re.findall(r"\bM\s*2\b", executable, re.IGNORECASE)),
        "m30": len(re.findall(r"\bM\s*30\b", executable, re.IGNORECASE)),
    }


def feed_metrics(text: str) -> dict[str, Any]:
    executable = [line.split(";", 1)[0].strip().upper() for line in text.splitlines()]
    xy_cut = [line for line in executable if line.startswith("G1 ") and re.search(r"\b[XY]\s*", line)]
    plunge = [line for line in executable if line.startswith("G1 Z-")]
    return {
        "xyCutMoveCount": len(xy_cut),
        "plungeMoveCount": len(plunge),
        "xyCutFeedsMmPerMin": sorted({float(re.search(r"\bF\s*([\d.]+)", line).group(1)) for line in xy_cut}),
        "plungeFeedsMmPerMin": sorted({float(re.search(r"\bF\s*([\d.]+)", line).group(1)) for line in plunge}),
    }


def path_summary(paths: dict[float, tuple[tuple[tuple[float, float], ...], ...]]) -> dict[str, Any]:
    return {
        f"z{depth:.4f}": {
            "pathCount": len(level_paths),
            "xyVertices": sum(len(path) for path in level_paths),
            "xyLengthMm": sum(LineString(path).length for path in level_paths),
        }
        for depth, level_paths in sorted(paths.items())
    }


def dry_run_stream(commands: tuple[str, ...]) -> dict[str, int]:
    """Exercise the app's GRBL character-counting streamer with a dummy sink."""
    prepared = JobService._motion_commands_without_terminal_stop(commands)
    max_line_bytes = 0
    max_buffered_bytes = 0
    sent_count = 0

    def dummy_send(payload: bytes) -> None:
        nonlocal max_line_bytes, sent_count
        payload.decode("ascii")
        max_line_bytes = max(max_line_bytes, len(payload))
        sent_count += 1

    streamer = JobStreamer(dummy_send, buffer_capacity=GRBL_DEFAULT_RX_CAPACITY_BYTES)
    streamer.start(prepared)
    max_buffered_bytes = max(max_buffered_bytes, streamer.buffered_bytes)
    while streamer.state == "running":
        if not streamer.awaiting_ack:
            raise AssertionError("Dry-run streamer stalled without an outstanding command")
        streamer.handle_response("ok")
        max_buffered_bytes = max(max_buffered_bytes, streamer.buffered_bytes)
    if streamer.state != "complete":
        raise AssertionError(f"Dry-run streamer ended in state {streamer.state!r}: {streamer.error}")
    if streamer.acknowledged_count != len(prepared) or sent_count != len(prepared):
        raise AssertionError("Dry-run streamer did not send and acknowledge every prepared command")
    return {
        "inputCommands": len(commands),
        "preparedMotionCommands": len(prepared),
        "dummySentAndAcknowledged": sent_count,
        "rxCapacityBytes": GRBL_DEFAULT_RX_CAPACITY_BYTES,
        "maxSingleLineBytesIncludingNewline": max_line_bytes,
        "maxBufferedBytes": max_buffered_bytes,
    }


def main() -> int:
    for path in (SOURCE_IMAGE, V6_NC, BASE_450_NC, CANDIDATE_NC, V6_REPORT, CANDIDATE_REPORT, BUILDER):
        if not path.is_file():
            raise FileNotFoundError(path)

    source_hash = sha256(SOURCE_IMAGE)
    v6_hash = sha256(V6_NC)
    base_450_hash = sha256(BASE_450_NC)
    candidate_hash = sha256(CANDIDATE_NC)
    builder_hash = sha256(BUILDER)
    verifier_hash = sha256(Path(__file__).resolve())
    v6_report = load_json(V6_REPORT)
    candidate_report = load_json(CANDIDATE_REPORT)

    v6_text, base_450_text, candidate_text = map(file_text, (V6_NC, BASE_450_NC, CANDIDATE_NC))
    texts = {"v6_600_160": v6_text, "base_450_120": base_450_text, "candidate_450_120": candidate_text}
    programs = {key: parse_gcode(text, {"v6_600_160": V6_NC, "base_450_120": BASE_450_NC, "candidate_450_120": CANDIDATE_NC}[key]) for key, text in texts.items()}
    paths = {key: read_emitted_paths(text) for key, text in texts.items()}

    with __import__("PIL.Image", fromlist=["Image"]).open(SOURCE_IMAGE) as image:
        image_size = image.size
    settings = OrnamentSettings(
        crop=(0, 0, image_size[0], image_size[1]),
        outer_diameter=100.0,
        art_diameter=90.0,
        stock_thickness=3.25,
        stock_margin=5.0,
        engraving_depth=TARGET_DEPTH_MM,
        v_angle=V_ANGLE_DEGREES,
        tip_diameter=TIP_DIAMETER_MM,
        stepover=0.27,
        max_stepdown=0.6,
        safe_z=SAFE_Z_MM,
        cut_feed=600.0,
        plunge_feed=160.0,
        spindle_rpm=1000,
        threshold=128,
        optimize_paths=True,
        approach_z=0.2,
    )
    source_region, pixel_size_mm = raster_region(SOURCE_IMAGE, settings)
    keepout = Point(*HOLE_CENTER).buffer(HOLE_KEEPOUT_RADIUS_MM, quad_segs=256)
    work_region = source_region.difference(keepout)
    broad_diameter_mm = effective_diameter(TARGET_DEPTH_MM)
    fine_diameter_mm = effective_diameter(FINE_DEPTH_MM)
    expected_depths = {-0.6, -1.2, -1.625, -0.04}
    stock = box(0, 0, STOCK_MM, STOCK_MM)

    for key, program in programs.items():
        validate_nonnegative_work_xy(program)
        validate_rapid_xy_clearance(program, SAFE_Z_MM)
        bounds = program.bounds
        if bounds.minimum.z != -TARGET_DEPTH_MM or bounds.maximum.z != SAFE_Z_MM:
            raise AssertionError(f"{key}: parser bounds have unexpected Z depth or clearance")
        if min(bounds.minimum.x, bounds.minimum.y) < 0 or max(bounds.maximum.x, bounds.maximum.y) > STOCK_MM:
            raise AssertionError(f"{key}: parsed XY bounds leave the declared 110 mm stock")
        if set(paths[key]) != expected_depths:
            raise AssertionError(f"{key}: emitted cut levels differ: {sorted(paths[key])}")
        if any(len(level_paths) != 349 for depth, level_paths in paths[key].items() if depth != FINE_DEPTH_MM * -1):
            raise AssertionError(f"{key}: unexpected broad path count")
        if len(paths[key][-FINE_DEPTH_MM]) != 3645:
            raise AssertionError(f"{key}: unexpected fine path count")
        control = program_control_counts(texts[key])
        if control != {"m3": 1, "m4": 0, "m5": 1, "m6": 0, "m2": 1, "m30": 0}:
            raise AssertionError(f"{key}: unsupported or misplaced machine-control commands: {control}")
        executable_lines = [line.split(";", 1)[0].strip() for line in texts[key].splitlines() if line.split(";", 1)[0].strip()]
        if executable_lines[:3] != ["G21 G17 G90 G94 G54", "G0 Z3.0000", "M3 S1000"]:
            raise AssertionError(f"{key}: stream-compatible setup block changed")
        if executable_lines[-2:] != ["M5", "M2"]:
            raise AssertionError(f"{key}: terminal spindle/program stops are not standalone")
        if executable_lines.count("G4 P2.000") != 1:
            raise AssertionError(f"{key}: expected exactly one explicit spindle dwell")
        line_lengths = [len(line.encode("ascii")) + 1 for line in programs[key].commands]
        if not line_lengths or max(line_lengths) > GRBL_DEFAULT_RX_CAPACITY_BYTES:
            raise AssertionError(f"{key}: a command exceeds the default GRBL RX payload capacity")

    expected_feeds = {
        "v6_600_160": (600.0, 160.0),
        "base_450_120": (450.0, 120.0),
        "candidate_450_120": (450.0, 120.0),
    }
    feed_report: dict[str, Any] = {}
    for key, text in texts.items():
        metrics = feed_metrics(text)
        expected_cut, expected_plunge = expected_feeds[key]
        if metrics["xyCutFeedsMmPerMin"] != [expected_cut] or metrics["plungeFeedsMmPerMin"] != [expected_plunge]:
            raise AssertionError(f"{key}: emitted feed words do not match the declared cut/plunge rates")
        feed_report[key] = metrics

    # The 450/120 unsimplified file must reproduce the approved v6 paths exactly.
    for depth in expected_depths:
        if paths["v6_600_160"][depth] != paths["base_450_120"][depth]:
            raise AssertionError(f"Unsimplified 450/120 geometry differs from v6 at Z{depth:g}")
    if paths["candidate_450_120"][-FINE_DEPTH_MM] != paths["v6_600_160"][-FINE_DEPTH_MM]:
        raise AssertionError("Candidate fine paths differ from v6")
    candidate_broad = paths["candidate_450_120"][-TARGET_DEPTH_MM]
    original_broad = paths["v6_600_160"][-TARGET_DEPTH_MM]
    if len(candidate_broad) != len(original_broad):
        raise AssertionError("Candidate changed the number of broad paths")
    if not (paths["candidate_450_120"][-0.6] == paths["candidate_450_120"][-1.2] == candidate_broad):
        raise AssertionError("Candidate broad geometry differs between incremental depth passes")
    if any(new[0] != old[0] or new[-1] != old[-1] for old, new in zip(original_broad, candidate_broad)):
        raise AssertionError("Candidate simplification changed a broad path endpoint")

    areas: dict[str, dict[str, Any]] = {}
    nominal_sweeps = {}
    containment: dict[str, dict[str, bool]] = {}
    for key in ("v6_600_160", "candidate_450_120"):
        broad = full_diameter_sweep(paths[key][-TARGET_DEPTH_MM], broad_diameter_mm)
        fine = full_diameter_sweep(paths[key][-FINE_DEPTH_MM], fine_diameter_mm)
        broad_guard = full_diameter_sweep(paths[key][-TARGET_DEPTH_MM], broad_diameter_mm, conservative=True)
        fine_guard = full_diameter_sweep(paths[key][-FINE_DEPTH_MM], fine_diameter_mm, conservative=True)
        combined = unary_union((broad, fine))
        omitted = work_region.difference(combined).area
        nominal_sweeps[key] = (broad, fine)
        containment[key] = {
            "broadSweepInsideApprovedBlackOutsideKeepout": bool(source_region.covers(broad_guard) and work_region.covers(broad_guard)),
            "fineSweepInsideApprovedBlackOutsideKeepout": bool(source_region.covers(fine_guard) and work_region.covers(fine_guard)),
            "broadSweepInsideStock": bool(stock.buffer(0.001).covers(broad_guard)),
            "fineSweepInsideStock": bool(stock.buffer(0.001).covers(fine_guard)),
        }
        if not all(containment[key].values()):
            raise AssertionError(f"{key}: full-diameter conservative sweep leaves approved region, keepout, or stock")
        areas[key] = {
            "broadSweepMm2": broad.area,
            "fineSweepMm2": fine.area,
            "combinedOmittedMm2": omitted,
            "combinedOmittedPercentOfAvailableBlack": 100 * omitted / work_region.area,
        }
    omission_change_mm2 = areas["candidate_450_120"]["combinedOmittedMm2"] - areas["v6_600_160"]["combinedOmittedMm2"]
    omission_change_pp = (
        areas["candidate_450_120"]["combinedOmittedPercentOfAvailableBlack"]
        - areas["v6_600_160"]["combinedOmittedPercentOfAvailableBlack"]
    )

    stream_report = dry_run_stream(programs["candidate_450_120"].commands)
    broad_before_vertices = sum(map(len, original_broad))
    broad_after_vertices = sum(map(len, candidate_broad))
    actual_changed_paths = sum(old != new for old, new in zip(original_broad, candidate_broad))
    v6_minutes = programs["v6_600_160"].estimated_seconds / 60
    base_450_minutes = programs["base_450_120"].estimated_seconds / 60
    candidate_minutes = programs["candidate_450_120"].estimated_seconds / 60

    candidate_geometry = candidate_report["geometry"]
    reported_vs_recomputed = {
        "broadSweepBaselineMm2": math.isclose(candidate_geometry["broadSweepBaselineMm2"], areas["v6_600_160"]["broadSweepMm2"], abs_tol=0.01),
        "broadSweepCandidateMm2": math.isclose(candidate_geometry["broadSweepCandidateMm2"], areas["candidate_450_120"]["broadSweepMm2"], abs_tol=0.01),
        "combinedOmittedMm2": math.isclose(candidate_geometry["combinedOmittedMm2"], areas["candidate_450_120"]["combinedOmittedMm2"], abs_tol=0.01),
        "combinedOmittedPercent": math.isclose(candidate_geometry["combinedOmittedPercent"], areas["candidate_450_120"]["combinedOmittedPercentOfAvailableBlack"], abs_tol=0.01),
        "combinedOmissionChangeMm2": math.isclose(candidate_geometry["combinedOmissionChangeMm2"], omission_change_mm2, abs_tol=0.01),
        "broadPathsSimplifiedMeansActuallyChanged": candidate_geometry["broadPathsSimplified"] == actual_changed_paths,
    }
    hash_checks = {
        "sourceMatchesV6Report": source_hash == v6_report["source"]["sha256"],
        "v6NcMatchesV6Report": v6_hash == v6_report["artifacts"]["gcode"]["sha256"],
        "sourceMatchesCandidateReport": source_hash == candidate_report["source"]["sha256"],
        "candidateMatchesCandidateReport": candidate_hash == candidate_report["candidate"]["sha256"],
        "v6NcMatchesCandidateBaseHash": v6_hash == candidate_report["baseArtifacts"]["v6GcodeSha256"],
        "builderMatchesCandidateReport": builder_hash == candidate_report["generator"]["sha256"],
    }
    report_consistency = all(reported_vs_recomputed.values()) and all(hash_checks.values())

    result = {
        "schemaVersion": 1,
        "result": "passed" if report_consistency else "NC_checks_passed_report_mismatch",
        "scope": "offline file verification and dummy-sender streamer exercise only; no app UI, controller, or hardware access",
        "releaseStatus": "offline-review-only; not authorization for cutting",
        "files": {
            "sourceImage": str(SOURCE_IMAGE.relative_to(ROOT)),
            "v6Nc": str(V6_NC.relative_to(ROOT)),
            "base450120Nc": str(BASE_450_NC.relative_to(ROOT)),
            "candidateNc": str(CANDIDATE_NC.relative_to(ROOT)),
            "verifier": str(Path(__file__).resolve().relative_to(ROOT)),
        },
        "hashes": {
            "sourceImageSha256": source_hash,
            "v6NcSha256": v6_hash,
            "base450120NcSha256": base_450_hash,
            "candidateNcSha256": candidate_hash,
            "candidateBuilderSha256": builder_hash,
            "verifierSha256": verifier_hash,
            "candidateReportSha256": sha256(CANDIDATE_REPORT),
            "v6ReportSha256": sha256(V6_REPORT),
        },
        "hashChecks": hash_checks,
        "geometry": {
            "sourcePixelSizeMm": pixel_size_mm,
            "availableApprovedBlackMm2": work_region.area,
            "tool": {
                "includedAngleDegrees": V_ANGLE_DEGREES,
                "tipDiameterMm": TIP_DIAMETER_MM,
                "broadDepthMm": TARGET_DEPTH_MM,
                "broadEffectiveDiameterMm": broad_diameter_mm,
                "fineDepthMm": FINE_DEPTH_MM,
                "fineEffectiveDiameterMm": fine_diameter_mm,
                "conservativeSweepIncludesPolygonGuard": True,
            },
            "coverage": areas,
            "candidateMinusV6OmittedMm2": omission_change_mm2,
            "candidateMinusV6OmittedPercentagePoints": omission_change_pp,
            "containment": containment,
            "pathSummary": {key: path_summary(value) for key, value in paths.items()},
            "actualChangedBroadPaths": actual_changed_paths,
            "broadVerticesPerPassBeforeAfter": [broad_before_vertices, broad_after_vertices],
        },
        "motionAndFeeds": {
            "feeds": feed_report,
            "parserCommandCounts": {key: len(program.commands) for key, program in programs.items()},
            "lineCounts": {key: len(text.splitlines()) for key, text in texts.items()},
            "estimatedMinutes": {
                "v6_600_160": v6_minutes,
                "base_450_120": base_450_minutes,
                "candidate_450_120": candidate_minutes,
            },
            "candidateSavingsVsBase450120Minutes": base_450_minutes - candidate_minutes,
            "candidateSavingsVsBase450120Percent": 100 * (base_450_minutes - candidate_minutes) / base_450_minutes,
            "candidateVsV6Minutes": candidate_minutes - v6_minutes,
        },
        "parserAndStreamer": {
            "parsedAllThreeNcFiles": True,
            "nonnegativeWorkXY": True,
            "rapidXYAtSafeZ": True,
            "singleM3M5M2NoM4M6": True,
            "candidateDryRun": stream_report,
        },
        "builderReportConsistency": {
            "checks": reported_vs_recomputed,
            "allChecksMatch": all(reported_vs_recomputed.values()),
        },
    }
    OUTPUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(result, indent=2))
    return 0 if report_consistency else 2


if __name__ == "__main__":
    raise SystemExit(main())
