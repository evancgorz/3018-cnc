from __future__ import annotations

from datetime import datetime
import logging
import math
import os
import queue
from pathlib import Path
import re
from types import SimpleNamespace
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ttc3018_control.qt.main import build_engine
from ttc3018_control.qt.view_model import ControllerViewModel
from ttc3018_control.application.controller import ApplicationController
from ttc3018_control.application.homing_service import HomingState
from ttc3018_control.application.job_service import JobService
from ttc3018_control.grbl import GrblStatus, Position
from ttc3018_control.machine_state import MachineProfile
from ttc3018_control.serial_connection import SerialEvent
from ttc3018_control.step_geometry import PlanarLoop, Point2D, StepPlanarModel, load_step_isolated
from ttc3018_control.z_touch_plate import ZTouchPlateRecord
from PySide6.QtCore import QObject, QUrl, Qt
from PySide6.QtTest import QTest


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
    assert roots[0].property("title") == "Pine"
    assert roots[0].property("guidedIndex") == 1
    assert not roots[0].icon().isNull()
    assert view_model.connection_text == "Disconnected"


def test_build_engine_accepts_preconstructed_controller_for_isolated_validation(qapp, tmp_path) -> None:
    controller = ApplicationController(tmp_path, usb_factory=lambda: (_ for _ in ()).throw(AssertionError("USB")),
                                        wifi_factory=lambda: (_ for _ in ()).throw(AssertionError("Wi-Fi")))
    engine, view_model = build_engine(application=controller, auto_connect=False)
    assert view_model.application is controller
    assert engine.rootObjects()[0].property("title") == "Pine"


def test_simulation_gui_launcher_sentinels_and_manifest_are_isolated(tmp_path) -> None:
    from scripts.run_simulation_gui_validation import _write_manifest, _write_sentinel_config
    from ttc3018_control.application.controller import ApplicationController
    import hashlib
    import json

    sentinels = _write_sentinel_config(tmp_path)
    assert sentinels
    assert not any(Path(filename).name == "simulation.json" for filename in sentinels)
    for filename, digest in sentinels.items():
        assert hashlib.sha256(Path(filename).read_bytes()).hexdigest() == digest
    manifest = {"main_pid": 123, "temp_root": str(tmp_path), "session_marker": "marker",
                "log_path": str(tmp_path / "logs" / "pine.log"),
                "physical_config_sentinels": sentinels, "owned_child_pids": [], "loopback_endpoint": None}
    path = tmp_path / "manifest.json"
    _write_manifest(path, manifest)
    assert json.loads(path.read_text(encoding="utf-8")) == manifest
    isolated = ApplicationController(tmp_path, usb_factory=lambda: None, wifi_factory=lambda: None)
    assert (isolated.profile.travel_x, isolated.profile.travel_y, isolated.profile.travel_z) == (290, 170, 40)


def test_main_qml_palette_references_are_declared() -> None:
    qml = (Path(__file__).parents[1] / "src" / "ttc3018_control" / "qt" / "qml" / "Main.qml").read_text(
        encoding="utf-8"
    )
    palette_block = qml.split("readonly property var palette: ({", 1)[1].split("})", 1)[0]
    declared = set(re.findall(r"\b(\w+)\s*:\s*Qt\.color", palette_block))
    referenced = set(re.findall(r"window\.palette\.(\w+)", qml))
    assert referenced <= declared


def test_gcode_picker_binding_and_filter_are_public_and_validated() -> None:
    qml = (Path(__file__).parents[1] / "src" / "ttc3018_control" / "qt" / "qml" / "Main.qml").read_text(
        encoding="utf-8"
    )
    picker = qml[qml.index("id: gcodeFileDialog"):qml.index("id: saveGcodeDialog")]
    assert 'title: "Load existing job"' in picker
    assert 'CNC jobs (*.nc *.gcode *.tap *.cnc *.txt *.json)' in picker
    assert 'onAccepted: appViewModel.load_gcode_file(selectedFile)' in picker


def test_gcode_picker_replaces_valid_job_and_preserves_it_on_rejection(qapp, tmp_path) -> None:
    controller = ApplicationController(tmp_path)
    view_model = ControllerViewModel(controller)
    first = tmp_path / "first.nc"
    second = tmp_path / "second.gcode"
    invalid = tmp_path / "invalid.nc"
    first.write_text("G21 G90\nG0 X0 Y0 Z3\nG1 X10 Y10 F100\nM5\n", encoding="ascii")
    second.write_text("G21 G90\nG0 X1 Y2 Z3\nG1 X6 Y8 F100\nM5\n", encoding="ascii")
    invalid.write_text("G21 G90\nG1 Xnot-a-number F100\n", encoding="ascii")
    notices: list[str] = []
    view_model.toast_requested.connect(notices.append)

    view_model.load_gcode_file(QUrl.fromLocalFile(str(first)))
    original = controller.program
    assert original is not None
    assert view_model.job_file == "first.nc"
    assert notices[-1] == "G-code loaded and validated"

    view_model.load_gcode_file(QUrl.fromLocalFile(str(invalid)))
    assert controller.program is original
    assert view_model.job_file == "first.nc"
    assert "G-code rejected" in notices[-1]

    view_model.load_gcode_file(QUrl.fromLocalFile(str(second)))
    assert controller.program is not original
    assert controller.program.path.name == "second.gcode"
    assert view_model.job_file == "second.gcode"
    assert notices[-1] == "G-code loaded and validated"


def test_loading_new_job_clears_previous_failure_issue(qapp, tmp_path) -> None:
    controller = ApplicationController(tmp_path)
    # A fake connected transport lets the presentation path expose a job issue
    # without opening or interacting with physical hardware.
    controller.connection_service.transport = _FakeConnection()
    view_model = ControllerViewModel(controller)
    service = JobService(controller.session, lambda _command: None, lambda _command: None)
    controller.job = service

    assert service.start(("G1 X1",)).accepted
    assert service.handle_response("error:2")
    view_model._emit_state()
    assert view_model.has_issue
    assert view_model.issue_title == "Job stopped"

    controller.load_generated("G21 G90\nG1 X2 F100\n", "replacement.gcode")
    view_model._emit_state()

    assert controller.job_state == "idle"
    assert not view_model.has_issue
    assert view_model.job_state == "Idle"
    view_model.close()


def test_gcode_picker_empty_selection_and_active_job_are_truthful(qapp, tmp_path) -> None:
    controller = ApplicationController(tmp_path)
    view_model = ControllerViewModel(controller)
    fixture = tmp_path / "job.nc"
    replacement = tmp_path / "replacement.nc"
    fixture.write_text("G21 G90\nG0 X0 Y0 Z3\nG1 X2 Y2 F100\nM5\n", encoding="ascii")
    replacement.write_text("G21 G90\nG0 X1 Y1 Z3\nG1 X3 Y4 F100\nM5\n", encoding="ascii")
    notices: list[str] = []
    view_model.toast_requested.connect(notices.append)
    view_model.load_gcode_file(QUrl.fromLocalFile(str(fixture)))
    original = controller.program

    view_model.load_gcode_file(QUrl())
    assert controller.program is original
    assert notices[-1] == "G-code load ignored — choose a local file"

    controller.job._completion_waiting_for_idle = True
    try:
        view_model.load_gcode_file(QUrl.fromLocalFile(str(replacement)))
    finally:
        controller.job._completion_waiting_for_idle = False
    assert controller.program is original
    assert view_model.job_file == "job.nc"
    assert notices[-1] == "G-code load ignored — a job is active"


