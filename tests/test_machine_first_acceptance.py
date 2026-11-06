"""Isolated acceptance journeys through CAM, Pine GUI, CLI, and the twin.

These fixtures are representative acceptance workflows. They never attach to
the user's GUI/backend or a physical CNC controller.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
from pathlib import Path
import time

from PySide6.QtCore import QUrl

from ttc3018_control.agent_cam import build
from ttc3018_control.backend import BackendClient, BackendRuntime, BackendServer
from ttc3018_control.backend.cli import main as cli_main
from ttc3018_control.qt.main import build_engine


EXAMPLES = Path(__file__).resolve().parents[1] / "examples" / "agent-cam"


def _wait_for(client: BackendClient, predicate, timeout: float = 3.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        snapshot = client.snapshot()
        if predicate(snapshot):
            return snapshot
        time.sleep(0.03)
    raise AssertionError(f"backend state did not reach expected condition: {client.snapshot()}")


def _cli(*args: str) -> tuple[int, dict]:
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        result = cli_main([*args, "--json"])
    return result, json.loads(output.getvalue())


def _start_isolated_backend(root: Path):
    server = BackendServer(BackendRuntime(root), root=root)
    server.start(poll=True)
    client = BackendClient(root)
    client.attach()
    return server, client


def test_repeated_known_job_is_same_bytes_in_cli_and_offscreen_gui(qapp, tmp_path: Path) -> None:
    """Repeat a saved known cut through both frontends without touching source files."""
    source = EXAMPLES / "plaque.json"
    bundle = tmp_path / "known-cut"
    report = build(source, bundle)
    job = bundle / "candidate-review-only.nc"
    first_bytes = job.read_bytes()
    first_hash = hashlib.sha256(first_bytes).hexdigest()
    assert report["status"] == "review-only"

    machine_root = tmp_path / "machine"
    server, client = _start_isolated_backend(machine_root)
    engine, view_model = build_engine(visible=False, backend_client=client, root=machine_root)
    try:
        rc, loaded = _cli("--root", str(machine_root), "load-job", str(job))
        assert rc == 0
        assert loaded["accepted"] is True
        snapshot = _wait_for(client, lambda state: isinstance(state.get("program_detail"), dict)
                             and state["program_detail"].get("source_sha256") == first_hash)
        assert snapshot["job_active"] is False

        # The GUI's file-picker loader asks its adapter to refresh immediately;
        # refresh once after the CLI request has settled to share that snapshot.
        view_model.application._refresh()

        # The desktop uses this same slot for its local-file picker binding.
        view_model.load_gcode_file(QUrl.fromLocalFile(str(job)))
        assert view_model.job_provenance["file_sha256"] in ("", first_hash)
        assert view_model.job_file == job.name
        root_object = engine.rootObjects()[0]
        view_model.select_guided_step(5)
        qapp.processEvents()
        assert root_object.property("guidedIndex") == 5

        # The repeat is byte-for-byte identical and accepted by both interfaces.
        assert job.read_bytes() == first_bytes
        rc, repeated = _cli("--root", str(machine_root), "load-job", str(job))
        assert rc == 0 and repeated["accepted"] is True
        _wait_for(client, lambda state: isinstance(state.get("program_detail"), dict)
                  and state["program_detail"].get("source_sha256") == first_hash)
        assert hashlib.sha256(job.read_bytes()).hexdigest() == first_hash

        # No connection, homing, zero, authorization, or job start was requested.
        final = client.snapshot()
        assert final["connected"] is False
        assert final["job_active"] is False
    finally:
        view_model.close()
        engine.deleteLater()
        qapp.processEvents()
        server.stop()


def test_new_agent_prepared_job_crosses_cli_and_offscreen_gui_review(qapp, tmp_path: Path) -> None:
    """A newly compiled concept bundle is reviewable through CLI and Pine's GUI."""
    bundle = tmp_path / "new-concept"
    report = build(EXAMPLES / "raster.json", bundle)
    job = bundle / "candidate-review-only.nc"
    expected_hash = report["sha256"][job.name]

    machine_root = tmp_path / "machine"
    server, client = _start_isolated_backend(machine_root)
    engine, view_model = build_engine(visible=False, backend_client=client, root=machine_root)
    try:
        manifest = bundle / "report.json"
        view_model.load_gcode_file(QUrl.fromLocalFile(str(manifest)))
        assert client.snapshot()["program_detail"]["source_sha256"] == expected_hash
        rc, loaded = _cli("--root", str(machine_root), "load-job", str(manifest))
        assert rc == 0 and loaded["accepted"] is True
        assert not client.snapshot()["job_active"]

        assert view_model.job_provenance["report_state"] == "matched"
        assert hashlib.sha256(job.read_bytes()).hexdigest() == expected_hash
        assert view_model.job_file == job.name
        assert view_model.job_provenance["file_sha256"] == expected_hash
        assert view_model.job_provenance["release_status"] == "review-only"

        # A review candidate cannot start with the isolated backend disconnected.
        rc, preflight = _cli("--root", str(machine_root), "preflight")
        assert rc == 2
        assert preflight["accepted"] is False
        assert "setup only" in preflight["message"].lower()
        assert client.snapshot()["job_active"] is False
        assert client.snapshot()["connected"] is False
    finally:
        view_model.close()
        engine.deleteLater()
        qapp.processEvents()
        server.stop()
