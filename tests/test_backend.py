from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import json
import urllib.error
import urllib.request
import os

import pytest

from ttc3018_control.application.controller import ApplicationController
from ttc3018_control.backend import (BackendClient, BackendOwnershipError,
                                     BackendRequestRejected, BackendRuntime, BackendServer)
from ttc3018_control.qt.main import build_engine
from ttc3018_control.backend.discovery import DiscoveryRecord, DiscoveryStore
from ttc3018_control.backend.protocol import SCHEMA_VERSION, PROTOCOL_VERSION
from ttc3018_control.application.state import ConnectionMode
from ttc3018_control.machine_config import TTC3018_HARDWARE
from ttc3018_control.machine_config import MachineDefinition
from ttc3018_control.work_zero_settings import SavedWorkZero, WorkZeroStore
from ttc3018_control.backend.job_recovery import JobRecoveryStore
from ttc3018_control.grbl import GrblStatus, Position


class _ConnectedTransport:
    connected = True

    def send_line(self, _command: bytes, display_text: str | None = None) -> None:
        pass

    def send_realtime(self, _command: bytes) -> None:
        pass

    @property
    def events(self):
        return ()


def _server(tmp_path: Path, *, poll: bool = False):
    runtime = BackendRuntime(tmp_path)
    server = BackendServer(runtime)
    server.start(poll=poll)
    return runtime, server


def test_runtime_snapshot_and_event_cursor_are_qt_free(tmp_path: Path) -> None:
    runtime = BackendRuntime(tmp_path)
    snapshot = runtime.poll_once(now=10.0)
    assert snapshot["schema_version"] == SCHEMA_VERSION
    assert snapshot["protocol_version"] == PROTOCOL_VERSION
    assert snapshot["machine"]["name"] == "Two Trees TTC 3018"
    events = runtime.events_since(0)
    assert events["events"] and events["events"][0]["sequence"] == 1


def test_backend_snapshot_exposes_job_timing(tmp_path: Path) -> None:
    runtime = BackendRuntime(tmp_path)
    runtime.application.job.load_generated("G21 G90\nG1 X60 F60\nM5\nM2\n", "timed.nc")
    job = runtime.poll_once()["job"]
    assert job["estimated_seconds"] == pytest.approx(60)
    assert job["elapsed_seconds"] == 0
    assert job["remaining_seconds"] == pytest.approx(60)


def test_backend_persists_hash_bound_recovery_context_without_resume_cursor(tmp_path: Path) -> None:
    runtime = BackendRuntime(tmp_path)
    runtime.application.job.load_generated("G21 G90\nG1 X60 F60\nM5\nM2\n", "recovery.nc")
    streamer = runtime.application.job.streamer
    streamer.commands = ("G21 G90", "G1 X60 F60")
    streamer.next_index = 2
    streamer.acknowledged_count = 1
    streamer.state = "failed"
    streamer.error = "transport lost"

    recovery = runtime.poll_once()["job_recovery"]
    assert recovery["state"] == "failed"
    assert recovery["filename"] == "recovery.nc"
    assert recovery["source_sha256"] == runtime.application.program.source_sha256
    assert recovery["accepted_commands"] == 1
    assert recovery["sent_commands"] == 2
    assert recovery["resume_supported"] is False
    assert recovery["requires_operator_review"] is True

    restored = JobRecoveryStore(tmp_path).load()
    assert restored["source_sha256"] == recovery["source_sha256"]
    assert restored["accepted_commands"] == 1


def test_active_recovery_record_becomes_interrupted_on_backend_restart(tmp_path: Path) -> None:
    store = JobRecoveryStore(tmp_path)
    record = store.load()
    record.update({"state": "running", "source_sha256": "abc", "accepted_commands": 42})
    store.save(record)
    recovered = JobRecoveryStore(tmp_path).load()
    assert recovered["state"] == "interrupted"
    assert recovered["accepted_commands"] == 42
    assert recovered["resume_supported"] is False


