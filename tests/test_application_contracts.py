from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from ttc3018_control.application.events import EventLevel, NoticeEvent
from ttc3018_control.application.connection_service import ConnectionService, WifiAttempt
from ttc3018_control.application.state import ApplicationState, ConnectionMode, JobSnapshot


def test_application_state_is_immutable_and_qt_independent() -> None:
    state = ApplicationState(connection_mode=ConnectionMode.WIFI)

    assert state.connection_mode is ConnectionMode.WIFI
    assert state.connected is False
    with pytest.raises(FrozenInstanceError):
        state.connected = True  # type: ignore[misc]


def test_job_snapshot_reports_progress_without_ui_formatting() -> None:
    assert JobSnapshot(completed=3, total=4).progress == pytest.approx(0.75)
    assert JobSnapshot().progress == 0.0


def test_events_are_typed_data() -> None:
    event = NoticeEvent("Machine ready", EventLevel.INFO)

    assert event.message == "Machine ready"
    assert event.level is EventLevel.INFO
    assert not hasattr(event, "show")


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