def test_qml_keyboard_focus_reaches_actionable_controls_offscreen(qapp) -> None:
    engine, view_model = build_engine(visible=False)
    root = engine.rootObjects()[0]
    root.show()
    root.requestActivate()
    qapp.processEvents()

    focused_labels: list[str] = []
    for _ in range(2):
        QTest.keyClick(root, Qt.Key_Tab)
        qapp.processEvents()
        focused = root.activeFocusItem()
        assert focused is not None
        text = focused.property("text")
        assert isinstance(text, str) and text.strip(), type(focused).__name__
        focused_labels.append(text)

    assert focused_labels == ["Machine", "Job"]
    root.close()
    view_model.close()


def test_real_qml_shell_constrained_size_and_guided_transitions_offscreen(qapp, tmp_path, caplog) -> None:
    factory_calls: list[str] = []

    def forbidden_usb():
        factory_calls.append("usb")
        raise AssertionError("USB factory must remain untouched")

    def forbidden_wifi():
        factory_calls.append("wifi")
        raise AssertionError("Wi-Fi factory must remain untouched")

    controller = ApplicationController(
        tmp_path,
        usb_factory=forbidden_usb,
        wifi_factory=forbidden_wifi,
    )
    with caplog.at_level(logging.WARNING, logger="pine.qt"):
        engine, view_model = build_engine(visible=False, application=controller)
        root = engine.rootObjects()[0]
        root.resize(1180, 720)
        root.show()
        qapp.processEvents()

        assert root.minimumWidth() == 1180
        assert root.minimumHeight() == 720
        assert root.width() == 1180
        assert root.height() == 720

        for guided_step in (0, 1, 5, 0):
            view_model.select_guided_step(guided_step)
            qapp.processEvents()
            assert root.property("guidedIndex") == guided_step
            assert root.width() == 1180
            assert root.height() == 720

        assert not factory_calls
        assert controller.transport is None
        assert controller.simulation_runtime is None
        assert not [record for record in caplog.records if record.name == "pine.qt" and record.levelno >= logging.WARNING]

    root.close()
    view_model.close()


def test_ux2_guided_shell_and_projection_traverse_offscreen(qapp, tmp_path, caplog) -> None:
    factory_calls: list[str] = []
    controller = ApplicationController(
        tmp_path,
        usb_factory=lambda: factory_calls.append("usb"),
        wifi_factory=lambda: factory_calls.append("wifi"),
    )
    with caplog.at_level(logging.WARNING, logger="pine.qt"):
        engine, view_model = build_engine(visible=False, application=controller)
        root = engine.rootObjects()[0]
        root.resize(1180, 720)
        root.show()
        qapp.processEvents()
        assert root.property("guidedIndex") == 1
        assert root.property("guidedContentIndex") == 3
        assert len(view_model.workflow_steps) == 7
        assert [item["name"] for item in view_model.workflow_steps] == [
            "Configure", "Connect", "Home", "Work Zero", "Prepare Job", "Review", "Run"
        ]
        for index in range(7):
            button = root.findChildren(QObject, "configureUtility" if index == 0 else f"guidedStep{index}")[0]
            if index:
                assert str(button.property("text")) in ("Connect", "Home", "Work Zero", "CAM tools…", "Review", "Run")
            assert button.property("enabled") is True
        for guided_step in range(7):
            view_model.select_guided_step(guided_step)
            qapp.processEvents()
            assert root.width() == 1180 and root.height() == 720
            assert view_model.guided_step == guided_step
            assert not root.findChildren(QObject, "connectionDialog")[0].property("visible")
        assert not root.findChildren(QObject, "machineStepPanel")
        assert not root.findChildren(QObject, "machineStep0")
        assert not root.findChildren(QObject, "selectedMachineStep")
        assert not factory_calls
        assert not [record for record in caplog.records if record.name == "pine.qt" and record.levelno >= logging.WARNING]
    root.close()
    view_model.close()


def test_ux2_single_content_surface_and_named_rail_at_constrained_sizes(qapp, tmp_path, caplog) -> None:
    controller = ApplicationController(tmp_path, usb_factory=lambda: (_ for _ in ()).throw(AssertionError("USB")),
                                        wifi_factory=lambda: (_ for _ in ()).throw(AssertionError("Wi-Fi")))
    with caplog.at_level(logging.WARNING, logger="pine.qt"):
        engine, view_model = build_engine(visible=False, application=controller)
        root = engine.rootObjects()[0]
        for width, height in ((1180, 720), (1500, 920)):
            root.resize(width, height)
            for index in range(7):
                # guidedIndex is bound to the ViewModel. Exercise the same
                # selection path used by the workspace controls so the binding
                # remains live while the test checks each page projection.
                view_model.select_guided_step(index)
                qapp.processEvents()
                assert root.width() == width and root.height() == height
                assert root.property("guidedIndex") == index
                assert root.findChildren(QObject, "configureUtility" if index == 0 else f"guidedStep{index}")[0].property("checked") is True
                pages = [root.findChildren(QObject, name)[0].property("visible") for name in
                         ("setupPage", "machinePage", "guidedPreparePage", "guidedReviewPage", "guidedRunPage")]
                expected = [index == 0, 1 <= index <= 3, index == 4, index == 5, index == 6]
                assert pages == expected
                assert root.findChildren(QObject, "guidedReviewPage")[0].property("visible") is (index == 5)
                assert root.findChildren(QObject, "guidedRunPage")[0].property("visible") is (index == 6)
                assert root.findChildren(QObject, "acknowledgeReview")[0].property("visible") is (index == 5)
                assert root.findChildren(QObject, "physicalPreflight")[0].property("visible") is (index == 6)
        assert not [record for record in caplog.records if record.name == "pine.qt" and record.levelno >= logging.WARNING]
    root.close()
    view_model.close()


