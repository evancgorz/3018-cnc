from __future__ import annotations

from datetime import datetime
import math
import os
import queue
from pathlib import Path
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ttc3018_control.qt.main import build_engine
from ttc3018_control.qt.view_model import ControllerViewModel
from ttc3018_control.application.controller import ApplicationController
from ttc3018_control.grbl import GrblStatus, Position
from ttc3018_control.machine_state import MachineProfile
from ttc3018_control.serial_connection import SerialEvent
from ttc3018_control.step_geometry import PlanarLoop, Point2D, StepPlanarModel, load_step_isolated
from PySide6.QtCore import QUrl


class _FakeConnection:
    connected = True

    def __init__(self) -> None:
        self.events = queue.Queue()
        self.lines: list[bytes] = []
        self.realtime: list[bytes] = []
        self.disconnect_calls = 0

    def disconnect(self) -> None:
        self.connected = False
        self.disconnect_calls += 1

    def send_line(self, command: bytes, **_kwargs) -> None:
        self.lines.append(command)

    def send_realtime(self, command: bytes) -> None:
        self.realtime.append(command)


def test_qt_shell_loads(qapp) -> None:
    engine, view_model = build_engine()
    roots = engine.rootObjects()
    assert len(roots) == 1
    assert roots[0].property("title") == "TTC 3018 Control"
    assert view_model.connection_text == "Disconnected"


def test_qt_shutdown_releases_transport_once(qapp) -> None:
    _engine, view_model = build_engine()
    connection = _FakeConnection()
    view_model.connection = connection

    view_model.close()
    view_model.close()

    assert connection.disconnect_calls == 1
    assert not connection.connected
    assert view_model.application.transport is None


def test_guided_setup_is_state_gated_and_advances_in_order(qapp) -> None:
    _engine, view_model = build_engine()

    assert view_model.guided_step == 0
    assert view_model.guided_step_count == 9
    assert view_model.guided_step_names[0] == "Safety"
    assert view_model.guided_step_ready

    view_model.guided_next()
    assert view_model.guided_step == 1
    assert not view_model.guided_step_ready
    assert "Connect" in view_model.guided_step_reason

    view_model.guided_next()
    assert view_model.guided_step == 1

    view_model.guided_previous()
    assert view_model.guided_step == 0
    view_model.guided_reset()
    assert view_model.guided_step == 0
    assert not view_model.guided_preflight_confirmed


def test_production_launcher_has_no_legacy_tk_presentation() -> None:
    root = Path(__file__).parents[1]
    source = root / "src" / "ttc3018_control"
    assert not list(source.glob("*window.py"))
    assert not (source / "app.py").exists()
    assert "ttkbootstrap" not in (root / "pyproject.toml").read_text(encoding="utf-8")
    build_script = (root / "packaging" / "build.ps1").read_text(encoding="utf-8")
    assert "-m nuitka" in build_script
    assert "--enable-plugin=pyside6" in build_script


def test_reference_controls_follow_operator_workflow_order() -> None:
    qml = (Path(__file__).parents[1] / "src" / "ttc3018_control" / "qt" / "qml" / "Main.qml").read_text(
        encoding="utf-8"
    )

    establish = qml.index('text: "Establish reference"')
    go_to = qml.index('text: "Go to reference"')
    safe_z = qml.index('text: "Retract to safe Z"')
    work_zero = qml.index('text: "Return to work zero"')
    zero_x = qml.index('text: "Zero X"')

    assert establish < go_to < safe_z < zero_x < work_zero


def test_step_import_runs_without_blocking_and_reports_completion(qapp, tmp_path) -> None:
    _engine, view_model = build_engine()
    path = tmp_path / "part.step"
    path.write_text("placeholder", encoding="ascii")
    model = StepPlanarModel(
        path,
        (PlanarLoop((Point2D(0, 0), Point2D(10, 0), Point2D(10, 5), Point2D(0, 5))),),
        0,
        2,
        (0, 0, 0, 10, 5, 2),
    )
    view_model.application.import_step = lambda selected: model

    view_model.import_step_file(QUrl.fromLocalFile(str(path)))

    assert view_model.step_importing
    assert view_model.step_source.startswith("Importing")
    deadline = time.monotonic() + 2
    while view_model.step_importing and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)
    assert not view_model.step_importing
    assert view_model.step_loaded
    assert view_model.step_source == "part.step"

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
    assert view_model.preview_stock_width == 0

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


