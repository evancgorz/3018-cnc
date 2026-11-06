"""Pure guided-operator projection used by the Qt shell.

The projection is intentionally Qt-, transport-, and motion-free. It turns a
snapshot of immutable session facts into the canonical operator workflow so
that presentation code cannot accidentally make a safety decision by checking
a convenient flag.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..machine_config import MachineDefinition, ProbeKind, SwitchMode


GUIDED_STEP_KEYS = ("configure", "connect", "reference", "work_zero", "prepare_job", "review", "run")
GUIDED_STEP_NAMES = ("Configure", "Connect", "Home", "Work Zero", "Prepare Job", "Review", "Run")


@dataclass(frozen=True)
class WorkflowObservation:
    """Read-only facts needed to project the guided operator flow."""

    machine_definition: MachineDefinition | None = None
    connected: bool = False
    controller_state: str = "Unknown"
    simulation_active: bool = False
    supervision_healthy: bool = True
    fresh_status: bool = False
    homing_inputs_safe: bool = True
    spindle_off: bool = True
    job_spindle_off_confirmed: bool = False
    reference_trusted: bool = False
    work_zero_confirmed: bool = False
    job_loaded: bool = False
    job_active: bool = False
    z_plate_status: str = "disabled"
    simulation_plate_commissioned: bool = False
    auto_xyz_state: str = "idle"
    auto_xyz_wco_confirmed: bool = False
    hazard: bool = False
    estop: bool = False
    active_operation: bool = False
    review_acknowledged: bool = False
    profile_valid: bool | None = None
    job_preflight_ok: bool = True


@dataclass(frozen=True)
class StepProjection:
    """Stable QML-friendly description of one guided step."""

    key: str
    name: str
    state: str
    reason: str
    action: str
    selectable: bool = False
    continuable: bool = False
    depends_on: str | None = None

    @property
    def available(self) -> bool:
        return self.selectable

    def as_dict(self) -> dict[str, Any]:
        return {"key": self.key, "name": self.name, "state": self.state, "reason": self.reason,
                "action": self.action, "selectable": self.selectable, "continuable": self.continuable,
                "available": self.selectable, "depends_on": self.depends_on}


@dataclass(frozen=True)
class WorkZeroMethodProjection:
    key: str
    label: str
    state: str
    available: bool
    reason: str
    action: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"key": self.key, "label": self.label, "state": self.state, "available": self.available,
                "reason": self.reason, "action": self.action}


@dataclass(frozen=True)
class SetupWarning:
    key: str
    title: str
    reason: str
    action: str
    severity: str = "warning"

    def as_dict(self) -> dict[str, str]:
        return {"key": self.key, "title": self.title, "reason": self.reason, "action": self.action,
                "severity": self.severity}


@dataclass(frozen=True)
class WorkflowProjection:
    steps: tuple[StepProjection, ...]
    reference_mode: str
    work_zero_methods: tuple[WorkZeroMethodProjection, ...]
    setup_warnings: tuple[SetupWarning, ...]
    next_action: str
    reason: str

    @property
    def ready(self) -> bool:
        return all(step.state == "complete" for step in self.steps)

    @property
    def earliest_incomplete(self) -> int:
        return next((i for i, step in enumerate(self.steps) if step.state != "complete"), len(self.steps) - 1)

    def as_dict(self) -> dict[str, Any]:
        return {"steps": [step.as_dict() for step in self.steps], "reference_mode": self.reference_mode,
                "work_zero_methods": [method.as_dict() for method in self.work_zero_methods],
                "setup_warnings": [warning.as_dict() for warning in self.setup_warnings],
                "next_action": self.next_action, "reason": self.reason, "ready": self.ready,
                "earliest_incomplete": self.earliest_incomplete}


def _status(observation: WorkflowObservation) -> str:
    return observation.controller_state.strip().lower()


def project_workflow(observation: WorkflowObservation) -> WorkflowProjection:
    """Project the complete guided flow from one immutable observation."""
    definition = observation.machine_definition
    axes = definition.axes if definition is not None else {}
    switched = {axis for axis in "XYZ" if axes.get(axis) and axes[axis].switch_mode is not SwitchMode.NONE}
    # A machine reference is now established only by a complete homing cycle.
    # Partial or missing switch declarations must never turn into a manual
    # position-trust fallback in the operator workflow.
    reference_mode = "guarded homing" if len(switched) == 3 else "homing required"

    warnings: list[SetupWarning] = []
    profile_valid = observation.profile_valid
    if profile_valid is None and definition is not None:
        try:
            definition.to_profile().validate()
            profile_valid = True
        except (TypeError, ValueError):
            profile_valid = False
    if definition is None or not profile_valid:
        warnings.append(SetupWarning("machine", "Machine profile unavailable or invalid",
                                     "Select a valid machine profile before connecting.", "Open Configure", "error"))
    if len(switched) in (1, 2):
        axes_text = ", ".join(sorted(switched)) or "none"
        warnings.append(SetupWarning("partial_switches", "Partial homing declaration",
                                     f"Only {axes_text} switch axes are declared; full homing is not claimed.", "Open Configure"))
    elif not switched:
        warnings.append(SetupWarning(
            "homing_not_configured", "Homing switches not configured",
            "Configure and commission X, Y, and Z homing switches before establishing machine reference.",
            "Open Configure", "error",
        ))
    probes = {probe.kind: probe for probe in (definition.probes if definition else ()) if probe.enabled}
    for kind, label in ((ProbeKind.FIXED_TOOL_SETTER, "Fixed tool setter"),
                        (ProbeKind.MOVABLE_XYZ, "Movable physical XYZ"), (ProbeKind.FIXED_XYZ, "Fixed XYZ")):
        if kind in probes:
            warnings.append(SetupWarning(kind.value, label, "Configured — workflow not available", "Open Configure"))
    if not observation.supervision_healthy:
        warnings.append(SetupWarning("supervision", "Safety supervision unavailable",
                                     "The session is fail-closed until the supervisor is healthy.", "Reconnect", "error"))

    status = _status(observation)
    safety_ok = bool(observation.connected and observation.supervision_healthy and observation.fresh_status
                     and status == "idle" and not observation.hazard and not observation.estop
                     and not observation.active_operation and not observation.job_active)
    homing_ok = bool(observation.connected and observation.supervision_healthy and observation.fresh_status
                     and status in {"idle", "alarm"} and observation.homing_inputs_safe
                     and observation.spindle_off and not observation.hazard and not observation.estop
                     and not observation.active_operation and not observation.job_active)

    configure_state = "complete" if definition is not None and profile_valid else "required"
    configure_reason = "Machine profile is valid. Review configuration periodically." if configure_state == "complete" else "Select and validate a machine profile before connecting."
    configure_action = "Review configuration" if configure_state == "complete" else "Open Configure"
    connect_state = "complete" if observation.connected else "required"
    connect_reason = "Connected to the controller." if observation.connected else "Choose a controller or the loopback digital twin."

    if not observation.connected:
        safety_state, safety_reason = "blocked", "Connect before checking safety."
    elif safety_ok:
        safety_state, safety_reason = "complete", "Fresh Idle state is safe for guarded actions."
    elif observation.active_operation or observation.job_active:
        safety_state, safety_reason = "working", "An operation or job is active; monitor it from Run."
    else:
        safety_state, safety_reason = "blocked", "Safety requires a fresh Idle controller, healthy supervisor, no active operation or job, and clear hazards, limits, and E-stop."

    if not observation.connected:
        reference_state, reference_reason, reference_action = "blocked", "Connect before establishing reference.", "Connect"
    elif observation.active_operation or observation.job_active:
        reference_state, reference_reason, reference_action = "working", "A machine operation is active; safety remains enforced by the backend.", "Monitor run"
    elif observation.reference_trusted and safety_ok and observation.homing_inputs_safe:
        reference_state, reference_reason, reference_action = "complete", "Machine reference is trusted for this profile.", ""
    elif not homing_ok:
        if not observation.fresh_status or status not in {"idle", "alarm"}:
            reason = "Wait for fresh GRBL Idle or Alarm status before homing."
        elif not observation.homing_inputs_safe:
            reason = "Release active homing inputs or resolve their polarity before homing."
        elif not observation.spindle_off:
            reason = "Turn off the spindle before homing."
        else:
            reason = "Resolve the active safety or machine operation before homing."
        reference_state, reference_reason, reference_action = "blocked", reason, "Resolve homing block"
    elif status == "alarm":
        if len(switched) == 3:
            reference_state, reference_reason, reference_action = "required", "GRBL reports Alarm; run guarded homing to restore a trusted reference.", "Home machine"
        else:
            reference_state, reference_reason, reference_action = "blocked", "Configure and commission X, Y, and Z homing switches before homing; a trusted reference cannot be established yet.", "Open Configure"
    elif observation.reference_trusted:
        reference_state, reference_reason, reference_action = "complete", "Machine reference is trusted for this profile.", ""
    elif len(switched) == 3:
        reference_state, reference_reason, reference_action = "required", "Home the machine to establish a trusted reference.", "Home machine"
    else:
        reference_state, reference_reason, reference_action = "blocked", "Configure and commission X, Y, and Z homing switches before homing; a trusted reference cannot be established yet.", "Open Configure"

    manual_available = safety_ok and observation.reference_trusted
    manual_blocked_reason = "Home the machine to establish a trusted reference before setting work zero." if safety_ok and not observation.reference_trusted else "Requires a connected, fresh, Idle controller with clear safety state."
    methods = [WorkZeroMethodProjection(key, label, "available" if manual_available else "blocked", manual_available,
                                         text if manual_available else manual_blocked_reason, action)
               for key, label, text, action in (("manual_x", "Manual X", "Jog to the X datum and set X zero.", "Zero X"),
                                                ("manual_y", "Manual Y", "Jog to the Y datum and set Y zero.", "Zero Y"),
                                                ("manual_z", "Manual Z", "Jog to the Z datum and set Z zero.", "Zero Z"),
                                                ("manual_xyz", "Manual XYZ", "Set all work-zero axes from guarded jog controls.", "Zero XYZ"))]
    plate_status = observation.z_plate_status
    plate_available = bool(safety_ok and observation.reference_trusted and plate_status == "ready")
    plate_reason = {"disabled": "Movable Z touch plate is not configured.", "needs_input_test": "Run the no-motion probe-input test in Configure.",
                    "needs_commissioning": "Complete supervised plate commissioning in Configure.", "stale": "Configuration changed; repeat plate verification.",
                    "remove_plate": "Remove the plate and clip before continuing.", "probing": "A Z-probe cycle is already running.",
                    "commissioning": "A supervised Z-plate commissioning sample is already running.",
                    "ready": "Ready to probe Z at the current X/Y position; X/Y work zero is not required."}.get(plate_status, "Movable Z touch plate is unavailable.")
    if not observation.connected:
        plate_reason = "Connect before probing work Z."
    elif not observation.fresh_status or status != "idle":
        plate_reason = "Wait for a fresh Idle controller before probing work Z."
    elif observation.active_operation or observation.job_active:
        plate_reason = "Finish the active machine operation before probing work Z."
    elif not observation.supervision_healthy or observation.hazard or observation.estop:
        plate_reason = "Resolve the current safety condition before probing work Z."
    elif not observation.reference_trusted:
        plate_reason = "Home the machine to establish a trusted reference before probing work Z."
    methods.append(WorkZeroMethodProjection("movable_z_plate", "Movable Z touch plate", "available" if plate_available else "blocked",
                                            plate_available, plate_reason, "Probe work Z"))

    auto_state = str(observation.auto_xyz_state or "idle").lower()
    auto_complete = auto_state == "complete" and observation.auto_xyz_wco_confirmed
    auto_active = auto_state in {"searching", "fitted", "z_touch", "active", "running"}
    auto_failed = auto_state == "failed"
    auto_available = bool(observation.simulation_active and observation.simulation_plate_commissioned and safety_ok
                          and observation.reference_trusted and not auto_active and not auto_complete and not auto_failed and auto_state != "complete")
    if auto_state == "complete" and not observation.auto_xyz_wco_confirmed:
        auto_method_state, auto_reason, auto_action = "warning", "Calibration motions completed, but no fresh matching WCO was observed; do not claim work zero.", "Review Work Zero"
    elif auto_complete:
        auto_method_state, auto_reason, auto_action = "complete", "Auto XYZ complete with a fresh matching WCO report.", ""
    elif auto_active:
        auto_method_state, auto_reason, auto_action = "working", "Auto XYZ is active; wait for its guarded transaction to finish.", "Abort Auto XYZ"
    elif auto_failed:
        auto_method_state, auto_reason, auto_action = "warning", "Auto XYZ failed; review the failure and recover before retrying.", "Open Configure"
    elif not observation.simulation_active:
        auto_method_state, auto_reason, auto_action = "blocked", "Auto XYZ is available only on the digital twin until a physical workflow is commissioned.", "Open Configure"
    elif not observation.simulation_plate_commissioned:
        auto_method_state, auto_reason, auto_action = "blocked", "Commission the digital-twin corner plate first.", "Open Configure"
    elif not safety_ok or not observation.reference_trusted:
        auto_method_state, auto_reason, auto_action = "blocked", "Requires fresh Idle status, trusted reference, clear safety, and no active job.", "Review Safety"
    else:
        auto_method_state, auto_reason, auto_action = "available", "Ready for bounded Auto XYZ.", "Start Auto XYZ"
    methods.append(WorkZeroMethodProjection("auto_xyz", "Auto XYZ corner plate", auto_method_state, auto_available, auto_reason, auto_action))

    if observation.z_plate_status == "remove_plate":
        zero_state, zero_reason, zero_action = "blocked", "Remove the touch plate and clip, then acknowledge removal before continuing.", "Acknowledge plate removal"
    elif observation.work_zero_confirmed:
        zero_state, zero_reason, zero_action = "complete", "A confirmed work zero is active.", ""
    elif not observation.connected:
        zero_state, zero_reason, zero_action = "blocked", "Connect before setting work zero.", "Connect"
    elif not observation.reference_trusted:
        zero_state, zero_reason, zero_action = "blocked", "Home the machine to establish a trusted reference before setting work zero.", "Home machine"
    else:
        zero_state, zero_reason, zero_action = "required", "Choose a visible work-zero method below.", "Set work zero"

    if not observation.job_loaded:
        prepare_state, prepare_reason, prepare_action = "required", "Load or create a validated metric job.", "Prepare a job"
    elif not observation.job_preflight_ok:
        prepare_state, prepare_reason, prepare_action = "blocked", "The loaded job failed validation or envelope checks.", "Review job"
    else:
        prepare_state, prepare_reason, prepare_action = "complete", "A validated job is loaded.", ""
    if not observation.job_loaded:
        review_state, review_reason, review_action = "blocked", "Prepare and validate a job before reviewing it.", "Prepare a job"
    elif not observation.job_preflight_ok:
        review_state, review_reason, review_action = "blocked", "Resolve the job validation or envelope failure first.", "Review job"
    elif observation.review_acknowledged:
        review_state, review_reason, review_action = "complete", "The current validated path has been reviewed.", ""
    else:
        review_state, review_reason, review_action = "required", "Inspect the path and acknowledge this session's review.", "Acknowledge review"
    if observation.job_active:
        run_state, run_reason, run_action = "working", "The job is active; monitor progress and hazards here.", "Monitor run"
    elif not observation.review_acknowledged:
        run_state, run_reason, run_action = "blocked", "Acknowledge the current Review before starting a job.", "Review"
    elif not safety_ok:
        run_state, run_reason, run_action = "blocked", "Run requires a fresh safe Idle state and healthy supervision.", "Review Safety"
    elif not observation.job_spindle_off_confirmed:
        run_state, run_reason, run_action = "blocked", "Wait for a fresh report confirming the spindle is off before starting a job.", "Turn spindle off"
    else:
        run_state, run_reason, run_action = "required", "Complete physical preflight, then start the guarded job.", "Start job"

    raw_steps = [("configure", "Configure", configure_state, configure_reason, configure_action),
                 ("connect", "Connect", connect_state, connect_reason, "Connect" if not observation.connected else ""),
                 ("reference", "Home", reference_state, reference_reason, reference_action),
                 ("work_zero", "Work Zero", zero_state, zero_reason, zero_action),
                 ("prepare_job", "Prepare Job", prepare_state, prepare_reason, prepare_action),
                 ("review", "Review", review_state, review_reason, review_action),
                 ("run", "Run", run_state, run_reason, run_action)]
    # Facts are intentionally evaluated in a strict chain.  A later local fact
    # (for example a preloaded job or stale trusted WCO) cannot make that step
    # look complete while an earlier session/safety prerequisite is missing.
    prerequisites = (None, "configure", "connect", "reference", "work_zero", "prepare_job", "review")
    gated_steps: list[tuple[str, str, str, str, str, str | None]] = []
    prior_complete = True
    for index, (key, name, state, reason, action) in enumerate(raw_steps):
        dependency = prerequisites[index]
        if dependency is not None and not prior_complete and not (index == 6 and observation.job_active):
            previous = GUIDED_STEP_NAMES[index - 1]
            # Keep the local fact in the reason so an operator understands why
            # recovery is needed, while the displayed state remains blocked.
            reason = f"{previous} is not complete; {gated_steps[index - 1][3]}"
            action = previous
            state = "blocked"
        gated_steps.append((key, name, state, reason, action, dependency))
        prior_complete = prior_complete and state == "complete"
    first_incomplete = next((i for i, item in enumerate(gated_steps) if item[2] != "complete"), len(gated_steps) - 1)
    steps: list[StepProjection] = []
    for index, (key, name, state, reason, action, dependency) in enumerate(gated_steps):
        # Reached steps are revisitable, but only through the contiguous safe
        # prefix.  The active Run exception keeps monitoring/abort reachable.
        selectable = index <= first_incomplete or (index == 6 and observation.job_active)
        continuable = bool(state == "complete")
        if index == 0:
            continuable = bool(profile_valid)
        elif index == 1:
            continuable = observation.connected
        elif index == 2:
            continuable = observation.reference_trusted
        elif index == 3:
            continuable = observation.work_zero_confirmed
        elif index == 4:
            continuable = observation.job_loaded and observation.job_preflight_ok
        elif index == 5:
            continuable = observation.review_acknowledged
        elif index == 6:
            # Run has no forward step.  Active jobs are selectable for
            # monitoring/abort, but Continue never authorizes a start.
            continuable = False
        if state == "blocked" and dependency is not None and not (index == 6 and observation.job_active):
            continuable = False
        if index > first_incomplete and state != "blocked" and not (index == 6 and observation.job_active):
            reason = f"Complete {GUIDED_STEP_NAMES[index - 1]} first."
            action = GUIDED_STEP_NAMES[index - 1]
            selectable = False
            continuable = False
        steps.append(StepProjection(key, name, state, reason, action, selectable, continuable, dependency))
    first = steps[first_incomplete]
    return WorkflowProjection(tuple(steps), reference_mode, tuple(methods), tuple(warnings), first.action or first.name, first.reason)


WorkflowState = WorkflowProjection
WorkflowInputs = WorkflowObservation
project_operator_workflow = project_workflow
build_workflow_projection = project_workflow