def test_pause_bookmark_requires_fresh_hold_and_survives_restart_as_review_context(tmp_path: Path) -> None:
    runtime = BackendRuntime(tmp_path)
    app = runtime.application
    app.set_transport_for_testing(_ConnectedTransport())
    app.connection_service.mode = ConnectionMode.WIFI
    program_path = tmp_path / "paused-job.nc"
    program_path.write_text("G21 G90\nG1 X1 F100\n", encoding="utf-8")
    app.load_program(program_path)
    program = app.program
    assert program is not None
    (tmp_path / "paused-job-review.json").write_text(json.dumps({
        "gcodeSha256": program.source_sha256,
        "tool": {"type": "30 degree V-bit", "tipDiameterVerified": False},
    }), encoding="utf-8")
    app.tool_setting.active_offset = 1.25
    app.apply_status(GrblStatus("Run", machine_position=Position(4, 5, -0.2)))
    assert app.job.start().accepted
    assert app.pause_job().accepted

    # Streamer pause is only a request. Neither the prior Run report nor a
    # controller Hold:1 deceleration report creates a confirmed bookmark.
    assert runtime.poll_once()["job_recovery"]["pause_bookmark"]["confirmed"] is False
    app.apply_status(GrblStatus("Hold:1", machine_position=Position(4, 5, -0.1)))
    assert runtime.poll_once()["job_recovery"]["pause_bookmark"]["confirmed"] is False

    app.apply_status(GrblStatus(
        "Hold:0", machine_position=Position(4, 5, -0.1),
        work_position=Position(4, 5, -0.1), work_offset=Position(0, 0, 0), spindle=1000,
    ))
    recovery = runtime.poll_once()["job_recovery"]
    bookmark = recovery["pause_bookmark"]
    assert bookmark["state"] == "confirmed_paused"
    assert bookmark["confirmed"] is True
    assert bookmark["live_hold_confirmed"] is True
    assert bookmark["source_sha256"] == program.source_sha256
    assert bookmark["machine_id"] == app.machine_id
    assert bookmark["run_id"] == app.job_nonce
    assert bookmark["controller_state"] == "Hold:0"
    assert bookmark["accepted_commands"] == app.job.streamer.acknowledged_count
    assert bookmark["position_context"]["position_is_resume_cursor"] is False
    assert bookmark["tool_context"]["provenance_file_sha256"] == program.source_sha256
    assert bookmark["tool_context"]["reported_tool_details"] == [
        "Reported tool: 30 degree V-bit (tip diameter unverified)"
    ]
    assert bookmark["tool_context"]["active_tool_length_offset_mm"] == pytest.approx(1.25)
    assert bookmark["tool_context"]["physical_tool_verified"] is False
    fence = bookmark["recovery_fence"]
    assert fence["automatic_resume_allowed"] is False
    assert fence["resume_supported"] is False
    assert fence["accepted_command_count_is_physical_position"] is False
    assert fence["requires_same_program_sha256"] is True
    assert fence["requires_homing_after_disconnect_or_restart"] is True

    restored = JobRecoveryStore(tmp_path).load()
    restored_bookmark = restored["pause_bookmark"]
    assert restored["state"] == "interrupted"
    assert restored_bookmark["state"] == "interrupted_after_restart"
    assert restored_bookmark["confirmed"] is True  # historical evidence only
    assert restored_bookmark["live_hold_confirmed"] is False
    assert restored_bookmark["current_for_active_run"] is False
    assert restored_bookmark["recovery_fence"]["backend_restart_observed"] is True
    assert restored_bookmark["recovery_fence"]["automatic_resume_allowed"] is False


def test_large_program_snapshot_exposes_bounded_current_cutting_layer(tmp_path: Path) -> None:
    runtime = BackendRuntime(tmp_path)
    program = runtime.application.job.load_generated(
        "G21 G90\nG1 Z-0.6 F120\nG1 X1 Y0 F300\nG1 X2 Y0\nG0 Z3\nM2\n", "layer.nc"
    )
    runtime.application.job.streamer.state = "running"
    runtime.application.status = GrblStatus("Run", Position(2, 0, -0.6), Position(2, 0, -0.6),
                                             Position(0, 0, 0), 300, 1000, "", {})
    layer = runtime._execution_layer_snapshot(program, program.segments)
    assert layer["state"] == "cutting_layer"
    assert layer["z"] == pytest.approx(-0.6)
    assert layer["source_segment_count"] == 2
    assert len(layer["strokes"]) == 1


def test_runtime_snapshot_exposes_saved_work_zero_after_backend_restart(tmp_path: Path) -> None:
    saved = SavedWorkZero(35.0, 40.0, 12.0)
    machine_id = MachineDefinition.legacy_3018().machine_id
    WorkZeroStore(tmp_path / "config" / "work-zero.json").save(saved, machine_id)

    # Constructing a fresh runtime is the same persistence boundary used by a
    # backend restart; it loads only the selected machine's previous zero.
    runtime = BackendRuntime(tmp_path)
    snapshot = runtime.snapshot()

    assert snapshot["saved_work_zero"] == {
        "x": 35.0, "y": 40.0, "z": 12.0, "confirmed_axes": ["X", "Y", "Z"]
    }
    assert snapshot["work_zero_confirmed"] is False


