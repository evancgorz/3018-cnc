"""Public-boundary digital-twin acceptance scenarios.

These scenarios intentionally drive ``ApplicationController`` and its normal
loopback ``TcpGrblConnection``.  They are not a second plant oracle: the
backend and independent supervisor remain the only motion and safety owners.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import time
from typing import Callable

from ..application.controller import ApplicationController
from ..grbl import Position
from .models import SimulationWorkpiece


@dataclass(frozen=True)
class PublicCollisionLifecycleResult:
    passed: bool
    startup_hazard_count: int
    incident_count: int
    incident_kinds: tuple[str, ...]
    final_job_state: str
    work_offset: Position | None
    trace_path: str
    physical_factory_calls: int
    cleanup_complete: bool
    failure: str = ""


def _pump(controller: ApplicationController, predicate: Callable[[], bool], *, timeout: float = 8.0) -> None:
    """Run the normal twin poll and TCP response path until a state edge."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        controller.poll_simulation()
        events = controller.transport_events()
        while not events.empty():
            controller.handle_transport_response(events.get_nowait().text)
        if predicate():
            return
        if controller.connected:
            controller.request_status()
        time.sleep(0.01)
    raise TimeoutError("digital-twin public scenario did not reach its expected state")


def run_public_collision_lifecycle(root: Path, evidence_path: Path) -> PublicCollisionLifecycleResult:
    """Exercise connect through cleanup using only production app boundaries."""
    physical_factory_calls = 0

    def forbidden_factory():
        nonlocal physical_factory_calls
        physical_factory_calls += 1
        raise AssertionError("physical transport factory was called by the twin scenario")

    controller = ApplicationController(root, usb_factory=forbidden_factory, wifi_factory=forbidden_factory)
    runtime = None
    startup_hazard_count = 0
    incident_count = 0
    incident_kinds: tuple[str, ...] = ()
    final_job_state = ""
    final_work_offset: Position | None = None
    failure = ""
    cleanup_complete = False
    try:
        # Keep the fixture bounded for a deterministic acceptance run while
        # retaining the real collision-only STEP provenance/path.
        configured_workpiece = SimulationWorkpiece(stock_width=8.0, stock_height=8.0, stock_thickness=5.0)
        controller.save_simulation_settings(type(controller.simulation_settings)(
            controller.simulation_settings.schema_version,
            "realtime",
            configured_workpiece,
            controller.simulation_settings.profile,
        ))
        configured = controller.configure_simulation("realtime", "Collision-only STEP")
        if not configured.accepted:
            raise RuntimeError(configured.message)
        outcome = controller.connect_simulation()
        if not outcome.accepted:
            raise RuntimeError(outcome.message)
        runtime = controller.simulation_runtime
        assert runtime is not None
        _pump(controller, lambda: controller.status is not None and controller.status.state == "Idle")
        # A boot/setup pose is not a motion transition and must never create an
        # incident merely because a stock fixture is present.
        _pump(controller, lambda: True, timeout=0.15)
        startup_hazard_count = len(runtime.hazards)
        if startup_hazard_count:
            raise AssertionError(f"startup produced {startup_hazard_count} hazard(s)")
        controller.record_simulation_event("initial_idle", {"state": controller.status.state})

        if not controller.establish_reference().accepted:
            raise AssertionError("reference establishment was rejected")
        controller.record_simulation_event("reference_established")
        if not controller.move_to(Position(0.0, 0.0, 30.0), 600.0).accepted:
            raise AssertionError("safe-Z move was rejected")
        _pump(controller, lambda: controller.status is not None and controller.status.state == "Idle" and controller.machine_position is not None and controller.machine_position.z == 30.0)
        controller.record_simulation_event("safe_z", {"machine_z": 30.0})

        if not controller.set_work_zero("XYZ").accepted:
            raise AssertionError("work-zero request was rejected")
        _pump(controller, lambda: controller.work_zero_confirmed)
        if controller.work_offset != Position(0.0, 0.0, 30.0):
            raise AssertionError(f"unexpected WCO {controller.work_offset}")
        controller.record_simulation_event("work_zero_confirmed", {"wco": controller.work_offset.__dict__})

        # This generated collision-only program descends from work-Z +5 to -2
        # at the work origin.  With WCO Z=30 it fits the machine envelope and
        # enters the stock exactly once with the spindle off.
        controller.load_generated("G90 G21\nG0 Z5\nG1 Z-2 F300\n", "collision-only.step.gcode")
        fits, reason = controller.preflight()
        if not fits:
            raise AssertionError(reason)
        if not controller.start_job().accepted:
            raise AssertionError("collision-only job was rejected")
        controller.record_simulation_event("collision_job_started")
        _pump(controller, lambda: bool(runtime.hazards) and controller.job_state == "failed", timeout=12.0)
        incident_count = len(runtime.hazards)
        incident_kinds = tuple(hazard.kind.value for hazard in runtime.hazards)
        if incident_count != 1:
            raise AssertionError(f"expected one first-contact incident, got {incident_count}: {incident_kinds}")
        first_count = incident_count
        # Give the live producer enough time to emit several snapshots.  The
        # active episode must remain one bounded incident, not a timestamp flood.
        time.sleep(0.15)
        controller.poll_simulation()
        if len(runtime.hazards) != first_count:
            raise AssertionError("continuous contact produced duplicate incidents")
        controller.record_simulation_event("first_contact_interlock", {"kind": incident_kinds[0]})
        controller.record_simulation_event("evidence_exported", {"path": evidence_path.name})
        controller.export_simulation_trace(evidence_path)
        if not evidence_path.exists() or not evidence_path.with_suffix(".md").exists():
            raise AssertionError("simulation evidence export did not produce both artifacts")
        final_job_state = controller.job_state
        final_work_offset = controller.work_offset
    except Exception as exc:
        failure = str(exc)
        if runtime is not None:
            failure += f"; status={controller.status.state if controller.status else None}; job={controller.job_state}; hazards={[(hazard.kind.value, hazard.source, hazard.message) for hazard in runtime.hazards[:12]]}; supervisor_exit={runtime.supervisor.exitcode if runtime.supervisor is not None else None}; healthy={runtime.supervisor_healthy}"
        incident_count = len(runtime.hazards) if runtime is not None else 0
        incident_kinds = tuple(hazard.kind.value for hazard in runtime.hazards) if runtime is not None else ()
    finally:
        owned = runtime
        try:
            controller.disconnect("Public headless scenario complete")
        finally:
            controller.close()
        cleanup_complete = bool(
            owned is None or (
                not owned.started
                and owned.backend is None
                and owned.supervisor is None
                and owned.endpoint is None
            )
        )
        if owned is not None and evidence_path.exists():
            # Include the terminal runtime_stopped marker after normal
            # disconnect while retaining the public export path above.
            owned.trace.export_json(evidence_path)
            owned.trace.export_markdown(evidence_path.with_suffix(".md"), title="Digital twin lifecycle evidence")

    return PublicCollisionLifecycleResult(
        passed=not failure and startup_hazard_count == 0 and cleanup_complete and physical_factory_calls == 0,
        startup_hazard_count=startup_hazard_count,
        incident_count=incident_count,
        incident_kinds=incident_kinds,
        final_job_state=final_job_state,
        work_offset=final_work_offset,
        trace_path=str(evidence_path),
        physical_factory_calls=physical_factory_calls,
        cleanup_complete=cleanup_complete,
        failure=failure,
    )
