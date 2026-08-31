from ttc3018_control.application.homing_service import HomingService, HomingState
from ttc3018_control.application.machine_session import MachineSession
from ttc3018_control.grbl import GrblStatus, Position
from ttc3018_control.machine_config import AxisDefinition, AxisEnd, MachineDefinition, SwitchMode
from ttc3018_control.machine_state import MachineProfile


def configured_machine() -> MachineDefinition:
    axis = AxisDefinition(switch_mode=SwitchMode.SINGLE, input_pin="X")
    return MachineDefinition(machine_id="m1", axes={"X": axis, "Y": axis, "Z": axis})


def test_homing_requires_switches_and_confirms_fresh_idle_position() -> None:
    sent = []
    session = MachineSession(profile=MachineProfile(travel_x=290, travel_y=170, travel_z=40, safe_z=30))
    session.status = GrblStatus("Alarm", machine_position=Position(290, 0, 40))
    service = HomingService(session, sent.append)
    assert service.start(configured_machine(), connected=True, spindle_off=True).accepted
    assert sent == [b"$H\n"]
    assert service.handle_response("ok")
    assert service.state is HomingState.WAITING_IDLE
    assert service.observe_status(GrblStatus("Idle", machine_position=Position(290, 0, 40)), configured_machine())
    assert session.envelope.trusted
    assert session.envelope.relative_position(Position(290, 0, 40)) == Position(290, 170, 40)
    assert session.envelope.relative_position(Position(0, 0, 0)) == Position(0, 170, 0)


def test_homing_failure_clears_reference() -> None:
    axis = AxisDefinition(switch_mode=SwitchMode.SINGLE, input_pin="X")
    definition = MachineDefinition(machine_id="m1", axes={"X": axis, "Y": axis, "Z": axis})
    session = MachineSession(profile=definition.to_profile())
    session.status = GrblStatus("Idle", machine_position=Position(0, 0, 0))
    session.envelope.establish(Position(0, 0, 0), definition.to_profile())
    service = HomingService(session, lambda _line: None)
    assert service.start(definition, connected=True, spindle_off=True).accepted
    assert service.handle_response("ALARM: Homing fail")
    assert not session.envelope.trusted