def test_server_requires_auth_and_client_reconnect_keeps_session(tmp_path: Path) -> None:
    runtime, server = _server(tmp_path)
    try:
        request = urllib.request.Request(f"http://{server.address[0]}:{server.address[1]}/v1", data=b"{}", method="POST")
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(request, timeout=1)
        assert error.value.code == 401
        first = BackendClient(tmp_path)
        attached = first.attach()
        second = BackendClient(tmp_path)
        assert second.attach()["health"]["session_id"] == attached["health"]["session_id"]
        assert second.snapshot()["backend"]["session_id"] == attached["health"]["session_id"]
    finally:
        server.stop(shutdown_runtime=False)


def test_dispatch_rejects_unknown_actions_and_never_exposes_raw_send(tmp_path: Path) -> None:
    runtime, server = _server(tmp_path)
    try:
        client = BackendClient(tmp_path)
        client.attach()
        with pytest.raises(BackendRequestRejected):
            client.invoke("send-line", command="G0 X0")
        with pytest.raises(BackendRequestRejected):
            client.invoke("jog", axis="X", distance=1.0, raw="G0 X0")
    finally:
        server.stop(shutdown_runtime=False)


def test_discovery_requires_pid_and_authenticated_health(tmp_path: Path) -> None:
    store = DiscoveryStore(tmp_path)
    record = DiscoveryRecord(SCHEMA_VERSION, PROTOCOL_VERSION, os.getpid(), "127.0.0.1", 1234, "token", "session")
    store.write(record)
    assert store.is_stale()  # PID alone cannot establish freshness.
    assert not store.is_stale(lambda current: current.session_id == "session")
    assert store.is_stale(lambda current: False)
    assert not store.remove(DiscoveryRecord(record.schema_version, record.protocol_version, 2, record.host, record.port, record.token, record.session_id))
    assert store.remove(record)


def test_backend_root_has_one_owner_and_releases_exact_marker(tmp_path: Path) -> None:
    runtime, server = _server(tmp_path)
    try:
        second = BackendServer(BackendRuntime(tmp_path), root=tmp_path)
        with pytest.raises(BackendOwnershipError, match="healthy backend"):
            second.start(poll=False)
        owner = server.discovery.read_owner()
        assert owner is not None and owner.pid == os.getpid()
    finally:
        server.stop(shutdown_runtime=False)
    assert server.discovery.read() is None
    assert server.discovery.read_owner() is None


def test_dead_discovery_record_is_cleaned_before_startup(tmp_path: Path) -> None:
    store = DiscoveryStore(tmp_path)
    dead_pid = os.getpid() + 1_000_000
    while store.pid_is_alive(dead_pid):
        dead_pid += 1
    stale = DiscoveryRecord(SCHEMA_VERSION, PROTOCOL_VERSION, dead_pid, "127.0.0.1",
                            1234, "stale-token", "stale-session")
    store.write(stale)
    runtime, server = _server(tmp_path)
    try:
        assert server.record is not None
        assert server.record.session_id != stale.session_id
        assert store.read() == server.record
    finally:
        server.stop(shutdown_runtime=False)


def test_backend_client_heartbeat_and_close_do_not_change_session(tmp_path: Path) -> None:
    runtime, server = _server(tmp_path)
    try:
        first = BackendClient(tmp_path)
        attached = first.attach()
        assert first.heartbeat()["session_id"] == attached["health"]["session_id"]
        first_record = first.record
        first_record = first_record.session_id if first_record is not None else ""
        # Dropping a client is frontend-local; a new client observes the same owner.
        second = BackendClient(tmp_path)
        assert second.attach()["health"]["session_id"] == first_record
    finally:
        server.stop(shutdown_runtime=False)


def test_ttc_declaration_is_fixed_and_uncommissioned() -> None:
    facts = TTC3018_HARDWARE.to_dict()
    assert facts["machine"] == "Two Trees TTC 3018"
    assert facts["controller"].startswith("MKS DLC32")
    assert facts["nominal_travel_mm"] == {"X": 290.0, "Y": 170.0, "Z": 40.0}
    assert facts["safe_z_mm"] == 30.0
    assert facts["estop"] == "installed_uncommissioned"


def test_client_backed_qt_composition_does_not_construct_controller(qapp, tmp_path: Path, monkeypatch) -> None:
    runtime, server = _server(tmp_path)
    try:
        client = BackendClient(tmp_path)
        client.attach()
        monkeypatch.setattr("ttc3018_control.qt.main.ApplicationController", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("controller constructed")))
        engine, view_model = build_engine(backend_client=client, root=tmp_path)
        assert engine.rootObjects()
        view_model.close()
        engine.deleteLater()
    finally:
        server.stop(shutdown_runtime=False)
