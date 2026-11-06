from __future__ import annotations

import time
from pathlib import Path

from ttc3018_control.application.connection_service import ConnectionService
from ttc3018_control.application.envelope_projection import project_machine_position
from ttc3018_control.connection_settings import ConnectionSettings
from ttc3018_control.grbl import Position


class _Transport:
    def __init__(self, *, usb_ok: bool = True, wifi_ok: bool = True) -> None:
        self.connected = False
        self.usb_ok = usb_ok
        self.wifi_ok = wifi_ok
        self.endpoint = ""

    @property
    def events(self):
        return ()

    def connect(self, *args, **kwargs) -> None:
        endpoint = str(args[0])
        self.endpoint = endpoint
        ok = self.wifi_ok if "timeout" in kwargs else self.usb_ok
        if not ok:
            raise OSError(f"unavailable {endpoint}")
        self.connected = True

    def disconnect(self) -> None:
        self.connected = False

    def send_line(self, *_args, **_kwargs) -> None:
        return None

    def send_realtime(self, *_args) -> None:
        return None


def test_envelope_projection_preserves_orientation_z_and_out_of_bounds() -> None:
    marker = project_machine_position(
        Position(145, 85, 12), 290, 170, 40,
        connected=True, status_fresh=True, session_id="one",
    )
    assert marker.state == "visible"
    assert (marker.x, marker.y, marker.z) == (0.5, 0.5, 12)
    assert (marker.render_x, marker.render_y) == (0.5, 0.5)

    corner = project_machine_position(
        Position(0, 0, 0), 290, 170, 40,
        connected=True, status_fresh=True, session_id="one",
    )
    assert (corner.render_x, corner.render_y) == (0.0, 0.0)

    outside = project_machine_position(
        Position(320, -5, 12), 290, 170, 40,
        connected=True, status_fresh=True, session_id="one",
    )
    assert outside.state == "out_of_bounds"
    assert outside.direction == "X+ / Y−"
    assert outside.x > 1 and outside.y < 0
    assert (outside.render_x, outside.render_y) == (1.0, 0.0)


def test_machine_workflow_has_no_click_through_safety_step_and_home_is_full_width() -> None:
    qml = (Path(__file__).parents[1] / "src" / "ttc3018_control" / "qt" / "qml" / "Main.qml").read_text(encoding="utf-8")
    assert 'text: "2. Safety' not in qml
    assert 'objectName: "guidedSafetyContent"' not in qml
    assert 'objectName: "guidedStep2"; text: "Home"' in qml
    assert 'objectName: "guidedHomeContent"' in qml
    assert 'objectName: "panelHomeMachineIcon"; visible: window.guidedIndex === 2; Layout.fillWidth: true; text: "Home machine"' in qml


def test_shell_uses_restrained_semantic_visual_system() -> None:
    root = Path(__file__).parents[1]
    qml = (root / "src" / "ttc3018_control" / "qt" / "qml" / "Main.qml").read_text(encoding="utf-8")
    issue = (root / "src" / "ttc3018_control" / "qt" / "qml" / "components" / "IssueBanner.qml").read_text(encoding="utf-8")
    assert 'accent: Qt.color("#0A84FF")' in qml
    assert 'surface: Qt.color("#1C1C1E")' in qml
    assert 'component Panel: Rectangle' in qml and 'radius: 16' in qml
    assert 'Behavior on color { ColorAnimation { duration: 120 } }' in qml
    assert 'objectName: "abortJob"' in qml and 'dangerous: true' in qml
    assert "maximumLineCount" not in issue


def test_envelope_projection_hides_stale_unknown_and_session_change() -> None:
    for kwargs in (
        {"connected": False, "status_fresh": False},
        {"connected": True, "status_fresh": False},
        {"connected": True, "status_fresh": True, "position": None},
    ):
        marker = project_machine_position(
            kwargs.pop("position", Position(1, 2, 3)), 290, 170, 40,
            session_id="one", **kwargs,
        )
        assert marker.state == "unknown"
    marker = project_machine_position(
        Position(1, 2, 3), 290, 170, 40,
        connected=True, status_fresh=True, session_id="two", expected_session_id="one",
    )
    assert marker.state == "unknown"


def test_backend_auto_connection_prefers_saved_tcp_then_falls_back_to_one_com() -> None:
    transports: list[_Transport] = []

    def wifi_factory() -> _Transport:
        transport = _Transport(wifi_ok=False)
        transports.append(transport)
        return transport

    usb = _Transport(usb_ok=True)
    service = ConnectionService(
        lambda: usb, wifi_factory, lambda _port: (_ for _ in ()).throw(AssertionError("network discovery")),
    )
    outcome = service.begin_auto_connect(
        ConnectionSettings("192.168.4.20", 23, "Wi-Fi TCP", "COM9"), ["COM9"],
    )
    assert outcome.accepted and service.wifi_connecting
    deadline = time.monotonic() + 1.0
    result = None
    while time.monotonic() < deadline and result is None:
        result = service.poll_wifi()
        if result is None:
            time.sleep(0.01)
    assert result is not None and result.accepted
    assert result.mode.value == "USB serial"
    assert service.endpoint == "COM9"
    assert len(transports) == 1
    assert any("Wi-Fi" in failure for failure in service.auto_connection_failures)


