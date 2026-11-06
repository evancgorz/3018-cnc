import json
from pathlib import Path
import time

import pytest

from ttc3018_control import cam_worker

EXAMPLES = Path(__file__).resolve().parents[1] / "examples" / "agent-cam"


def wait(root, job_id, timeout=60):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = cam_worker.status(root, job_id)
        if result["state"] in {"completed", "failed", "cancelled"}:
            return result
        time.sleep(0.1)
    raise AssertionError(f"CAM worker did not finish within {timeout}s")


@pytest.mark.parametrize("kind", ["plaque", "raster", "step-pocket"])
def test_background_job_publishes_review_bundle(tmp_path, kind):
    root = tmp_path / "runs"
    queued = cam_worker.submit(EXAMPLES / f"{kind}.json", root)
    assert queued["state"] == "queued"
    assert queued["worker_pid"] > 0

    result = wait(root, queued["job_id"])
    assert result["state"] == "completed", result["error"]
    assert result["progress_percent"] == 100
    bundle = Path(result["bundle_path"])
    assert bundle.is_dir()
    manifest = json.loads((bundle / "report.json").read_text())
    assert manifest["kind"] == kind
    assert result["gcode_sha256"] == manifest["sha256"]["candidate-review-only.nc"]
    assert cam_worker.status(root, queued["job_id"])["state"] == "completed"
    with pytest.raises(ValueError, match="Only failed or cancelled"):
        cam_worker.retry(root, queued["job_id"])


def test_cancel_and_retry_use_immutable_source_snapshot(tmp_path):
    spec = tmp_path / "design.json"
    source = tmp_path / "art.pgm"
    original_source = (EXAMPLES / "cross.pgm").read_bytes()
    source.write_bytes(original_source)
    original_spec = json.loads((EXAMPLES / "raster.json").read_text())
    original_spec["source"] = source.name
    spec.write_text(json.dumps(original_spec), encoding="utf-8")
    root = tmp_path / "runs"

    queued = cam_worker.submit(spec, root)
    old_id = queued["job_id"]
    source.write_bytes(b"changed")
    snap = cam_worker._job_path(root, old_id) / "input" / "source.pgm"
    assert snap.read_bytes() == original_source

    cam_worker.cancel(root, old_id)
    cancelled = wait(root, old_id)
    assert cancelled["state"] == "cancelled"
    assert not (cam_worker._job_path(root, old_id) / "bundle").exists()

    retried = cam_worker.retry(root, old_id)
    assert retried["job_id"] != old_id
    completed = wait(root, retried["job_id"])
    assert completed["state"] == "completed", completed["error"]
    assert Path(completed["bundle_path"], "source.pgm").read_bytes() == original_source


def test_rejects_absolute_source_without_creating_job(tmp_path):
    data = json.loads((EXAMPLES / "step-pocket.json").read_text())
    data["source"] = str((EXAMPLES / "extruded-circle.step").resolve())
    spec = tmp_path / "absolute.json"
    spec.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="relative"):
        cam_worker.submit(spec, tmp_path / "runs")
    assert not (tmp_path / "runs" / "jobs").exists()


def test_saved_setup_snapshot_survives_registry_changes_and_rebuild(tmp_path):
    from ttc3018_control.agent_cam import build

    registry = tmp_path / "setups"
    registry.mkdir()
    record_name = "plywood-vbit-engraving.json"
    record_path = registry / record_name
    record = json.loads((EXAMPLES.parent / "hardware-setups" / record_name).read_text(encoding="utf-8"))
    record_path.write_text(json.dumps(record), encoding="utf-8")
    design = json.loads((EXAMPLES / "plaque-saved-setup.json").read_text(encoding="utf-8"))
    design["setup"]["registry"] = "setups"
    spec = tmp_path / "design.json"
    spec.write_text(json.dumps(design), encoding="utf-8")

    root = tmp_path / "runs"
    queued = cam_worker.submit(spec, root)
    record["stock"]["dimensions_mm"]["thickness"]["value"] = 4.0
    record_path.write_text(json.dumps(record), encoding="utf-8")
    result = wait(root, queued["job_id"])
    assert result["state"] == "completed", result["error"]
    bundle = Path(result["bundle_path"])
    report = json.loads((bundle / "report.json").read_text(encoding="utf-8"))
    assert report["setup"]["id"] == "plywood-vbit-engraving"
    assert report["stock_mm"] == [100, 100, 3.25]
    from ttc3018_control.application.job_provenance import build_job_provenance, load_review_bundle

    program = load_review_bundle(bundle / "report.json")
    evidence = build_job_provenance(program.path, program.source_sha256)
    assert evidence["setup_name"] == report["setup"]["name"]
    assert "Reported XY datum: Lower-left stock corner" in evidence["details"]
    rebuilt = build(bundle / "design.json", tmp_path / "rebuilt")
    assert rebuilt["sha256"] == report["sha256"]
