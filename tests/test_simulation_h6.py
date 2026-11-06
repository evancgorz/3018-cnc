from __future__ import annotations

import json
import queue
import time

from PySide6.QtCore import QCoreApplication, QUrl

from ttc3018_control.application.controller import ApplicationController
from ttc3018_control.grbl import GrblStatus, Position
from ttc3018_control.machine_catalog import MachineCatalogStore
from ttc3018_control.application.state import ConnectionMode
from ttc3018_control.simulation.runtime import SimulationRuntime
from ttc3018_control.qt.view_model import ControllerViewModel


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


def _declarations(*, enabled: bool = True, end: str = "max", active_low: bool = True) -> dict[str, dict[str, object]]:
    return {
        axis: {
            "enabled": enabled,
            "end": end,
            "pin": f"{axis}1" if enabled else "",
            "active_low": active_low,
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
    controller = ApplicationController(tmp_path)
    assert controller.configure_simulation("10x").accepted
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


def test_ux2_public_viewmodel_loopback_guided_progression_and_cleanup(tmp_path) -> None:
    physical_calls: list[str] = []

    def forbidden_usb():
        physical_calls.append("usb")
        raise AssertionError("USB factory must remain untouched")

    def forbidden_wifi():
        physical_calls.append("wifi")
        raise AssertionError("Wi-Fi factory must remain untouched")

    app = QCoreApplication.instance() or QCoreApplication([])
    controller = ApplicationController(tmp_path, usb_factory=forbidden_usb, wifi_factory=forbidden_wifi)
    view_model = ControllerViewModel(controller)

    projection_events: list[str] = []
    view_model.state_changed.connect(lambda: projection_events.append(view_model.workflow_json))

    def pump_until(predicate, timeout=12.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            view_model._poll()
            app.processEvents()
            if predicate():
                return True
            time.sleep(0.01)
        return False

    try:
        assert view_model.guided_step == 1
        view_model.select_guided_step(4)
        assert view_model.guided_step == 4
        assert not physical_calls
        assert not next(item for item in view_model.work_zero_methods if item["key"] == "auto_xyz")["available"]
        view_model.configure_simulation("10×", "Pocket + retained island")
        assert controller.save_homing_limit_declarations(_declarations(active_low=False)).accepted
        view_model.connect_to_simulation()
        assert pump_until(lambda: view_model.connected and controller.status is not None)
        assert view_model.workflow_steps[1]["state"] == "complete"
        view_model.select_guided_step(2)
        assert view_model.guided_step == 2
        pre = next(item for item in view_model.work_zero_methods if item["key"] == "auto_xyz")
        assert not pre["available"]
        assert view_model.can_home_machine, (
            f"status={controller.status!r} fresh={controller.status_fresh} "
            f"inputs={controller.homing_input_observation!r} "
            f"safe={controller.homing_inputs_safe} homing={controller.homing.state.value}"
        )
        view_model.home_machine()
        assert pump_until(
            lambda: controller.reference_trusted
            and controller.homing.state.value == "complete"
            and not controller.homing.active
            and view_model.guided_step == 3
        )
        assert view_model.workflow_steps[2]["state"] == "complete"
        assert view_model.guided_step == 3
        view_model.commission_simulation_calibration_plate()
        assert pump_until(lambda: controller.simulation_plate_commissioned)
        post = next(item for item in view_model.work_zero_methods if item["key"] == "auto_xyz")
        assert post["available"]
        view_model.start_auto_xyz_calibration(20.0, 20.0, 30.0)
        assert pump_until(lambda: controller.auto_xyz_calibration_state in {"complete", "failed"})
        assert controller.auto_xyz_calibration_state == "complete", controller.auto_xyz_calibration_status
        done = next(item for item in view_model.work_zero_methods if item["key"] == "auto_xyz")
        assert done["state"] == "complete"
        assert not done["available"]
        assert controller.calibration.work_offset_confirmed
        assert view_model.workflow_steps[3]["state"] == "complete"
        assert view_model.guided_step == 4
        # Later steps remain navigable; starting still requires a reviewed job.
        view_model.select_guided_step(6)
        assert view_model.guided_step == 6
        view_model.guided_start_job()
        assert not view_model.confirmation_token.startswith("job_start:")
        assert projection_events
        assert any('"auto_xyz"' in event for event in projection_events)

        # Batch E closes the proof at the public run boundary.  Keep the job
        # deterministic and record the same evidence fields as a real twin
        # acceptance report; this never opens a physical endpoint.
        seed = 20260910
        controller.record_simulation_event("e5_configuration", {
            "seed": seed,
            "transport": "owned-loopback",
            "configuration": "commissioned-twin-auto-xyz",
            "collision_analysis": "not_run",
        })
        job = tmp_path / "e5-guided-job.nc"
        job.write_text(
            "G21 G90\nG0 X1 Y1 Z3\nG1 X5 Y5 Z3 F120\nG0 Z3\nM5\n",
            encoding="ascii",
        )
        view_model.load_gcode_file(QUrl.fromLocalFile(str(job)))
        assert view_model.program is not None
        assert view_model.guided_step == 6
        view_model.select_guided_step(5)
        assert view_model.guided_step == 5
        assert view_model.workflow_steps[5]["state"] == "required", (
            f"step={view_model.workflow_steps[5]!r} preflight={controller.preflight()} "
            f"reference={controller.session.envelope.reference!r} wco={controller.work_offset!r}"
        )
        view_model.acknowledge_review()
        assert view_model.review_acknowledged
        assert view_model.workflow_steps[5]["state"] == "complete"
        view_model.guided_continue()
        assert view_model.guided_step == 6
        view_model.set_physical_preflight_confirmed(True)
        view_model.guided_start_job()
        assert view_model.confirmation_token.startswith("job_start:")
        token = view_model.confirmation_token
        view_model.confirm_pending_action(token)
        assert pump_until(lambda: controller.job_active or controller.job_state in {"complete", "failed"}, 4.0)
        assert controller.job_active
        controller.record_simulation_event("e5_streaming", {
            "state": controller.job_state,
            "work_offset": repr(controller.work_offset),
        })
        assert pump_until(lambda: not controller.job_active and view_model.next_part_available, 20.0), (
            controller.job_state, controller.job_active, view_model._last_job_projection,
            view_model._next_part_available,
        )
        assert controller.job_state == "complete", controller.job.streamer.error
        assert view_model.next_part_available
        controller.record_simulation_event("e5_completed", {
            "expected": "complete",
            "observed": controller.job_state,
            "commands": len(controller.program.commands),
        })
        evidence = tmp_path / "evidence" / "e5-guided.json"
        controller.export_simulation_trace(evidence)
        assert evidence.exists() and evidence.with_suffix(".md").exists()
        exported = json.loads(evidence.read_text(encoding="utf-8"))
        assert any(event["kind"] == "e5_configuration" for event in exported["events"])
        assert any(event["kind"] == "e5_completed" for event in exported["events"])

        # Repetition is explicit and must return to Review rather than
        # silently replaying a stale authorization.
        view_model.prepare_next_part()
        assert view_model.guided_step == 5
        assert not view_model.review_acknowledged
        assert not view_model.guided_preflight_confirmed
    finally:
        view_model.close()
        controller.close()
    assert not physical_calls
    assert controller.simulation_runtime is None
