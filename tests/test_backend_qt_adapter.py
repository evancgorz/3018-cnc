from __future__ import annotations

from pathlib import Path

from ttc3018_control.backend.client import BackendUnavailable
from ttc3018_control.backend.qt_adapter import BackendApplicationAdapter
from ttc3018_control.application.state import ConnectionMode
from ttc3018_control.step_prepare_settings import StepPrepareSettings
from ttc3018_control.grbl import Position


class _FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.attach_count = 0
        self.fail_events = False
        self.saved_work_zero = None

    def snapshot(self):
        return {
            "schema_version": 1, "protocol_version": 1, "revision": 4,
            "backend": {"available": True, "session_id": "session-a"},
            "machine": {"machine_id": "ttc3018-3018", "name": "Two Trees TTC 3018"},
            "connection_mode": "Virtual Machine (Digital Twin)", "connected": False,
            "status_state": "unavailable", "status_fresh": False,
            "reference_trusted": False, "work_zero_confirmed": False,
            "saved_work_zero": self.saved_work_zero,
            "safety": {"physical_estop": {
                "state": "latched", "raw_state": "active", "commissioned": True,
                "latched": True, "blocks_motion": True, "power_removal": "unknown",
                "reason": "channels open", "channel_a_closed": False,
                "channel_b_closed": False, "transition_id": 3,
            }},
            "capabilities": {"actions": ["status"]},
        }

    def events(self, *, after=None, limit=100):
        if self.fail_events:
            raise BackendUnavailable("temporary backend outage")
        return {"events": [{"sequence": 1, "kind": "status", "payload": {"state": "Idle"}, "timestamp": 1.0}],
                "next_sequence": 1}

    def attach(self):
        self.attach_count += 1
        return {"health": {"session_id": "session-a"}, "snapshot": self.snapshot()}

    def invoke(self, action, **kwargs):
        self.calls.append((action, kwargs))
        return {"accepted": True, "message": "ok"}


def test_adapter_rebuilds_from_backend_events_and_close_is_frontend_only(tmp_path: Path) -> None:
    client = _FakeClient()
    client.saved_work_zero = {"x": 35, "y": 40, "z": 12}
    adapter = BackendApplicationAdapter(client, tmp_path)
    events = adapter.poll_backend()
    assert [event.sequence for event in events] == [1]
    assert adapter.backend_available is True
    assert adapter.physical_safety_input_status["state"] == "latched"
    assert adapter.physical_safety_input_status["power_removal"] == "unknown"
    assert adapter.physical_safety_input_status["blocks_motion"] is True
    assert adapter.saved_work_zero == Position(35, 40, 12)
    assert adapter.saved_work_zero_axes == frozenset("XYZ")
    adapter.close()
    assert all(action != "shutdown" for action, _ in client.calls)


def test_adapter_preserves_bounded_large_job_preview_payload(tmp_path: Path) -> None:
    client = _FakeClient()
    preview = {
        "kind": "raster_xy_all_moves",
        "data_url": "data:image/png;base64,abc",
        "width": 1024,
        "height": 768,
        "segment_count": 6001,
        "rendered_segment_count": 6001,
        "all_segments_rendered": True,
        "note": "every move projected into XY",
    }
    snapshot = client.snapshot
    client.snapshot = lambda: {
        **snapshot(),
        "program_detail": {
            "path": str(tmp_path / "large.nc"),
            "commands": [], "segments": [],
            "bounds": {
                "minimum": {"x": 0, "y": 0, "z": 0},
                "maximum": {"x": 10, "y": 10, "z": 0},
            },
            "estimated_seconds": 1,
            "command_count": 6001,
            "preview_available": True,
            "preview": preview,
        },
    }

    adapter = BackendApplicationAdapter(client, tmp_path)

    assert adapter.program is not None
    assert len(adapter.program.commands) == 6001
    assert adapter.program.segments == ()
    assert adapter.program_preview == preview


def test_adapter_exposes_setup_only_usb_connection_state(tmp_path: Path) -> None:
    client = _FakeClient()
    original_snapshot = client.snapshot
    client.snapshot = lambda: {
        **original_snapshot(),
        "connection_mode": "USB serial",
        "operation_transport_ready": False,
        "connection": {"mode": "USB serial", "setup_only": True},
    }
    adapter = BackendApplicationAdapter(client, tmp_path)

    assert adapter.connection_setup_only


