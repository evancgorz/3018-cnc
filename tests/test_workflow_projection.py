from dataclasses import replace

import pytest

from ttc3018_control.application.workflow_projection import WorkflowObservation, project_workflow
from ttc3018_control.machine_config import AxisDefinition, MachineDefinition, ProbeDefinition, ProbeKind, SwitchMode


def _machine(*, switches=(), probes=()):
    axes = {axis: AxisDefinition() for axis in "XYZ"}
    for axis in switches:
        axes[axis] = replace(axes[axis], switch_mode=SwitchMode.SINGLE, input_pin=axis)
    return replace(MachineDefinition.legacy_3018(), axes=axes, probes=tuple(probes))


def _obs(**kwargs):
    values = {"machine_definition": _machine()}
    values.update(kwargs)
    return WorkflowObservation(**values)


@pytest.mark.parametrize(
    ("switches", "mode", "state"),
    [
        ((), "homing required", "blocked"),
        (("X", "Y", "Z"), "guarded homing", "required"),
        (("X",), "homing required", "blocked"),
    ],
)
def test_reference_projection_is_honest_for_switch_declarations(switches, mode, state):
    projection = project_workflow(_obs(machine_definition=_machine(switches=switches), connected=True, fresh_status=True, controller_state="Idle"))
    assert projection.reference_mode == mode
    reference = next(item for item in projection.steps if item.key == "reference")
    assert reference.state == state
    if switches != ("X", "Y", "Z"):
        assert any(item.key == "partial_switches" for item in projection.setup_warnings) is (bool(switches))
        assert "manual" not in projection.reference_mode
        assert "manual" not in reference.reason.lower()


@pytest.mark.parametrize("status", ["disabled", "needs_input_test", "needs_commissioning", "stale", "probing", "commissioning", "remove_plate", "ready"])
def test_movable_z_status_is_visible_and_gated(status):
    projection = project_workflow(_obs(
        connected=True, controller_state="Idle", fresh_status=True,
        reference_trusted=True, work_zero_confirmed=False, z_plate_status=status,
    ))
    method = next(item for item in projection.work_zero_methods if item.key == "movable_z_plate")
    assert method.available is (status == "ready")
    assert method.reason
    if status == "ready":
        assert "not required" in method.reason


def test_movable_z_probe_reports_current_prerequisites_without_xy_zero():
    projection = project_workflow(_obs(
        connected=True, controller_state="Idle", fresh_status=True,
        reference_trusted=True, work_zero_confirmed=False, z_plate_status="ready",
    ))
    method = next(item for item in projection.work_zero_methods if item.key == "movable_z_plate")

    assert method.available
    assert method.action == "Probe work Z"
    assert "current X/Y position" in method.reason


def test_work_zero_methods_keep_manual_and_auto_peer_routes():
    projection = project_workflow(_obs(
        connected=True, controller_state="Idle", fresh_status=True, reference_trusted=True,
        work_zero_confirmed=False, simulation_active=True, simulation_plate_commissioned=True,
    ))
    assert [item.key for item in projection.work_zero_methods] == [
        "manual_x", "manual_y", "manual_z", "manual_xyz", "movable_z_plate", "auto_xyz"
    ]
    assert next(item for item in projection.work_zero_methods if item.key == "auto_xyz").available


def test_guided_projection_has_seven_ordered_steps_and_earliest_safe_selection():
    projection = project_workflow(_obs())
    assert [step.key for step in projection.steps] == [
        "configure", "connect", "reference", "work_zero", "prepare_job", "review", "run"
    ]
    assert projection.earliest_incomplete == 1
    assert projection.steps[0].selectable
    assert projection.steps[2].state == "blocked"
    assert not projection.steps[2].selectable


def test_guided_projection_progression_and_review_acknowledgement():
    projection = project_workflow(_obs(
        connected=True, controller_state="Idle", fresh_status=True,
        reference_trusted=True, work_zero_confirmed=True, job_loaded=True,
        review_acknowledged=False, job_spindle_off_confirmed=True,
    ))
    assert [step.state for step in projection.steps[:5]] == ["complete"] * 5
    assert projection.steps[5].state == "required"
    assert projection.steps[5].continuable is False
    acknowledged = project_workflow(_obs(
        connected=True, controller_state="Idle", fresh_status=True,
        reference_trusted=True, work_zero_confirmed=True, job_loaded=True,
        review_acknowledged=True, job_spindle_off_confirmed=True,
    ))
    assert acknowledged.steps[5].state == "complete"
    assert acknowledged.steps[6].state == "required"


