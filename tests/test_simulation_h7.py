from __future__ import annotations

import time
from pathlib import Path

from ttc3018_control.application.controller import ApplicationController
from ttc3018_control.qt.view_model import ControllerViewModel


def _wait_idle(controller: ApplicationController, timeout: float = 4.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        events = controller.transport_events()
        while not events.empty():
            controller.handle_transport_response(events.get_nowait().text)
        if controller.status is not None and controller.status.state == "Idle":
            return
        time.sleep(0.02)
    raise AssertionError("digital twin did not report Idle")


def _poll_until(controller: ApplicationController, predicate, timeout: float = 4.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        controller.poll_simulation()
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("digital-twin predicate did not become true")


def test_h7_public_estop_aborts_invalidates_and_requires_release_reference_ack(tmp_path) -> None:
    physical_calls: list[str] = []

    def forbidden():
        physical_calls.append("physical")
        raise AssertionError("physical transport factory was touched")

    controller = ApplicationController(tmp_path, usb_factory=forbidden, wifi_factory=forbidden)
    assert controller.connect_simulation().accepted
    try:
        _wait_idle(controller)
        assert controller.establish_reference().accepted
        controller.session.work_zero_confirmed = True
        assert controller.inject_simulation_estop(reset_asserted=True).accepted
        _poll_until(controller, lambda: bool(controller.simulation_runtime.estop_status.get("latched")))
        assert not controller.reference_trusted
        assert not controller.work_zero_confirmed
        assert not controller.acknowledge_simulation_estop().accepted

        assert controller.release_simulation_estop().accepted
        _poll_until(controller, lambda: not controller.simulation_runtime.estop_status.get("active"))
        controller.send_manual(b"$X")
        _wait_idle(controller)
        assert controller.establish_reference().accepted
        assert controller.acknowledge_simulation_estop().accepted
        _poll_until(controller, lambda: bool(controller.simulation_runtime.estop_status.get("recovery_authorized")))
    finally:
        controller.disconnect()
    assert physical_calls == []


def test_h7_public_limit_toggles_reach_twin_sensor_bank_and_clear(tmp_path) -> None:
    physical_calls: list[str] = []

    def forbidden():
        physical_calls.append("physical")
        raise AssertionError("physical transport factory was touched")

    controller = ApplicationController(tmp_path, usb_factory=forbidden, wifi_factory=forbidden)
    assert controller.connect_simulation().accepted
    try:
        _wait_idle(controller)
        declarations = {
            axis: {"enabled": True, "pin": f"{axis}1", "debounce_ms": 0}
            for axis in "XYZ"
        }
        assert controller.save_homing_limit_declarations(declarations).accepted
        assert controller.set_simulation_limit_input("X", True).accepted
        _poll_until(controller, lambda: controller.simulation_runtime.estop_status.get("limit_states", {}).get("X"))
        safety = controller.simulation_runtime.estop_status
        assert safety["limit_pins"] == "X"
        assert safety["limit_states"] == {"X": True, "Y": False, "Z": False}
        assert controller.set_simulation_limit_input("X", False).accepted
        _poll_until(controller, lambda: not controller.simulation_runtime.estop_status.get("limit_states", {}).get("X"))
        assert controller.simulation_runtime.estop_status["limit_pins"] == ""
    finally:
        controller.disconnect()
    assert physical_calls == []


def test_h7_viewmodel_guards_status_and_controls_to_digital_twin(qapp, tmp_path) -> None:
    view_model = ControllerViewModel(ApplicationController(tmp_path))
    assert "unavailable while disconnected" in view_model.simulation_limit_status
    assert "safety-rated" in view_model.simulation_estop_status
    assert not view_model.simulation_limit_x
    assert not view_model.simulation_estop_latched

    qml = (Path(__file__).parents[1] / "src" / "ttc3018_control" / "qt" / "qml" / "Main.qml").read_text(encoding="utf-8")
    assert "Simulation-only safety exercise" in qml
    assert 'appViewModel.inject_simulation_estop(true, false)' in qml
    assert 'appViewModel.inject_simulation_estop(false, false)' in qml
    assert 'appViewModel.release_simulation_estop()' in qml
    assert 'appViewModel.acknowledge_simulation_estop()' in qml
    assert 'appViewModel.inject_simulation_limit("X", checked)' in qml
    assert 'appViewModel.inject_simulation_limit("Y", checked)' in qml
    assert 'appViewModel.inject_simulation_limit("Z", checked)' in qml
    assert 'visible: appViewModel && appViewModel.simulation_active' in qml
