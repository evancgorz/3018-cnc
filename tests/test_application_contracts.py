from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from ttc3018_control.application.events import EventLevel, NoticeEvent
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

