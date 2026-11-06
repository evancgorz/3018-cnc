from ttc3018_control.application.controller import ApplicationController
from ttc3018_control.grbl import GrblStatus, Position
from ttc3018_control.machine_state import MachineProfile
from ttc3018_control.work_zero_settings import WorkZeroStore


class _Wire:
    connected = True

    def __init__(self) -> None:
        self.sent: list[bytes] = []

    def send_line(self, command: bytes, display_text=None) -> None:
        self.sent.append(command)

    def send_realtime(self, command: bytes) -> None:
        pass

    def disconnect(self) -> None:
        self.connected = False


def _status(machine: Position, offset: Position) -> GrblStatus:
    return GrblStatus("Idle", machine_position=machine, work_offset=offset)


def test_separately_confirmed_xy_survive_restart_without_promoting_z(tmp_path) -> None:
    store = WorkZeroStore(tmp_path / "config" / "work-zero.json")
    app = ApplicationController(tmp_path)
    wire = _Wire()
    app.set_transport_for_testing(wire)
    machine = Position(40, 60, 12)
    app.apply_status(_status(machine, Position(0, 0, 7)))

    assert app.set_work_zero("X").accepted
    app.handle_response("ok")
    app.apply_status(_status(machine, Position(40, 0, 7)))
    assert app._work_zero_expected_offset is None
    saved_x = store.load(app.machine_id)
    assert saved_x is not None
    assert saved_x.confirmed_axes == frozenset("X")

    assert app.set_work_zero("Y").accepted
    app.handle_response("ok")
    app.apply_status(_status(machine, Position(40, 60, 7)))
    assert app._work_zero_expected_offset is None
    saved_xy = store.load(app.machine_id)
    assert saved_xy is not None
    assert saved_xy.confirmed_axes == frozenset("XY")
    assert app.session.confirmed_work_zero_axes == frozenset("XY")
    assert not app.work_zero_confirmed

    restarted = ApplicationController(tmp_path)
    restarted.session.profile = MachineProfile(travel_x=300, travel_y=180, travel_z=40, safe_z=30)
    return_wire = _Wire()
    restarted.set_transport_for_testing(return_wire)
    restarted.apply_status(_status(Position(0, 0, 0), Position(40, 60, 7)))

    # The live WCO matches the saved machine-coordinate X/Y origin, but its Z
    # differs from the placeholder persisted for an unconfirmed Z axis.
    assert restarted.session.confirmed_work_zero_axes == frozenset("XY")
    assert not restarted.work_zero_confirmed
    assert restarted.establish_reference().accepted
    restarted.apply_status(_status(Position(5, 6, 10), Position(40, 60, 7)))

    outcome = restarted.return_to_work_zero()

    assert outcome.accepted
    assert return_wire.sent == [b"$J=G91 G21 Z20 F500\n"]
    assert restarted.motion._position_queue == [
        ("X", 35.0, 500.0),
        ("Y", 54.0, 500.0),
        ("Z", -20.0, 500.0),
    ]
