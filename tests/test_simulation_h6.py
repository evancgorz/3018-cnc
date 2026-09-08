from __future__ import annotations

import json
import queue
import time

from ttc3018_control.application.controller import ApplicationController
from ttc3018_control.grbl import GrblStatus, Position
from ttc3018_control.machine_catalog import MachineCatalogStore
from ttc3018_control.application.state import ConnectionMode
from ttc3018_control.simulation.runtime import SimulationRuntime


class _FakeTransport:
    connected = True

    def __init__(self) -> None:
        self.events = queue.Queue()
        self.lines: list[bytes] = []

    def send_line(self, command: bytes, **_kwargs) -> None:
        self.lines.append(command)

    def send_realtime(self, _command: bytes) -> None:
        pass

    def disconnect(self) -> None:
        self.connected = False


def _declarations(*, enabled: bool = True, end: str = "max") -> dict[str, dict[str, object]]:
    return {
        axis: {
            "enabled": enabled,
            "end": end,
            "pin": f"{axis}1" if enabled else "",
            "active_low": True,
            "hard_limit": True,
            "debounce_ms": 8,
            "max_override": 100.0 if axis == "X" else None,
        }
        for axis in "XYZ"
    }


def test_homing_declarations_validate_persist_and_map_to_machine_profile(tmp_path) -> None:
    controller = ApplicationController(tmp_path)
    outcome = controller.save_homing_limit_declarations(_declarations())
    assert outcome.accepted, outcome.message
    assert controller.machine_definition.axes["X"].switch_mode.value == "single"
    assert controller.machine_definition.axes["X"].switch_end.value == "max"
    assert controller.machine_definition.axes["X"].max_override == 100.0
    assert controller.homing_limit_profile.axes[0].input_pin == "X1"
    saved = MachineCatalogStore(tmp_path / "config" / "machines.json").load().selected()
    assert saved.axes["Y"].active_low is True
    assert json.loads((tmp_path / "config" / "machines.json").read_text())


def test_physical_grbl_settings_are_idle_gated_and_global_safe(tmp_path) -> None:
    controller = ApplicationController(tmp_path)
    transport = _FakeTransport()
    controller.set_transport_for_testing(transport)
    controller.connection_service.mode = ConnectionMode.USB
    controller.status = GrblStatus("Idle", Position(0, 0, 0), Position(0, 0, 0), Position(0, 0, 0))
    outcome = controller.save_homing_limit_declarations(_declarations())
    assert outcome.accepted, outcome.message
    assert [line.decode() for line in transport.lines] == ["$5=1\n", "$21=1\n", "$22=1\n", "$23=7\n"]

    controller.manual_pending_acks = 0
    controller.status = GrblStatus("Run", Position(0, 0, 0), Position(0, 0, 0), Position(0, 0, 0))
    rejected = controller.save_homing_limit_declarations(_declarations(end="min"))
    assert not rejected.accepted
    assert "Idle" in rejected.message


def test_simulation_declarations_use_runtime_boundary_without_physical_settings(tmp_path) -> None:
    controller = ApplicationController(tmp_path)
    transport = _FakeTransport()
    captured = []

    class Runtime:
        def configure_homing(self, profile) -> None:
            captured.append(profile)

    controller.set_transport_for_testing(transport)
    controller.connection_service.mode = ConnectionMode.SIMULATION
    controller.connection_service.simulation_runtime = Runtime()
    outcome = controller.save_homing_limit_declarations(_declarations(end="min"))
    assert outcome.accepted, outcome.message
    assert len(captured) == 1
    assert captured[0].axes[0].homing_end.value == "min"
    assert transport.lines == []


def test_public_loopback_commissioned_plate_enables_auto_xyz(tmp_path) -> None:
    controller = ApplicationController(tmp_path, simulation_factory=lambda: SimulationRuntime(speed="10x", probe_surface_z=20.0))
    assert controller.connect_simulation().accepted

    def pump_until(predicate, timeout=6.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            while not controller.transport_events().empty():
                controller.handle_transport_response(controller.transport_events().get_nowait().text)
            controller.request_status()
            if predicate():
                return True
            time.sleep(0.01)
        return False

    try:
        assert pump_until(lambda: controller.status is not None)
        assert controller.establish_reference().accepted
        assert controller.commission_simulation_calibration_plate().accepted
        assert controller.simulation_plate_commissioned
        outcome = controller.start_auto_xyz_calibration((20.0, 20.0, 30.0))
        assert outcome.accepted, outcome.message
        assert pump_until(lambda: controller.auto_xyz_calibration_state in {"complete", "failed"}, 12.0)
        assert controller.auto_xyz_calibration_state == "complete", controller.auto_xyz_calibration_status
    finally:
        controller.close()
