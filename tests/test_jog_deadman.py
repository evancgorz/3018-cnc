from __future__ import annotations

import pytest

from ttc3018_control.application.machine_session import MachineSession
from ttc3018_control.application.motion_service import MotionService
from ttc3018_control.grbl import GrblStatus, Position, REALTIME_JOG_CANCEL
from ttc3018_control.machine_state import MachineProfile


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _motion(*, position: Position = Position(10, 10, 10)):
    clock = _Clock()
    sent: list[bytes] = []
    realtime: list[bytes] = []
    notices: list[str] = []
    session = MachineSession(
        profile=MachineProfile(travel_x=100, travel_y=80, travel_z=40, safe_z=3),
        status=GrblStatus("Idle", machine_position=position),
    )
    assert session.establish_reference().accepted
    service = MotionService(session, sent.append, realtime.append, notices.append, clock=clock)
    return service, session, clock, sent, realtime, notices


def _start(service: MotionService, token: str = "press-1") -> None:
    outcome = service.start_live_jog("X", 1, False, 500, lease_token=token)
    assert outcome.accepted, outcome.message


def test_fast_ack_and_elapsed_time_do_not_advance_without_fresh_idle_endpoint() -> None:
    service, session, clock, sent, _realtime, _notices = _motion()

    _start(service)
    assert sent == [b"$J=G91 G21 X1.66667 F500\n"]
    assert service.pending_acks == 1
    assert service.handle_response("ok", 500)
    assert service.pending_acks == 0

    clock.now = 0.199
    service.poll_live_jog()
    assert len(sent) == 1

    clock.now = 0.2
    service.poll_live_jog()
    assert len(sent) == 1

    old_idle = GrblStatus("Idle", machine_position=Position(10, 10, 10))
    session.update_status(old_idle)
    service.observe_status(old_idle)
    service.poll_live_jog()
    assert len(sent) == 1
    service.observe_status(old_idle)
    service.poll_live_jog()
    assert len(sent) == 1

    expected_jog = GrblStatus("Jog", machine_position=Position(11.66667, 10, 10))
    session.update_status(expected_jog)
    service.observe_status(expected_jog)
    service.poll_live_jog()
    assert len(sent) == 1

    expected_idle = GrblStatus("Idle", machine_position=Position(11.66667, 10, 10))
    session.update_status(expected_idle)
    service.observe_status(expected_idle)
    service.poll_live_jog()
    assert len(sent) == 2
    assert sent[1] == sent[0]
    assert service.pending_acks == 1


def test_lease_renewal_is_token_bound_and_expiry_cancels_without_more_segments() -> None:
    service, session, clock, sent, realtime, _notices = _motion()

    _start(service, "current-press")
    assert not service.renew_live_jog("stale-press", now=0.1)
    assert service.renew_live_jog("current-press", now=0.1)
    assert service.handle_response("ok", 500)

    clock.now = 0.2
    service.poll_live_jog()
    assert len(sent) == 1
    completed = GrblStatus("Idle", machine_position=Position(11.66667, 10, 10))
    session.update_status(completed)
    service.observe_status(completed)
    service.poll_live_jog()
    assert len(sent) == 2
    service.handle_response("ok", 500)
    before_expiry = len(sent)

    clock.now = 0.5
    service.poll_live_jog()
    assert len(sent) == before_expiry
    assert realtime == [REALTIME_JOG_CANCEL]
    assert service.live_jog_axis is None
    assert service.live_jog_stop_pending
    assert not service.renew_live_jog("current-press", now=0.5)


def test_stop_invalidates_lease_before_cancel_and_duplicate_stop_is_safe() -> None:
    service, _session, clock, sent, realtime, _notices = _motion()
    _start(service)

    assert not service.stop_live_jog("wrong-press").accepted
    assert service.stop_live_jog("press-1").accepted
    count_at_release = len(sent)
    assert service.stop_live_jog("press-1").accepted
    assert realtime == [REALTIME_JOG_CANCEL, REALTIME_JOG_CANCEL]

    assert not service.renew_live_jog("press-1", now=0.1)
    clock.now = 1.0
    service.poll_live_jog()
    assert len(sent) == count_at_release


def test_travel_limit_caps_final_segment_and_waits_for_expected_idle_position() -> None:
    service, session, clock, sent, _realtime, _notices = _motion(position=Position(99.5, 10, 10))
    session.envelope.reference = Position(0, 0, 0)
    _start(service)
    assert sent == [b"$J=G91 G21 X0.5 F500\n"]
    assert service.handle_response("ok", 500)
    clock.now = 0.06
    service.poll_live_jog()
    assert len(sent) == 1
    at_limit = GrblStatus("Idle", machine_position=Position(100, 10, 10))
    session.update_status(at_limit)
    service.observe_status(at_limit)
    assert service.live_jog_axis is None


@pytest.mark.parametrize("response", ["error:2", "ALARM:1"])
def test_error_or_alarm_clears_lease_and_prevents_resumption(response: str) -> None:
    service, _session, clock, sent, realtime, _notices = _motion()
    _start(service)

    assert service.handle_response(response, 500)
    assert realtime == [REALTIME_JOG_CANCEL]
    assert service.live_jog_axis is None
    assert not service.renew_live_jog("press-1", now=0.1)
    clock.now = 1.0
    service.poll_live_jog()
    assert len(sent) == 1


def test_reset_cancel_and_unexpected_alarm_state_clear_the_lease() -> None:
    service, session, _clock, sent, realtime, _notices = _motion()
    _start(service)
    service.cancel()
    assert service.pending_acks == 0
    assert service.live_jog_axis is None
    assert not service.renew_live_jog("press-1", now=0.1)
    assert realtime == [REALTIME_JOG_CANCEL]

    _start(service, "second-press")
    session.update_status(GrblStatus("Alarm", machine_position=Position(11, 10, 10)))
    service.observe_status(session.status)
    assert service.live_jog_axis is None
    assert not service.renew_live_jog("second-press", now=0.2)
    assert realtime[-1] == REALTIME_JOG_CANCEL

    service.reset()
    assert len(sent) == 2


def test_no_token_legacy_path_keeps_full_envelope_command() -> None:
    service, _session, _clock, sent, _realtime, _notices = _motion()

    outcome = service.start_live_jog("X", 1, False, 500)

    assert outcome.accepted
    assert sent == [b"$J=G91 G21 X100 F500\n"]