def test_ux2_configure_sections_and_step_rail_are_interactive_at_both_layouts(qapp, tmp_path, caplog) -> None:
    controller = ApplicationController(tmp_path, usb_factory=lambda: (_ for _ in ()).throw(AssertionError("USB")),
                                        wifi_factory=lambda: (_ for _ in ()).throw(AssertionError("Wi-Fi")))
    with caplog.at_level(logging.WARNING, logger="pine.qt"):
        engine, view_model = build_engine(visible=False, application=controller)
        root = engine.rootObjects()[0]
        for width, height in ((1180, 720), (1500, 920)):
            root.resize(width, height)
            view_model.select_guided_step(0)
            qapp.processEvents()
            for index in range(5):
                button = root.findChildren(QObject, f"setupSection{index}")[0]
                button.clicked.emit()
                qapp.processEvents()
                assert root.property("setup_section_index") == index
                assert button.property("checked") is True
                setup_name = ("setupMachineSection", "setupAxesSection", "setupProbeSection", "setupCommissioningSection", "setupTwinSection")[index]
                setup_section = root.findChildren(QObject, setup_name)[0]
                assert setup_section.property("visible") is True
                if index == 0:
                    assert root.findChildren(QObject, "editProfile")[0].property("visible") is True
                elif index == 1:
                    assert root.findChildren(QObject, "axisDeclarationX")[0].property("visible") is True
                    assert root.findChildren(QObject, "editAxesLimits")[0].property("visible") is True
                elif index == 2:
                    assert root.findChildren(QObject, "probeDeclarationSummary")[0].property("visible") is True
                    assert root.findChildren(QObject, "editProbesSafety")[0].property("visible") is True
                elif index == 3:
                    assert root.findChildren(QObject, "openCommissioning")[0].property("visible") is True
                else:
                    assert root.findChildren(QObject, "connectDigitalTwin")[0].property("visible") is True
                assert not root.findChildren(QObject, "connectionDialog")[0].property("visible")
            for index in range(8):
                view_model.select_guided_step(index)
                qapp.processEvents()
                # Navigation remains available; actions inside each page keep
                # enforcing their own prerequisites.
                if index < 7:
                    assert root.property("guidedIndex") == index
                assert not root.findChildren(QObject, "connectionDialog")[0].property("visible")
        assert not [record for record in caplog.records if record.name == "pine.qt" and record.levelno >= logging.WARNING]
    root.close()
    view_model.close()


def test_h6_public_safety_and_auto_xyz_controls_are_guarded() -> None:
    root = Path(__file__).parents[1]
    main_qml = (root / "src" / "ttc3018_control" / "qt" / "qml" / "Main.qml").read_text(encoding="utf-8")
    setup_qml = (root / "src" / "ttc3018_control" / "qt" / "qml" / "MachineSetupDialog.qml").read_text(encoding="utf-8")
    assert "save_homing_limit_declarations" in setup_qml
    for label in ("active_low", "hard_limit", "debounce_ms", "max_override"):
        assert label in setup_qml
    assert "commission_simulation_calibration_plate" in main_qml
    assert "autoXyzDialog.open()" in main_qml
    assert "start_auto_xyz_calibration" in main_qml
    assert "abort_auto_xyz_calibration" in main_qml
    assert "onClicked: {}" not in main_qml
    assert "Zero X" in main_qml and "Zero Y" in main_qml and "Zero Z" in main_qml


def test_simulation_hazard_detail_projection_and_public_visualization_surface(qapp, tmp_path) -> None:
    view_model = ControllerViewModel(ApplicationController(tmp_path))
    assert not view_model.simulation_hazard_active
    assert not view_model.simulation_collision_active
    view_model._simulation_active_hazard = {
        "kind": "tool_fixture",
        "message": "Tool entered fixture",
        "body_a": "tool",
        "body_b": "fixture",
        "position": (1.234, 2.345, 3.456),
    }

    assert view_model.simulation_hazard_active
    assert view_model.simulation_collision_active
    assert view_model.simulation_collision_state == "FIRST CONTACT — INTERLOCK ACTIVE"
    assert view_model.simulation_collision_kind == "tool_fixture"
    assert view_model.simulation_collision_body == "tool versus fixture"
    assert view_model.simulation_collision_point == "X1.23  Y2.35  Z3.46"
    assert (view_model.simulation_collision_x, view_model.simulation_collision_y, view_model.simulation_collision_z) == (1.234, 2.345, 3.456)

    qml = (Path(__file__).parents[1] / "src" / "ttc3018_control" / "qt" / "qml" / "Main.qml").read_text(encoding="utf-8")
    assert 'text: "Export evidence…"' in qml
    assert 'fillText("FIRST CONTACT"' in qml
    assert "simulation_collision_message" in qml


def test_terminal_simulation_hazard_survives_clear_until_safe_recovery(qapp, tmp_path) -> None:
    controller = ApplicationController(tmp_path)
    view_model = ControllerViewModel(controller)
    connection = _FakeConnection()
    controller.connection_service.transport = connection
    from ttc3018_control.application.state import ConnectionMode
    controller.connection_service.mode = ConnectionMode.SIMULATION

    class _Supervisor:
        def is_alive(self): return True

    class _Runtime:
        supervisor = _Supervisor()
        supervisor_healthy = True
        def __init__(self):
            self.items = []
        def poll(self):
            items, self.items = self.items, []
            return tuple(items)

    runtime = _Runtime()
    controller.connection_service.simulation_runtime = runtime
    runtime.items = [
        {"type": "hazard", "hazard": {
            "kind": "tool_fixture", "message": "first contact", "body_a": "tool",
            "body_b": "fixture", "position": (2.0, 3.0, 4.0), "severity": "alarm",
        }},
        {"type": "hazard_clear", "key": ("tool_fixture", "tool", "fixture")},
    ]
    controller.poll_simulation = runtime.poll  # type: ignore[method-assign]
    controller.transport_events = lambda: queue.Queue()  # type: ignore[method-assign]
    controller.request_status = lambda: None  # type: ignore[method-assign]
    controller.check_job_watchdog = lambda: None  # type: ignore[method-assign]
    view_model._poll()
    assert view_model.simulation_collision_state == "FIRST CONTACT — INTERLOCK ACTIVE"
    assert view_model.simulation_collision_point == "X2.00  Y3.00  Z4.00"

    # A successful home plus a fresh Idle report is the explicit safe recovery
    # boundary. Seed the session envelope directly because this test's fake
    # supervisor does not implement the full homing transaction.
    controller.session.envelope.establish(Position(0, 0, 0), controller.session.profile)
    controller.homing.state = HomingState.COMPLETE
    view_model.apply_status(GrblStatus("Idle", machine_position=Position(0, 0, 0)))
    assert not view_model.simulation_hazard_active

    # Ordinary warning edges still clear without a recovery action.
    runtime.items = [
        {"type": "hazard", "hazard": {"kind": "protocol", "message": "diagnostic", "severity": "warning"}},
        {"type": "hazard_clear", "key": ("protocol", "", "")},
    ]
    view_model._poll()
    assert not view_model.simulation_hazard_active


