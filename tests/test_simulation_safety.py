from __future__ import annotations

import math

import pytest

from ttc3018_control.simulation.safety import (
    AutoXYZCalibrationWorkflow,
    AxisEnd,
    AxisSensorDeclaration,
    CalibrationPlateDefinition,
    CalibrationState,
    EStopDefinition,
    EStopLatch,
    EStopMode,
    HomingCommissioningRecord,
    HomingLimitProfile,
    HomingSensorBank,
    PlateContact,
    fit_plate_circle,
)
from ttc3018_control.simulation.controller import VirtualGrblController


def test_homing_profile_defaults_polarity_debounce_and_fingerprint_invalidation() -> None:
    profile = HomingLimitProfile.default_3018("m1")
    profile.validate()
    bank = HomingSensorBank(profile)
    assert bank.pins() == ""
    assert not bank.set_input("X", True, 0)
    assert bank.set_input("X", True, 5_000_000)
    assert bank.pins() == "X"
    assert bank.homing_position() == (0.0, 0.0, 0.0)
    record = HomingCommissioningRecord(machine_id="m1", profile_fingerprint=profile.fingerprint(),
                                       tested_inputs={a: True for a in "XYZ"}, directions_confirmed=True,
                                       homing_verified=True)
    assert record.valid_for(profile)
    changed = HomingLimitProfile(1, "m1", tuple(
        AxisSensorDeclaration(a, t, AxisEnd.MAX if a == "X" else AxisEnd.MIN)
        for a, t in zip("XYZ", (290, 170, 40))))
    assert not record.valid_for(changed)
    assert record.invalidate_if_changed(changed).profile_fingerprint == changed.fingerprint()


def test_homing_active_low_and_max_override() -> None:
    profile = HomingLimitProfile(1, "m2", tuple(
        AxisSensorDeclaration(a, t, AxisEnd.MAX if a == "Y" else AxisEnd.MIN,
                              active_low=True, input_pin=f"{a}1", hard_limit=True,
                              max_override=(175.0 if a == "Y" else None))
        for a, t in zip("XYZ", (290, 170, 40))))
    bank = HomingSensorBank(profile)
    assert not bank.set_input("Y", False, 0)
    assert bank.set_input("Y", False, 5_000_000)
    assert bank.homing_position() == (0.0, 175.0, 0.0)


def test_estop_modes_latch_debounce_release_and_manual_recovery() -> None:
    definition = EStopDefinition(mode=EStopMode.RESET_PLUS_FEEDBACK, input_pin="E", reset_pin="R",
                                  active_low=True, debounce_ms=10)
    stop = EStopLatch(definition)
    assert not stop.observe(feedback_electrical=True, now_ns=0)
    assert not stop.observe(feedback_electrical=False, now_ns=10_000_000)
    assert stop.observe(feedback_electrical=False, now_ns=20_000_000)
    assert stop.status()["latched"]
    stop.release()
    assert not stop.acknowledge(controller_idle=True, reference_trusted=False)
    assert stop.acknowledge(controller_idle=True, reference_trusted=True)
    assert not stop.interlocked
    stop.observe(reset_asserted=True, now_ns=20_000_000)
    assert stop.interlocked


def test_estop_disabled_is_inert_and_feedback_mode_requires_input() -> None:
    stop = EStopLatch(EStopDefinition())
    assert not stop.observe(reset_asserted=True)
    assert stop.acknowledge(controller_idle=False, reference_trusted=False)
    with pytest.raises(ValueError):
        EStopDefinition(mode=EStopMode.FEEDBACK_ONLY).validate()


def test_circle_fit_compensation_and_fail_closed_noise() -> None:
    contacts = tuple(PlateContact(x, y) for x, y in ((10, 0), (0, 10), (-10, 0), (0, -10)))
    result = fit_plate_circle(contacts, tool_radius=1.5, tolerance=.01)
    assert result.center == pytest.approx((0, 0))
    assert result.tool_radius_compensation == 1.5
    with pytest.raises(ValueError):
        fit_plate_circle(contacts[:3])
    with pytest.raises(ValueError):
        fit_plate_circle((*contacts[:3], PlateContact(0, 13)), tolerance=.1)


def test_auto_xyz_workflow_requires_truthful_state_and_fresh_wco() -> None:
    workflow = AutoXYZCalibrationWorkflow(CalibrationPlateDefinition(diameter=20, repeatability_tolerance=.2))
    assert workflow.start(seed=(10, 10, 10), reference_trusted=False, controller_idle=True,
                         spindle_rpm=0, envelope=(290, 170, 40)) is False
    assert workflow.state is CalibrationState.FAILED
    workflow = AutoXYZCalibrationWorkflow()
    assert workflow.start(seed=(10, 10, 10), reference_trusted=True, controller_idle=True,
                         spindle_rpm=0, envelope=(290, 170, 40))
    for point in ((10, 0), (0, 10), (-10, 0), (0, -10)):
        assert workflow.record_contact(PlateContact(*point))
    assert workflow.state is CalibrationState.FITTED
    assert workflow.complete_z_touch(2, wco_fresh=False, envelope=(290, 170, 40)) is False
    assert workflow.state is CalibrationState.FAILED


def test_auto_xyz_success_generates_only_intended_offset() -> None:
    workflow = AutoXYZCalibrationWorkflow()
    assert workflow.start(seed=(20, 20, 15), reference_trusted=True, controller_idle=True,
                         spindle_rpm=0, envelope=(290, 170, 40))
    for point in ((20, 10), (10, 20), (20, 30), (30, 20)):
        workflow.record_contact(PlateContact(*point))
    assert workflow.complete_z_touch(3, wco_fresh=True, envelope=(290, 170, 40))
    assert workflow.state is CalibrationState.COMPLETE
    assert workflow.result is not None
    assert workflow.result.center == pytest.approx((20, 20))
    assert workflow.commands[-2] == "G10 L20 P1 X0 Y0 Z0"


def test_virtual_controller_homing_pins_and_estop_are_fail_closed() -> None:
    controller = VirtualGrblController()
    profile = HomingLimitProfile.default_3018("twin")
    controller.configure_homing(profile)
    controller.receive(b"$22=1\n")
    assert controller.drain()[-1] == "ok"
    controller.set_limit_input("X", True, now_ns=0)
    controller.set_limit_input("X", True, now_ns=5_000_000)
    controller.receive(b"$H\n")
    assert controller.drain()[-1] == "ok"
    assert controller.plant.machine_position == (0.0, 0.0, 0.0)
    controller.configure_estop(EStopDefinition(mode=EStopMode.RESET_ONLY, reset_pin="R"))
    assert controller.inject_estop(reset_asserted=True)
    controller.receive(b"G0 X1\n")
    assert controller.drain()[-1] == "ALARM:1"
    controller.release_estop()
    assert not controller.acknowledge_estop(reference_trusted=False)
    controller.receive(b"$X\n")
    assert controller.drain()[-1] == "ok"
    assert controller.acknowledge_estop(reference_trusted=True)
