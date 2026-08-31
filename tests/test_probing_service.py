from ttc3018_control.application.machine_session import MachineSession
from ttc3018_control.application.probing_service import ProbePlan, ProbeState, ProbingService
from ttc3018_control.controller_adapters import Grbl11Adapter
from ttc3018_control.grbl import GrblStatus, Position
from ttc3018_control.machine_state import MachineProfile


def ready_session() -> MachineSession:
    session = MachineSession(profile=MachineProfile(travel_x=100, travel_y=100, travel_z=40, safe_z=30))
    session.envelope.establish(Position(0, 0, 0), session.profile)
    session.status = GrblStatus("Idle", machine_position=Position(10, 10, 20), pins="")
    return session


def plan() -> ProbePlan:
    return ProbePlan("Z", -5, -2, 1, 5, 100, 25, 25, 1, Position(10, 10, 0))


def test_probe_order_is_fast_report_retract_release_slow_offset_safe_retract() -> None:
    sent = []
    session = ready_session()
    service = ProbingService(session, Grbl11Adapter(), sent.append)
    assert service.start(plan(), connected=True, spindle_off=True).accepted
    assert sent == [b"G91 G21 G38.2 Z-5 F100\n"]
    assert service.handle_response("[PRB:10,10,15:1]")
    assert sent[-1] == b"G91 G21 Z1 F25\n"
    assert service.handle_response("ok")
    assert service.state is ProbeState.WAIT_RELEASE
    assert service.observe_status(GrblStatus("Idle", machine_position=Position(10, 10, 16), pins=""))
    assert sent[-1] == b"G91 G21 G38.2 Z-2 F25\n"
    assert service.handle_response("[PRB:10,10,14:1]")
    assert sent[-1] == b"G10 L20 P1 X10 Y10 Z0\n"
    assert service.handle_response("ok")
    assert sent[-1] == b"G91 G21 Z5 F25\n"
    assert service.handle_response("ok")
    assert service.state is ProbeState.COMPLETE


def test_failed_probe_never_applies_offset() -> None:
    sent = []
    service = ProbingService(ready_session(), Grbl11Adapter(), sent.append)
    assert service.start(plan(), connected=True, spindle_off=True).accepted
    assert service.handle_response("[PRB:10,10,15:0]")
    assert service.state is ProbeState.FAILED
    assert not any(command.startswith(b"G10") for command in sent)