def test_simulation_show_action_is_connected_only_and_raises_window() -> None:
    qml = (Path(__file__).parents[1] / "src" / "ttc3018_control" / "qt" / "qml" / "Main.qml").read_text(encoding="utf-8")
    assert "function showSimulator()" in qml
    assert "if (!(appViewModel && appViewModel.simulation_active)) return" in qml
    assert "simulationWindow.visible = true" in qml
    assert "simulationWindow.raise()" in qml
    assert "simulationWindow.requestActivate()" in qml
    assert 'objectName: "showSimulator"' in qml
    assert 'visible: appViewModel && appViewModel.simulation_active && appViewModel.expert_mode' in qml
    assert 'text: "Hide simulator"; onClicked: simulationWindow.visible = false' in qml
    assert 'visible: appViewModel && appViewModel.simulation_active; text: "Hide simulator"' in qml
    assert 'if (appViewModel && appViewModel.job_active)' in qml
    assert 'enabled: appViewModel && appViewModel.simulation_export_available' in qml
    assert 'text: "Show simulator"' in qml
    assert 'text: "Review"; onClicked: window.selectGuidedStep(6)' not in qml
    assert 'id: readinessStrip' not in qml
    assert 'readinessEntries' not in qml
    assert 'routeReadinessAction' not in qml


def test_simulator_inspection_is_expert_only_in_the_offscreen_header(qapp, tmp_path, caplog) -> None:
    controller = ApplicationController(tmp_path, usb_factory=lambda: (_ for _ in ()).throw(AssertionError("USB")),
                                        wifi_factory=lambda: (_ for _ in ()).throw(AssertionError("Wi-Fi")))
    with caplog.at_level(logging.WARNING, logger="pine.qt"):
        engine, view_model = build_engine(visible=False, application=controller)
        root = engine.rootObjects()[0]
        root.resize(1180, 720)
        view_model.set_expert_mode(False)
        view_model.configure_simulation("10×", "Pocket + retained island")
        view_model.connect_to_simulation()
        QTest.qWait(700)
        qapp.processEvents()
        simulator_button = root.findChildren(QObject, "showSimulator")[0]
        assert view_model.simulation_active
        assert simulator_button.property("visible") is False
        issue_banner = root.findChildren(QObject, "issueBanner")[0]
        for width, height in ((1180, 720), (1500, 920)):
            root.resize(width, height)
            qapp.processEvents()
            assert root.width() == width and root.height() == height
            assert issue_banner.property("x") == 18
            assert issue_banner.property("width") > 0
            assert issue_banner.property("y") == 198
        view_model.set_expert_mode(True)
        qapp.processEvents()
        assert simulator_button.property("visible") is True
        assert not [record for record in caplog.records if record.name == "pine.qt" and record.levelno >= logging.WARNING]
    root.close()
    view_model.close()
    controller.close()


def test_simulator_safety_and_evidence_column_is_bounded_and_scrollable() -> None:
    qml = (Path(__file__).parents[1] / "src" / "ttc3018_control" / "qt" / "qml" / "Main.qml").read_text(encoding="utf-8")
    assert "ScrollView" in qml
    assert "id: simulatorControlsScroll" in qml
    assert "contentWidth: simulatorControlsScroll.width" in qml
    assert "width: simulatorControlsScroll.width" in qml
    simulator_panel = qml[qml.index("id: simulatorControlsScroll"):qml.index("    Dialog {", qml.index("id: simulatorControlsScroll"))]
    assert "availableWidth" not in simulator_panel
    assert "ScrollBar.vertical.policy: ScrollBar.AsNeeded" in qml
    assert "Layout.preferredHeight: 120" in qml
    assert 'text: "Export evidence…"' in qml
    assert 'text: "Disconnect digital twin"' in qml


def test_simulation_safety_capabilities_are_public_and_fail_closed(qapp, tmp_path) -> None:
    view_model = ControllerViewModel(ApplicationController(tmp_path))
    assert not view_model.simulation_auto_xyz_available
    assert "not commissioned" in view_model.simulation_auto_xyz_status
    assert "safety-rated" in view_model.simulation_estop_status
    qml = (Path(__file__).parents[1] / "src" / "ttc3018_control" / "qt" / "qml" / "Main.qml").read_text(encoding="utf-8")
    assert "simulation_homing_status" in qml
    assert "simulation_estop_status" in qml
    assert "simulation_auto_xyz_status" in qml
    assert "Preview Auto XYZ calibration plate (commissioning required)" in qml
    assert "enabled: appViewModel && appViewModel.simulation_auto_xyz_available" in qml
    assert '"Stock metrics " + (appViewModel ? appViewModel.simulation_stock_metrics_json : "{}")' in qml
    assert 'RowLayout { visible: appViewModel && appViewModel.job_active' in qml
    assert 'text: "Pause"; onClicked: appViewModel.pause_job()' in qml
    assert 'text: "Resume"; onClicked: appViewModel.resume_job()' in qml
    assert 'text: "Abort"; dangerous: true; onClicked: appViewModel.abort_job()' in qml
    assert 'appViewModel.requires_exit_prompt' not in qml
    assert 'id: exitDialog' not in qml
    assert 'Home, then close' not in qml


def test_run_recovery_exposes_confirmed_pause_bookmark_and_review_fence() -> None:
    qml = (Path(__file__).parents[1] / "src" / "ttc3018_control" / "qt" / "qml" / "Main.qml").read_text(encoding="utf-8")
    assert 'objectName: "confirmedPauseBookmark"' in qml
    assert 'bookmark["live_hold_confirmed"]' in qml
    assert 'tool["reported_tool_details"]' in qml
    assert "Automatic resume is disabled" in qml
    assert "after disconnect or restart" in qml


def test_simulation_projection_clears_stale_hazard_stock_and_export_state_on_disconnect(qapp, tmp_path) -> None:
    controller = ApplicationController(tmp_path)
    view_model = ControllerViewModel(controller)
    view_model._simulation_active_hazard = {"kind": "tool_fixture", "message": "contact", "position": (1, 2, 3)}
    view_model._simulation_terminal_hazard = dict(view_model._simulation_active_hazard)
    view_model._simulation_hazards = ["contact"]
    view_model._simulation_stock_metrics = {"removed_volume": 4}
    view_model._simulation_export_status = "Evidence exported"
    view_model._disconnected("test cleanup")
    assert not view_model.simulation_hazard_active
    assert not view_model._simulation_terminal_hazard
    assert view_model.simulation_hazards == []
    assert view_model.simulation_stock_metrics_json == "{}"
    assert view_model.simulation_export_status == "No simulation evidence exported"
    assert not view_model.simulation_export_available


