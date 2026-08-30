from __future__ import annotations

from ttc3018_control.application.machine_session import MachineSession
from ttc3018_control.grbl import GrblStatus, Position
from ttc3018_control.machine_state import MachineProfile


def ready_session() -> MachineSession:
    session = MachineSession(profile=MachineProfile(travel_x=300, travel_y=180, travel_z=45, safe_z=30))
    session.update_status(GrblStatus("Idle", machine_position=Position(10, 20, 3)))
    assert session.establish_reference().accepted
    return session


def test_reference_requires_idle_machine_position() -> None:
    session = MachineSession(profile=MachineProfile(travel_x=300, travel_y=180, travel_z=45, safe_z=30))

    outcome = session.establish_reference()

    assert not outcome.accepted
    assert not session.envelope.trusted


def test_xyz_work_zero_is_confirmed_only_by_fresh_controller_offset() -> None:
    session = ready_session()

    assert session.request_work_zero_confirmation("XYZ").accepted
    assert not session.work_zero_confirmed
    session.update_status(GrblStatus("Idle", machine_position=Position(10, 20, 3), work_offset=Position(35, 40, 12)))

    assert session.work_zero_confirmed


def test_return_to_work_zero_uses_safe_position_plan() -> None:
    session = ready_session()
    assert session.request_work_zero_confirmation("XYZ").accepted
    session.update_status(GrblStatus("Idle", machine_position=Position(20, 30, 10), work_offset=Position(35, 40, 12)))

    outcome, moves = session.plan_return_to_work_zero()

    assert outcome.accepted
    assert moves == [("Z", 23), ("X", 15), ("Y", 10), ("Z", -21)]


def test_establishing_reference_preserves_confirmed_work_zero() -> None:
    session = MachineSession(profile=MachineProfile(travel_x=300, travel_y=180, travel_z=45, safe_z=30))
    session.update_status(
        GrblStatus(
            "Idle",
            machine_position=Position(10, 20, 3),
            work_offset=Position(35, 40, 12),
        )
    )
    session.work_zero_confirmed = True

    assert session.establish_reference().accepted

    assert session.envelope.trusted
    assert session.work_zero_confirmed
    assert session.work_offset == Position(35, 40, 12)


def test_reference_invalidation_also_invalidates_work_zero() -> None:
    session = ready_session()
    assert session.request_work_zero_confirmation("XYZ").accepted
    session.update_status(GrblStatus("Idle", machine_position=Position(10, 20, 3), work_offset=Position(10, 20, 3)))

    session.invalidate_reference("Disconnected")

    assert not session.envelope.trusted
    assert not session.work_zero_confirmed
