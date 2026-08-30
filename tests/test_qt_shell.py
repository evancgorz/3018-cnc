from __future__ import annotations

from datetime import datetime
import os
import queue

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ttc3018_control.qt.main import build_engine
from ttc3018_control.grbl import GrblStatus, Position
from ttc3018_control.machine_state import MachineProfile
from ttc3018_control.serial_connection import SerialEvent


class _FakeConnection:
    connected = True

    def __init__(self) -> None:
        self.events = queue.Queue()
        self.lines: list[bytes] = []
        self.realtime: list[bytes] = []

    def send_line(self, command: bytes, **_kwargs) -> None:
        self.lines.append(command)

    def send_realtime(self, command: bytes) -> None:
        self.realtime.append(command)


def test_qt_shell_loads(qapp) -> None:
    engine, view_model = build_engine()

    roots = engine.rootObjects()
    assert len(roots) == 1
    assert roots[0].property("title") == "TTC 3018 Control — Qt Preview"
    assert view_model.connection_text == "Disconnected"


def test_qt_view_model_projects_grbl_status(qapp) -> None:
    _engine, view_model = build_engine()

    view_model.apply_status(
        GrblStatus(
            "Idle",
            machine_position=Position(10, 20, 3),
            work_position=Position(1, 2, 3),
            spindle=12000,
        )
    )

    assert view_model.connection_text == "Connected — GRBL Idle"
    assert view_model.machine_position == "X10.00  Y20.00  Z3.00"
    assert view_model.work_position == "X1.00  Y2.00  Z3.00"
    assert view_model.spindle == "12000 RPM"


def test_qt_generator_preview_and_load_use_shared_parser(qapp) -> None:
    _engine, view_model = build_engine()

    view_model.preview_text("Hello", "Cursive", 8, -0.3, 3, 300, 100, 0.18, 1.4, "Center", 0)
    assert view_model.preview_strokes
    assert "strokes" in view_model.preview_summary

    view_model.create_plaque(
        "Hello",
        "World",
        True,
        "Script",
        "Simple",
        10,
        5,
        100,
        50,
        5,
        "Rounded rectangle",
        -0.3,
        3,
        300,
        100,
        0,
    )
    assert view_model.job_file == "generated-plaque.gcode"
    assert view_model.preview_strokes


def test_qt_live_jog_stops_at_whole_millimeter(qapp) -> None:
    _engine, view_model = build_engine()
    view_model.session.profile = MachineProfile(travel_x=100, travel_y=100, travel_z=50, safe_z=3)
    connection = _FakeConnection()
    view_model.connection = connection
    view_model.apply_status(GrblStatus("Idle", machine_position=Position(0, 0, 0)))
    view_model.establish_reference()
    view_model.apply_status(GrblStatus("Idle", machine_position=Position(10.25, 0, 0)))

    view_model.start_live_jog("X", 1)
    assert connection.lines[-1] == b"$J=G91 G21 X0.75 F500\n"
    view_model._handle_event(SerialEvent("rx", "ok", datetime.now()))
    assert connection.lines[-1] == b"$J=G91 G21 X1 F500\n"

    view_model.stop_live_jog()
    assert connection.realtime[-1] == b"\x85"
    view_model._handle_event(SerialEvent("rx", "ok", datetime.now()))
    view_model._handle_event(SerialEvent("rx", "<Idle|MPos:10.25,0,0>", datetime.now()))
    assert connection.lines[-1] == b"$J=G91 G21 X-0.25 F500\n"
    view_model._handle_event(SerialEvent("rx", "ok", datetime.now()))
