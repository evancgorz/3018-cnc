from __future__ import annotations

import pytest

from ttc3018_control.application.calibration_service import AutoXYZCalibrationService
from ttc3018_control.grbl import GrblStatus, Position
from ttc3018_control.simulation import ProbeCornerCircle, VirtualGrblController, VirtualMachinePlant
from ttc3018_control.simulation.models import SimulationProfile
from ttc3018_control.simulation.runtime import SimulationRuntime
from ttc3018_control.simulation.safety import (
    CalibrationCommissioningRecord, CalibrationPlateDefinition, CalibrationState,
)


def _commissioning(definition: CalibrationPlateDefinition) -> CalibrationCommissioningRecord:
    return CalibrationCommissioningRecord(plate_fingerprint=definition.fingerprint(),
                                          input_tested=True, geometry_tested=True)


def test_corner_circle_probe_stops_at_first_swept_contact_and_preserves_z_probe() -> None:
    plant = VirtualMachinePlant(SimulationProfile(initial_x=4.0, initial_y=0.0, initial_z=10.0))
    controller = VirtualGrblController(plant)
    controller.configure_probe_corner_circle(ProbeCornerCircle(5.0, 0.0, 2.0, 10.0))
    controller.receive(b"G91 G38.2 X5 F60\n")
    assert controller.drain() == ("ok",)
    plant.advance(10_000_000_000)
    assert plant.machine_position == pytest.approx((7.0, 0.0, 10.0), abs=0.001)
    assert controller.drain() == ("[PRB:7.000,0.000,10.000:1]",)


def test_auto_xyz_service_requires_commissioning_and_uses_ordinary_commands() -> None:
    sent: list[bytes] = []
    notices: list[str] = []
    service = AutoXYZCalibrationService(sent.append, on_notice=notices.append, require_idle_boundary=False)
    definition = CalibrationPlateDefinition()
    rejected = service.start(seed=(20.0, 20.0, 10.0), definition=definition,
                             commissioning_record=None, reference_trusted=True,
                             controller_idle=True, spindle_rpm=0.0,
                             envelope=(300.0, 300.0, 100.0))
    assert not rejected.accepted
    assert service.failure.value == "uncommissioned"
    assert not sent

    assert service.start(seed=(20.0, 20.0, 10.0), definition=definition,
                         commissioning_record=_commissioning(definition),
                         reference_trusted=True, controller_idle=True, spindle_rpm=0.0,
                         envelope=(300.0, 300.0, 100.0)).accepted
    assert sent[0].startswith(b"G90 G21 G0")
    assert service.state is CalibrationState.SEARCHING
    assert service.handle_response("ok")
    assert sent[1].startswith(b"G0 X")
    assert service.handle_response("ok")
    assert service.handle_response("[PRB:10.000,20.000,10.000:1]")


def test_auto_xyz_service_rejects_stale_wco_and_collision() -> None:
    sent: list[bytes] = []
    service = AutoXYZCalibrationService(sent.append, require_idle_boundary=False)
    definition = CalibrationPlateDefinition()
    assert service.start(seed=(20.0, 20.0, 10.0), definition=definition,
                         commissioning_record=_commissioning(definition),
                         reference_trusted=True, controller_idle=True, spindle_rpm=0.0,
                         envelope=(300.0, 300.0, 100.0)).accepted
    assert service.handle_response("alarm:1")
    assert service.failure.value == "collision_interlock"

    service.reset()
    assert service.start(seed=(20.0, 20.0, 10.0), definition=definition,
                         commissioning_record=_commissioning(definition),
                         reference_trusted=True, controller_idle=True, spindle_rpm=0.0,
                         envelope=(300.0, 300.0, 100.0)).accepted
    service.observe_status(GrblStatus("Idle", Position(20, 20, 10), Position(20, 20, 10), Position(0, 0, 0)))
    # A no-contact report is a typed fail-closed outcome, not completion.
    for _ in range(3):
        service.handle_response("ok")
    assert service.handle_response("[PRB:20.000,20.000,10.000:0]")
    assert service.failure.value == "no_contact"


def test_application_loopback_calibration_uses_tcp_and_cleans_up(tmp_path) -> None:
    from ttc3018_control.application.controller import ApplicationController

    definition = CalibrationPlateDefinition()
    controller = ApplicationController(
        tmp_path,
        simulation_factory=lambda: SimulationRuntime(
            speed="10x", probe_corner_circle=ProbeCornerCircle(20.0, 20.0, 10.0, 20.0),
            probe_surface_z=20.0),
    )
    assert controller.connect_simulation().accepted
    try:
        import time
        deadline = time.time() + 6.0
        while time.time() < deadline and controller.status is None:
            while not controller.transport_events().empty():
                controller.handle_transport_response(controller.transport_events().get_nowait().text)
            controller.request_status()
            time.sleep(0.01)
        assert controller.status is not None and controller.establish_reference().accepted
        assert controller.jog("X", 20.0, 900).accepted
        deadline = time.time() + 6.0
        while time.time() < deadline and (controller.machine_position is None or controller.machine_position.x < 19.9 or controller.status is None or controller.status.state != "Idle"):
            controller.request_status()
            while not controller.transport_events().empty():
                controller.handle_transport_response(controller.transport_events().get_nowait().text)
            time.sleep(0.01)
        assert controller.jog("Y", 20.0, 900).accepted
        deadline = time.time() + 6.0
        while time.time() < deadline and (controller.machine_position is None or controller.machine_position.y < 19.9 or controller.status is None or controller.status.state != "Idle"):
            controller.request_status()
            while not controller.transport_events().empty():
                controller.handle_transport_response(controller.transport_events().get_nowait().text)
            time.sleep(0.01)
        outcome = controller.start_auto_xyz_calibration(
            (20.0, 20.0, 10.0), definition=definition, commissioning_record=_commissioning(definition))
        assert outcome.accepted
        deadline = time.time() + 10.0
        while time.time() < deadline and controller.auto_xyz_calibration_state not in {"complete", "failed"}:
            controller.request_status()
            while not controller.transport_events().empty():
                controller.handle_transport_response(controller.transport_events().get_nowait().text)
            time.sleep(0.01)
        assert controller.auto_xyz_calibration_state == "complete", controller.auto_xyz_calibration_status
        assert controller.work_zero_confirmed, (controller.status, controller.calibration.work_offset_confirmation_pending, controller.calibration.last_status)
    finally:
        controller.close()
    assert not controller.connected
