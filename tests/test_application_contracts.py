from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from ttc3018_control.application.events import EventLevel, LogEvent, NoticeEvent
from ttc3018_control.application.connection_service import ConnectionService, WifiAttempt
from ttc3018_control.application.generation_service import GenerationService
from ttc3018_control.application.job_service import JobService
from ttc3018_control.application.machine_session import MachineSession
from ttc3018_control.application.state import ApplicationState, ConnectionMode, JobSnapshot
from ttc3018_control.application.wifi_service import WifiProvisioningService
from ttc3018_control.grbl import GrblStatus, Position
from ttc3018_control.machine_state import MachineProfile


def test_application_state_is_immutable_and_qt_independent() -> None:
    state = ApplicationState(connection_mode=ConnectionMode.WIFI)

    assert state.connection_mode is ConnectionMode.WIFI
    assert state.connected is False
    with pytest.raises(FrozenInstanceError):
        state.connected = True  # type: ignore[misc]


def test_job_snapshot_reports_progress_without_ui_formatting() -> None:
    assert JobSnapshot(completed=3, total=4).progress == pytest.approx(0.75)
    assert JobSnapshot().progress == 0.0


def test_application_controller_exposes_a_qt_independent_state_snapshot(tmp_path) -> None:
    from ttc3018_control.application.controller import ApplicationController

    controller = ApplicationController(tmp_path)

    snapshot = controller.state

    assert isinstance(snapshot, ApplicationState)
    assert not snapshot.connected
    assert snapshot.job.state == "idle"
    assert snapshot.program is None


def test_application_controller_publishes_typed_transient_events(tmp_path) -> None:
    from ttc3018_control.application.controller import ApplicationController

    controller = ApplicationController(tmp_path)
    controller._publish_notice("Ready")  # service callback seam
    controller.publish_log("rx", "ok")

    events = controller.application_events()

    assert isinstance(events[0], NoticeEvent)
    assert events[0].message == "Ready"
    assert isinstance(events[1], LogEvent)
    assert events[1].kind == "rx"
    assert controller.application_events() == ()


def test_controller_reset_can_retain_or_invalidate_reference(tmp_path) -> None:
    from ttc3018_control.application.controller import ApplicationController

    controller = ApplicationController(tmp_path)
    controller.session.profile = MachineProfile(travel_x=100, travel_y=100, travel_z=50, safe_z=3)
    transport = _Transport()
    transport.connected = True
    controller.set_transport_for_testing(transport)
    controller.apply_status(GrblStatus("Idle", machine_position=Position(0, 0, 0)))

    assert controller.establish_reference().accepted
    controller.handle_transport_response("Grbl 1.1h", preserve_reference=True)
    assert controller.reference_trusted
    assert controller.status is None
    assert controller.session.status is None
    assert not controller.can_jog

    controller.handle_transport_response("Grbl 1.1h")
    assert not controller.reference_trusted

    controller.set_transport_for_testing(transport)
    controller.apply_status(GrblStatus("Idle", machine_position=Position(0, 0, 0)))
    assert controller.can_jog
    assert controller.establish_reference().accepted
    controller.disconnect("link lost")
    assert not controller.reference_trusted
    assert controller.status is None
    assert controller.session.status is None
    assert not controller.can_jog


def test_abort_owns_one_shot_reference_retention_and_requires_fresh_status(tmp_path) -> None:
    from ttc3018_control.application.controller import ApplicationController

    controller = ApplicationController(tmp_path)
    controller.session.profile = MachineProfile(travel_x=100, travel_y=100, travel_z=50, safe_z=3)
    transport = _Transport()
    transport.connected = True
    controller.set_transport_for_testing(transport)
    controller.apply_status(
        GrblStatus(
            "Idle",
            machine_position=Position(10, 10, 10),
            work_offset=Position(5, 5, 5),
        )
    )
    assert controller.establish_reference().accepted
    controller.session.work_zero_confirmed = True

    controller.abort_job()
    controller.handle_transport_response("Grbl 1.1h")

    assert controller.reference_trusted
    assert controller.status is None
    assert not controller.can_jog
    assert not controller.work_zero_confirmed
    assert controller.session.awaiting_work_zero_report

    controller.apply_status(
        GrblStatus(
            "Idle",
            machine_position=Position(10, 10, 10),
            work_offset=Position(5, 5, 5),
        )
    )
    assert controller.can_jog
    assert controller.work_zero_confirmed


def test_bound_notice_callback_does_not_leave_duplicate_queued_events(tmp_path) -> None:
    from ttc3018_control.application.controller import ApplicationController

    notices: list[str] = []
    controller = ApplicationController(tmp_path, on_notice=notices.append)

    controller._publish_notice("Ready")

    assert notices == ["Ready"]
    assert controller.application_events() == ()


def test_confirmed_work_zero_restores_only_after_matching_fresh_wco(tmp_path) -> None:
    from ttc3018_control.application.controller import ApplicationController

    transport = _Transport()
    transport.connected = True
    first = ApplicationController(tmp_path)
    first.set_transport_for_testing(transport)
    first.apply_status(GrblStatus("Idle", machine_position=Position(20, 20, 5)))
    assert first.set_work_zero("XYZ").accepted
    first.apply_status(
        GrblStatus("Idle", machine_position=Position(20, 20, 5), work_offset=Position(20, 20, 5))
    )
    assert first.work_zero_confirmed

    restored = ApplicationController(tmp_path)
    restored.set_transport_for_testing(transport)
    assert not restored.work_zero_confirmed
    restored.apply_status(
        GrblStatus("Idle", machine_position=Position(21, 20, 5), work_offset=Position(20, 20, 5))
    )
    assert restored.work_zero_confirmed

    mismatch = ApplicationController(tmp_path)
    mismatch.set_transport_for_testing(transport)
    mismatch.apply_status(
        GrblStatus("Idle", machine_position=Position(21, 20, 5), work_offset=Position(19, 20, 5))
    )
    assert not mismatch.work_zero_confirmed