def test_adapter_infers_setup_only_from_usb_mode_and_readiness(tmp_path: Path) -> None:
    client = _FakeClient()
    original_snapshot = client.snapshot
    state = {"mode": "USB serial", "ready": False}
    client.snapshot = lambda: {
        **original_snapshot(),
        "connection_mode": state["mode"],
        "operation_transport_ready": state["ready"],
        "connection": {"mode": state["mode"], "setup_only": False},
    }
    adapter = BackendApplicationAdapter(client, tmp_path)

    assert adapter.connection_setup_only

    state.update(mode="Wi-Fi TCP", ready=False)
    adapter._refresh()
    assert not adapter.connection_setup_only


def test_adapter_preserves_partial_saved_work_zero_axes(tmp_path: Path) -> None:
    client = _FakeClient()
    client.saved_work_zero = {
        "x": 35, "y": 40, "z": 12, "confirmed_axes": ["X", "Y"]
    }
    adapter = BackendApplicationAdapter(client, tmp_path)

    assert adapter.saved_work_zero == Position(35, 40, 12)
    assert adapter.saved_work_zero_axes == frozenset("XY")


def test_adapter_reconnects_after_backend_unavailable_and_routes_configuration(tmp_path: Path) -> None:
    client = _FakeClient()
    adapter = BackendApplicationAdapter(client, tmp_path)
    client.fail_events = True
    adapter.poll_backend()
    assert adapter.backend_available is False
    client.fail_events = False
    adapter._retry_after = 0.0
    adapter.poll_backend()
    assert adapter.backend_available is True
    assert client.attach_count == 1
    assert adapter.save_homing_limit_declarations({axis: {"enabled": False} for axis in "XYZ"}).accepted
    assert adapter.save_step_prepare_settings(StepPrepareSettings()).accepted
    assert any(action == "save-homing-declarations" for action, _ in client.calls)
    assert any(action == "save-step-settings" for action, _ in client.calls)


def test_adapter_preserves_connection_outcome_fields(tmp_path: Path) -> None:
    client = _FakeClient()

    def invoke(action, **kwargs):
        client.calls.append((action, kwargs))
        return {
            "accepted": True,
            "message": "Trying saved endpoint",
            "mode": "Wi-Fi TCP",
            "host": "192.168.86.38",
            "port": 23,
        }

    client.invoke = invoke
    adapter = BackendApplicationAdapter(client, tmp_path)
    outcome = adapter.begin_wifi("192.168.86.38", 23)

    assert outcome.accepted
    assert outcome.mode is ConnectionMode.WIFI
    assert outcome.host == "192.168.86.38"
    assert outcome.port == 23


def test_adapter_exposes_guarded_target_move(tmp_path: Path) -> None:
    client = _FakeClient()
    adapter = BackendApplicationAdapter(client, tmp_path)
    outcome = adapter.move_to(Position(12.5, 8.0, 3.0), 450.0)
    assert outcome.accepted
    action, arguments = client.calls[-1]
    assert action == "move-to"
    assert {key: arguments[key] for key in ("x", "y", "z", "feed")} == {
        "x": 12.5, "y": 8.0, "z": 3.0, "feed": 450.0,
    }


def test_adapter_exposes_travel_calibration_lifecycle(tmp_path: Path) -> None:
    client = _FakeClient()
    adapter = BackendApplicationAdapter(client, tmp_path)
    assert adapter.start_travel_calibration(
        increment_mm=10.0, max_overshoot_mm=30.0,
        search_feed=120.0, return_feed=600.0,
    ).accepted
    assert adapter.abort_travel_calibration().accepted
    assert adapter.accept_travel_calibration().accepted
    assert [action for action, _ in client.calls[-3:]] == [
        "travel-calibration-start", "travel-calibration-abort", "travel-calibration-accept",
    ]


def test_adapter_keeps_watchdog_recovery_separate_from_job_resume(tmp_path: Path) -> None:
    client = _FakeClient()
    snapshot = client.snapshot
    client.snapshot = lambda: {
        **snapshot(),
        "watchdog_recovery": {"state": "ready", "can_continue_to_home": True, "can_cancel": True},
        "automatic_continuation": {"enabled": False},
    }
    adapter = BackendApplicationAdapter(client, tmp_path)
    assert adapter.watchdog_recovery["can_continue_to_home"]
    assert not adapter.automatic_continuation["enabled"]
    assert adapter.continue_to_home().accepted
    assert adapter.cancel_recovery().accepted
    assert [action for action, _ in client.calls] == ["continue-to-home", "cancel-recovery"]