def test_guided_job_start_requires_spindle_off_after_review():
    projection = project_workflow(_obs(
        connected=True, controller_state="Idle", fresh_status=True,
        reference_trusted=True, work_zero_confirmed=True, job_loaded=True,
        review_acknowledged=True, job_spindle_off_confirmed=False,
    ))

    run = projection.steps[6]
    assert run.state == "blocked"
    assert "spindle is off" in run.reason.lower()

    spindle_off = project_workflow(_obs(
        connected=True, controller_state="Idle", fresh_status=True,
        reference_trusted=True, work_zero_confirmed=True, job_loaded=True,
        review_acknowledged=True, job_spindle_off_confirmed=True,
    ))
    assert spindle_off.steps[6].state == "required"


@pytest.mark.parametrize("state", ["Run", "Jog", "Hold", "Home", "Alarm", "Door", "Unknown"])
def test_guided_safety_degradation_locks_future_steps(state):
    projection = project_workflow(_obs(
        connected=True, controller_state=state, fresh_status=True,
        reference_trusted=True, work_zero_confirmed=True, job_loaded=True,
        review_acknowledged=True,
    ))
    assert projection.steps[2].state == "blocked"
    assert all(step.state == "blocked" for step in projection.steps[3:])
    assert all(not step.selectable for step in projection.steps[3:])


def test_preloaded_job_cannot_skip_disconnected_chain():
    projection = project_workflow(_obs(job_loaded=True, reference_trusted=True, work_zero_confirmed=True,
                                       review_acknowledged=True))
    assert projection.steps[1].state == "required"
    assert projection.steps[5].state == "blocked"
    assert not projection.steps[5].selectable
    assert "Connect" in projection.steps[5].reason


def test_lost_reference_blocks_existing_zero_job_and_review_facts():
    projection = project_workflow(_obs(connected=True, controller_state="Idle", fresh_status=True,
                                       reference_trusted=False, work_zero_confirmed=True, job_loaded=True,
                                       review_acknowledged=True))
    assert projection.steps[2].state == "blocked"
    assert projection.steps[2].action == "Open Configure"
    assert all(projection.steps[index].state == "blocked" for index in (3, 4, 5, 6))
    assert all(not projection.steps[index].selectable for index in (3, 4, 5, 6))


def test_active_job_run_remains_reachable_for_monitoring_when_safety_changes():
    projection = project_workflow(_obs(connected=True, controller_state="Run", fresh_status=True,
                                       reference_trusted=True, work_zero_confirmed=True, job_loaded=True,
                                       review_acknowledged=True, job_active=True))
    assert projection.steps[2].state == "working"
    assert projection.steps[6].state == "working"
    assert projection.steps[6].selectable
    assert not projection.steps[6].continuable


def test_failed_job_preflight_blocks_prepare_and_review_chain():
    projection = project_workflow(_obs(connected=True, controller_state="Idle", fresh_status=True,
                                       reference_trusted=True, work_zero_confirmed=True, job_loaded=True,
                                       job_preflight_ok=False))
    assert projection.steps[4].state == "blocked"
    assert projection.steps[5].state == "blocked"
    assert not projection.steps[5].selectable


def test_manual_work_zero_waits_for_trusted_reference():
    projection = project_workflow(_obs(
        machine_definition=_machine(switches=("X", "Y", "Z")),
        connected=True, controller_state="Idle", fresh_status=True, reference_trusted=False,
    ))
    manual = [item for item in projection.work_zero_methods if item.key.startswith("manual_")]
    assert all(not item.available for item in manual)
    assert all("Home the machine" in item.reason for item in manual)
    assert projection.steps[2].action == "Home machine"
    assert "Home" in projection.steps[2].reason


def test_fresh_alarm_keeps_guarded_homing_available_without_unlocking_other_motion():
    projection = project_workflow(_obs(
        machine_definition=_machine(switches=("X", "Y", "Z")),
        connected=True, controller_state="Alarm", fresh_status=True,
        reference_trusted=False,
    ))

    home = projection.steps[2]
    assert home.state == "required"
    assert home.action == "Home machine"
    assert not any(method.available for method in projection.work_zero_methods)
    assert projection.steps[3].state == "blocked"


