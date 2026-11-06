from __future__ import annotations

from pathlib import Path

import pytest

from ttc3018_control.application.controller import ApplicationController
from ttc3018_control.backend import (
    ActionCommand,
    ActionResult,
    BackendClient,
    BackendRuntime,
    BackendServer,
    BackendSnapshot,
)
from ttc3018_control.backend.dispatcher import ActionDispatcher, ActionRejected
from ttc3018_control.backend.protocol import (MAX_REQUEST_BYTES, ProtocolError,
                                              request, validate_request)
from ttc3018_control.step_prepare_settings import StepPrepareSettings
from ttc3018_control.application.machine_session import ActionOutcome


def _runtime(tmp_path: Path) -> BackendRuntime:
    application = ApplicationController(tmp_path, usb_ports=lambda: [("COM-test", "isolated fake")])
    return BackendRuntime(tmp_path, application=application)


def test_typed_snapshot_advertises_capabilities_and_semantic_revision(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    first = BackendSnapshot.from_dict(runtime.snapshot())
    assert first.schema_version == 1
    assert first.protocol_version == 1
    assert "jog" in first.capabilities.actions
    assert "move-to" in first.capabilities.actions
    assert "travel-calibration-start" in first.capabilities.actions
    assert "travel-calibration-accept" in first.capabilities.actions
    assert "home" in first.capabilities.actions
    assert "establish-reference" not in first.capabilities.actions
    assert "raw-command" not in first.capabilities.actions
    assert "loopback_digital_twin" in first.capabilities.simulation_only
    revision = first.revision
    runtime.snapshot()
    assert runtime.state_revision == revision
    runtime.poll_once(now=10.0)
    assert runtime.state_revision == revision


def test_event_cursor_reports_missed_history_without_reordering(tmp_path: Path) -> None:
    runtime = BackendRuntime(tmp_path, max_events=2)
    runtime._emit("first", {"value": 1})
    runtime._emit("second", {"value": 2})
    runtime._emit("third", {"value": 3})
    result = runtime.events_since(0, limit=2)
    assert result["lost"] is True
    assert [item["sequence"] for item in result["events"]] == sorted(item["sequence"] for item in result["events"])


def test_protocol_rejects_unknown_envelope_fields_and_version_mismatch() -> None:
    with pytest.raises(ProtocolError):
        validate_request({**request("status"), "privileged": True})
    with pytest.raises(ProtocolError):
        validate_request({**request("status"), "protocol_version": 99})


def test_dispatcher_covers_discovery_config_and_generated_job_without_qt(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    dispatcher = ActionDispatcher(runtime)
    assert dispatcher.invoke("discover-usb") == {
        "ports": [{"port": "COM-test", "description": "isolated fake"}]
    }
    saved = dispatcher.invoke("save-profile", {"name": "Two Trees TTC 3018",
                              "travel_x": 290.0, "travel_y": 170.0, "travel_z": 40.0, "safe_z": 30.0})
    assert saved["accepted"] is True
    loaded = dispatcher.invoke("load-generated-job", {"gcode": "G21 G90\nG1 X1 F100\n", "filename": "generated.nc"})
    assert loaded["accepted"] is True
    review = dispatcher.invoke("review-job")
    assert review["accepted"] is False
    assert "reference" in review["message"].lower()


def test_dispatcher_enforces_revision_idempotency_and_raw_action_boundary(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    dispatcher = ActionDispatcher(runtime)
    with pytest.raises(ActionRejected, match="revision mismatch"):
        dispatcher.invoke("status", expected_revision=runtime.state_revision + 1)
    with pytest.raises(ActionRejected):
        dispatcher.invoke("send-line", {"command": "G0 X0"})
    with pytest.raises(ActionRejected):
        dispatcher.invoke("establish-reference")
    first = dispatcher.invoke("save-profile", {"name": "Two Trees TTC 3018",
                              "travel_x": 290.0, "travel_y": 170.0, "travel_z": 40.0, "safe_z": 30.0},
                             idempotency_key="profile-1")
    second = dispatcher.invoke("save-profile", {"name": "Two Trees TTC 3018",
                               "travel_x": 290.0, "travel_y": 170.0, "travel_z": 40.0, "safe_z": 30.0},
                              idempotency_key="profile-1")
    assert first == second
    with pytest.raises(ActionRejected, match="different command"):
        dispatcher.invoke("save-profile", {"name": "Other", "travel_x": 290.0, "travel_y": 170.0,
                          "travel_z": 40.0, "safe_z": 30.0}, idempotency_key="profile-1")


def test_dispatcher_routes_remaining_typed_configuration_actions(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    dispatcher = ActionDispatcher(runtime)
    declarations = {axis: {"enabled": False, "end": "min"} for axis in "XYZ"}
    homing = dispatcher.invoke("save-homing-declarations", {"declarations": declarations})
    assert homing["accepted"] is True
    step = dispatcher.invoke("save-step-settings", StepPrepareSettings().__dict__)
    assert step["accepted"] is True
    plate = dispatcher.invoke("save-z-plate-settings", {
        "thickness": 1.0, "active_low": False, "fast_feed": 100.0,
        "slow_feed": 25.0, "max_search": 10.0, "retract": 1.0,
        "safe_retract": 2.0, "tolerance": 0.05,
    })
    assert plate["accepted"] is False
    assert "enable" in plate["message"].lower()


def test_dispatcher_routes_guarded_target_move(tmp_path: Path, monkeypatch) -> None:
    runtime = _runtime(tmp_path)
    dispatcher = ActionDispatcher(runtime)
    captured = {}

    def move_to(target, feed):
        captured.update(target=target, feed=feed)
        return ActionOutcome(True, "Position move accepted.")

    monkeypatch.setattr(runtime.application, "move_to", move_to)
    result = dispatcher.invoke("move-to", {"x": 12.5, "y": 8.0, "z": 3.0, "feed": 450.0})
    assert result["accepted"] is True
    assert (captured["target"].x, captured["target"].y, captured["target"].z) == (12.5, 8.0, 3.0)
    assert captured["feed"] == 450.0


def test_dispatcher_routes_travel_calibration_lifecycle(tmp_path: Path, monkeypatch) -> None:
    runtime = _runtime(tmp_path)
    dispatcher = ActionDispatcher(runtime)
    calls = []
    monkeypatch.setattr(runtime.application, "start_travel_calibration",
                        lambda **options: calls.append(("start", options)) or ActionOutcome(True, "started"))
    monkeypatch.setattr(runtime.application, "abort_travel_calibration",
                        lambda: calls.append(("abort", {})) or ActionOutcome(True, "aborted"))
    monkeypatch.setattr(runtime.application, "accept_travel_calibration",
                        lambda: calls.append(("accept", {})) or ActionOutcome(True, "accepted"))
    assert dispatcher.invoke("travel-calibration-start", {
        "increment_mm": 5.0, "max_overshoot_mm": 20.0,
        "search_feed": 100.0, "return_feed": 500.0,
    })["accepted"]
    assert dispatcher.invoke("travel-calibration-abort")["accepted"]
    assert dispatcher.invoke("travel-calibration-accept")["accepted"]
    assert [name for name, _ in calls] == ["start", "abort", "accept"]


def test_client_exposes_typed_command_and_structured_rejection(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    server = BackendServer(runtime)
    server.start(poll=False)
    try:
        client = BackendClient(tmp_path)
        client.attach()
        result = client.invoke_command(ActionCommand("capabilities"))
        assert isinstance(result, ActionResult)
        assert result.accepted is True
        with pytest.raises(Exception) as error:
            client.invoke("jog", axis="X", distance=1.0, raw="G0 X0")
        assert getattr(error.value, "error", None) is not None
        assert getattr(error.value.error, "code", "") == "invalid_request"
    finally:
        server.stop(shutdown_runtime=False)


def test_client_accepts_bounded_snapshot_larger_than_request_limit(tmp_path: Path, monkeypatch) -> None:
    runtime = _runtime(tmp_path)
    server = BackendServer(runtime)
    server.start(poll=False)
    try:
        # Raster-preview snapshots can legitimately exceed the smaller inbound
        # request cap while remaining below MAX_RESPONSE_BYTES.
        snapshot = {"preview_blob": "x" * (MAX_REQUEST_BYTES + 1024)}
        monkeypatch.setattr(runtime, "snapshot", lambda: snapshot)
        client = BackendClient(tmp_path)
        attached = client.attach()
        assert attached["snapshot"]["preview_blob"] == snapshot["preview_blob"]
    finally:
        server.stop(shutdown_runtime=False)


def test_client_exposes_backend_owned_safety_status_and_guarded_acknowledgement(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    server = BackendServer(runtime)
    server.start(poll=False)
    try:
        client = BackendClient(tmp_path)
        client.attach()
        status = client.safety_input_status()
        assert status["state"] == "unknown"
        assert status["commissioned"] is False
        assert status["power_removal"] == "unknown"
        acknowledgement = client.acknowledge_safety_input()
        assert acknowledgement["accepted"] is False
    finally:
        server.stop(shutdown_runtime=False)