def test_simulation_poll_projects_snapshot_hazard_metrics_and_caps_history(qapp, tmp_path, monkeypatch) -> None:
    controller = ApplicationController(tmp_path)
    view_model = ControllerViewModel(controller)
    connection = _FakeConnection()
    controller.connection_service.transport = connection
    from ttc3018_control.application.state import ConnectionMode
    controller.connection_service.mode = ConnectionMode.SIMULATION
    class _Supervisor:
        def is_alive(self): return True
    class _Runtime:
        supervisor = _Supervisor()
        supervisor_healthy = True
        poll = lambda self: ()
    controller.connection_service.simulation_runtime = _Runtime()
    items = [
        {"type": "snapshot", "snapshot": {"state": "Run", "machine_position": (1, 2, 3)}},
        {"type": "stock_metrics", "metrics": {"removed_volume": 2.5}},
        {"type": "hazard", "hazard": {"kind": "tool_fixture", "message": "contact", "body_a": "tool", "body_b": "fixture", "position": (1, 2, 3)}},
    ] * 2
    controller.poll_simulation = lambda: tuple(items)  # type: ignore[method-assign]
    controller.transport_events = lambda: queue.Queue()  # type: ignore[method-assign]
    controller.request_status = lambda: None  # type: ignore[method-assign]
    controller.check_job_watchdog = lambda: None  # type: ignore[method-assign]
    view_model._poll()
    assert view_model.simulation_snapshot_json.startswith('{')
    assert view_model.simulation_stock_metrics_json == '{"removed_volume":2.5}'
    assert view_model.simulation_hazard_active
    assert view_model.simulation_collision_kind == "tool_fixture"
    assert len(view_model.simulation_hazards) == 2
    assert view_model.simulation_supervisor_healthy
    controller.poll_simulation = lambda: tuple(  # type: ignore[method-assign]
        {"type": "hazard", "hazard": {"kind": "tool_fixture", "message": f"contact-{index}"}}
        for index in range(60)
    )
    view_model._poll()
    assert len(view_model.simulation_hazards) == 50


def test_simulation_operator_and_supervisor_projections_are_truthful(qapp, tmp_path, monkeypatch) -> None:
    controller = ApplicationController(tmp_path)
    view_model = ControllerViewModel(controller)
    connection = _FakeConnection()
    controller.connection_service.transport = connection
    from ttc3018_control.application.state import ConnectionMode
    controller.connection_service.mode = ConnectionMode.SIMULATION

    class _Runtime:
        supervisor = SimpleNamespace(is_alive=lambda: True)
        supervisor_healthy = False
        poll = lambda self: ()

    controller.connection_service.simulation_runtime = _Runtime()
    assert not view_model.simulation_supervisor_healthy

    monkeypatch.setattr(controller, "hold", lambda: SimpleNamespace(accepted=False, message="alarm latched"))
    notices: list[str] = []
    view_model.toast_requested.connect(notices.append)
    view_model._apply_operator_intent({"action": "hold", "reason": "collision"})
    assert notices[-1] == "Digital twin operator hold rejected — alarm latched"
    view_model._apply_operator_intent({"action": "interlock", "reason": "first contact"})
    assert notices[-1] == "Digital twin operator interlock — first contact"


def test_simulation_evidence_export_slot_reports_success_and_failure(qapp, tmp_path, monkeypatch) -> None:
    controller = ApplicationController(tmp_path)
    view_model = ControllerViewModel(controller)
    monkeypatch.setattr(type(controller), "simulation_active", property(lambda _self: True))
    monkeypatch.setattr(
        type(controller),
        "simulation_runtime",
        property(lambda _self: SimpleNamespace(supervisor=SimpleNamespace(is_alive=lambda: True), poll=lambda: ())),
    )
    events: list[tuple[str, dict]] = []
    exported: list[Path] = []
    controller.record_simulation_event = lambda kind, payload=None, **_kwargs: events.append((kind, payload or {}))  # type: ignore[method-assign]

    def export(path: Path) -> None:
        exported.append(path)
        path.write_text('{"schema_version": 1, "events": []}\n', encoding="utf-8")
        path.with_suffix(".md").write_text("# evidence\n", encoding="utf-8")

    controller.export_simulation_trace = export  # type: ignore[method-assign]
    notices: list[str] = []
    view_model.toast_requested.connect(notices.append)
    view_model.export_simulation_evidence(QUrl.fromLocalFile(str(tmp_path / "evidence.trace")))
    assert exported == [tmp_path / "evidence.json"]
    assert events == [("evidence_export_requested", {"path": "evidence.json"})]
    assert (tmp_path / "evidence.md").exists()
    assert "Evidence exported" in view_model.simulation_export_status
    assert notices and notices[-1] == view_model.simulation_export_status

    controller.export_simulation_trace = lambda _path: (_ for _ in ()).throw(OSError("read-only"))  # type: ignore[method-assign]
    view_model.export_simulation_evidence(QUrl.fromLocalFile(str(tmp_path / "failed.json")))
    assert "Evidence export failed" in view_model.simulation_export_status
    assert notices[-1] == view_model.simulation_export_status


def test_pine_brand_assets_and_launch_surfaces_are_packaged() -> None:
    root = Path(__file__).parents[1]
    assets = root / "src" / "ttc3018_control" / "qt" / "assets"
    assert (assets / "pine-mark.svg").is_file()
    assert (assets / "pine-mark.png").stat().st_size > 10_000
    assert (assets / "pine.ico").stat().st_size > 10_000
    assert (assets / "pine-splash.png").stat().st_size > 10_000
    bootstrap = (root / "src" / "ttc3018_control" / "qt" / "main.py").read_text(encoding="utf-8")
    setup = (root / "setup.ps1").read_text(encoding="utf-8")
    assert 'app.setApplicationDisplayName("Pine")' in bootstrap
    assert 'SetCurrentProcessExplicitAppUserModelID(WINDOWS_APP_USER_MODEL_ID)' in bootstrap
    assert 'engine.rootObjects()[0].setIcon(QIcon(str(PINE_ICON)))' in bootstrap
    assert "QSplashScreen" in bootstrap
    assert "RotatingFileHandler" in bootstrap
    assert '"Pine.lnk"' in setup
    assert "$shortcut.IconLocation" in setup
    assert "pythonw.exe" in setup


def test_qt_shutdown_releases_transport_once(qapp) -> None:
    _engine, view_model = build_engine()
    connection = _FakeConnection()
    view_model.connection = connection

    view_model.close()
    view_model.close()

    assert connection.disconnect_calls == 1
    assert not connection.connected
    assert view_model.application.transport is None


def test_qt_auto_connects_to_last_successful_usb_endpoint(qapp, tmp_path) -> None:
    from ttc3018_control.connection_settings import ConnectionSettings, ConnectionSettingsStore

    transport = _FakeConnection()
    transport.connected = False
    transport.connect = lambda port: setattr(transport, "connected", port == "COM7")  # type: ignore[attr-defined]
    ConnectionSettingsStore(tmp_path / "config" / "connection.json").save(
        ConnectionSettings(preferred_transport="USB serial", usb_port="COM7")
    )
    controller = ApplicationController(
        tmp_path,
        usb_factory=lambda: transport,
        usb_ports=lambda: [("COM7", "Pine test controller")],
    )
    view_model = ControllerViewModel(controller)

    view_model._auto_connect_last()

    assert view_model.connected
    assert controller.settings.usb_port == "COM7"
    assert controller.settings.preferred_transport == "USB serial"