def test_qt_step_generator_preview_and_load_use_shared_parser(qapp) -> None:
    _engine, view_model = build_engine()
    outer = PlanarLoop(tuple(Point2D(x, y) for x, y in ((0, 0), (40, 0), (40, 25), (0, 25))))
    hole = PlanarLoop(
        tuple(
            Point2D(20 + 4 * math.cos(index * math.tau / 32), 12.5 + 4 * math.sin(index * math.tau / 32))
            for index in range(32)
        )
    )
    view_model._step_model = StepPlanarModel(Path("plate.step"), (outer, hole), 5, 5, (0, 0, 0, 40, 25, 5))

    view_model.preview_step("Pocket", "Top (XY)", 50, 35, "Center", 3.175, -0.8, 2, 5, 0.2, 4, 4, 0.8, 3, 300, 100, 12000)
    assert view_model.preview_strokes
    assert "Pocket" in view_model.preview_summary
    assert view_model.step_preview_valid
    assert view_model.preview_stock_width == 50
    assert view_model.preview_stock_height == 35
    assert view_model.step_operations == [
        {
            "operationId": "pocket",
            "kind": "Pocket",
            "targetDepth": -0.8,
            "dependsOn": "",
            "strategy": "connected scanline/offset clearing",
            "featureKinds": "",
        }
    ]

    view_model.create_step("Pocket", "Top (XY)", 50, 35, "Center", 3.175, -0.8, 2, 5, 0.2, 4, 4, 0.8, 3, 300, 100, 12000)
    assert view_model.job_file == "generated-step.gcode"
    assert view_model.program is not None
    assert any(command.startswith("M3 S12000") for command in view_model.program.commands)

    view_model.preview_step("Profile cutout", "Top (XY)", 50, 35, "Center", 3.175, -0.8, 3, 5, 0.2, 4, 4, 0.8, 3, 300, 100, 12000)
    assert "Profile cutout" in view_model.preview_summary
    assert "4 outer tabs" in view_model.preview_summary
    assert view_model.step_preview_valid
    assert [operation["operationId"] for operation in view_model.step_operations] == [
        "internal-through", "outer-profile"
    ]

    view_model.preview_step("Pocket", "Top (XY)", 50, 35, "Center", 3.175, -21, 2, 5, 0.2, 4, 4, 0.8, 3, 300, 100, 12000)
    assert not view_model.step_preview_valid
    assert view_model.step_operations == []


def test_step_preview_draws_physical_stock_and_work_zero_in_canvas() -> None:
    qml = (Path(__file__).parents[1] / "src" / "ttc3018_control" / "qt" / "qml" / "Main.qml").read_text(
        encoding="utf-8"
    )

    assert "preview_stock_width" in qml
    assert "preview_stock_height" in qml
    assert "ctx.strokeRect(offsetX, offsetY - stockHeight * scale" in qml
    assert "ctx.arc(workZeroX, workZeroY" in qml
    assert "Max stepdown (mm, 0 = auto)" in qml
    assert "modeCombo.currentText === \"Detected feature\"" in qml
    assert "Guided STEP setup" in qml
    assert "component IsometricCanvas" in qml
    assert "Automatic part" in qml
    assert "step_isometric_faces" in qml


@pytest.mark.parametrize(
    ("fixture", "face_kind"),
    (
        ("removed-cylinder.step", "feature"),
        ("extruded-circle.step", "feature"),
        ("wedge.step", "ramp"),
    ),
)
def test_qt_automatic_step_preview_builds_3d_model_and_complete_toolpath(
    qapp,
    tmp_path,
    fixture: str,
    face_kind: str,
) -> None:
    view_model = ControllerViewModel(ApplicationController(tmp_path))
    model = load_step_isolated(Path(__file__).parents[1] / "examples" / fixture)
    view_model._step_model = model
    view_model._step_path = model.path
    view_model._set_step_isometric_model(model)

    view_model.preview_step(
        "Automatic part",
        "Top (XY)",
        model.width + 3.175,
        model.height + 3.175,
        "Lower-left",
        3.175,
        -0.5,
        2,
        model.thickness,
        0.2,
        4,
        4.0,
        min(0.8, model.thickness * 0.4),
        3.0,
        300.0,
        100.0,
        0,
        1.0,
    )

    assert view_model.step_preview_valid
    assert any(face["kind"] == face_kind for face in view_model.step_isometric_faces)
    assert any(path["kind"] == "profile" for path in view_model.step_isometric_paths)
    assert view_model.step_operations[-1]["operationId"] == "outer-profile"
    if fixture == "wedge.step":
        assert any(path["kind"] == "surface" for path in view_model.step_isometric_paths)


def test_qt_prepare_defaults_persist_across_controllers(qapp, tmp_path) -> None:
    first = ControllerViewModel(ApplicationController(tmp_path))

    first.save_step_prepare_defaults(
        "Top (YX)", "Center", 2.0, 3, 0.5, 4.0, 450.0, 120.0,
        12000, 0.25, 3, 5.0, 0.6,
    )
    restored = ControllerViewModel(ApplicationController(tmp_path))

    assert restored.step_default_orientation == "Top (YX)"
    assert restored.step_default_zero_location == "Center"
    assert restored.step_default_tool_diameter == pytest.approx(2.0)
    assert restored.step_default_cut_feed == pytest.approx(450.0)
    assert restored.step_default_spindle_rpm == 12000


