from __future__ import annotations

import queue
from pathlib import Path

import pytest
from PySide6.QtCore import QUrl

from ttc3018_control.application.connection_service import ConnectionOutcome
from ttc3018_control.application.controller import ApplicationController
from ttc3018_control.application.state import ConnectionMode
from ttc3018_control.grbl import GrblStatus, Position
from ttc3018_control.machine_state import MachineProfile
from ttc3018_control.qt.view_model import ControllerViewModel
from ttc3018_control.z_touch_plate import ZTouchPlateRecord


class _Transport:
    connected = True

    def __init__(self) -> None:
        self.lines: list[bytes] = []
        self.realtime: list[bytes] = []
        self.events = queue.Queue()

    def send_line(self, command: bytes, **_kwargs) -> None:
        self.lines.append(command)

    def send_realtime(self, command: bytes) -> None:
        self.realtime.append(command)

    def disconnect(self) -> None:
        self.connected = False


def test_prepare_load_picker_accept_cancel_and_invalid_preserve_previous_job(tmp_path, qapp) -> None:
    vm = ControllerViewModel(ApplicationController(tmp_path))
    valid = tmp_path / "valid.nc"
    valid.write_text("G21 G90\nG1 X1 F100\n", encoding="ascii")
    vm.load_gcode_file(QUrl.fromLocalFile(str(valid)))
    previous = vm.job_file
    vm.load_gcode_file(QUrl())
    assert vm.job_file == previous
    vm.load_gcode_file(QUrl.fromLocalFile(str(tmp_path / "invalid.nc")))
    assert vm.job_file == previous
    qml = (Path(__file__).parents[1] / "src" / "ttc3018_control" / "qt" / "qml" / "Main.qml").read_text(encoding="utf-8")
    prepare = qml[qml.index('objectName: "guidedPreparePage"'):qml.index('// Review —')]
    assert 'objectName: "loadGcode"' in prepare
    assert 'gcodeFileDialog.open()' in prepare


def test_guided_rail_advances_only_on_observed_connect_home_and_zero_completion(tmp_path, qapp) -> None:
    app = ApplicationController(tmp_path)
    declarations = {
        axis: {
            "enabled": True,
            "end": "max",
            "pin": f"{axis}1",
            "active_low": False,
            "hard_limit": True,
            "debounce_ms": 0,
        }
        for axis in "XYZ"
    }
    assert app.save_homing_limit_declarations(declarations).accepted
    transport = _Transport()
    transport.connected = False
    app.set_transport_for_testing(transport)
    app.connection_service.mode = ConnectionMode.USB
    def connect(_port: str) -> ConnectionOutcome:
        transport.connected = True
        return ConnectionOutcome(True, "Connected", ConnectionMode.USB)
    app.connect_usb = connect  # type: ignore[method-assign]
    vm = ControllerViewModel(app)
    try:
        assert vm.guided_step == 1
        vm.connect_to_usb("COM9")
        assert vm.guided_step == 2

        position = Position(10, 20, 30)
        vm.apply_status(GrblStatus("Idle", machine_position=position, work_offset=Position(0, 0, 0)))
        vm.select_guided_step(2)
        vm.home_machine()
        assert vm.guided_step == 2
        assert transport.lines == [b"$H\n"]
        app.handle_response("ok")
        vm.apply_status(GrblStatus("Idle", machine_position=Position(0, 0, 0), work_offset=Position(0, 0, 0)))
        assert vm.guided_step == 3

        vm.apply_status(GrblStatus("Idle", machine_position=position, work_offset=Position(0, 0, 0)))
        vm.set_work_zero("XYZ")
        assert vm.guided_step == 3
        app.handle_response("ok")
        vm.apply_status(GrblStatus("Idle", machine_position=position, work_offset=position))
        assert vm.guided_step == 4
        assert transport.lines == [b"$H\n", b"G10 L20 P1 X0 Y0 Z0\n"]
    finally:
        vm.close()
        app.close()


def test_window_close_has_no_homing_prompt_or_motion_route() -> None:
    qml = (Path(__file__).parents[1] / "src" / "ttc3018_control" / "qt" / "qml" / "Main.qml").read_text(encoding="utf-8")
    view_model = (Path(__file__).parents[1] / "src" / "ttc3018_control" / "qt" / "view_model.py").read_text(encoding="utf-8")
    assert "Home, then close" not in qml
    assert "exitDialog" not in qml
    assert "requires_exit_prompt" not in qml
    assert "home_machine_then_close" not in view_model