def test_qt_auto_connects_to_last_successful_wifi_endpoint(qapp, tmp_path) -> None:
    from ttc3018_control.application.connection_service import ConnectionOutcome
    from ttc3018_control.application.state import ConnectionMode
    from ttc3018_control.connection_settings import ConnectionSettings, ConnectionSettingsStore

    ConnectionSettingsStore(tmp_path / "config" / "connection.json").save(
        ConnectionSettings("192.168.86.36", 23, "Wi-Fi TCP")
    )
    controller = ApplicationController(tmp_path)
    attempts: list[tuple[str, int]] = []

    def begin_wifi(host: str, port: int) -> ConnectionOutcome:
        attempts.append((host, port))
        return ConnectionOutcome(True, "Connecting", ConnectionMode.WIFI, host, port)

    controller.begin_wifi = begin_wifi  # type: ignore[method-assign]
    view_model = ControllerViewModel(controller)

    view_model._auto_connect_last()

    assert attempts == [("192.168.86.36", 23)]
    assert view_model.preferred_transport == "Wi-Fi TCP"


def test_guided_setup_is_state_gated_and_advances_in_order(qapp) -> None:
    _engine, view_model = build_engine()

    assert view_model.guided_step == 1
    assert view_model.guided_step_count == 7
    assert view_model.guided_step_names[0] == "Configure"
    assert view_model.guided_step_names[-1] == "Run"
    assert not view_model.guided_step_ready

    view_model.select_guided_step(0)
    view_model.guided_next()
    assert view_model.guided_step == 1
    assert not view_model.guided_step_ready
    assert "controller" in view_model.guided_step_reason

    view_model.guided_continue()
    assert view_model.guided_step == 1

    view_model.guided_back()
    assert view_model.guided_step == 0
    view_model.guided_reset()
    assert view_model.guided_step == 1
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


def test_home_step_leads_with_only_the_home_action() -> None:
    qml = (Path(__file__).parents[1] / "src" / "ttc3018_control" / "qt" / "qml" / "Main.qml").read_text(
        encoding="utf-8"
    )

    assert 'text: "Establish reference"' not in qml
    assert 'text: "Go to reference"' not in qml
    assert 'text: "Retract to safe Z"' not in qml
    motion_panel = qml.index('objectName: "machineMotionPanel"')
    home = qml.index('objectName: "panelHomeMachineIcon"', motion_panel)
    jog_pad = qml.index('id: xyJogPad', motion_panel)
    assert home < jog_pad


def test_disabled_actions_show_current_inline_guidance_offscreen(qapp, tmp_path) -> None:
    controller = ApplicationController(
        tmp_path,
        usb_factory=lambda: (_ for _ in ()).throw(AssertionError("USB")),
        wifi_factory=lambda: (_ for _ in ()).throw(AssertionError("Wi-Fi")),
    )
    engine, view_model = build_engine(visible=False, application=controller)
    root = engine.rootObjects()[0]
    try:
        root.show()
        qapp.processEvents()
        find = lambda name: root.findChildren(QObject, name)[0]

        continue_button = find("guidedContinue")
        assert not continue_button.property("enabled")
        assert continue_button.property("disabledReason") == view_model.guided_step_reason

        root.setProperty("guidedIndex", 2)
        qapp.processEvents()
        home_reason = find("homeMachineGateMessage")
        assert home_reason.property("visible")
        assert "Connect" in home_reason.property("text")

        root.setProperty("guidedIndex", 3)
        qapp.processEvents()
        jog_reason = find("jogGateMessage")
        assert jog_reason.property("visible")
        assert "Connect" in jog_reason.property("text")
        machine_page = find("machinePage")
        machine_page.setProperty("coordinatesExpanded", True)
        qapp.processEvents()
        move_reason = find("moveSafelyGateMessage")
        assert move_reason.property("visible")
        assert "Connect" in move_reason.property("text")

        root.setProperty("guidedIndex", 6)
        qapp.processEvents()
        start_button = find("startJob")
        start_reason = find("startJobGateMessage")
        assert not start_button.property("enabled")
        assert start_reason.property("visible")
        assert "Review" in start_reason.property("text")

        view_model._review_acknowledged = True
        view_model._emit_state()
        qapp.processEvents()
        assert "Connect" in start_reason.property("text")
        assert start_button.property("disabledReason") == start_reason.property("text")
    finally:
        root.close()
        view_model.close()


def test_fresh_alarm_keeps_home_action_available_in_projection_and_qml(qapp, tmp_path) -> None:
    from dataclasses import replace

    from ttc3018_control.application.state import ConnectionMode
    from ttc3018_control.machine_config import SwitchMode

    controller = ApplicationController(tmp_path)
    controller._wifi_only_operations = False
    controller.connection_service.mode = ConnectionMode.WIFI
    controller.connection_service.transport = _FakeConnection()
    definition = controller.machine_definition
    axes = {
        axis: replace(definition.axes[axis], switch_mode=SwitchMode.SINGLE, input_pin=axis)
        for axis in "XYZ"
    }
    controller._machine_definition = replace(definition, axes=axes)
    controller.apply_status(GrblStatus(
        "Alarm", machine_position=Position(10, 20, 3), spindle=0, pins="",
    ))
    assert controller.can_home_machine

    engine, view_model = build_engine(visible=False, application=controller)
    root = engine.rootObjects()[0]
    try:
        root.show()
        qapp.processEvents()
        assert view_model.workflow_steps[2]["state"] == "required"
        assert root.findChildren(QObject, "panelHomeMachineIcon")[0].property("enabled")
    finally:
        root.close()
        view_model.close()


def test_machine_page_makes_xyz_probe_plate_discoverable() -> None:
    qml = (Path(__file__).parents[1] / "src" / "ttc3018_control" / "qt" / "qml" / "Main.qml").read_text(
        encoding="utf-8"
    )

    assert 'text: "XYZ probe plate"' in qml
    assert 'text: "Commission plate"' in qml
    assert 'text: "Open Auto XYZ"' in qml
    assert 'label: "DIGITAL TWIN"' in qml
    assert 'appViewModel.simulation_auto_xyz_status' in qml