@pytest.mark.parametrize(
    ("extra", "reason"),
    [
        ({"homing_inputs_safe": False}, "homing inputs"),
        ({"spindle_off": False}, "spindle"),
    ],
)
def test_home_projection_explains_remaining_alarm_home_gates(extra, reason):
    projection = project_workflow(_obs(
        machine_definition=_machine(switches=("X", "Y", "Z")),
        connected=True, controller_state="Alarm", fresh_status=True,
        reference_trusted=False, **extra,
    ))

    home = projection.steps[2]
    assert home.state == "blocked"
    assert reason in home.reason.lower()


def test_unsupported_probe_kinds_are_inert_setup_warnings():
    probes = [ProbeDefinition(kind, enabled=True) for kind in (ProbeKind.FIXED_TOOL_SETTER, ProbeKind.MOVABLE_XYZ, ProbeKind.FIXED_XYZ)]
    projection = project_workflow(_obs(machine_definition=_machine(probes=probes)))
    assert {warning.key for warning in projection.setup_warnings} == {
        "homing_not_configured",
        *(kind.value for kind in (ProbeKind.FIXED_TOOL_SETTER, ProbeKind.MOVABLE_XYZ, ProbeKind.FIXED_XYZ)),
    }
    assert all(method.key not in {kind.value for kind in ProbeKind if kind is not ProbeKind.MOVABLE_Z_PLATE} for method in projection.work_zero_methods)


def test_safety_and_supervision_fail_closed_and_recovery_is_deterministic():
    blocked = project_workflow(_obs(connected=True, controller_state="Idle", fresh_status=True, reference_trusted=True, hazard=True))
    assert all(not method.available for method in blocked.work_zero_methods)
    assert blocked.steps[2].state == "blocked"
    recovered = project_workflow(_obs(connected=True, controller_state="Idle", fresh_status=True, reference_trusted=True, hazard=False))
    assert all(method.available for method in recovered.work_zero_methods if method.key.startswith("manual_"))


@pytest.mark.parametrize("state", ["Run", "Jog", "Hold", "Home", "Door", "Unknown"])
def test_every_non_idle_controller_state_blocks_all_motion_zero_methods(state):
    projection = project_workflow(_obs(
        connected=True, controller_state=state, fresh_status=True, reference_trusted=True,
        work_zero_confirmed=True, simulation_active=True, simulation_plate_commissioned=True,
    ))
    assert all(not method.available for method in projection.work_zero_methods)
    assert projection.steps[2].state == "blocked"


@pytest.mark.parametrize("kwargs", [{"fresh_status": False}, {"active_operation": True}, {"job_active": True}, {"estop": True}, {"hazard": True}, {"supervision_healthy": False}])
def test_idle_motion_zero_methods_require_every_safety_gate(kwargs):
    values = dict(connected=True, controller_state="Idle", fresh_status=True, reference_trusted=True,
                  simulation_active=True, simulation_plate_commissioned=True)
    values.update(kwargs)
    projection = project_workflow(_obs(**values))
    assert all(not method.available for method in projection.work_zero_methods)


@pytest.mark.parametrize("auto_state, wco, expected_state, available", [
    ("idle", False, "available", True),
    ("searching", False, "working", False),
    ("fitted", False, "working", False),
    ("z_touch", False, "working", False),
    ("failed", False, "warning", False),
    ("complete", False, "warning", False),
    ("complete", True, "complete", False),
])
def test_auto_xyz_transaction_and_fresh_wco_are_projected_honestly(auto_state, wco, expected_state, available):
    projection = project_workflow(_obs(
        connected=True, controller_state="Idle", fresh_status=True, reference_trusted=True,
        simulation_active=True, simulation_plate_commissioned=True,
        auto_xyz_state=auto_state, auto_xyz_wco_confirmed=wco,
    ))
    method = next(item for item in projection.work_zero_methods if item.key == "auto_xyz")
    assert method.state == expected_state
    assert method.available is available
    if auto_state == "complete" and not wco:
        assert "fresh" in method.reason.lower()


def test_completion_requires_fresh_wco_and_not_fixture_commissioning_alone():
    projection = project_workflow(_obs(
        connected=True, controller_state="Idle", fresh_status=True, reference_trusted=True,
        simulation_active=True, simulation_plate_commissioned=True, auto_xyz_state="complete",
        auto_xyz_wco_confirmed=False,
    ))
    method = next(item for item in projection.work_zero_methods if item.key == "auto_xyz")
    assert method.state == "warning"
    assert not method.available
    assert "fresh" in method.reason.lower()
