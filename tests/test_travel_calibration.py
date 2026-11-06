from __future__ import annotations

from dataclasses import replace

from ttc3018_control.application.machine_session import MachineSession
from ttc3018_control.application.travel_calibration_service import (
    TravelCalibrationOptions,
    TravelCalibrationService,
    TravelCalibrationState,
)
from ttc3018_control.grbl import GrblStatus, Position
from ttc3018_control.machine_config import AxisDefinition, AxisEnd, MachineDefinition, SwitchMode
from ttc3018_control.machine_state import MachineProfile


def _definition() -> MachineDefinition:
    machine = MachineDefinition.legacy_3018(
        profile=MachineProfile("Test", 100.0, 80.0, 40.0, 30.0)
    )
    return replace(machine, axes={
        "X": AxisDefinition(switch_mode=SwitchMode.SINGLE, switch_end=AxisEnd.MIN, input_pin="X1"),
        "Y": AxisDefinition(switch_mode=SwitchMode.SINGLE, switch_end=AxisEnd.MIN, input_pin="Y1"),
        "Z": AxisDefinition(switch_mode=SwitchMode.SINGLE, switch_end=AxisEnd.MAX, input_pin="Z1"),
    })


def _service():
    profile = MachineProfile("Test", 100.0, 80.0, 40.0, 30.0)
    session = MachineSession(profile=profile)
    session.update_status(GrblStatus("Idle", machine_position=Position(0.0, 0.0, 0.0), spindle=0.0))
    lines: list[bytes] = []
    realtime: list[bytes] = []
    service = TravelCalibrationService(session, lines.append, realtime.append)
    return service, session, lines, realtime


def test_travel_calibration_preflight_is_fail_closed() -> None:
    service, _session, lines, _realtime = _service()
    result = service.start(
        _definition(), TravelCalibrationOptions(), connected=False,
        status_fresh=True, spindle_off=True, homing_inputs_safe=True,
    )
    assert not result.accepted
    assert not lines
    hard_limit_definition = replace(_definition(), axes={
        axis: replace(item, hard_limit=True) for axis, item in _definition().axes.items()
    })
    result = service.start(
        hard_limit_definition, TravelCalibrationOptions(), connected=True,
        status_fresh=True, spindle_off=True, homing_inputs_safe=True,
    )
    assert not result.accepted
    assert "hard-limit" in result.message


def test_travel_calibration_checks_settings_then_starts_home_and_abort_invalidates_trust() -> None:
    service, session, lines, realtime = _service()
    result = service.start(
        _definition(), TravelCalibrationOptions(), connected=True,
        status_fresh=True, spindle_off=True, homing_inputs_safe=True,
    )
    assert result.accepted
    assert service.state is TravelCalibrationState.SETTINGS
    assert lines == [b"$$\n"]
    for response in ("$20=0", "$27=1", "$130=100", "$131=80", "$132=40", "ok"):
        assert service.handle_response(response)
    assert service.state is TravelCalibrationState.HOMING
    assert lines[-1] == b"$H\n"
    session.envelope.establish(Position(0.0, 0.0, 0.0), session.profile)
    aborted = service.abort()
    assert aborted.accepted
    assert realtime[-1] == b"\x18"
    assert not session.envelope.trusted


def test_travel_calibration_results_are_staged_until_ready() -> None:
    service, _session, _lines, _realtime = _service()
    service.results = {"X": 98.5, "Y": 78.25, "Z": 39.1}
    assert not service.can_accept
    service.state = TravelCalibrationState.READY
    assert service.can_accept
    snapshot = service.snapshot()
    assert snapshot["results"] == service.results
    assert snapshot["can_accept"] is True


def test_travel_calibration_options_bound_crash_search() -> None:
    for options in (
        TravelCalibrationOptions(increment_mm=0.5),
        TravelCalibrationOptions(max_overshoot_mm=101.0),
        TravelCalibrationOptions(search_feed=301.0),
    ):
        try:
            options.validate()
        except ValueError:
            pass
        else:
            raise AssertionError("unsafe calibration options must be rejected")


def test_travel_calibration_detects_repeats_and_validates_all_axes() -> None:
    service, _session, lines, _realtime = _service()
    assert service.start(
        _definition(), TravelCalibrationOptions(increment_mm=10.0, max_overshoot_mm=30.0),
        connected=True, status_fresh=True, spindle_off=True, homing_inputs_safe=True,
    ).accepted
    actual = {"X": 95.0, "Y": 75.0, "Z": 35.0}
    handled = 0
    while service.state not in {TravelCalibrationState.READY, TravelCalibrationState.FAILED}:
        assert handled < 250
        command = lines[handled]
        handled += 1
        if command == b"$$\n":
            for response in ("$20=0", "$27=1", "$130=100", "$131=80", "$132=40", "ok"):
                service.handle_response(response)
            continue
        if command == b"$H\n":
            service.handle_response("ok")
            service.observe_status(GrblStatus("Idle", machine_position=Position(0.0, 0.0, 0.0), spindle=0.0))
            continue
        service.handle_response("ok")
        axis = service.axis
        if "return" in service.phase:
            candidate = 0.0 if service.phase == "baseline_return" else service._candidate
            lost = max(0.0, candidate - actual[axis])
            sign = service._away_sign()
            trigger = sign * lost
            released = Position(trigger, 0, 0) if axis == "X" else Position(0, trigger, 0) if axis == "Y" else Position(0, 0, trigger)
            service.observe_status(GrblStatus("Jog", machine_position=released, pins="", spindle=0.0))
            service.observe_status(GrblStatus("Jog", machine_position=released, pins=axis, spindle=0.0))
            service.observe_status(GrblStatus("Idle", machine_position=released, pins=axis, spindle=0.0))
        else:
            service.observe_status(GrblStatus("Jog", machine_position=Position(0, 0, 0), spindle=0.0))
            service.observe_status(GrblStatus("Idle", machine_position=Position(0, 0, 0), spindle=0.0))

    assert service.state is TravelCalibrationState.READY, service.failure_reason
    assert service.results == actual
    assert service.can_accept
