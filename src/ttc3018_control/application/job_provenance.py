"""Read exact-file-matched setup and provenance from adjacent review reports.

Reports are treated as descriptive inputs. A report is surfaced only when a
recognized G-code SHA-256 field matches the bytes that were parsed into the
loaded program. The report does not establish physical tool, stock, or machine
setup.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any, Mapping

from ..gcode import GCodeError, GCodeProgram, load_gcode


_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
_REPORT_LIMIT = 1_000_000
_SIDECAR_LIMIT = 64


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _text(value: object, limit: int = 180) -> str:
    if value is None or isinstance(value, (dict, list, tuple)):
        return ""
    text = " ".join(str(value).split())
    return text[: limit - 1] + "…" if len(text) > limit else text


def _hash(value: object) -> str:
    text = str(value or "").strip()
    return text.lower() if _SHA256.fullmatch(text) else ""


_PROGRAM_NAME = "candidate-review-only.nc"
_BUNDLE_FILES = {_PROGRAM_NAME, "design.json", "cutter-sweep.svg"}
_SOURCE_NAME = re.compile(r"source(?:\.[a-zA-Z0-9_-]{1,32})?")


def _is_cam_report(report: Mapping[str, Any]) -> bool:
    return type(report.get("schema_version")) is int and report["schema_version"] == 1 and (
        report.get("status") == "review-only" and report.get("kind") in ("plaque", "raster", "step-pocket", "step-profile")
    )


def read_review_bundle(path: Path) -> tuple[GCodeProgram, Mapping[str, Any], str]:
    """Resolve a portable v1 report and parse the exact hash-matched program."""
    with path.open("rb") as handle:
        raw = handle.read(_REPORT_LIMIT + 1)
    if len(raw) > _REPORT_LIMIT:
        raise GCodeError("Review bundle report exceeds the size limit")
    try:
        report = _mapping(json.loads(raw.decode("utf-8-sig")))
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise GCodeError("Choose a valid Pine CAM report.json") from exc
    if not _is_cam_report(report):
        raise GCodeError("Unsupported Pine CAM review bundle; choose a v1 report.json")
    hashes = _mapping(report.get("sha256"))
    required = set(_BUNDLE_FILES)
    if report["kind"] != "plaque":
        sources = [name for name in hashes if _SOURCE_NAME.fullmatch(name)]
        if len(sources) != 1:
            raise GCodeError("Review bundle must declare exactly one copied source")
        required.add(sources[0])
    if set(hashes) != required or any(not _hash(value) for value in hashes.values()):
        raise GCodeError("Review bundle has missing or invalid file hashes")

    root = path.absolute().parent.resolve()
    for name in sorted(required):
        candidate = root / name
        if candidate.resolve() != candidate or not candidate.is_file():
            raise GCodeError(f"Review bundle is missing a local file: {name}")
        if name == _PROGRAM_NAME:
            continue
        with candidate.open("rb") as handle:
            digest = hashlib.file_digest(handle, "sha256").hexdigest()
        if digest != _hash(hashes[name]):
            raise GCodeError(f"Review bundle file changed: {name}; restore or regenerate the bundle")
    program = load_gcode(root / _PROGRAM_NAME)
    if program.source_sha256 != _hash(hashes[_PROGRAM_NAME]):
        raise GCodeError("Review bundle G-code changed; restore or regenerate the bundle")
    return program, report, hashlib.sha256(raw).hexdigest()


def load_review_bundle(path: Path) -> GCodeProgram:
    return read_review_bundle(path)[0]


def _report_hashes(report: Mapping[str, Any]) -> set[str]:
    """Return hashes explicitly labelled as generated G-code/output hashes."""
    found: set[str] = set()
    if _is_cam_report(report):
        digest = _hash(_mapping(report.get("sha256")).get(_PROGRAM_NAME))
        if digest:
            found.add(digest)
    for field in ("gcodeSha256", "candidateSha256", "outputSha256", "programSha256"):
        digest = _hash(report.get(field))
        if digest:
            found.add(digest)

    for group_name in ("candidate", "gcode", "output", "program"):
        group = _mapping(report.get(group_name))
        digest = _hash(group.get("sha256"))
        if digest:
            found.add(digest)

    for container_name in ("hashes", "sha256", "files", "artifacts"):
        container = _mapping(report.get(container_name))
        for label in ("gcode", "candidate", "output", "program", "nc"):
            item = container.get(label)
            digest = _hash(_mapping(item).get("sha256") if isinstance(item, Mapping) else item)
            if digest:
                found.add(digest)
    return found


def _load_matching_reports(directory: Path, source_sha256: str) -> list[tuple[Path, Mapping[str, Any]]]:
    try:
        candidates = sorted(directory.glob("*.json"), key=lambda item: item.name.casefold())[:_SIDECAR_LIMIT]
    except OSError:
        return []
    matches: list[tuple[Path, Mapping[str, Any]]] = []
    for candidate in candidates:
        try:
            if candidate.is_symlink() or candidate.stat().st_size > _REPORT_LIMIT:
                continue
            parsed = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
            continue
        if isinstance(parsed, Mapping) and source_sha256 in _report_hashes(parsed):
            matches.append((candidate, parsed))
    return matches


def _number(value: object, digits: int = 3) -> str:
    if isinstance(value, bool):
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    if not math.isfinite(number):
        return ""
    if digits == 0:
        return f"{number:.0f}"
    return f"{number:.{digits}f}".rstrip("0").rstrip(".")


def _first(*values: object) -> object | None:
    for value in values:
        if value is not None and value != "":
            return value
    return None


def _details(report: Mapping[str, Any]) -> list[str]:
    if _is_cam_report(report):
        details = []
        setup = _mapping(report.get("setup"))
        if setup:
            material = _text(_mapping(_mapping(setup.get("stock")).get("material")).get("value"))
            fixture = _mapping(setup.get("fixture"))
            datum = _mapping(fixture.get("datum"))
            fixture_name = _text(fixture.get("name"))
            if material:
                details.append("Reported stock material: " + material)
            if fixture_name:
                details.append("Reported fixture: " + fixture_name)
            for axis, label in (("xy_description", "XY"), ("z_description", "Z")):
                value = _text(_mapping(datum.get(axis)).get("value"))
                if value:
                    details.append(f"Reported {label} datum: {value}")
        stock = report.get("stock_mm")
        if isinstance(stock, list) and len(stock) == 3 and all(_number(v) for v in stock):
            details.append("Reported stock: " + " × ".join(_number(v) for v in stock) + " mm")
        tool = _mapping(report.get("tool"))
        label = _text(tool.get("type")) or ("Flat endmill" if report["kind"] in ("step-pocket", "step-profile") else "V-bit")
        width = _number(report.get("surface_sweep_diameter_mm"))
        details.append("Reported tool: " + label + (f" · surface sweep {width} mm" if width else ""))
        angle, tip = _number(tool.get("included_angle_deg")), _number(tool.get("tip_diameter_mm"))
        if angle and tip:
            details.append(f"Reported V-bit: {angle}° included angle · {tip} mm tip")
        origin = _text(report.get("origin"))
        if origin:
            details.append("Reported work origin: " + origin)
        depths = report.get("cut_depths_mm_below_top")
        if isinstance(depths, list):
            levels = [_number(v) for v in depths[:8]]
            if levels and all(levels):
                details.append("Reported depth levels below top: " + ", ".join(levels) + " mm")
        return details

    details: list[str] = []
    source = _mapping(report.get("source"))
    generator = _mapping(report.get("generator"))
    geometry = _mapping(report.get("geometry"))
    stock = _mapping(geometry.get("stock"))
    tool = _mapping(report.get("tool"))
    motion = _mapping(report.get("motion"))

    source_path = _text(source.get("path"))
    source_hash = _hash(source.get("sha256"))
    if source_path or source_hash:
        details.append("Source: " + (source_path or "path not recorded") +
                       (f" · SHA-256 {source_hash}" if source_hash else ""))

    generator_path = _text(generator.get("path"))
    generator_hash = _hash(generator.get("sha256"))
    if generator_path or generator_hash:
        details.append("Generator: " + (generator_path or "path not recorded") +
                       (f" · SHA-256 {generator_hash}" if generator_hash else ""))
    else:
        rebuild = _text(_mapping(report.get("commands")).get("rebuild"))
        if rebuild:
            details.append("Rebuild command: " + rebuild)

    tool_description = _text(_first(tool.get("type"), tool.get("name")))
    if tool_description:
        tool_notes = []
        if tool.get("tipDiameterVerified") is False:
            tool_notes.append("tip diameter unverified")
        if tool.get("runoutVerified") is False:
            tool_notes.append("runout unverified")
        details.append("Reported tool: " + tool_description +
                       (" (" + ", ".join(tool_notes) + ")" if tool_notes else ""))

    width = _number(stock.get("width"))
    height = _number(stock.get("height"))
    thickness = _number(_first(stock.get("assumedThickness"), stock.get("thickness")))
    dimensions = " × ".join(item for item in (width, height) if item)
    if dimensions:
        detail = f"Reported stock: {dimensions} mm"
        if thickness:
            measured = stock.get("thicknessMeasured") is True
            detail += f" · {thickness} mm thickness ({'measured' if measured else 'reported assumed'})"
        details.append(detail)

    origin = _text(_first(stock.get("origin"), geometry.get("origin"),
                          report.get("workOrigin"), _mapping(report.get("settings")).get("origin")))
    if origin:
        details.append("Reported work origin: " + origin)

    cut_feed = _number(_first(motion.get("cutFeedMmPerMin"), motion.get("cutFeed"),
                              _mapping(report.get("feeds")).get("cutMmPerMin")))
    plunge_feed = _number(_first(motion.get("plungeFeedMmPerMin"), motion.get("plungeFeed"),
                                 _mapping(report.get("feeds")).get("plungeMmPerMin")))
    feed_parts = []
    if cut_feed:
        feed_parts.append(f"cut {cut_feed} mm/min")
    if plunge_feed:
        feed_parts.append(f"plunge {plunge_feed} mm/min")
    if feed_parts:
        details.append("Reported feeds: " + " · ".join(feed_parts))

    spindle = _number(_first(motion.get("spindleCommand"), tool.get("spindleRpm"),
                             _mapping(report.get("settings")).get("spindleRpm")), digits=0)
    if spindle:
        details.append("Reported spindle command/setting: S" + spindle)

    stages = report.get("stages")
    if isinstance(stages, list):
        stage_lines = []
        for stage in stages[:4]:
            stage_data = _mapping(stage)
            name = _text(stage_data.get("name"), 50)
            passes = stage_data.get("depthPassesMm")
            depths = [_number(value) for value in passes[:8]] if isinstance(passes, list) else []
            depths = [value for value in depths if value]
            if not depths:
                maximum = _number(stage_data.get("maximumDepthMm"))
                if maximum:
                    depths = [maximum]
            if depths:
                stage_lines.append((name + ": " if name else "") + ", ".join(depths) + " mm")
        if stage_lines:
            details.append("Reported passes: " + " · ".join(stage_lines))

    omitted_before_after = geometry.get("combinedApprovedBlackOmittedBeforeAfterMm2")
    if isinstance(omitted_before_after, list) and len(omitted_before_after) >= 2:
        before, after = (_number(value) for value in omitted_before_after[:2])
        if before and after:
            details.append(f"Reported approved-black omission: {before} → {after} mm²")
    else:
        coverage = _mapping(report.get("coverage"))
        omitted = _number(_first(geometry.get("combinedApprovedBlackOmittedAfterMm2"),
                                 coverage.get("omittedBlackAreaMm2")))
        if omitted:
            details.append(f"Reported approved-black omission: {omitted} mm²")

    estimate = _number(_first(motion.get("estimatedMinutesIgnoringJunctionSlowdown"),
                              report.get("estimatedMinutes"), report.get("estimated_minutes"),
                              _mapping(report.get("runtime")).get("estimatedMinutes")), digits=1)
    if estimate:
        assumption = " (ignores junction slowdown)" if motion.get("estimatedMinutesIgnoringJunctionSlowdown") is not None else ""
        details.append(f"Report estimate: {estimate} min{assumption}")
    return details[:10]


def build_job_provenance(
    path: Path, source_sha256: str, header_comments: tuple[str, ...] = ()
) -> dict[str, Any]:
    """Build a small display payload using only exact-hash-matched sidecars."""
    digest = _hash(source_sha256)
    payload: dict[str, Any] = {
        "file_sha256": digest,
        "report_state": "missing",
        "report_name": "",
        "release_status": "",
        "bundle": "",
        "details": [],
        "header_notes": [_text(note, 240) for note in header_comments[:10] if _text(note, 240)],
        "verification_text": "",
        "notice": "No adjacent review report matches the loaded G-code bytes.",
    }
    if not digest or path.name.startswith("<"):
        payload["report_state"] = "unavailable"
        payload["notice"] = "Review report matching is unavailable for this in-memory job."
        return payload

    reports = _load_matching_reports(path.parent, digest)
    if not reports:
        return payload

    def score(item: tuple[Path, Mapping[str, Any]]) -> tuple[int, str]:
        report = item[1]
        keys = ("source", "generator", "tool", "geometry", "stages", "motion", "feeds", "coverage")
        return (sum(bool(report.get(key)) for key in keys), item[0].name.casefold())

    report_path, report = max(reports, key=score)
    setup = _mapping(report.get("setup")) if _is_cam_report(report) else {}
    payload.update({
        "setup_name": _text(setup.get("name")),
        "setup_machine_id": _text(_mapping(setup.get("fixture")).get("machine_profile_id")),
        "report_state": "matched",
        "report_name": report_path.name,
        "release_status": _text(report.get("releaseStatus") or (report.get("status") if _is_cam_report(report) else "")),
        "bundle": _text(report.get("bundle")),
        "details": _details(report),
        "notice": "Report details are tied to the loaded bytes by SHA-256; they do not verify physical setup.",
    })
    verification_reports = [
        (candidate.name, _text(document.get("result")))
        for candidate, document in reports
        if document.get("result") not in (None, "")
        and ("verif" in candidate.name.casefold() or "check" in candidate.name.casefold())
    ]
    if verification_reports:
        name, result = sorted(verification_reports, key=lambda item: item[0].casefold())[0]
        payload["verification_text"] = f"Matched {name}: reported result {result}"
    else:
        payload["verification_text"] = ""
    return payload


__all__ = ["build_job_provenance"]
