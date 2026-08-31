from ttc3018_control.application.fixture_service import FixtureService
from ttc3018_control.application.machine_session import MachineSession
from ttc3018_control.application.tool_setting_service import ToolSettingService
from ttc3018_control.controller_adapters import Grbl11Adapter
from ttc3018_control.fixture_settings import FixtureRecord
from ttc3018_control.grbl import GrblStatus, Position
from ttc3018_control.machine_state import MachineProfile
from ttc3018_control.tool_settings import ToolSetterRecord


def session() -> MachineSession:
    value = MachineSession(profile=MachineProfile(travel_x=100, travel_y=100, travel_z=40, safe_z=30))
    value.status = GrblStatus("Idle", machine_position=Position(10, 10, 20))
    value.envelope.establish(Position(0, 0, 0), value.profile)
    return value


def test_tool_service_requires_repeatable_record_and_sends_tlo() -> None:
    sent = []
    service = ToolSettingService(session(), Grbl11Adapter(), sent.append)
    record = ToolSetterRecord("m1", Position(1, 2, 30), 10, samples=(4, 4.01, 4.02))
    assert service.apply_measurement(record, 8, connected=True, spindle_off=True).accepted
    assert sent == [b"G43.1 Z2\n"]
    assert service.active_offset is None
    assert service.handle_response("[TLO:2]")
    assert service.active_offset == 2
    assert service.clear(connected=True).accepted
    assert sent[-1] == b"G49\n"


def test_fixture_service_never_restores_without_trusted_reference() -> None:
    sent = []
    machine_session = session()
    machine_session.envelope.invalidate("lost")
    service = FixtureService(machine_session, Grbl11Adapter(), sent.append)
    record = FixtureRecord("m1", "fixture", 2, Position(0, 0, 30))
    outcome = service.restore_from_probe(record, Position(4, 5, 6), connected=True, spindle_off=True)
    assert not outcome.accepted
    assert sent == []
