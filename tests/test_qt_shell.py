from __future__ import annotations

from datetime import datetime
import math
import os
import queue
from pathlib import Path
from types import SimpleNamespace
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
from ttc3018_control.z_touch_plate import ZTouchPlateRecord
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
    assert roots[0].property("title") == "Pine"
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


def test_simulation_show_action_is_connected_only_and_raises_window() -> None:
    qml = (Path(__file__).parents[1] / "src" / "ttc3018_control" / "qt" / "qml" / "Main.qml").read_text(encoding="utf-8")
    assert "function showSimulator()" in qml
    assert "if (!(appViewModel && appViewModel.simulation_active)) return" in qml
    assert "simulationWindow.visible = true" in qml
    assert "simulationWindow.raise()" in qml
    assert "simulationWindow.requestActivate()" in qml
    assert 'SecondaryButton { visible: appViewModel && appViewModel.simulation_active; text: "Show simulator"; onClicked: window.showSimulator() }' in qml
    assert 'if (appViewModel && appViewModel.job_active)' in qml
    assert 'enabled: appViewModel && appViewModel.simulation_export_available' in qml
    assert 'visible: appViewModel && appViewModel.simulation_active; text: "Show simulator"' in qml
    assert '"Stock metrics " + (appViewModel ? appViewModel.simulation_stock_metrics_json : "{}")' in qml
    assert 'text: "Pause"; enabled: appViewModel && appViewModel.job_active; onClicked: appViewModel.pause_job()' in qml
    assert 'text: "Resume"; enabled: appViewModel && appViewModel.job_active; onClicked: appViewModel.resume_job()' in qml
    assert 'text: "Abort"; enabled: appViewModel && appViewModel.job_active; onClicked: appViewModel.abort_job()' in qml
    assert 'appViewModel.requires_exit_prompt' in qml
    assert 'closeEvent.accepted = false' in qml


def test_simulation_projection_clears_stale_hazard_stock_and_export_state_on_disconnect(qapp, tmp_path) -> None:
    controller = ApplicationController(tmp_path)
    view_model = ControllerViewModel(controller)
    view_model._simulation_active_hazard = {"kind": "tool_fixture", "message": "contact", "position": (1, 2, 3)}
    view_model._simulation_hazards = ["contact"]
    view_model._simulation_stock_metrics = {"removed_volume": 4}
    view_model._simulation_export_status = "Evidence exported"
    view_model._disconnected("test cleanup")
    assert not view_model.simulation_hazard_active
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


def test_qml_workspaces_and_creation_flow_are_consolidated() -> None:
    qml = (Path(__file__).parents[1] / "src" / "ttc3018_control" / "qt" / "qml" / "Main.qml").read_text(
        encoding="utf-8"
    )

    assert 'model: ["Prepare", "Preview & Run", "Machine"]' in qml
    assert 'text: "Engraving designer"' in qml
    assert 'id: engravingDialog' in qml
    assert 'model: ["Plain text", "Plaque"]' in qml
    assert 'text: "Load existing job…"' in qml
    assert 'id: guidedSetupDialog' in qml
    assert '"Move to coordinates"' in qml
    assert 'property bool coordinatesExpanded: false' in qml
    assert 'appViewModel.job_estimate' in qml
    assert 'appViewModel.job_time_remaining' in qml
    assert 'id: textDialog' not in qml
    assert 'id: plaqueDialog' not in qml
    assert '"Guided Setup"]' not in qml
    assert 'PineLiveCard { Layout.fillWidth: true; palette: window.palette }' in qml
    assert 'text: "Machine settings…"' in qml
    assert "window.usableContentHeight - height" in qml
    assert 'set_physical_preflight_confirmed(checked)' in qml
    assert 'index === 3 ?' not in qml
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
