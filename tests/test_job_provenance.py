from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ttc3018_control.application.job_provenance import build_job_provenance
from ttc3018_control.gcode import load_gcode, parse_gcode


GCODE = "; Listed tool: review cutter; physical setup unverified\nG21\nG90\nG1 X1 F100\nM5\nM2\n"


def test_loaded_program_hash_covers_exact_file_bytes_including_bom(tmp_path: Path) -> None:
    path = tmp_path / "review.nc"
    raw = b"\xef\xbb\xbf" + GCODE.encode("utf-8")
    path.write_bytes(raw)

    program = load_gcode(path)

    assert program.source_sha256 == hashlib.sha256(raw).hexdigest()
    assert program.path == path
    assert parse_gcode(GCODE).source_sha256 == hashlib.sha256(GCODE.encode("utf-8")).hexdigest()
    assert program.header_comments == ("Listed tool: review cutter; physical setup unverified",)


def test_matching_report_exposes_reported_setup_and_source_facts(tmp_path: Path) -> None:
    path = tmp_path / "candidate.nc"
    path.write_text(GCODE, encoding="utf-8")
    program = load_gcode(path)
    report = {
        "schemaVersion": 1,
        "bundle": "demo-review",
        "releaseStatus": "offline-review-only",
        "candidate": {"path": "candidate.nc", "sha256": program.source_sha256},
        "source": {"path": "artwork.png", "sha256": "a" * 64},
        "generator": {"path": "prepare.py", "sha256": "b" * 64},
        "tool": {"type": "30 degree V-bit", "tipDiameterVerified": False},
        "geometry": {
            "stock": {"width": 110, "height": 110, "assumedThickness": 3, "thicknessMeasured": False, "origin": "lower-left"},
            "combinedApprovedBlackOmittedBeforeAfterMm2": [16.4, 23.6],
        },
        "motion": {
            "cutFeedMmPerMin": 450,
            "plungeFeedMmPerMin": 120,
            "spindleCommand": 1000,
            "estimatedMinutesIgnoringJunctionSlowdown": 115.04,
        },
        "stages": [{"name": "deep", "depthPassesMm": [-0.6, -1.2, -1.625]}],
    }
    (tmp_path / "candidate-report.json").write_text(json.dumps(report), encoding="utf-8")
    (tmp_path / "independent-verification.json").write_text(json.dumps({
        "gcodeSha256": program.source_sha256,
        "result": "passed",
    }), encoding="utf-8")

    provenance = build_job_provenance(program.path, program.source_sha256, program.header_comments)

    assert provenance["report_state"] == "matched"
    assert provenance["report_name"] == "candidate-report.json"
    assert provenance["release_status"] == "offline-review-only"
    assert provenance["verification_text"] == "Matched independent-verification.json: reported result passed"
    details = "\n".join(provenance["details"])
    assert "Source: artwork.png" in details
    assert "Generator: prepare.py" in details
    assert "Reported stock: 110 × 110 mm" in details
    assert "Reported feeds: cut 450 mm/min · plunge 120 mm/min" in details
    assert "S1000" in details
    assert "-0.6, -1.2, -1.625 mm" in details
    assert "16.4 → 23.6 mm²" in details
    assert "115 min (ignores junction slowdown)" in details


def test_stale_or_source_only_sidecars_do_not_supply_setup(tmp_path: Path) -> None:
    path = tmp_path / "candidate.nc"
    path.write_text(GCODE, encoding="utf-8")
    program = load_gcode(path)
    # A source digest is not a digest of this generated file.
    (tmp_path / "stale-report.json").write_text(json.dumps({
        "source": {"sha256": program.source_sha256},
        "tool": {"type": "unrelated cutter"},
    }), encoding="utf-8")
    (tmp_path / "wrong-candidate.json").write_text(json.dumps({
        "candidate": {"sha256": "0" * 64},
        "tool": {"type": "unrelated cutter"},
    }), encoding="utf-8")

    provenance = build_job_provenance(program.path, program.source_sha256, program.header_comments)

    assert provenance["report_state"] == "missing"
    assert provenance["file_sha256"] == program.source_sha256
    assert provenance["header_notes"] == ["Listed tool: review cutter; physical setup unverified"]
    assert provenance["details"] == []
    assert "No adjacent review report" in provenance["notice"]


def test_unreadable_or_oversized_sidecars_are_ignored(tmp_path: Path) -> None:
    path = tmp_path / "candidate.nc"
    path.write_text(GCODE, encoding="utf-8")
    program = load_gcode(path)
    (tmp_path / "broken.json").write_text("{", encoding="utf-8")
    (tmp_path / "large.json").write_text(" " * 1_000_001, encoding="utf-8")

    provenance = build_job_provenance(program.path, program.source_sha256)

    assert provenance["report_state"] == "missing"


def test_in_memory_job_reports_unavailable_sidecar_matching(tmp_path: Path) -> None:
    program = parse_gcode(GCODE)
    (tmp_path / "candidate-report.json").write_text(json.dumps({
        "candidate": {"sha256": program.source_sha256},
    }), encoding="utf-8")

    provenance = build_job_provenance(program.path, program.source_sha256)

    assert provenance["report_state"] == "unavailable"
    assert provenance["file_sha256"] == program.source_sha256


def test_backend_snapshot_uses_loaded_hash_and_caches_matched_report(tmp_path: Path) -> None:
    from ttc3018_control.application.controller import ApplicationController
    from ttc3018_control.backend.runtime import BackendRuntime

    path = tmp_path / "candidate.nc"
    path.write_text(GCODE, encoding="utf-8")
    program = load_gcode(path)
    report_path = tmp_path / "candidate-report.json"
    report_path.write_text(json.dumps({
        "candidate": {"sha256": program.source_sha256},
        "tool": {"type": "reported cutter"},
    }), encoding="utf-8")
    controller = ApplicationController(tmp_path / "app")
    controller.load_program(path)
    runtime = BackendRuntime(tmp_path / "app", application=controller)

    first = runtime._program_provenance_snapshot()
    report_path.write_text(json.dumps({
        "candidate": {"sha256": "0" * 64},
        "tool": {"type": "different cutter"},
    }), encoding="utf-8")
    second = runtime.poll_once()["program_provenance"]

    assert runtime._last_snapshot["program_detail"]["source_sha256"] == program.source_sha256
    assert first["report_state"] == "matched"
    assert first["header_notes"] == ["Listed tool: review cutter; physical setup unverified"]
    assert second == first


def test_view_model_exposes_matched_report_and_loaded_header_notes(tmp_path: Path) -> None:
    from ttc3018_control.application.controller import ApplicationController
    from ttc3018_control.qt.view_model import ControllerViewModel

    path = tmp_path / "candidate.nc"
    path.write_text(GCODE, encoding="utf-8")
    program = load_gcode(path)
    (tmp_path / "candidate-report.json").write_text(json.dumps({
        "candidate": {"sha256": program.source_sha256},
        "tool": {"type": "30 degree V-bit"},
        "motion": {"cutFeedMmPerMin": 450, "spindleCommand": 1000},
    }), encoding="utf-8")
    controller = ApplicationController(tmp_path / "app")
    view_model = ControllerViewModel(controller)
    loaded = controller.load_program(path)

    view_model._remember_backend_program_projection(loaded)

    assert view_model.job_provenance["report_state"] == "matched"
    assert view_model.job_provenance["header_notes"] == [
        "Listed tool: review cutter; physical setup unverified"
    ]
    assert "Reported tool: 30 degree V-bit" in view_model.job_provenance["details"]
    view_model.close()