def test_qml_guided_flow_and_creation_flow_are_consolidated() -> None:
    qml = (Path(__file__).parents[1] / "src" / "ttc3018_control" / "qt" / "qml" / "Main.qml").read_text(
        encoding="utf-8"
    )

    for label in ("Configure", "Machine", "Connect", "Home", "Work Zero", "Prepare", "Job", "Review", "Run"):
        assert label in qml
    assert 'text: "Engraving designer"' in qml
    assert 'id: engravingDialog' in qml
    assert 'model: ["Plain text", "Plaque"]' in qml
    assert 'title: "Load existing job"' in qml
    assert 'id: retiredGuidedWorkflowDialog' not in qml
    assert 'id: retiredMachineSettingsDialog' not in qml
    assert 'Machine settings' not in qml
    assert 'Guided setup' not in qml
    assert 'text: "Guided setup"' not in qml
    assert '"Move to coordinates"' in qml
    assert 'property bool coordinatesExpanded: false' in qml
    assert 'appViewModel.job_estimate' in qml
    assert 'appViewModel.job_time_remaining' in qml
    assert 'id: textDialog' not in qml
    assert 'id: plaqueDialog' not in qml
    assert '"Guided Setup"]' not in qml
    assert 'PineLiveCard { Layout.fillWidth: true; palette: window.palette }' in qml
    assert 'text: "Open Configure"' not in qml
    assert 'objectName: "guidedReviewPage"' in qml
    assert 'objectName: "guidedRunPage"' in qml
    assert 'id: machineStepPanel' not in qml
    assert 'selectedMachineStep' not in qml
    assert "window.usableContentHeight - height" in qml
    assert 'set_physical_preflight_confirmed(checked)' in qml
    assert 'readonly property int guidedContentIndex' in qml
    engraving_dialog = qml.split("id: engravingDialog", 1)[1].split("id: wifiSetupDialog", 1)[0]
    assert 'SectionTitle { text: "Live preview"' in engraving_dialog
    assert 'ToolpathCanvas { Layout.fillWidth: true; Layout.fillHeight: true' in engraving_dialog
    assert 'source: "../assets/pine-mark.svg"' in qml


def test_machine_setup_hardware_page_scrolls_within_the_dialog() -> None:
    qml = (
        Path(__file__).parents[1]
        / "src"
        / "ttc3018_control"
        / "qt"
        / "qml"
        / "MachineSetupDialog.qml"
    ).read_text(encoding="utf-8")

    hardware_page = qml.split("id: hardwareScroll", 1)[1].split('text: "Current configuration"', 1)[0]
    assert "Layout.fillHeight: true" in hardware_page
    assert "clip: true" in hardware_page
    assert "contentWidth: availableWidth" in hardware_page
    assert "width: hardwareScroll.availableWidth" in hardware_page
    assert 'text: "Save touch plate settings"' in hardware_page
    assert "property bool zPlateActiveLow: false" in qml
    assert "onToggled: dialog.zPlateActiveLow = checked" in hardware_page
    assert 'text: "Invert probe input polarity in GRBL ($6)"' in hardware_page
    assert "display only" not in hardware_page


def test_z_probe_input_uses_a_guided_no_motion_wizard() -> None:
    root = Path(__file__).parents[1]
    main_qml = (root / "src" / "ttc3018_control" / "qt" / "qml" / "Main.qml").read_text(encoding="utf-8")
    wizard_qml = (root / "src" / "ttc3018_control" / "qt" / "qml" / "ZProbeWizard.qml").read_text(encoding="utf-8")

    assert "ZProbeWizard {" in main_qml
    assert 'text: "Test input…"' in main_qml
    assert "onClicked: zProbeWizard.open()" in main_qml
    assert "onOpenZProbeWizard" in main_qml
    assert 'title: "Z-probe input wizard"' in wizard_qml
    assert "This wizard only watches the electrical probe input" in wizard_qml
    assert "Step 1 — Leave the probe open" in wizard_qml
    assert "Step 2 — Touch and hold" in wizard_qml
    assert "Step 3 — Separate the contacts" in wizard_qml
    assert "Three supervised probe samples are still required" in wizard_qml
    assert "onContinueToCommissioning" in main_qml
    commissioning_qml = (root / "src" / "ttc3018_control" / "qt" / "qml" / "CommissioningDialog.qml").read_text(encoding="utf-8")
    assert "Samples completed:" in commissioning_qml
    assert "Run supervised sample " in commissioning_qml
    assert "no values need to be copied or entered manually" in commissioning_qml
    assert 'placeholderText: "Sample 1"' not in commissioning_qml


def test_commissioning_copy_exposes_available_twin_capabilities_without_claiming_physical_safety() -> None:
    root = Path(__file__).parents[1]
    commissioning_qml = (root / "src" / "ttc3018_control" / "qt" / "qml" / "CommissioningDialog.qml").read_text(encoding="utf-8")
    plate_docs = (root / "docs" / "Z_TOUCH_PLATE.md").read_text(encoding="utf-8")
    for text in (commissioning_qml, plate_docs):
        normalized = re.sub(r"\s+", " ", text.lower())
        assert "per-axis homing/limit declarations" in normalized
        assert "simulation-only" in normalized
        assert "physical commissioning remains explicit" in normalized
        assert "never certifies physical safety" in normalized
    assert "hidden until their workflows are implemented" not in commissioning_qml
    assert "remain hidden until their workflows are implemented" not in plate_docs


def test_z_probe_status_distinguishes_input_verification_from_samples(qapp, tmp_path) -> None:
    controller = ApplicationController(tmp_path)
    view_model = ControllerViewModel(controller)
    assert controller.save_z_plate_capability(True).accepted

    assert view_model.z_touch_plate_status_text == "Input test required"
    controller._z_touch_plate_record = ZTouchPlateRecord(
        controller.machine_id or "", (), controller.z_touch_plate_definition.tolerance,
        controller.z_touch_plate_fingerprint, input_tested=True,
    )

    assert view_model.z_touch_plate_status_text == "Input verified — 3 supervised probe samples required"


def test_z_probe_action_stays_clickable_and_shows_current_gate(qapp, tmp_path) -> None:
    from PySide6.QtCore import QObject

    controller = ApplicationController(tmp_path)
    assert controller.save_z_plate_capability(True).accepted
    engine, view_model = build_engine(visible=False, application=controller)
    view_model._guided_step = 3
    view_model._emit_state()
    root = engine.rootObjects()[0]
    buttons = root.findChildren(QObject, "probeWorkZ")
    assert buttons
    assert buttons[0].property("enabled")
    method = next(item for item in view_model.work_zero_methods if item["key"] == "movable_z_plate")
    assert not method["available"]

    notices: list[str] = []
    view_model.toast_requested.connect(notices.append)
    try:
        view_model.probe_work_z()
        assert notices[-1] == controller.probe_work_z().message
        assert "touch plate is needs input test" in notices[-1].lower()
    finally:
        view_model.close()


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


def test_bundled_showcase_step_uses_shared_async_pipeline_and_reports_errors(qapp, tmp_path, monkeypatch) -> None:
    _engine, view_model = build_engine()
    path = tmp_path / "examples" / "showcase-pocket-island.step"
    path.parent.mkdir()
    path.write_text("placeholder", encoding="ascii")
    model = StepPlanarModel(
        path,
        (PlanarLoop((Point2D(0, 0), Point2D(10, 0), Point2D(10, 5), Point2D(0, 5))),),
        0,
        2,
        (0, 0, 0, 10, 5, 2),
    )
    calls: list[Path] = []
    monkeypatch.setattr(
        type(view_model.application),
        "bundled_showcase_step_path",
        property(lambda _controller: path),
    )
    view_model.application.import_step = lambda selected: calls.append(selected) or model

    view_model.load_bundled_showcase_step()
    deadline = time.monotonic() + 2
    while view_model.step_importing and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)
    assert not view_model.step_importing
    assert calls == [path]
    assert view_model.step_source == path.name
    assert view_model.step_loaded

    missing = tmp_path / "missing-showcase.step"
    monkeypatch.setattr(
        type(view_model.application),
        "bundled_showcase_step_path",
        property(lambda _controller: missing),
    )
    view_model._step_model = None
    view_model.load_bundled_showcase_step()
    assert "does not exist" in view_model.step_model_summary
    assert view_model.step_source == "STEP import failed"

    qml = (Path(__file__).parents[1] / "src" / "ttc3018_control" / "qt" / "qml" / "Main.qml").read_text(encoding="utf-8")
    assert qml.count('text: "Load bundled showcase STEP"') == 2
    assert qml.count("load_bundled_showcase_step()") == 2


