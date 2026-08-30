from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from ttc3018_control.application.events import EventLevel, NoticeEvent
from ttc3018_control.application.connection_service import ConnectionService, WifiAttempt
from ttc3018_control.application.generation_service import GenerationService
from ttc3018_control.application.job_service import JobService
from ttc3018_control.application.machine_session import MachineSession
from ttc3018_control.application.state import ApplicationState, ConnectionMode, JobSnapshot
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

    controller.handle_transport_response("Grbl 1.1h")
    assert not controller.reference_trusted


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