def test_terminal_run_has_explicit_repeat_without_navigation_motion(tmp_path, qapp) -> None:
    vm = ControllerViewModel(ApplicationController(tmp_path))
    vm.application.load_generated("G21 G90\nG1 X1 F100\n", "repeat.nc")
    vm._guided_step = 6
    vm._next_part_available = True
    vm.application.job.streamer.state = "complete"
    vm.prepare_next_part()
    assert vm.guided_step == 5
    assert not vm.review_acknowledged
    assert not vm.guided_preflight_confirmed
    qml = (Path(__file__).parents[1] / "src" / "ttc3018_control" / "qt" / "qml" / "Main.qml").read_text(encoding="utf-8")
    run = qml[qml.index('// Run — physical preflight'):qml.index('// Machine\n')]
    assert 'objectName: "nextPart"' in run
    assert 'objectName: "guidedContinue"' not in run


def test_guided_back_keeps_active_run_monitoring_selected(tmp_path, qapp) -> None:
    app = ApplicationController(tmp_path)
    transport = _Transport()
    app.set_transport_for_testing(transport)
    app.load_generated("G21 G90\nG1 X1 F100\nM5\n", "active.nc")
    assert app.job.start().accepted
    vm = ControllerViewModel(app)
    try:
        vm._guided_step = 6
        vm.guided_back()
        assert vm.guided_step == 6
        assert vm.guided_step_key == "run"
    finally:
        app.abort_job()
        vm.close()
        app.close()


def test_work_zero_requires_matching_per_axis_fresh_wco_reports(tmp_path) -> None:
    app = ApplicationController(tmp_path)
    app.session.profile = MachineProfile(travel_x=100, travel_y=100, travel_z=50, safe_z=3)
    transport = _Transport()
    app.set_transport_for_testing(transport)
    position = Position(10, 20, 30)
    app.apply_status(GrblStatus("Idle", machine_position=position, work_offset=Position(0, 0, 0)))
    assert app.establish_reference().accepted
    for axis, offset in (("X", Position(10, 0, 0)), ("Y", Position(10, 20, 0)), ("Z", Position(10, 20, 30))):
        assert app.set_work_zero(axis).accepted
        app.handle_response("ok")
        app.apply_status(GrblStatus("Idle", machine_position=position, work_offset=offset))
        assert axis in app.session.confirmed_work_zero_axes
        if axis != "Z":
            assert not app.work_zero_confirmed
    assert app.work_zero_confirmed


def test_plate_removal_blocks_work_zero_continue_and_atomic_probe_draft(tmp_path) -> None:
    app = ApplicationController(tmp_path)
    before = app.machine_definition.fingerprint()
    rejected = app.save_probe_configuration(
        z_plate=True, tool_setter=False, movable_xyz=False, fixed_xyz=False,
        plate_thickness=200, active_low=False, fast_feed=100, slow_feed=25,
        max_search=5, retract=2, safe_retract=2, tolerance=0.05,
    )
    assert not rejected.accepted
    assert app.machine_definition.fingerprint() == before

    saved = app.save_probe_configuration(
        z_plate=True, tool_setter=False, movable_xyz=False, fixed_xyz=False,
        plate_thickness=19, active_low=False, fast_feed=100, slow_feed=25,
        max_search=5, retract=2, safe_retract=2, tolerance=0.05,
    )
    assert saved.accepted
    after = app.machine_definition.fingerprint()
    unchanged = app.save_probe_configuration(
        z_plate=True, tool_setter=False, movable_xyz=False, fixed_xyz=False,
        plate_thickness=19, active_low=False, fast_feed=100, slow_feed=25,
        max_search=5, retract=2, safe_retract=2, tolerance=0.05,
    )
    assert unchanged.accepted and "unchanged" in unchanged.message
    assert app.machine_definition.fingerprint() == after

    vm = ControllerViewModel(app)
    transport = _Transport()
    app.set_transport_for_testing(transport)
    app.apply_status(GrblStatus("Idle", machine_position=Position(0, 0, 0), work_offset=Position(0, 0, 0)))
    app.session.profile = MachineProfile(travel_x=100, travel_y=100, travel_z=50, safe_z=3)
    assert app.establish_reference().accepted
    app.session.work_zero_confirmed = True
    app._z_plate_removal_required = True
    assert vm.workflow_steps[3]["state"] == "blocked"
    assert "Remove the touch plate" in vm.workflow_steps[3]["reason"]