def test_native_step_chooser_uses_real_fixture_and_public_acceptance_binding(qapp, tmp_path) -> None:
    fixture = Path(__file__).parents[1] / "examples" / "showcase-pocket-island.step"
    assert fixture.is_file()
    view_model = ControllerViewModel(ApplicationController(tmp_path))
    view_model.import_step_file(QUrl.fromLocalFile(str(fixture)))
    # STEP/OCP import is intentionally asynchronous; allow the bounded
    # offscreen worker a little headroom when the full safety suite is busy.
    deadline = time.monotonic() + 10
    while view_model.step_importing and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)
    assert not view_model.step_importing
    assert view_model.step_loaded
    assert view_model.step_source == fixture.name
    assert "40.00 × 30.00 mm" in view_model.step_model_summary

    qml = (Path(__file__).parents[1] / "src" / "ttc3018_control" / "qt" / "qml" / "Main.qml").read_text(encoding="utf-8")
    assert 'id: stepFileDialog' in qml
    assert 'title: "Import planar STEP model"' in qml
    assert 'STEP files (*.step *.stp)' in qml
    assert 'appViewModel.import_step_file(selectedFile)' in qml


def test_simulation_first_contact_and_evidence_controls_are_publicly_bound() -> None:
    qml = (Path(__file__).parents[1] / "src" / "ttc3018_control" / "qt" / "qml" / "Main.qml").read_text(encoding="utf-8")
    assert 'ctx.fillText("FIRST CONTACT"' in qml
    assert 'id: simulationEvidenceDialog' in qml
    assert 'title: "Export digital-twin evidence"' in qml
    assert 'fileMode: PlatformDialogs.FileDialog.SaveFile' in qml
    assert 'JSON evidence (*.json)' in qml
    assert 'appViewModel.export_simulation_evidence(selectedFile)' in qml

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


def test_qt_view_model_marks_stale_and_missing_usb_setup_status(qapp, tmp_path) -> None:
    from ttc3018_control.application.state import ConnectionMode

    controller = ApplicationController(tmp_path)
    # Keep this an isolated presentation test; the production backend would
    # automatically start Wi-Fi bootstrap while setup-only USB is connected.
    controller._wifi_only_operations = False
    controller.connection_service.usb_setup_only = True
    controller.connection_service.mode = ConnectionMode.USB
    controller.connection_service.transport = SimpleNamespace(
        connected=True, events=queue.Queue(), send_line=lambda *_args, **_kwargs: None,
        send_realtime=lambda *_args, **_kwargs: None,
    )
    view_model = ControllerViewModel(controller)
    try:
        controller.apply_status(
            GrblStatus("Idle", machine_position=Position(10, 20, 3), spindle=0, pins="X")
        )
        view_model._emit_state()
        assert view_model.connection_text == "Connected — GRBL Idle"
        assert view_model.machine_position == "X10.00  Y20.00  Z3.00"

        controller._last_status_received_at = time.monotonic() - 3.0
        view_model._emit_state()
        assert view_model.grbl_state == "Stale"
        assert "USB setup connection" in view_model.connection_text
        assert "stale" in view_model.connection_text.lower()
        assert view_model.machine_position == "X—  Y—  Z—"
        assert view_model.spindle == "Unknown"

        controller.status = None
        controller._status_generation = -1
        view_model._emit_state()
        assert view_model.grbl_state == "Waiting"
        assert view_model.connection_text == (
            "USB setup connection — waiting for the first GRBL status report"
        )
    finally:
        view_model._timer.stop()


def test_qt_generator_preview_and_load_use_shared_parser(qapp) -> None:
    _engine, view_model = build_engine()

    view_model.preview_text("Hello", "Cursive", 8, -0.3, 3, 300, 100, 0.18, 1.4, "Center", 0)
    assert view_model.preview_strokes


def test_qt_preview_requests_are_debounced_and_complete_offscreen(qapp) -> None:
    _engine, view_model = build_engine()
    for text in ("H", "He", "Hello"):
        view_model.request_preview_text(text, "Simple", 8, -0.3, 3, 300, 100, 0.18, 1.4, "Left", 0)
    deadline = time.monotonic() + 2
    while view_model.operation_active and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)
    assert not view_model.operation_active
    assert "Hello" in view_model.preview_summary or view_model.preview_strokes
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


def test_qt_live_jog_bounded_press_release_and_no_revival(qapp) -> None:
    _engine, vm = build_engine()
    vm.session.profile = MachineProfile(travel_x=100, travel_y=100, travel_z=50, safe_z=3)
    connection = _FakeConnection(); vm.connection = connection
    vm.apply_status(GrblStatus("Idle", machine_position=Position(0,0,0)))
    vm.session.establish_reference()
    vm.apply_status(GrblStatus("Idle", machine_position=Position(10.25,0,0)))
    vm.start_live_jog("X", 1)
    assert connection.lines[-1] == b"$J=G91 G21 X1.66667 F500\n"
    vm._handle_event(SerialEvent("rx", "ok", datetime.now()))
    assert len(connection.lines) == 1
    vm.stop_live_jog(); vm.stop_live_jog(); vm._renew_live_jog_lease()
    assert connection.realtime[-1] == b"\x85"
    assert not vm._live_jog_lease_token and not vm._live_jog_renew_timer.isActive()
    assert len(connection.lines) == 1


@pytest.mark.parametrize("axis,direction", [("X",1),("X",-1),("Y",1),("Y",-1),("Z",1),("Z",-1)])
def test_qt_live_jog_segments_bounded_each_direction(qapp, axis, direction) -> None:
    _engine, vm = build_engine()
    vm.session.profile = MachineProfile(travel_x=100, travel_y=100, travel_z=50, safe_z=3)
    connection = _FakeConnection(); vm.connection = connection
    vm.apply_status(GrblStatus("Idle", machine_position=Position(0,0,0)))
    vm.session.establish_reference()
    vm.apply_status(GrblStatus("Idle", machine_position=Position(10,10,10)))
    vm.start_live_jog(axis, direction)
    expected = f"$J=G91 G21 {axis}{'1.66667' if direction > 0 else '-1.66667'} F500\n".encode()
    assert connection.lines[-1] == expected
    vm.stop_live_jog()
    assert connection.realtime[-1] == b"\x85"
