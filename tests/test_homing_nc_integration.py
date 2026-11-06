from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import QCoreApplication

from ttc3018_control.application.controller import ApplicationController
from ttc3018_control.application.state import ConnectionMode
from ttc3018_control.grbl import GrblStatus, Position
from ttc3018_control.qt.view_model import ControllerViewModel
from ttc3018_control.simulation.safety import SwitchWiring, interpret_pn_transition


class _Transport:
    connected = True

    def __init__(self) -> None:
        self.lines: list[bytes] = []
        self.realtime: list[bytes] = []

    def send_line(self, command: bytes, **_kwargs) -> None:
        self.lines.append(command)

    def send_realtime(self, command: bytes) -> None:
        self.realtime.append(command)

    def disconnect(self) -> None:
        self.connected = False


def test_nc_and_no_pn_transition_interpretation_is_axis_specific() -> None:
    assert interpret_pn_transition(None, "XYZ", wiring=SwitchWiring.NC).state == "released"
    z = interpret_pn_transition("XYZ", "XY", wiring=SwitchWiring.NC)
    assert (z.state, z.changed_axis) == ("actuated", "Z")
    assert interpret_pn_transition("XYZ", "XYZ", wiring=SwitchWiring.NC).state == "released"
    inverted = interpret_pn_transition(None, "", wiring=SwitchWiring.NC, grbl_limit_inverted=True)
    assert inverted.state == "released"
    x_inverted = interpret_pn_transition("", "X", wiring=SwitchWiring.NC, grbl_limit_inverted=True)
    assert (x_inverted.state, x_inverted.changed_axis) == ("actuated", "X")

    assert interpret_pn_transition(None, "", wiring=SwitchWiring.NO).state == "released"
    x = interpret_pn_transition("", "X", wiring=SwitchWiring.NO)
    assert (x.state, x.changed_axis) == ("actuated", "X")
    assert interpret_pn_transition("", "", wiring=SwitchWiring.NO).state == "released"

    assert interpret_pn_transition("XYZ", "", wiring=SwitchWiring.NC).state == "mismatch"
    assert interpret_pn_transition("XYZ", "X", wiring=SwitchWiring.NC).state == "mismatch"
    unknown = interpret_pn_transition("XYZ", "XYZ", wiring="unknown")
    assert unknown.state == "unknown" and "polarity" in unknown.reason


def test_setup_surface_names_nc_no_polarity_and_raw_pn_recovery() -> None:
    qml = (Path(__file__).parents[1] / "src" / "ttc3018_control" / "qt" / "qml" / "MachineSetupDialog.qml").read_text(encoding="utf-8")
    assert "NC (normally closed; open on trigger)" in qml
    assert "NO (normally open; close on trigger)" in qml
    assert "homing_input_status" in qml and "homing_input_reason" in qml


def _nc_declarations(*, hard_limit: bool = True, debounce_ms: float = 0.0) -> dict[str, dict[str, object]]:
    return {
        axis: {
            "enabled": True,
            "end": "max",
            "pin": f"{axis}1",
            "wiring": "NC",
            "hard_limit": hard_limit,
            "debounce_ms": debounce_ms,
        }
        for axis in "XYZ"
    }


def test_physical_nc_mapping_is_global_and_divergence_sends_zero_commands(tmp_path) -> None:
    app = ApplicationController(tmp_path)
    transport = _Transport()
    app.set_transport_for_testing(transport)
    app.connection_service.mode = ConnectionMode.USB
    app.status = GrblStatus("Idle", Position(0, 0, 0), Position(0, 0, 0), Position(0, 0, 0), pins="")
    # apply_status establishes the fresh timestamp used by the guarded save.
    app.apply_status(app.status)
    outcome = app.save_homing_limit_declarations(_nc_declarations())
    assert outcome.accepted, outcome.message
    assert [line.decode() for line in transport.lines] == ["$5=1\n", "$21=1\n", "$22=1\n", "$23=7\n"]
    assert all(item["wiring"].startswith("NC") for item in app.homing_limit_declarations.values())
    app.manual_pending_acks = 0

    before = list(transport.lines)
    divergent = _nc_declarations()
    divergent["Y"]["wiring"] = "NO"
    rejected = app.save_homing_limit_declarations(divergent)
    assert not rejected.accepted and "global" in rejected.message
    assert transport.lines == before

    before = list(transport.lines)
    unknown = _nc_declarations()
    unknown["Z"]["wiring"] = "unspecified"
    rejected = app.save_homing_limit_declarations(unknown)
    assert not rejected.accepted and "wiring" in rejected.message
    assert transport.lines == before