def test_qt_live_jog_stops_at_whole_millimeter(qapp) -> None:
    _engine, view_model = build_engine()
    view_model.session.profile = MachineProfile(travel_x=100, travel_y=100, travel_z=50, safe_z=3)
    connection = _FakeConnection()
    view_model.connection = connection
    view_model.apply_status(GrblStatus("Idle", machine_position=Position(0, 0, 0)))
    view_model.establish_reference()
    view_model.apply_status(GrblStatus("Idle", machine_position=Position(10.25, 0, 0)))

    view_model.start_live_jog("X", 1)
    assert connection.lines[-1] == b"$J=G91 G21 X1 F500\n"
    # A live GRBL status changes from Idle to Jog. The outer button must remain
    # enabled while held; otherwise QML cancels the press after one segment.
    view_model.apply_status(GrblStatus("Jog", machine_position=Position(10.40, 0, 0)))
    assert view_model.can_live_jog
    view_model._handle_event(SerialEvent("rx", "ok", datetime.now()))
    assert connection.lines == [b"$J=G91 G21 X1 F500\n", b"$J=G91 G21 X1 F500\n"]

    view_model.apply_status(GrblStatus("Hold", machine_position=Position(10.40, 0, 0)))
    assert not view_model.can_live_jog
    view_model.apply_status(GrblStatus("Jog", machine_position=Position(10.40, 0, 0)))

    view_model.stop_live_jog()
    assert connection.realtime[-1] == b"\x85"
    view_model._handle_event(SerialEvent("rx", "ok", datetime.now()))
    # Snap forward from the settled position after deceleration. A positive
    # hold must never reverse after the operator releases the control.
    view_model._handle_event(SerialEvent("rx", "<Idle|MPos:11.40,0,0>", datetime.now()))
    assert connection.lines[-1] == b"$J=G91 G21 X0.6 F500\n"
    view_model._handle_event(SerialEvent("rx", "ok", datetime.now()))

    view_model.apply_status(GrblStatus("Idle", machine_position=Position(10.25, 0, 0)))
    view_model.start_live_jog("X", -1)
    assert connection.lines[-1] == b"$J=G91 G21 X-1 F500\n"
    view_model._handle_event(SerialEvent("rx", "ok", datetime.now()))
    assert connection.lines[-1] == b"$J=G91 G21 X-1 F500\n"
    view_model.stop_live_jog()
    view_model._handle_event(SerialEvent("rx", "ok", datetime.now()))
    view_model._handle_event(SerialEvent("rx", "<Idle|MPos:10.25,0,0>", datetime.now()))
    assert connection.lines[-1] == b"$J=G91 G21 X-0.25 F500\n"

    view_model._handle_event(SerialEvent("rx", "ok", datetime.now()))
    view_model.apply_status(GrblStatus("Idle", machine_position=Position(10, 0, 0)))
    view_model.jog("X", 0.1)
    assert connection.lines[-1] == b"$J=G91 G21 X0.1 F500\n"


def test_qt_live_z_jog_is_bounded_in_both_directions(qapp) -> None:
    _engine, view_model = build_engine()
    view_model.session.profile = MachineProfile(travel_x=100, travel_y=100, travel_z=50, safe_z=3)
    connection = _FakeConnection()
    view_model.connection = connection
    view_model.apply_status(GrblStatus("Idle", machine_position=Position(0, 0, 0)))
    view_model.establish_reference()
    view_model.apply_status(GrblStatus("Idle", machine_position=Position(10, 10, 10)))

    view_model.start_live_jog("Z", 1)
    assert connection.lines[-1] == b"$J=G91 G21 Z1 F500\n"
    view_model._handle_event(SerialEvent("rx", "ok", datetime.now()))
    assert connection.lines[-1] == b"$J=G91 G21 Z1 F500\n"

    view_model.stop_live_jog()
    view_model._handle_event(SerialEvent("rx", "ok", datetime.now()))
    view_model._handle_event(SerialEvent("rx", "<Idle|MPos:11,10,11>", datetime.now()))
    view_model._handle_event(SerialEvent("rx", "ok", datetime.now()))
    view_model.apply_status(GrblStatus("Idle", machine_position=Position(10, 10, 10)))

    view_model.start_live_jog("Y", 1)
    assert connection.lines[-1] == b"$J=G91 G21 Y1 F500\n"
    view_model.stop_live_jog()
    view_model._handle_event(SerialEvent("rx", "ok", datetime.now()))
    view_model.apply_status(GrblStatus("Idle", machine_position=Position(10, 10, 10)))

    view_model.start_live_jog("Z", -1)
    assert connection.lines[-1] == b"$J=G91 G21 Z-1 F500\n"