def test_successful_wifi_transport_remains_connected_after_poll() -> None:
    wifi = _Transport(wifi_ok=True)
    service = ConnectionService(
        lambda: _Transport(), lambda: wifi,
        lambda _port: (_ for _ in ()).throw(AssertionError("network discovery")),
    )
    outcome = service.begin_wifi("192.168.86.38", 23, discover=False)
    assert outcome.accepted

    deadline = time.monotonic() + 1.0
    result = None
    while time.monotonic() < deadline and result is None:
        result = service.poll_wifi()
        if result is None:
            time.sleep(0.01)

    assert result is not None and result.accepted
    assert service.transport is wifi
    assert service.connected
    assert wifi.connected


def test_backend_auto_connection_does_not_guess_multiple_new_com_ports() -> None:
    usb = _Transport()
    service = ConnectionService(
        lambda: usb,
        lambda: _Transport(wifi_ok=False),
        lambda _port: (_ for _ in ()).throw(AssertionError("network discovery")),
    )
    outcome = service.begin_auto_connect(
        ConnectionSettings("192.168.4.20", 23, "USB serial", "COM-stale"),
        ["COM10", "COM11"],
    )
    assert outcome.accepted and service.wifi_connecting
    deadline = time.monotonic() + 1.0
    result = None
    while time.monotonic() < deadline and result is None:
        result = service.poll_wifi()
        if result is None:
            time.sleep(0.01)
    assert result is not None and not result.accepted
    assert not usb.connected
    assert "Automatic connection failed" in result.message


def test_qml_groups_operator_steps_and_keeps_utilities(qapp, tmp_path) -> None:
    from PySide6.QtCore import QObject

    from ttc3018_control.application.controller import ApplicationController
    from ttc3018_control.qt.main import build_engine

    engine, view_model = build_engine(
        visible=False,
        application=ApplicationController(tmp_path),
    )
    root = engine.rootObjects()[0]
    try:
        step_names = [f"guidedStep{index}" for index in range(1, 7)]
        assert all(root.findChildren(QObject, name) for name in step_names)
        assert all(root.findChildren(QObject, name)[0].property("visible") for name in step_names[:4])
        assert all(root.findChildren(QObject, name)[0].property("visible")
                   for name in ("machineWorkspace", "jobWorkspace"))
        view_model.select_guided_step(5)
        assert all(root.findChildren(QObject, name)[0].property("visible") for name in step_names[4:])
        preview = root.findChildren(QObject, "jobPreview")[0]
        assert preview.property("visible")
        view_model.select_guided_step(6)
        assert root.findChildren(QObject, "jobPreview")[0] is preview
        assert preview.property("visible")
        assert root.findChildren(QObject, "configureUtility")[0].property("visible")
        assert root.findChildren(QObject, "configureUtility")[0].property("text") == "Configure"
        assert root.findChildren(QObject, "configureUtility")[0].property("visible")
        assert root.findChildren(QObject, "panelHomeMachineIcon")
        assert root.findChildren(QObject, "machineSafetyAttention")
        assert [root.findChildren(QObject, name)[0].property("text") for name in step_names] == [
            "Connect", "Home", "Work Zero", "CAM tools…", "Review", "Run"
        ]
        assert root.findChildren(QObject, "guidedStep1")[0].property("enabled")
        assert root.findChildren(QObject, "guidedStep2")[0].property("enabled")
        assert all(root.findChildren(QObject, name)[0].property("enabled") for name in step_names)
    finally:
        root.close()
        view_model.close()


def test_saved_previous_work_zero_is_visible_and_return_is_gated(qapp, tmp_path) -> None:
    from PySide6.QtCore import QObject

    from ttc3018_control.application.controller import ApplicationController
    from ttc3018_control.machine_config import MachineDefinition
    from ttc3018_control.qt.main import build_engine
    from ttc3018_control.work_zero_settings import SavedWorkZero, WorkZeroStore

    machine_id = MachineDefinition.legacy_3018().machine_id
    WorkZeroStore(tmp_path / "config" / "work-zero.json").save(
        SavedWorkZero(35.0, 40.0, 12.0), machine_id,
    )
    application = ApplicationController(tmp_path)
    engine, view_model = build_engine(visible=False, application=application)
    root = engine.rootObjects()[0]
    try:
        root.setProperty("guidedIndex", 3)
        saved_label = root.findChildren(QObject, "savedPreviousWorkZero")[0]
        return_button = root.findChildren(QObject, "returnWorkZero")[0]

        assert saved_label.property("visible") is True
        assert saved_label.property("text") == (
            "Saved previous work-zero coordinates: X 35.000 mm, Y 40.000 mm, Z 12.000 mm"
        )
        assert return_button.property("visible") is True
        assert return_button.property("text") == "Return to saved work zero"
        assert return_button.property("enabled") is False  # Requires a fresh connected Idle state and trusted reference.

        # The return planner uses the current confirmed WCO in preference to
        # the saved fallback, so the action label must follow that same choice.
        application.session.work_offset = Position(9.0, 8.0, 7.0)
        application.session.work_zero_confirmed = True
        view_model._emit_state()
        assert saved_label.property("text") == (
            "Saved previous work-zero coordinates: X 35.000 mm, Y 40.000 mm, Z 12.000 mm"
        )
        assert return_button.property("text") == "Return to confirmed work zero"
    finally:
        root.close()
        view_model.close()