def test_public_viewmodel_exposes_pn_and_blocks_unknown_or_actuated_inputs(qapp, tmp_path) -> None:
    app = ApplicationController(tmp_path)
    assert app.save_homing_limit_declarations(_nc_declarations()).accepted
    app.set_transport_for_testing(_Transport())
    app.connection_service.mode = ConnectionMode.USB
    vm = ControllerViewModel(app)
    vm.connection = _Transport()
    try:
        vm.apply_status(GrblStatus("Idle", Position(0, 0, 0), Position(0, 0, 0), Position(0, 0, 0), pins=""))
        assert "NC" in vm.homing_input_polarity
        assert "Pn:none" in vm.homing_input_status
        assert app.homing_inputs_safe, (app.connected, app.status_fresh, app.homing_input_observation)
        vm.apply_status(GrblStatus("Idle", Position(0, 0, 0), Position(0, 0, 0), Position(0, 0, 0), pins="X"))
        assert vm.homing_input_status.startswith("actuated")
        assert not app.homing_inputs_safe
        assert not app.can_jog
        assert "release" in vm.homing_input_reason.lower()
        # Deliberately age only this isolated fake status to prove the public
        # gate is freshness-based and fails closed.
        app._last_status_received_at = time.monotonic() - 3.0
        assert app.homing_input_observation.state == "stale"
        assert not app.homing_inputs_safe and not app.can_jog
    finally:
        vm.close()
        app.close()


def test_loopback_nc_inputs_debounce_and_release_for_each_axis(tmp_path) -> None:
    QCoreApplication.instance() or QCoreApplication([])
    app = ApplicationController(tmp_path)
    assert app.configure_simulation("10x").accepted
    assert app.connect_simulation().accepted
    view_model = ControllerViewModel(app)

    def pump(predicate, timeout=8.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            app.poll_simulation()
            events = app.transport_events()
            while not events.empty():
                app.handle_transport_response(events.get_nowait().text)
            app.request_status()
            if predicate():
                return True
            time.sleep(0.01)
        return False

    try:
        assert pump(lambda: app.status is not None)
        assert app.save_homing_limit_declarations(_nc_declarations(hard_limit=False, debounce_ms=20)).accepted
        # The public simulator toggles logical switch activity and translates
        # through each axis's NC/NO declaration at the view-model boundary.
        for axis in "XYZ":
            view_model.inject_simulation_limit(axis, False)
        assert pump(lambda: app.homing_input_observation.state == "released"
                    and app.homing_input_observation.pins == "XYZ")
        for axis in "XYZ":
            view_model.inject_simulation_limit(axis, True)
            assert pump(lambda axis=axis: app.homing_input_observation.state == "actuated"
                        and app.homing_input_observation.changed_axis == axis)
            assert axis not in app.homing_input_observation.pins
            assert not app.can_jog
            view_model.inject_simulation_limit(axis, False)
            assert pump(lambda: app.homing_input_observation.state == "released")
            assert all(item in app.homing_input_observation.pins for item in "XYZ")
            assert app.homing_inputs_safe
    finally:
        view_model.close()
    assert app.simulation_runtime is None


def test_view_model_translates_logical_simulator_activity_by_axis_polarity(qapp, tmp_path, monkeypatch) -> None:
    app = ApplicationController(tmp_path)
    declarations = _nc_declarations(hard_limit=False)
    declarations["Y"]["wiring"] = "NO"
    assert app.save_homing_limit_declarations(declarations).accepted
    electrical_levels: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        app,
        "set_simulation_limit_input",
        lambda axis, electrical_active: (
            electrical_levels.append((axis, electrical_active))
            or SimpleNamespace(accepted=True, message="ok")
        ),
    )
    view_model = ControllerViewModel(app)

    view_model.inject_simulation_limit("X", True)
    view_model.inject_simulation_limit("X", False)
    view_model.inject_simulation_limit("Y", True)
    view_model.inject_simulation_limit("Y", False)

    assert electrical_levels == [("X", False), ("X", True), ("Y", True), ("Y", False)]
    view_model.close()