def test_unchanged_capability_saves_preserve_reference_and_unedited_probe_data(tmp_path) -> None:
    app = ApplicationController(tmp_path)
    transport = _Transport()
    app.set_transport_for_testing(transport)
    app.apply_status(GrblStatus("Idle", machine_position=Position(10, 20, 30)))
    assert app.establish_reference().accepted
    definition = app.machine_definition
    flags = {
        "limit_switches": all(axis.switch_mode.value != "none" for axis in definition.axes.values()),
        "z_plate": any(probe.kind.value == "movable_z_plate" and probe.enabled for probe in definition.probes),
        "tool_setter": any(probe.kind.value == "fixed_tool_setter" and probe.enabled for probe in definition.probes),
        "movable_xyz": any(probe.kind.value == "movable_xyz" and probe.enabled for probe in definition.probes),
        "fixed_fixture": any(probe.kind.value == "fixed_xyz" and probe.enabled for probe in definition.probes),
    }
    before = definition.fingerprint()
    assert app.save_capabilities(**flags).accepted
    assert app.save_probe_capabilities(
        z_plate=flags["z_plate"], tool_setter=flags["tool_setter"],
        movable_xyz=flags["movable_xyz"], fixed_xyz=flags["fixed_fixture"],
    ).accepted
    assert app.machine_definition.fingerprint() == before
    assert app.reference_trusted


def test_probe_draft_persistence_failure_does_not_commit_partial_local_state(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    app = ApplicationController(tmp_path)
    assert app.save_z_plate_capability(True).accepted
    definition = app.z_touch_plate_definition
    assert definition is not None
    before = app.machine_definition.fingerprint()

    def fail(*_args, **_kwargs):
        raise OSError("read-only catalog")

    monkeypatch.setattr(app.machine_catalog_store, "upsert", fail)
    outcome = app.save_probe_configuration(
        z_plate=True, tool_setter=False, movable_xyz=False, fixed_xyz=False,
        plate_thickness=definition.plate_thickness + 1, active_low=definition.active_low,
        fast_feed=definition.fast_feed, slow_feed=definition.slow_feed,
        max_search=definition.max_search, retract=definition.retract,
        safe_retract=definition.safe_retract, tolerance=definition.tolerance,
    )
    assert not outcome.accepted
    assert "could not be saved" in outcome.message
    assert app.machine_definition.fingerprint() == before


def test_active_probe_has_public_abort_and_actionable_recovery(tmp_path, qapp) -> None:
    app = ApplicationController(tmp_path)
    assert app.save_z_plate_capability(True).accepted
    transport = _Transport()
    app.set_transport_for_testing(transport)
    app.apply_status(GrblStatus("Idle", machine_position=Position(0, 0, 0), work_offset=Position(0, 0, 0)))
    assert app.establish_reference().accepted
    position = Position(0, 0, 20)
    app.apply_status(GrblStatus("Idle", machine_position=position, work_offset=Position(0, 0, 0)))
    app.session.work_zero_confirmed = True
    definition = app.z_touch_plate_definition
    assert definition is not None
    record = ZTouchPlateRecord.commissioned_record(
        app.machine_id or "", (1.0, 1.01, 1.02), definition.tolerance,
        app.z_touch_plate_fingerprint,
    )
    app.z_touch_plate_store.save(record)
    app._z_touch_plate_record = record
    assert app.probe_work_z().accepted
    assert app.probing.active

    vm = ControllerViewModel(app)
    try:
        assert vm.probe_active
        outcome = app.abort_probe()
        assert outcome.accepted
        assert not app.probing.active
        assert "retry" in outcome.message.lower()
        assert not any(command.startswith(b"G10") for command in transport.lines)
        assert transport.realtime
    finally:
        vm.close()
        app.close()