def test_controller_rejects_overlapping_motion_and_job_start_without_preflight(tmp_path) -> None:
    from ttc3018_control.application.controller import ApplicationController

    controller = ApplicationController(tmp_path)
    controller.session.profile = MachineProfile(travel_x=100, travel_y=100, travel_z=50, safe_z=3)
    transport = _Transport()
    transport.connected = True
    controller.set_transport_for_testing(transport)
    controller.apply_status(GrblStatus("Idle", machine_position=Position(0, 0, 0)))
    assert controller.establish_reference().accepted

    assert controller.jog("X", 1).accepted
    overlapping = controller.jog("X", 1)
    assert not overlapping.accepted
    assert "another motion" in overlapping.message

    assert not controller.start_job().accepted


def test_events_are_typed_data() -> None:
    event = NoticeEvent("Machine ready", EventLevel.INFO)

    assert event.message == "Machine ready"
    assert event.level is EventLevel.INFO
    assert not hasattr(event, "show")


def test_application_modules_are_qt_independent_and_qt_adapter_has_no_transport_ownership() -> None:
    root = Path(__file__).parents[1]
    application_dir = root / "src" / "ttc3018_control" / "application"
    for path in application_dir.glob("*.py"):
        assert "PySide6" not in path.read_text(encoding="utf-8")

    view_model = (root / "src" / "ttc3018_control" / "qt" / "view_model.py").read_text(encoding="utf-8")
    assert "from ..serial_connection" not in view_model
    assert "from ..tcp_connection" not in view_model
    assert "JobStreamer" not in view_model


class _Transport:
    connected = False

    def connect(self, *args, **kwargs) -> None:
        self.connected = True

    def disconnect(self) -> None:
        self.connected = False

    def send_line(self, command: bytes, display_text: str | None = None) -> None:
        pass

    def send_realtime(self, command: bytes) -> None:
        pass

    @property
    def events(self):
        return ()


def test_connection_service_owns_one_usb_transport() -> None:
    service = ConnectionService(_Transport, _Transport, lambda _port: ())

    result = service.connect_usb("COM7")

    assert result.accepted
    assert service.connected
    assert service.endpoint == "COM7"
    assert not service.connect_usb("COM8").accepted
    assert service.disconnect().accepted
    assert not service.connected


def test_connection_service_discards_a_stale_wifi_result_after_disconnect() -> None:
    service = ConnectionService(_Transport, _Transport, lambda _port: ())
    stale_transport = _Transport()
    stale_transport.connected = True
    service._wifi_attempt_id = 2  # type: ignore[attr-defined]
    service._wifi_results.put(WifiAttempt(1, stale_transport, "192.168.4.1", 23))  # type: ignore[attr-defined]

    assert service.poll_wifi() is None
    assert not stale_transport.connected


def test_wifi_provisioning_sequences_acknowledged_commands_and_restart_delay() -> None:
    lines: list[tuple[bytes, str | None]] = []
    notices: list[str] = []
    service = WifiProvisioningService(lambda command, display: lines.append((command, display)), notices.append)

    assert service.start("network", "password", 23, now=0).accepted
    assert lines[0][0] == b"[ESP110]STA"

    now = 0.0
    for _ in range(7):
        assert service.handle_response("ok", now)
        now += 0.1
        service.poll(now)
    assert lines[-1][0] == b"[ESP444]RESTART"
    assert service.active

    service.poll(now + 7.9)
    assert service.active
    service.poll(now + 8.0)
    assert not service.active
    assert notices[-1].startswith("Controller Wi-Fi configuration sent")


def test_job_service_streams_and_stops_spindle_before_return() -> None:
    lines: list[bytes] = []
    realtime: list[bytes] = []
    notices: list[str] = []
    ready: list[bool] = []
    service = JobService(MachineSession(), lines.append, realtime.append, notices.append, on_ready_to_return=lambda: ready.append(True))

    assert service.start(("G1 X1",)).accepted
    assert lines == [b"G1 X1\n"]
    assert service.handle_response("ok")
    assert lines[-1] == b"M5\n"
    assert service.spindle_stop_pending
    assert service.handle_response("ok")
    service.observe_status(GrblStatus("Idle"))

    assert ready == [True]
    assert any("spindle stopped" in notice for notice in notices)


def test_generation_service_returns_stable_artifact_metadata() -> None:
    artifact = GenerationService().text("A", font="Simple", text_height=8, depth=-0.3)

    assert artifact.kind == "Text"
    assert artifact.filename == "generated-text.gcode"
    assert artifact.gcode.startswith("; Generated by TTC 3018")
    assert artifact.strokes


def test_generation_service_uses_auto_plane_when_step_plane_is_omitted(monkeypatch, tmp_path) -> None:
    from ttc3018_control.application import generation_service

    selected: list[tuple[Path, str]] = []
    expected = object()

    def fake_import(path: Path, plane: str = "Auto (largest planar face)"):
        selected.append((path, plane))
        return expected

    monkeypatch.setattr(generation_service, "load_step_isolated", fake_import)
    path = tmp_path / "part.step"

    result = GenerationService().import_step(path)

    assert result is expected
    assert selected == [(path, "Auto (largest planar face)")]
