"""Composition root for the Qt-independent TTC 3018 application layer."""

from __future__ import annotations

from .confirmation_facts import meaningful_status_facts

from pathlib import Path
import hashlib
import json
import queue
import secrets
import time
from dataclasses import dataclass, replace
from typing import Callable, Iterable

from ..connection_settings import ConnectionSettings, ConnectionSettingsStore
from ..grbl import GrblStatus, Position, REALTIME_HOLD, REALTIME_JOG_CANCEL, REALTIME_SOFT_RESET, REALTIME_STATUS, make_work_zero, parse_status
from ..machine_state import MachineProfile, ProfileStore
from ..machine_catalog import MachineCatalog, MachineCatalogStore
from ..machine_config import (
    DEFAULT_Z_TOUCH_PLATE_THICKNESS, AxisEnd as MachineAxisEnd, MachineDefinition,
    ProbeDefinition, ProbeKind, SwitchMode, TTC3018_HARDWARE,
)
from ..controller_adapters import Grbl11Adapter, GenericGrblAdapter
from ..work_zero_settings import SavedWorkZero, WorkZeroStore
from ..serial_connection import GrblConnection, available_ports
from ..step_prepare_settings import StepPrepareSettings, StepPrepareSettingsStore
from ..tcp_connection import TcpGrblConnection
from ..simulation.runtime import SimulationRuntime
from ..simulation.safety import (
    AxisEnd as SafetyAxisEnd, AxisSensorDeclaration, CalibrationCommissioningRecord,
    CalibrationPlateDefinition, EStopDefinition, EStopMode, HomingInputInterpretation,
    HomingLimitProfile, SwitchWiring, interpret_pn_transition,
)
from ..simulation.plant import ProbeCornerCircle
from ..simulation.settings import SimulationSettings, SimulationSettingsStore
from ..wifi_discovery import discover_grbl_hosts
from .connection_service import ConnectionOutcome, ConnectionService
from .events import ApplicationEvent, LogEvent, NoticeEvent
from .generation_service import GenerationService
from .job_service import JobService
from .job_provenance import build_job_provenance
from .machine_session import ActionOutcome, MachineSession
from .motion_service import MotionService
from .homing_service import HomingService
from .probing_service import ProbePlan, ProbingService
from .calibration_service import AutoXYZCalibrationService
from .travel_calibration_service import TravelCalibrationOptions, TravelCalibrationService
from .tool_setting_service import ToolSettingService
from .fixture_service import FixtureService
from .ports import ConnectionSettingsStorePort, ProfileStorePort, StepPrepareSettingsStorePort, WorkZeroStorePort
from .state import ApplicationState, ConnectionMode, JobSnapshot, ProgramSnapshot
from .wifi_service import WifiProvisioningService
from ..z_touch_plate import ZTouchPlateRecord, ZTouchPlateStore, ZTouchPlateWorkflow


@dataclass(frozen=True)
class JobStartAuthorization:
    """Single-use authorization bound to one exact reviewed machine state."""

    accepted: bool
    message: str
    token: str = ""


class ApplicationController:
    """Compose application services without importing Qt or presenting UI."""

    STATUS_FRESHNESS_SECONDS = 2.0

    def __init__(
        self,
        root: Path,
        *,
        on_notice: Callable[[str], None] | None = None,
        on_change: Callable[[], None] | None = None,
        on_position_complete: Callable[[], None] | None = None,
        on_ready_to_return: Callable[[], None] | None = None,
        profile_store: ProfileStorePort | None = None,
        connection_store: ConnectionSettingsStorePort | None = None,
        work_zero_store: WorkZeroStorePort | None = None,
        step_prepare_store: StepPrepareSettingsStorePort | None = None,
        usb_factory: Callable[[], object] | None = None,
        wifi_factory: Callable[[], object] | None = None,
        discover_hosts: Callable[[int], Iterable[str]] | None = None,
        usb_ports: Callable[[], list[tuple[str, str]]] | None = None,
        simulation_factory: Callable[[], object] | None = None,
    ) -> None:
        # Resolve once before constructing any store.  A relative root must
        # remain tied to the application instance even if a caller changes
        # the process working directory after composition (as isolated test
        # harnesses commonly do).
        self._root = Path(root).expanduser().resolve()
        root = self._root
        self.machine_catalog_store = MachineCatalogStore(
            root / "config" / "machines.json", root / "config" / "machine-profile.json"
        )
        self.machine_catalog: MachineCatalog | None = None
        self._machine_definition: MachineDefinition | None = None
        self.machine_id: str | None = None
        self.profile_store = profile_store or ProfileStore(root / "config" / "machine-profile.json")
        self.connection_store = connection_store or ConnectionSettingsStore(root / "config" / "connection.json")
        self.work_zero_store = work_zero_store or WorkZeroStore(root / "config" / "work-zero.json")
        self.z_touch_plate_store = ZTouchPlateStore(root / "config" / "z-touch-plates.json")
        self.step_prepare_store = step_prepare_store or StepPrepareSettingsStore(
            root / "config" / "step-prepare.json"
        )
        self.simulation_settings_store = SimulationSettingsStore(root / "config" / "simulation.json")
        try:
            self.simulation_settings = self.simulation_settings_store.load()
        except (OSError, ValueError, TypeError):
            self.simulation_settings = SimulationSettings()
        if profile_store is None:
            try:
                self.machine_catalog = self.machine_catalog_store.load()
                self._machine_definition = self.machine_catalog.selected()
                self.machine_id = self._machine_definition.machine_id
                profile = self._machine_definition.to_profile()
            except (OSError, ValueError, TypeError):
                profile = MachineProfile()
        else:
            try:
                profile = self.profile_store.load()
            except (OSError, ValueError, TypeError):
                profile = MachineProfile()
            self._machine_definition = MachineDefinition.legacy_3018(profile=profile)
            self.machine_id = self._machine_definition.machine_id
        if hasattr(self.work_zero_store, "legacy_machine_id"):
            self.work_zero_store.legacy_machine_id = MachineDefinition.legacy_3018().machine_id
        try:
            settings = self.connection_store.load()
        except (OSError, ValueError, TypeError):
            settings = ConnectionSettings()
        try:
            saved_work_zero = self.work_zero_store.load(self.machine_id)
        except (OSError, ValueError, TypeError):
            saved_work_zero = None
        try:
            z_touch_plate_record = self.z_touch_plate_store.load(self.machine_id)
        except (OSError, ValueError, TypeError):
            z_touch_plate_record = None
        try:
            step_prepare_settings = self.step_prepare_store.load()
        except (OSError, ValueError, TypeError):
            step_prepare_settings = StepPrepareSettings()

        self.session = MachineSession(profile=profile)
        self.adapter = Grbl11Adapter() if self.machine_definition.controller.value == "grbl_1_1" else GenericGrblAdapter()
        self.settings = settings
        self._saved_work_zero = saved_work_zero
        self._physical_saved_work_zero = saved_work_zero
        self._simulation_saved_work_zero: SavedWorkZero | None = None
        self._simulation_physical_saved_work_zero: SavedWorkZero | None = None
        self._z_touch_plate_record = z_touch_plate_record
        self._z_touch_plate = ZTouchPlateWorkflow()
        self._z_probe_pending = False
        self._z_probe_offset_confirmed = False
        self._z_commissioning_pending = False
        self._z_plate_removal_required = False
        self._z_probe_completion = {"state": "idle", "message": "Probe work Z to begin"}
        self._z_probe_completion_context = None
        self._z_probe_descent_ack = False
        self._simulation_plate_definition = CalibrationPlateDefinition()
        self._simulation_plate_record: CalibrationCommissioningRecord | None = None
        self.step_prepare_settings = step_prepare_settings
        self.status: GrblStatus | None = None
        self._last_status_received_at = 0.0
        self._session_generation = 0
        self._status_generation = -1
        self._homing_input_baseline_pins: str | None = None
        self._homing_input_observation = HomingInputInterpretation("unknown", "", reason="No fresh homing-input status has been observed.")
        self.manual_pending_acks = 0
        self._work_zero_request_pending_ack = False
        self._work_zero_expected_offset: Position | None = None
        self._work_zero_expected_axes = ""
        self._events: queue.Queue[ApplicationEvent] = queue.Queue()
        self._on_notice = on_notice
        self._on_change = on_change or (lambda: None)
        self._preserve_reference_on_next_reset = False
        self._job_nonce = ""
        self._run_authorization_token = ""
        self._run_authorization_fingerprint = ""
        self._live_sequence = 0
        self._usb_ports = usb_ports or available_ports
        self.connection_service = ConnectionService(
            usb_factory or GrblConnection,
            wifi_factory or TcpGrblConnection,
            discover_hosts or discover_grbl_hosts,
            simulation_factory or (lambda: SimulationRuntime(
                profile=self.simulation_settings.profile,
                workpiece=self.simulation_settings.workpiece,
                speed=self.simulation_settings.speed,
                # Re-read the selected, validated machine declaration for
                # every new twin session.  Explicit factories remain fully
                # caller-owned and are not given implicit arguments.
                homing_profile=self.homing_limit_profile,
                # Symbolic pins make the public exercise controls useful in
                # the twin while remaining completely inert for physical
                # transports.
                estop_definition=EStopDefinition(
                    mode=EStopMode.RESET_PLUS_FEEDBACK,
                    input_pin="E", reset_pin="R",
                ),
            )),
            TcpGrblConnection,
        )
        self.wifi_setup = WifiProvisioningService(self.connection_service.send_line, self._publish_notice)
        self.generation_service = GenerationService()
        self.motion = MotionService(
            self.session,
            self.connection_service.send_line,
            self.connection_service.send_realtime,
            on_notice=self._publish_notice,
            on_change=self._publish_change,
            on_position_complete=on_position_complete,
        )
        self.job = JobService(
            self.session,
            self.connection_service.send_line,
            self.connection_service.send_realtime,
            on_notice=self._publish_notice,
            on_change=self._publish_change,
            on_ready_to_return=on_ready_to_return,
        )
        self.homing = HomingService(self.session, self.connection_service.send_line, self._publish_notice)
        self.travel_calibration = TravelCalibrationService(
            self.session, self.connection_service.send_line,
            self.connection_service.send_realtime, self._publish_notice,
        )
        self.probing = ProbingService(self.session, self.adapter, self.connection_service.send_line, on_notice=self._publish_notice)
        self.calibration = AutoXYZCalibrationService(self.send_manual, on_notice=self._publish_notice)
        self.tool_setting = ToolSettingService(self.session, self.adapter, self.connection_service.send_line, self._publish_notice)
        self.fixtures = FixtureService(self.session, self.adapter, self.connection_service.send_line, self._publish_notice)

    def bind_callbacks(
        self,
        *,
        on_notice: Callable[[str], None] | None = None,
        on_change: Callable[[], None] | None = None,
        on_position_complete: Callable[[], None] | None = None,
        on_ready_to_return: Callable[[], None] | None = None,
    ) -> None:
        """Bind a presentation adapter after composition is complete."""
        if on_notice is not None:
            self._on_notice = on_notice
        if on_change is not None:
            self._on_change = on_change
        self.motion.bind_callbacks(
            on_notice=on_notice,
            on_change=on_change,
            on_position_complete=on_position_complete,
        )
        self.job.bind_callbacks(
            on_notice=on_notice,
            on_change=on_change,
            on_ready_to_return=on_ready_to_return,
        )

    def application_events(self) -> tuple[ApplicationEvent, ...]:
        """Drain transient, UI-neutral events emitted by application services."""
        events: list[ApplicationEvent] = []
        while True:
            try:
                events.append(self._events.get_nowait())
            except queue.Empty:
                return tuple(events)

    def publish_log(self, kind: str, text: str) -> None:
        self._events.put(LogEvent(kind, text))

    def _publish_notice(self, message: str) -> None:
        if self._on_notice is None:
            self._events.put(NoticeEvent(message))
        else:
            self._on_notice(message)

    def _publish_change(self) -> None:
        self._on_change()

    @property
    def connected(self) -> bool:
        return self.connection_service.connected

    @property
    def status_fresh(self) -> bool:
        """Whether a recent status report exists for the current connection."""
        return bool(
            self.connected and self.status is not None
            and self._status_generation == self._session_generation
            and time.monotonic() - self._last_status_received_at <= self.STATUS_FRESHNESS_SECONDS
        )

    @property
    def status_state(self) -> str:
        """Explicit freshness state used by authorization and presentation."""
        if not self.connected:
            return "unavailable"
        if self.status is None or self._status_generation != self._session_generation:
            return "unavailable"
        return "fresh" if self.status_fresh else "stale"

    @property
    def spindle_off_confirmed(self) -> bool:
        """Require a fresh current-session report with exactly zero spindle RPM."""
        return bool(
            self.status_fresh
            and self.status is not None
            and self.status.spindle == 0
        )

    @property
    def session_generation(self) -> int:
        """Monotonic generation for the currently attached controller session."""
        return self._session_generation

    @property
    def supervisor_state(self) -> str:
        """Truthful supervisor state for the current transport mode."""
        if not self.simulation_active:
            return "not_applicable"
        runtime = self.simulation_runtime
        if runtime is None:
            return "unavailable"
        started = getattr(runtime, "started", None)
        if started is False:
            return "unavailable"
        # Lightweight transport doubles from the public polling boundary may
        # expose the heartbeat decision without a lifecycle flag. Preserve
        # that explicit decision while real runtimes remain fail-closed on
        # their started state above.
        if started is None and not (
            hasattr(runtime, "supervisor_healthy") or hasattr(runtime, "supervisor")
        ):
            return "unavailable"
        return "healthy" if bool(getattr(runtime, "supervisor_healthy", False)) else "unhealthy"

    @property
    def root(self) -> Path:
        """The supplied application root; presentation stores must derive from it."""
        return self._root

    @property
    def simulation_active(self) -> bool:
        return bool(self.connected and self.connection_service.mode is ConnectionMode.SIMULATION)

    @property
    def simulation_runtime(self):
        return self.connection_service.simulation_runtime

    @property
    def homing_limit_declarations(self) -> dict[str, dict[str, object]]:
        """Return the validated per-axis declaration exposed to setup surfaces."""
        return {
            axis: {
                "enabled": definition.switch_mode is SwitchMode.SINGLE,
                "end": definition.switch_end.value,
                "pin": definition.input_pin or "",
                "active_low": bool(definition.active_low),
                "wiring": (SwitchWiring.NC.label if definition.active_low else SwitchWiring.NO.label),
                "hard_limit": bool(definition.hard_limit),
                "debounce_ms": float(definition.debounce_ms),
                "max_override": definition.max_override,
            }
            for axis, definition in self.machine_definition.axes.items()
        }

    @property
    def homing_input_observation(self) -> HomingInputInterpretation:
        """Truthful, read-only interpretation of the latest GRBL ``Pn`` report."""
        enabled = [axis for axis, item in self.machine_definition.axes.items()
                   if item.switch_mode is SwitchMode.SINGLE]
        if not enabled:
            return HomingInputInterpretation("not_configured", self.status.pins if self.status else "",
                                             reason="No homing inputs are configured.")
        if not self.status_fresh:
            return HomingInputInterpretation("stale", self.status.pins if self.status else "",
                                             reason="Homing inputs require a fresh GRBL status report; wait for status before moving.")
        wiring = {bool(self.machine_definition.axes[axis].active_low) for axis in enabled}
        if len(wiring) != 1:
            return HomingInputInterpretation("unknown", self.status.pins if self.status else "",
                                             reason="Homing input polarity differs by axis; resolve NC/NO declarations before moving.")
        return self._homing_input_observation

    @property
    def homing_inputs_safe(self) -> bool:
        observation = self.homing_input_observation
        return observation.state in {"not_configured", "released"}

    @property
    def homing_limit_profile(self) -> HomingLimitProfile:
        """Translate the public machine declarations into the twin contract."""
        travel = {"X": self.profile.travel_x, "Y": self.profile.travel_y, "Z": self.profile.travel_z}
        axes = []
        for axis in "XYZ":
            item = self.machine_definition.axes[axis]
            axes.append(AxisSensorDeclaration(
                axis=axis, travel=travel[axis], homing_end=SafetyAxisEnd(item.switch_end.value),
                active_low=item.active_low, input_pin=item.input_pin,
                hard_limit=item.hard_limit, debounce_ms=item.debounce_ms,
                max_override=item.max_override,
            ))
        return HomingLimitProfile(machine_id=self.machine_id or "digital-twin-3018", axes=tuple(axes))

    @property
    def simulation_plate_definition(self) -> CalibrationPlateDefinition:
        return self._simulation_plate_definition

    @property
    def simulation_plate_record(self) -> CalibrationCommissioningRecord | None:
        return self._simulation_plate_record

    @property
    def simulation_plate_commissioned(self) -> bool:
        record = self._simulation_plate_record
        return bool(self.simulation_active and record and record.valid_for(
            self._simulation_plate_definition, machine_id=self.machine_id or ""))

    @property
    def state(self) -> ApplicationState:
        status = self.status
        machine_position = self.session.machine_position
        work_position = status.work_position if status else None
        if work_position is None and machine_position is not None and self.session.work_offset is not None:
            work_position = machine_position.minus(self.session.work_offset)
        program = self.program
        program_snapshot = None
        if program is not None:
            program_snapshot = ProgramSnapshot(
                path=str(program.path),
                command_count=len(program.commands),
                minimum=program.bounds.minimum,
                maximum=program.bounds.maximum,
                estimated_seconds=program.estimated_seconds,
                source_sha256=program.source_sha256,
            )
        streamer = self.job.streamer
        return ApplicationState(
            connection_mode=self.connection_service.mode,
            connected=self.connected,
            status=status,
            machine_position=machine_position,
            work_position=work_position,
            virtual_position=self.session.virtual_position,
            reference_trusted=self.reference_trusted,
            work_zero_confirmed=self.work_zero_confirmed,
            profile=self.profile,
            program=program_snapshot,
            job=JobSnapshot(self.job.display_state, streamer.completed, streamer.total, streamer.error),
            machine_id=self.machine_id or "",
            machine_name=self.machine_definition.name,
        )

    @property
    def job_nonce(self) -> str:
        """Opaque identity for the currently running loaded program."""
        return self._job_nonce if self.job_active else ""

    def live_status_snapshot(self, *, camera_state: str = "off", remote_state: str = "off"):
        """Return a sanitized snapshot for optional monitoring adapters."""
        from ..live.models import LiveStatusSnapshot

        self._live_sequence += 1
        snapshot = LiveStatusSnapshot.from_application(
            self,
            sequence=self._live_sequence,
            camera_state=camera_state,
            remote_state=remote_state,
        )
        return snapshot.__class__(**{**snapshot.as_json(), "job_nonce": self.job_nonce})

    @property
    def profile(self) -> MachineProfile:
        return self.session.profile

    @property
    def machine_definition(self) -> MachineDefinition:
        """The selected machine's capability-aware definition."""
        if self._machine_definition is None:
            self._machine_definition = MachineDefinition.legacy_3018(profile=self.profile)
        return self._machine_definition

    @property
    def installed_hardware(self):
        """Fixed TTC 3018 facts; commissioning state remains separate."""
        return TTC3018_HARDWARE

    @property
    def machine_profiles(self) -> tuple[MachineDefinition, ...]:
        return self.machine_catalog.machines if self.machine_catalog else (self.machine_definition,)

    @property
    def reference_trusted(self) -> bool:
        return self.session.envelope.trusted

    @property
    def work_zero_confirmed(self) -> bool:
        return self.session.work_zero_confirmed

    @property
    def machine_position(self) -> Position | None:
        return self.session.machine_position

    @property
    def virtual_position(self) -> Position | None:
        return self.session.virtual_position

    @property
    def work_offset(self) -> Position | None:
        return self.session.work_offset

    @property
    def z_touch_plate_definition(self) -> ProbeDefinition | None:
        return next((probe for probe in self.machine_definition.probes
                     if probe.kind is ProbeKind.MOVABLE_Z_PLATE and probe.enabled), None)

    @property
    def z_touch_plate_record(self) -> ZTouchPlateRecord | None:
        return self._z_touch_plate_record

    @property
    def z_touch_plate_fingerprint(self) -> str:
        return self.machine_definition.fingerprint(
            "machine_id", "controller", "travel_x", "travel_y", "travel_z", "safe_z", "probes"
        )

    @property
    def z_touch_plate_status(self) -> str:
        definition = self.z_touch_plate_definition
        if definition is None:
            return "disabled"
        if self._z_plate_removal_required:
            return "remove_plate"
        record = self._z_touch_plate_record
        if record is None or not record.input_tested:
            return "needs_input_test"
        if record.fingerprint != self.z_touch_plate_fingerprint:
            return "stale"
        if self._z_probe_pending:
            return "probing"
        if self._z_commissioning_pending:
            return "commissioning"
        if not record.commissioned:
            return "needs_commissioning"
        return "ready"

    @property
    def z_touch_plate_input_message(self) -> str:
        return self._z_touch_plate.input_result.message

    @property
    def z_touch_plate_input_state(self) -> str:
        return self._z_touch_plate.input_result.state

    @property
    def z_touch_plate_sample_count(self) -> int:
        return len(self._z_touch_plate.samples)

    @property
    def motion_busy(self) -> bool:
        return self.motion.busy or self.travel_calibration.active

    @property
    def live_jog_active(self) -> bool:
        return bool(self.motion.live_jog_axis or self.motion.live_jog_stop_pending or self.motion.live_jog_alignment_pending)

    @property
    def job_active(self) -> bool:
        return self.job.active

    @property
    def job_state(self) -> str:
        return self.job.display_state

    @property
    def job_progress(self) -> float:
        return self.job.progress

    @property
    def job_estimated_seconds(self) -> float:
        return self.job.estimated_seconds

    @property
    def job_elapsed_seconds(self) -> float:
        return self.job.elapsed_seconds

    @property
    def job_remaining_seconds(self) -> float | None:
        return self.job.remaining_seconds

    @property
    def operation_transport_ready(self) -> bool:
        """Production USB is setup-only; operating Wi-Fi needs fresh GRBL status."""
        if self._z_probe_completion.get("state") == "lowering":
            return False
        if not getattr(self, "_wifi_only_operations", False):
            return True  # Explicit in-process test/compatibility compositions.
        return bool(self.simulation_active or (
            self.connection_service.mode is ConnectionMode.WIFI and self.status_fresh))

    @property
    def can_jog(self) -> bool:
        return bool(self.operation_transport_ready and self.connected and self.homing_inputs_safe and self.session.can_move and not self.job_active and not self.manual_pending_acks and not self.motion_busy)

    @property
    def can_live_jog(self) -> bool:
        controller_accepts_live_jog = self.session.can_move or bool(
            self.motion.live_jog_axis is not None
            and self.status is not None
            and self.status.state == "Jog"
        )
        return bool(
            self.operation_transport_ready
            and self.connected
            and self.homing_inputs_safe
            and controller_accepts_live_jog
            and not self.job_active
            and not self.motion.position_move_active
            and not self.motion.live_jog_stop_pending
            and not self.motion.live_jog_alignment_pending
            and (not self.motion.pending_acks or self.motion.live_jog_axis is not None)
        )

    @property
    def can_return_to_reference(self) -> bool:
        return bool(self.operation_transport_ready and self.connected and self.homing_inputs_safe and self.reference_trusted and self.session.can_move and not self.job_active and not self.manual_pending_acks and not self.motion_busy)

    @property
    def can_home_machine(self) -> bool:
        """Whether a fresh, guarded homing request may be started."""
        definition = self.machine_definition
        status = self.status
        return bool(
            self.operation_transport_ready
            and self.connected
            and self.status_fresh
            and self.homing_inputs_safe
            and status is not None
            and status.state in {"Idle", "Alarm"}
            and status.spindle in (None, 0)
            and all(axis.switch_mode is not SwitchMode.NONE for axis in definition.axes.values())
            and not self.homing.active
            and not self.probing.active
            and not self.calibration.active
            and not self.travel_calibration.active
            and not self.job_active
            and not self.manual_pending_acks
            and not self.motion_busy
        )

    @property
    def can_start_job(self) -> bool:
        runtime = self.simulation_runtime
        twin_safety_ready = not self.simulation_active or (
            self.supervisor_state == "healthy"
            and not getattr(runtime, "active_hazards", ())
            and not bool(getattr(runtime, "estop_status", {}).get("interlocked", False))
        )
        return bool(
            self.operation_transport_ready
            and self.connected
            and self.status_fresh
            and self.spindle_off_confirmed
            and self.homing_inputs_safe
            and twin_safety_ready
            and self.session.can_move
            and self.work_zero_confirmed
            and not self.manual_pending_acks
            and not self.motion_busy
            and not self.job_active
            and not self.job.restart_requires_reload
            and not self._z_plate_removal_required
            and self.program
            and self.preflight()[0]
        )

    @property
    def transport(self):
        return self.connection_service.transport

    def connect_usb(self, port: str) -> ConnectionOutcome:
        outcome = self.connection_service.connect_usb(port)
        if outcome.accepted:
            self._begin_session_generation()
            try:
                self.save_usb_settings(port)
            except (OSError, ValueError, RuntimeError):
                self._publish_notice("Last USB endpoint could not be persisted")
        return outcome

    def begin_wifi(self, host: str, port: int) -> ConnectionOutcome:
        return self.connection_service.begin_wifi(host, port)

    def reconnect_saved_wifi(self) -> ConnectionOutcome:
        """Reconnect only to the saved Wi-Fi endpoint, without discovery/fallback."""
        host = str(getattr(self.settings, "wifi_host", "")).strip()
        try:
            port = int(getattr(self.settings, "wifi_port", 0) or 0)
        except (TypeError, ValueError):
            port = 0
        if not host or not 1 <= port <= 65535:
            return ConnectionOutcome(False, "No valid saved Wi-Fi endpoint is configured")
        return self.connection_service.begin_wifi(host, port, discover=False)

    def connect_simulation(self) -> ConnectionOutcome:
        outcome = self.connection_service.connect_simulation()
        if outcome.accepted:
            self._begin_session_generation()
            self._simulation_plate_record = None
            self._simulation_physical_saved_work_zero = self._saved_work_zero
            self._simulation_saved_work_zero = None
            self._saved_work_zero = None
            self.session.work_zero_confirmed = False
            self.session.work_offset = None
        return outcome

    def configure_simulation(self, speed: str, workpiece_label: str = "Pocket + retained island") -> ConnectionOutcome:
        """Persist simulation-only controls before a twin session starts."""
        if self.simulation_active:
            return ConnectionOutcome(False, "Disconnect the digital twin before changing its settings")
        labels = {
            "Pocket + retained island": ("examples/showcase-pocket-island.step", False),
            "Collision-only STEP": ("examples/showcase-mounting-plate.step", True),
        }
        if speed not in {"realtime", "2x", "5x", "10x", "uncapped"}:
            return ConnectionOutcome(False, "Unknown digital-twin speed")
        path, collision_only = labels.get(workpiece_label, ("", False))
        candidate = self._root / path if path else None
        existing = self.simulation_settings.workpiece
        workpiece = existing
        if candidate is not None and candidate.exists():
            workpiece = replace(existing, path=str(candidate), collision_only=collision_only)
        self.simulation_settings = replace(self.simulation_settings, speed=speed, workpiece=workpiece)
        try:
            self.simulation_settings_store.save(self.simulation_settings)
        except (OSError, ValueError, TypeError) as exc:
            return ConnectionOutcome(False, f"Digital-twin settings could not be saved: {exc}")
        return ConnectionOutcome(True, "Digital-twin settings saved")

    def save_simulation_settings(self, settings: SimulationSettings) -> ActionOutcome:
        if self.simulation_active:
            return ActionOutcome(False, "Digital-twin settings cannot change during a session")
        try:
            self.simulation_settings_store.save(settings)
        except (OSError, ValueError, TypeError) as exc:
            return ActionOutcome(False, f"Digital-twin settings rejected — {exc}")
        self.simulation_settings = settings
        return ActionOutcome(True, "Digital-twin settings saved")

    def poll_wifi(self) -> ConnectionOutcome | None:
        service = self.connection_service
        if getattr(self, "_wifi_only_operations", False) and self.connected and service.mode is ConnectionMode.USB:
            status = self.status
            ready = bool(self.status_fresh and status is not None and status.state == "Idle"
                         and status.spindle == 0
                         and not self.job_active and not self.motion_busy
                         and not self.manual_pending_acks and not self.probing.active
                         and not self.calibration.active and not self.travel_calibration.active
                         and not self.wifi_setup.active)
            if ready and service.wifi_bootstrap_snapshot.get("state") == "idle":
                service.start_wifi_bootstrap(self.settings)
            outcome = service.poll_wifi_bootstrap(
                usb_status=status, usb_status_age=(time.monotonic() - self._last_status_received_at),
                allow_handoff=ready)
            if outcome is None:
                return None
        else:
            outcome = service.poll_wifi()
        if outcome is not None and outcome.accepted:
            self.session.invalidate_reference("Transport changed; home again over Wi-Fi")
            self._begin_session_generation()
            if outcome.mode is ConnectionMode.WIFI and outcome.host and outcome.port:
                try:
                    self.save_wifi_settings(outcome.host, outcome.port)
                except (OSError, ValueError, RuntimeError):
                    self._publish_notice("Last Wi-Fi endpoint could not be persisted")
        return outcome

    def auto_connect_saved(self) -> ConnectionOutcome:
        """Start the bounded saved physical connection plan owned by backend."""
        if self.connected:
            return ConnectionOutcome(True, "Existing controller connection adopted", self.connection_service.mode,
                                     self.connection_service.endpoint, self.connection_service.port)
        ports = [port for port, _description in self.usb_ports()]
        return self.connection_service.begin_auto_connect(
            replace(self.settings, preferred_transport="Wi-Fi TCP")
            if getattr(self, "_wifi_only_operations", False) else self.settings, ports)

    def transport_events(self):
        return self.connection_service.events()

    def poll_simulation(self) -> tuple[dict, ...]:
        """Poll the owned twin through the same boundary used by the UI.

        Keeping this small adapter on the Qt-independent controller lets
        headless acceptance scenarios exercise the real loopback transport,
        backend, and supervisor without reaching into a plant or process.
        """
        runtime = self.simulation_runtime
        if not self.simulation_active or runtime is None:
            return ()
        events = runtime.poll()
        for item in events:
            if item.get("type") == "safety" and dict(item.get("safety", {})).get("interlocked"):
                # E-stop is an application safety boundary: stop the job/jog
                # lifecycle and invalidate both trust records immediately.
                self.job.abort("Digital-twin E-stop latched")
                self.motion.reset()
                self.session.invalidate_reference("Digital-twin E-stop latched; homing required")
                self._publish_notice("Digital-twin E-stop latched; motion, probing, and homing are blocked until release and a successful home")
                self._publish_change()
        return events

    def inject_simulation_estop(self, *, reset_asserted: bool = False,
                                feedback_electrical: bool | None = None) -> ActionOutcome:
        """Inject only the twin E-stop path; never emits a physical reset/GPIO."""
        runtime = self.simulation_runtime
        if not self.simulation_active or runtime is None:
            return ActionOutcome(False, "Digital-twin E-stop is unavailable while disconnected")
        runtime.inject_estop(reset_asserted=reset_asserted, feedback_electrical=feedback_electrical)
        return ActionOutcome(True, "Digital-twin E-stop injection requested; safety latch requires release and a successful home")

    def configure_simulation_homing(self, profile: HomingLimitProfile) -> ActionOutcome:
        """Apply switch declarations only through the owned twin boundary."""
        runtime = self.simulation_runtime
        if not self.simulation_active or runtime is None:
            return ActionOutcome(False, "Digital-twin homing declarations are unavailable while disconnected")
        try:
            runtime.configure_homing(profile)
        except (RuntimeError, ValueError, TypeError) as exc:
            return ActionOutcome(False, f"Digital-twin homing declarations rejected — {exc}")
        return ActionOutcome(True, "Digital-twin homing/limit declarations applied")

    def save_homing_limit_declarations(self, declarations: dict[str, dict[str, object]]) -> ActionOutcome:
        """Validate and publish per-axis homing/limit declarations.

        The same immutable declaration is translated to the twin profile. A
        real GRBL controller receives only its four guarded settings while
        connected, Idle, and free of active operations; disconnected edits are
        persisted for the next commissioning session.
        """
        if not isinstance(declarations, dict):
            return ActionOutcome(False, "Homing declarations must be an object keyed by X, Y, and Z")
        if set(declarations) != set("XYZ"):
            return ActionOutcome(False, "Homing declarations must include exactly X, Y, and Z")
        if (self.motion_busy or self.job_active or self.manual_pending_acks
                or self.probing.active or self.homing.active or self.calibration.active):
            return ActionOutcome(False, "Homing/limit declarations require no active machine operation")
        if self.connected and not self.simulation_active:
            if self.status is None or self.status.state != "Idle" or not self.status.can_jog:
                return ActionOutcome(False, "GRBL must be Idle and safety-enabled before changing homing/limit settings")

        axes = dict(self.machine_definition.axes)
        try:
            for axis in "XYZ":
                raw = declarations[axis]
                if not isinstance(raw, dict):
                    raise ValueError(f"{axis} declaration must be an object")
                enabled = bool(raw.get("enabled", raw.get("switch_enabled", False)))
                end = MachineAxisEnd(str(raw.get("end", raw.get("switch_end", "min"))).lower())
                pin = str(raw.get("pin", raw.get("input_pin", ""))).strip() or None
                if enabled and not pin:
                    raise ValueError(f"{axis} enabled homing switch requires an input pin")
                wiring_raw = raw.get("wiring", raw.get("polarity"))
                if wiring_raw is None:
                    active_low = bool(raw.get("active_low", False))
                else:
                    wiring_text = str(wiring_raw).strip().lower().replace("_", " ").replace("-", " ")
                    if wiring_text in {"nc", "normally closed", "open on trigger", "nc open on trigger"}:
                        active_low = True
                    elif wiring_text in {"no", "normally open", "close on trigger", "no close on trigger"}:
                        active_low = False
                    else:
                        raise ValueError(f"{axis} wiring must be NC (open on trigger) or NO (close on trigger)")
                max_override_raw = raw.get("max_override")
                max_override = None if max_override_raw in (None, "", "null") else float(max_override_raw)
                updated = replace(
                    axes[axis], switch_mode=SwitchMode.SINGLE if enabled else SwitchMode.NONE,
                    switch_end=end, input_pin=pin if enabled else None,
                    active_low=active_low,
                    hard_limit=bool(raw.get("hard_limit", False)) if enabled else False,
                    debounce_ms=float(raw.get("debounce_ms", 5.0)), max_override=max_override,
                )
                updated.validate(axis)
                axes[axis] = updated
            updated_definition = replace(self.machine_definition, axes=axes)
            updated_definition.validate()
            if updated_definition.fingerprint() == self.machine_definition.fingerprint():
                return ActionOutcome(True, "Homing/limit declarations unchanged")
            homing_profile = HomingLimitProfile(
                machine_id=self.machine_id or "digital-twin-3018",
                axes=tuple(AxisSensorDeclaration(
                    axis=axis, travel=getattr(self.profile, f"travel_{axis.lower()}"),
                    homing_end=SafetyAxisEnd(axes[axis].switch_end.value),
                    active_low=axes[axis].active_low, input_pin=axes[axis].input_pin,
                    hard_limit=axes[axis].hard_limit, debounce_ms=axes[axis].debounce_ms,
                    max_override=axes[axis].max_override,
                ) for axis in "XYZ"),
            )
            homing_profile.validate()
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            return ActionOutcome(False, f"Homing/limit declarations rejected — {exc}")

        # GRBL exposes these as global settings. Refuse a lossy physical
        # translation when per-axis declarations disagree; the twin remains
        # per-axis and can represent the full declaration faithfully.
        if self.connected and not self.simulation_active:
            enabled_values = {item.switch_mode is SwitchMode.SINGLE for item in axes.values()}
            polarity_values = {item.active_low for item in axes.values() if item.switch_mode is SwitchMode.SINGLE}
            hard_values = {item.hard_limit for item in axes.values() if item.switch_mode is SwitchMode.SINGLE}
            if len(enabled_values) > 1 or len(polarity_values) > 1 or len(hard_values) > 1:
                return ActionOutcome(False, "Physical GRBL $5/$21/$22 are global; declarations must agree across enabled axes")

        try:
            if self.simulation_active:
                runtime = self.simulation_runtime
                if runtime is None:
                    return ActionOutcome(False, "Digital-twin runtime is unavailable")
                runtime.configure_homing(homing_profile)
            elif self.machine_catalog is not None:
                self.machine_catalog = self.machine_catalog_store.upsert(
                    self.machine_catalog, updated_definition)
            self._machine_definition = updated_definition
            if self.connected and not self.simulation_active:
                enabled = all(item.switch_mode is SwitchMode.SINGLE for item in axes.values())
                active_low = bool(next(iter({item.active_low for item in axes.values()}), False))
                hard_limit = bool(next(iter({item.hard_limit for item in axes.values()}), False))
                # `$23` selects the GRBL direction used to reach each
                # declared homing end.  `positive_direction` records whether
                # a GRBL-positive move is physically positive (+1) or
                # physically negative (-1) for that axis.
                direction_mask = sum(1 << index for index, axis in enumerate("XYZ")
                                     if ((axes[axis].switch_end is MachineAxisEnd.MAX)
                                         == (axes[axis].positive_direction == 1)))
                # GRBL's electrical limit polarity is independent of the
                # controller's raw Pn presentation.  An NC circuit is closed
                # in the safe state and opens on trigger, so invert GRBL's
                # internal active-low input for NC hardware.
                for number, value in ((5, 1 if active_low else 0), (21, 1 if hard_limit else 0),
                                      (22, 1 if enabled else 0), (23, direction_mask)):
                    self.send_manual(self.adapter.setting_command(number, value))
            self.session.invalidate_reference("Homing/limit declarations changed; recommission and home the machine")
            self._homing_input_baseline_pins = None
            self._homing_input_observation = HomingInputInterpretation(
                "unknown", "", reason="Homing declarations changed; wait for a fresh released-input status.")
        except (OSError, RuntimeError, ValueError, TypeError) as exc:
            return ActionOutcome(False, f"Homing/limit declarations could not be applied — {exc}")
        return ActionOutcome(True, "Homing/limit declarations saved and applied through the guarded boundary")

    def commission_simulation_calibration_plate(self) -> ActionOutcome:
        """Commission the bundled conductive plate fixture for this twin session."""
        if not self.simulation_active or self.simulation_runtime is None:
            return ActionOutcome(False, "The Auto XYZ fixture is simulation-only and requires an active digital twin")
        if self.status is not None and (self.status.state != "Idle" or self.status.spindle not in (None, 0)):
            return ActionOutcome(False, "The simulation plate requires GRBL Idle with the spindle off")
        try:
            definition = self._simulation_plate_definition
            definition.validate()
            self.simulation_runtime.configure_probe_corner_circle(
                ProbeCornerCircle(definition.circle_center_x, definition.circle_center_y, definition.radius, 0.0))
            self.simulation_runtime.configure_probe_surface(definition.effective_probe_surface_z)
            self._simulation_plate_record = CalibrationCommissioningRecord(
                plate_fingerprint=definition.fingerprint(), input_tested=True,
                geometry_tested=True, machine_id=self.machine_id or "digital-twin-3018")
        except (RuntimeError, ValueError, TypeError) as exc:
            return ActionOutcome(False, f"Simulation Auto XYZ fixture commissioning failed — {exc}")
        return ActionOutcome(True, "Simulation Auto XYZ plate commissioned for this machine session")

    def set_simulation_limit_input(self, axis: str, electrical_active: bool) -> ActionOutcome:
        runtime = self.simulation_runtime
        if not self.simulation_active or runtime is None:
            return ActionOutcome(False, "Digital-twin limit input is unavailable while disconnected")
        try:
            runtime.set_limit_input(axis, bool(electrical_active))
        except (RuntimeError, ValueError, TypeError) as exc:
            return ActionOutcome(False, f"Digital-twin limit input rejected — {exc}")
        return ActionOutcome(True, f"Digital-twin {axis.upper()} limit input injected")

    def configure_simulation_probe_corner_circle(self, circle: ProbeCornerCircle | None) -> ActionOutcome:
        runtime = self.simulation_runtime
        if not self.simulation_active or runtime is None:
            return ActionOutcome(False, "Digital-twin probe geometry is unavailable while disconnected")
        try:
            runtime.configure_probe_corner_circle(circle)
        except (RuntimeError, ValueError, TypeError) as exc:
            return ActionOutcome(False, f"Digital-twin probe geometry rejected — {exc}")
        return ActionOutcome(True, "Digital-twin conductive probe geometry applied")

    def release_simulation_estop(self) -> ActionOutcome:
        runtime = self.simulation_runtime
        if not self.simulation_active or runtime is None:
            return ActionOutcome(False, "Digital-twin E-stop is unavailable while disconnected")
        runtime.release_estop()
        return ActionOutcome(True, "Digital-twin E-stop input released; controller Idle and an explicit home are still required")

    def acknowledge_simulation_estop(self) -> ActionOutcome:
        runtime = self.simulation_runtime
        if not self.simulation_active or runtime is None:
            return ActionOutcome(False, "Digital-twin E-stop is unavailable while disconnected")
        if not self.reference_trusted:
            return ActionOutcome(False, "Home the machine to establish a trusted reference before E-stop recovery")
        runtime.acknowledge_estop(reference_trusted=True)
        return ActionOutcome(True, "Digital-twin E-stop recovery authorized; keep the machine Idle before motion")

    def export_simulation_trace(self, path) -> None:
        """Export canonical evidence from the active digital-twin runtime."""
        runtime = self.simulation_runtime
        if runtime is None:
            raise RuntimeError("Digital twin is not active")
        runtime.trace.export_json(path)
        runtime.trace.export_markdown(path.with_suffix(".md"), title="Digital twin lifecycle evidence")

    def record_simulation_event(self, kind: str, payload: dict | None = None, *, time_ns: int = 0) -> None:
        """Add an application-boundary event to the twin's canonical trace."""
        runtime = self.simulation_runtime
        if runtime is None:
            raise RuntimeError("Digital twin is not active")
        # Milestones are normally recorded without a plant timestamp.  Anchor
        # those events at the latest observed twin time so an otherwise valid
        # evidence export remains reloadable after status has advanced.
        if time_ns == 0 and runtime.trace.events:
            time_ns = runtime.trace.events[-1].time_ns
        runtime.trace.record(time_ns, kind, payload or {}, source="application")

    def usb_ports(self) -> list[tuple[str, str]]:
        """Return currently enumerated USB serial endpoints for the adapter."""
        # A twin session must never fall through to the physical discovery
        # callback, even if a non-Qt caller asks for ports directly.
        if self.simulation_active:
            return []
        return self._usb_ports()

    def set_transport_for_testing(self, transport) -> None:
        """Inject a fake transport without exposing service internals to Qt tests."""
        if transport is not self.connection_service.transport:
            self._begin_session_generation()
        self.connection_service.transport = transport

    @property
    def program(self):
        return self.job.program

    @property
    def program_provenance(self) -> dict[str, object]:
        program = self.program
        if program is None:
            return {
                "report_state": "unavailable", "file_sha256": "", "report_name": "",
                "release_status": "", "bundle": "", "details": [], "header_notes": [],
                "verification_text": "", "notice": "No job is loaded.",
            }
        return build_job_provenance(program.path, program.source_sha256, program.header_comments)

    def load_program(self, path: Path):
        program = self.job.load_program(path)
        self._job_nonce = secrets.token_urlsafe(24)
        self._invalidate_job_start_authorization()
        return program

    def load_generated(self, gcode: str, filename: str):
        program = self.job.load_generated(gcode, filename)
        self._job_nonce = secrets.token_urlsafe(24)
        self._invalidate_job_start_authorization()
        return program

    def preflight(self) -> tuple[bool, str]:
        if not self.operation_transport_ready:
            return False, "USB is Wi-Fi setup only; wait for a verified Wi-Fi connection"
        return self.job.preflight()

    def _begin_session_generation(self) -> None:
        """Invalidate status trust and start authorizations at a lifecycle edge."""
        if self._z_probe_completion_context is not None:
            self._fail_z_probe_completion("Connection changed; probe Z again before lowering")
        self._session_generation += 1
        self._status_generation = -1
        self._last_status_received_at = 0.0
        self._invalidate_job_start_authorization()

    def _job_start_fingerprint(self, *, review_acknowledged: bool,
                               physical_preflight_confirmed: bool) -> str:
        program = self.program
        runtime = self.simulation_runtime
        safety = getattr(runtime, "estop_status", {}) if runtime is not None else {}
        hazards = getattr(runtime, "active_hazards", ()) if runtime is not None else ()
        fixture_origin = getattr(self.fixtures, "pending_origin", None)
        runtime_facts = {
            "supervisor": self.supervisor_state,
            "estop": safety if isinstance(safety, dict) else repr(safety),
            "hazards": [repr(hazard) for hazard in hazards],
        }
        payload = {
            "program": None if program is None else {
                "path": str(program.path),
                "commands": tuple(program.commands),
                "bounds": repr(program.bounds),
            },
            "machine": self.machine_definition.fingerprint(),
            "reference": repr(self.session.envelope.reference),
            "work_offset": repr(self.session.work_offset),
            "status": meaningful_status_facts(self.status),
            "status_state": self.status_state,
            "session_generation": self._session_generation,
            "status_fresh": self.status_fresh,
            "connected": self.connected,
            "simulation": self.simulation_active,
            "runtime": runtime_facts,
            "z_plate_status": self.z_touch_plate_status,
            "z_plate_removal_required": self._z_plate_removal_required,
            "z_probe_pending": self._z_probe_pending,
            "fixture_pending_origin": repr(fixture_origin),
            "homing_inputs": repr(self.homing_input_observation),
            "confirmed_work_zero_axes": tuple(sorted(self.session.confirmed_work_zero_axes)),
            "work_zero_confirmed": bool(self.session.work_zero_confirmed),
            "awaiting_work_zero_report": bool(self.session.awaiting_work_zero_report),
            "review_acknowledged": bool(review_acknowledged),
            "physical_preflight_confirmed": bool(physical_preflight_confirmed),
        }
        encoded = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def _invalidate_job_start_authorization(self) -> None:
        self._run_authorization_token = ""
        self._run_authorization_fingerprint = ""

    def authorize_job_start(self, *, review_acknowledged: bool,
                            physical_preflight_confirmed: bool) -> JobStartAuthorization:
        """Validate and issue a one-use token for the exact current state."""
        if not review_acknowledged:
            return JobStartAuthorization(False, "Review the current validated path before starting a job")
        if not physical_preflight_confirmed:
            return JobStartAuthorization(False, "Complete physical preflight before starting a job")
        if self.supervisor_state not in {"healthy", "not_applicable"}:
            return JobStartAuthorization(False, f"Job not authorized — safety supervisor is {self.supervisor_state}")
        runtime = self.simulation_runtime
        if runtime is not None and getattr(runtime, "active_hazards", ()):
            return JobStartAuthorization(False, "Job not authorized — clear the active digital-twin safety hazard")
        if runtime is not None and bool(getattr(runtime, "estop_status", {}).get("interlocked", False)):
            return JobStartAuthorization(False, "Job not authorized — release and recover the digital-twin E-stop")
        if not self.connected:
            return JobStartAuthorization(False, "Job not authorized — connect to the controller before starting")
        if not self.status_fresh:
            return JobStartAuthorization(False, "Job not authorized — wait for a fresh GRBL status report")
        status = self.status
        if status is None or status.state != "Idle":
            state = status.state if status is not None else "unknown"
            return JobStartAuthorization(False, f"Job not authorized — wait for GRBL Idle (current state: {state})")
        if status.spindle is None:
            return JobStartAuthorization(
                False,
                "Job not authorized — wait for a fresh GRBL report confirming the spindle is off (zero RPM)",
            )
        if status.spindle != 0:
            return JobStartAuthorization(
                False,
                "Job not authorized — turn the spindle off and wait for a zero-RPM status report",
            )
        if not self.can_start_job:
            fits, reason = self.preflight()
            if not fits:
                return JobStartAuthorization(False, f"Job not authorized — {reason}")
            return JobStartAuthorization(False, "Job not authorized — machine is not ready")
        token = secrets.token_urlsafe(32)
        self._run_authorization_token = token
        self._run_authorization_fingerprint = self._job_start_fingerprint(
            review_acknowledged=review_acknowledged,
            physical_preflight_confirmed=physical_preflight_confirmed,
        )
        return JobStartAuthorization(True, "Job start authorization issued", token)

    def start_authorized_job(self, token: str) -> ActionOutcome:
        """Consume a current authorization exactly once, then stream the job."""
        if not token or token != self._run_authorization_token:
            return ActionOutcome(False, "No current job approval; review the selected job before starting")
        expected = self._run_authorization_fingerprint
        current = self._job_start_fingerprint(
            review_acknowledged=True, physical_preflight_confirmed=True,
        )
        if not expected or current != expected:
            self._invalidate_job_start_authorization()
            return ActionOutcome(False, "Job approval needs review because the program, position, work zero or safety state changed")
        # Consume before entering the streamer so retries cannot replay a
        # command sequence even if the transport fails during start.
        self._invalidate_job_start_authorization()
        return self._start_job_unchecked()

    def _start_job_unchecked(self) -> ActionOutcome:
        if self._z_plate_removal_required:
            return ActionOutcome(False, "Remove the Z touch plate and clip, then acknowledge their removal before starting a job.")
        if self.job.restart_requires_reload:
            return ActionOutcome(
                False,
                "Job not started — reload and review the program after the previous failure",
            )
        if not self.can_start_job:
            fits, reason = self.preflight()
            if not fits:
                return ActionOutcome(False, f"Job not started — {reason}")
            return ActionOutcome(False, "Job not started — machine is not ready")
        return self.job.start()

    def start_job(self, authorization_token: str | None = None) -> ActionOutcome:
        """Start only through an application-issued reviewed-state token."""
        if authorization_token is None:
            return ActionOutcome(False, "Job start requires review acknowledgement and physical preflight")
        return self.start_authorized_job(authorization_token)

    def pause_job(self) -> ActionOutcome:
        return self.job.pause()

    def resume_job(self) -> ActionOutcome:
        if not self.operation_transport_ready:
            return ActionOutcome(False, "Resume requires verified Wi-Fi; USB is setup only")
        return self.job.resume()

    def abort_job(self, reason: str = "Aborted by operator") -> None:
        reset_sent = False
        try:
            self.send_realtime(REALTIME_HOLD)
            self.send_realtime(REALTIME_SOFT_RESET)
            reset_sent = True
        except RuntimeError:
            pass
        self._preserve_reference_on_next_reset = reset_sent
        self.job.abort(reason)
        self._job_nonce = ""
        self.motion.reset()
        self.manual_pending_acks = 0
        self._work_zero_request_pending_ack = False
        self._work_zero_expected_offset = None
        self._work_zero_expected_axes = ""

    def _homing_input_motion_allowed(self, operation: str) -> ActionOutcome:
        """Require one fresh, released interpretation before starting motion.

        This is deliberately shared by the public motion, probe, homing, and
        calibration entry points.  Stop/cancel/abort paths do not call this
        helper, so a stale or asserted input can never strand an operation
        that is already being safely recovered.
        """
        if not self.operation_transport_ready:
            return ActionOutcome(False, "USB is Wi-Fi setup only; wait for a verified Wi-Fi connection")
        if not self.homing_inputs_safe:
            return ActionOutcome(False, f"{operation} blocked — {self.homing_input_observation.reason}")
        return ActionOutcome(True, f"{operation} homing-input interlock accepted")

    def _motion_operation_allowed(self) -> ActionOutcome:
        if not self.connected:
            return ActionOutcome(False, "Motion command ignored — not connected")
        homing = self._homing_input_motion_allowed("Motion command")
        if not homing.accepted:
            return homing
        if self.job_active:
            return ActionOutcome(False, "Motion command ignored — a job is active")
        if self.manual_pending_acks:
            return ActionOutcome(False, "Motion command ignored — waiting for GRBL acknowledgement")
        if self.motion_busy:
            return ActionOutcome(False, "Motion command ignored — another motion operation is active")
        return ActionOutcome(True, "Motion operation accepted")

    def request_status(self) -> None:
        self.send_realtime(REALTIME_STATUS)

    def begin_wifi_setup(self, ssid: str, password: str, port: int, now: float) -> ActionOutcome:
        if not self.connected or self.connection_service.mode is not ConnectionMode.USB:
            return ActionOutcome(False, "Wi-Fi setup requires an active USB connection")
        if not self.session.can_move:
            return ActionOutcome(False, "Wi-Fi setup requires GRBL Idle")
        outcome = self.wifi_setup.start(ssid, password, port, now)
        if outcome.accepted:
            self.session.invalidate_reference("Controller Wi-Fi reconfiguration")
        return outcome

    def validate_wifi_setup(self, ssid: str, password: str, port: int) -> None:
        self.wifi_setup.validate(ssid, password, port)

    def poll_wifi_setup(self, now: float) -> None:
        self.wifi_setup.poll(now)

    def check_job_watchdog(self) -> str | None:
        return self.job.check_controller_watchdog()

    def generate_text(self, *args, **kwargs):
        return self.generation_service.text(*args, **kwargs)

    def generate_plaque(self, *args, **kwargs):
        return self.generation_service.plaque(*args, **kwargs)

    def generate_step(self, *args, **kwargs):
        return self.generation_service.step(*args, **kwargs)

    def import_step(self, path, plane: str | None = None):
        return self.generation_service.import_step(path, plane)

    @property
    def bundled_showcase_step_path(self) -> Path:
        """Resolve the read-only, versioned showcase STEP fixture."""
        path = (self._root / "examples" / "showcase-pocket-island.step").resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Bundled showcase STEP fixture is missing: {path}")
        return path

    def save_wifi_settings(self, host: str, port: int) -> None:
        if self.simulation_active:
            raise RuntimeError("Physical connection settings are disabled in the digital twin")
        self.settings = ConnectionSettings(host, port, "Wi-Fi TCP", self.settings.usb_port)
        self.connection_store.save(self.settings)

    def save_usb_settings(self, port: str) -> None:
        if self.simulation_active:
            raise RuntimeError("Physical connection settings are disabled in the digital twin")
        self.settings = ConnectionSettings(
            self.settings.wifi_host,
            self.settings.wifi_port,
            "Wi-Fi TCP" if getattr(self, "_wifi_only_operations", False) else "USB serial",
            port.strip(),
        )
        self.connection_store.save(self.settings)

    def save_profile(self, profile: MachineProfile) -> None:
        if self.simulation_active:
            raise RuntimeError("Machine profile changes are disabled while the digital twin is connected")
        profile.validate()
        self.profile_store.save(profile)
        self.session.profile = profile
        if self.machine_catalog is not None and self._machine_definition is not None:
            updated = replace(self._machine_definition, name=profile.name, travel_x=profile.travel_x,
                              travel_y=profile.travel_y, travel_z=profile.travel_z, safe_z=profile.safe_z)
            self.machine_catalog = self.machine_catalog_store.upsert(self.machine_catalog, updated)
            self._machine_definition = updated

    def start_travel_calibration(self, *, increment_mm: float = 10.0,
                                 max_overshoot_mm: float = 30.0,
                                 search_feed: float = 120.0,
                                 return_feed: float = 600.0) -> ActionOutcome:
        if self.job_active or self.motion.busy or self.homing.active or self.probing.active or self.calibration.active:
            return ActionOutcome(False, "Finish the active machine operation before travel calibration")
        spindle_off = self.status is not None and self.status.spindle in (None, 0)
        return self.travel_calibration.start(
            self.machine_definition,
            TravelCalibrationOptions(
                increment_mm=increment_mm, max_overshoot_mm=max_overshoot_mm,
                search_feed=search_feed, return_feed=return_feed,
            ),
            connected=self.connected, status_fresh=self.status_fresh,
            spindle_off=spindle_off, homing_inputs_safe=self.homing_inputs_safe,
        )

    def abort_travel_calibration(self) -> ActionOutcome:
        return self.travel_calibration.abort()

    def accept_travel_calibration(self) -> ActionOutcome:
        if not self.travel_calibration.can_accept:
            return ActionOutcome(False, "Complete and validate all three axes before accepting travel calibration")
        result = self.travel_calibration.results
        profile = MachineProfile(
            self.profile.name, result["X"], result["Y"], result["Z"],
            min(self.profile.safe_z, result["Z"]),
        )
        try:
            self.save_profile(profile)
            if self.machine_catalog is not None and self._machine_definition is not None:
                calibrated_axes = {
                    axis: replace(item, max_override=result[axis])
                    for axis, item in self._machine_definition.axes.items()
                }
                updated = replace(self._machine_definition, axes=calibrated_axes)
                self.machine_catalog = self.machine_catalog_store.upsert(self.machine_catalog, updated)
                self._machine_definition = updated
        except (OSError, ValueError, TypeError) as exc:
            return ActionOutcome(False, f"Calibrated travel could not be saved — {exc}")
        self.travel_calibration.reset()
        self.session.invalidate_reference("Travel limits changed; home with the accepted profile")
        return ActionOutcome(True, "Calibrated XYZ travel limits saved; home once more before normal motion")

    def select_machine(self, machine_id: str) -> ActionOutcome:
        if self.connected or self.motion_busy or self.job_active or self.homing.active or self.probing.active:
            return ActionOutcome(False, "Machine selection requires a disconnected, idle application.")
        if self.machine_catalog is None:
            return ActionOutcome(False, "Machine catalog is unavailable for this controller instance.")
        try:
            self.machine_catalog = self.machine_catalog_store.select(self.machine_catalog, machine_id)
            self._machine_definition = self.machine_catalog.selected()
            self.machine_id = self._machine_definition.machine_id
            self.session.profile = self._machine_definition.to_profile()
            self.adapter = Grbl11Adapter() if self._machine_definition.controller.value == "grbl_1_1" else GenericGrblAdapter()
            self.probing = ProbingService(self.session, self.adapter, self.connection_service.send_line, on_notice=self._publish_notice)
            self.tool_setting = ToolSettingService(self.session, self.adapter, self.connection_service.send_line, self._publish_notice)
            self.fixtures = FixtureService(self.session, self.adapter, self.connection_service.send_line, self._publish_notice)
            self.session.invalidate_reference("Machine profile changed")
            self._saved_work_zero = self.work_zero_store.load(self.machine_id)
            self._z_touch_plate_record = self.z_touch_plate_store.load(self.machine_id)
            self._z_touch_plate = ZTouchPlateWorkflow()
        except (OSError, ValueError, TypeError) as exc:
            return ActionOutcome(False, f"Machine selection failed — {exc}")
        return ActionOutcome(True, f"Selected machine {self._machine_definition.name}.")

    def save_capabilities(self, *, limit_switches: bool, z_plate: bool, tool_setter: bool,
                          movable_xyz: bool, fixed_fixture: bool) -> ActionOutcome:
        if self.simulation_active:
            return ActionOutcome(False, "Hardware capability changes are disabled in the digital twin")
        if (self.motion_busy or self.job_active or self.manual_pending_acks
                or self.probing.active or self.homing.active):
            return ActionOutcome(False, "Machine capabilities require no active machine operation.")
        if self.connected and (self.status is None or not self.status.can_jog):
            return ActionOutcome(False, "GRBL must be Idle before changing machine capabilities.")
        if self.machine_catalog is None or self._machine_definition is None:
            return ActionOutcome(False, "Machine catalog is unavailable for this controller instance.")
        axes = self._machine_definition.axes
        if limit_switches:
            axes = {
                axis: replace(item, switch_mode=SwitchMode.SINGLE, input_pin=item.input_pin or axis)
                for axis, item in axes.items()
            }
        else:
            axes = {
                axis: replace(item, switch_mode=SwitchMode.NONE, input_pin=None, hard_limit=False)
                for axis, item in axes.items()
            }
        existing = {probe.kind: probe for probe in self._machine_definition.probes}
        from ..machine_config import ProbeDefinition, ProbeKind
        probes = []
        for kind, is_enabled in (
            (ProbeKind.MOVABLE_Z_PLATE, z_plate),
            (ProbeKind.FIXED_TOOL_SETTER, tool_setter),
            (ProbeKind.MOVABLE_XYZ, movable_xyz),
            (ProbeKind.FIXED_XYZ, fixed_fixture),
        ):
            probe = existing.get(kind, ProbeDefinition(kind))
            probe = replace(probe, enabled=bool(is_enabled))
            if is_enabled or kind in existing:
                probes.append(probe)
        updated = replace(self._machine_definition, axes=axes, probes=tuple(probes))
        if updated.fingerprint() == self._machine_definition.fingerprint():
            return ActionOutcome(True, "Machine capabilities unchanged")
        try:
            updated.validate()
            self.machine_catalog = self.machine_catalog_store.upsert(self.machine_catalog, updated)
        except (OSError, ValueError, TypeError) as exc:
            return ActionOutcome(False, f"Capability configuration rejected — {exc}")
        self._machine_definition = updated
        self.session.invalidate_reference("Machine capabilities changed; recommission homing and home the machine")
        return ActionOutcome(True, "Machine capabilities saved; commissioning evidence and session reference require review.")

    def save_z_plate_capability(self, enabled: bool) -> ActionOutcome:
        """Save the currently supported capability without touching hidden ones."""
        if self.simulation_active:
            return ActionOutcome(False, "Hardware capability changes are disabled in the digital twin")
        if (self.motion_busy or self.job_active or self.manual_pending_acks
                or self.probing.active or self.homing.active):
            return ActionOutcome(False, "Machine capabilities require no active machine operation.")
        if self.connected and (self.status is None or not self.status.can_jog):
            return ActionOutcome(False, "GRBL must be Idle before changing machine capabilities.")
        if self.machine_catalog is None or self._machine_definition is None:
            return ActionOutcome(False, "Machine catalog is unavailable for this controller instance.")
        existing = list(self._machine_definition.probes)
        found = False
        updated_probes: list[ProbeDefinition] = []
        for probe in existing:
            if probe.kind is ProbeKind.MOVABLE_Z_PLATE:
                updated_probes.append(replace(probe, enabled=enabled))
                found = True
            else:
                updated_probes.append(probe)
        if enabled and not found:
            updated_probes.append(ProbeDefinition(
                ProbeKind.MOVABLE_Z_PLATE, enabled=True,
                plate_thickness=DEFAULT_Z_TOUCH_PLATE_THICKNESS,
            ))
        updated = replace(self._machine_definition, probes=tuple(updated_probes))
        if updated.fingerprint() == self._machine_definition.fingerprint():
            return ActionOutcome(True, "Z touch plate capability unchanged")
        try:
            updated.validate()
            self.machine_catalog = self.machine_catalog_store.upsert(self.machine_catalog, updated)
        except (OSError, ValueError, TypeError) as exc:
            return ActionOutcome(False, f"Z touch plate configuration rejected — {exc}")
        self._machine_definition = updated
        self.session.invalidate_reference("Z touch plate capability changed; recommission homing and home the machine")
        return ActionOutcome(True, "Z touch plate capability saved. Configure and test it before probing.")

    def save_probe_capabilities(self, *, z_plate: bool, tool_setter: bool,
                                movable_xyz: bool, fixed_xyz: bool) -> ActionOutcome:
        """Save every declared probe kind without changing axis declarations.

        The focused Setup editor uses this boundary instead of the legacy
        all-capabilities helper so editing probe choices cannot silently reset
        per-axis pins, polarity, debounce, or hard-limit settings.
        """
        if self.simulation_active:
            return ActionOutcome(False, "Hardware probe capability changes are disabled in the digital twin")
        if (self.motion_busy or self.job_active or self.manual_pending_acks
                or self.probing.active or self.homing.active):
            return ActionOutcome(False, "Probe capabilities require no active machine operation.")
        if self.connected and (self.status is None or not self.status.can_jog):
            return ActionOutcome(False, "GRBL must be Idle before changing probe capabilities.")
        if self.machine_catalog is None or self._machine_definition is None:
            return ActionOutcome(False, "Machine catalog is unavailable for this controller instance.")

        enabled = {
            ProbeKind.MOVABLE_Z_PLATE: bool(z_plate),
            ProbeKind.FIXED_TOOL_SETTER: bool(tool_setter),
            ProbeKind.MOVABLE_XYZ: bool(movable_xyz),
            ProbeKind.FIXED_XYZ: bool(fixed_xyz),
        }
        existing = {probe.kind: probe for probe in self._machine_definition.probes}
        probes = []
        for kind, is_enabled in enabled.items():
            probe = existing.get(kind)
            if probe is None:
                probe = ProbeDefinition(kind, enabled=is_enabled)
            else:
                probe = replace(probe, enabled=is_enabled)
            if is_enabled or probe.kind in existing:
                probes.append(probe)
        updated = replace(self._machine_definition, probes=tuple(probes))
        try:
            updated.validate()
            if updated.fingerprint() == self._machine_definition.fingerprint():
                return ActionOutcome(True, "Probe capabilities unchanged")
            self.machine_catalog = self.machine_catalog_store.upsert(self.machine_catalog, updated)
        except (OSError, ValueError, TypeError) as exc:
            return ActionOutcome(False, f"Probe capability configuration rejected — {exc}")
        self._machine_definition = updated
        self.session.invalidate_reference("Probe capabilities changed; recommission homing and home the machine")
        return ActionOutcome(True, "Probe capabilities saved; commissioning and session reference require review.")

    def save_probe_configuration(self, *, z_plate: bool, tool_setter: bool,
                                 movable_xyz: bool, fixed_xyz: bool,
                                 plate_thickness: float, active_low: bool,
                                 fast_feed: float, slow_feed: float,
                                 max_search: float, retract: float,
                                 safe_retract: float, tolerance: float) -> ActionOutcome:
        """Validate and persist one complete probe draft atomically."""
        if self.simulation_active:
            return ActionOutcome(False, "Hardware probe configuration changes are disabled in the digital twin")
        if (self.motion_busy or self.job_active or self.manual_pending_acks
                or self.probing.active or self.homing.active):
            return ActionOutcome(False, "Probe configuration requires no active machine operation.")
        if self.connected and (self.status is None or not self.status.can_jog):
            return ActionOutcome(False, "GRBL must be Idle before changing probe configuration.")
        if self.machine_catalog is None or self._machine_definition is None:
            return ActionOutcome(False, "Machine catalog is unavailable for this controller instance.")
        enabled = {
            ProbeKind.MOVABLE_Z_PLATE: bool(z_plate),
            ProbeKind.FIXED_TOOL_SETTER: bool(tool_setter),
            ProbeKind.MOVABLE_XYZ: bool(movable_xyz),
            ProbeKind.FIXED_XYZ: bool(fixed_xyz),
        }
        existing = {probe.kind: probe for probe in self._machine_definition.probes}
        probes: list[ProbeDefinition] = []
        try:
            for kind, is_enabled in enabled.items():
                probe = existing.get(kind, ProbeDefinition(kind))
                if kind is ProbeKind.MOVABLE_Z_PLATE:
                    probe = replace(
                        probe, enabled=is_enabled, plate_thickness=float(plate_thickness),
                        active_low=bool(active_low), fast_feed=float(fast_feed),
                        slow_feed=float(slow_feed), max_search=float(max_search),
                        retract=float(retract), safe_retract=float(safe_retract),
                        tolerance=float(tolerance),
                    )
                else:
                    probe = replace(probe, enabled=is_enabled)
                probes.append(probe)
            updated = replace(self._machine_definition, probes=tuple(probes))
            updated.validate()
        except (TypeError, ValueError, OverflowError) as exc:
            return ActionOutcome(False, f"Probe configuration rejected — {exc}")
        if updated.fingerprint() == self._machine_definition.fingerprint():
            return ActionOutcome(True, "Probe configuration unchanged")
        try:
            catalog = self.machine_catalog_store.upsert(self.machine_catalog, updated)
        except (OSError, ValueError, TypeError) as exc:
            return ActionOutcome(False, f"Probe configuration could not be saved — {exc}")
        self.machine_catalog = catalog
        self._machine_definition = updated
        self.session.invalidate_reference("Probe configuration changed; recommission homing and home the machine")
        return ActionOutcome(True, "Probe configuration saved atomically; commissioning and reference require review.")

    def save_z_touch_plate_settings(self, *, plate_thickness: float, active_low: bool,
                                    fast_feed: float, slow_feed: float, max_search: float,
                                    retract: float, safe_retract: float, tolerance: float) -> ActionOutcome:
        if self.simulation_active:
            return ActionOutcome(False, "Probe configuration changes are disabled in the digital twin")
        definition = self.z_touch_plate_definition
        if definition is None:
            return ActionOutcome(False, "Enable the movable Z touch plate first.")
        if self.motion_busy or self.job_active or self.manual_pending_acks:
            return ActionOutcome(False, "Z touch plate settings require no active machine operation.")
        if self.connected and (self.status is None or not self.status.can_jog):
            return ActionOutcome(False, "GRBL must be Idle before changing probe polarity.")
        try:
            updated_probe = replace(
                definition, plate_thickness=float(plate_thickness), active_low=bool(active_low),
                fast_feed=float(fast_feed), slow_feed=float(slow_feed), max_search=float(max_search),
                retract=float(retract), safe_retract=float(safe_retract), tolerance=float(tolerance),
            )
            updated_probe.validate()
            updated = replace(self._machine_definition, probes=tuple(
                updated_probe if probe.kind is ProbeKind.MOVABLE_Z_PLATE else probe
                for probe in self._machine_definition.probes
            ))
            updated.validate()
            assert self.machine_catalog is not None
            if updated.fingerprint() == self._machine_definition.fingerprint():
                return ActionOutcome(True, "Z touch plate settings unchanged")
            self.machine_catalog = self.machine_catalog_store.upsert(self.machine_catalog, updated)
        except (OSError, ValueError, TypeError) as exc:
            return ActionOutcome(False, f"Z touch plate settings rejected — {exc}")
        self._machine_definition = updated
        self.session.invalidate_reference("Z touch plate settings changed; recommission homing and home the machine")
        if not self.connected:
            return ActionOutcome(
                True,
                "Z touch plate settings saved. Connect while Idle and save again to apply GRBL $6.",
            )
        try:
            self.send_manual(self.adapter.setting_command(6, 1 if active_low else 0))
        except (RuntimeError, ValueError) as exc:
            return ActionOutcome(False, f"Settings saved, but GRBL $6 was not applied — {exc}")
        return ActionOutcome(
            True,
            f"Z touch plate settings saved; GRBL $6 set to {1 if active_low else 0}. Retest the input before probing.",
        )

    def home_machine(self) -> ActionOutcome:
        homing = self._homing_input_motion_allowed("Homing")
        if not homing.accepted:
            return homing
        status = self.status
        spindle_off = status is None or status.spindle in (None, 0)
        return self.homing.start(self.machine_definition, connected=self.connected, spindle_off=spindle_off)

    def start_probe(self, plan: ProbePlan) -> ActionOutcome:
        homing = self._homing_input_motion_allowed("Probe")
        if not homing.accepted:
            return homing
        status = self.status
        spindle_off = status is None or status.spindle in (None, 0)
        return self.probing.start(plan, connected=self.connected, spindle_off=spindle_off)

    def abort_probe(self, reason: str = "Aborted by operator") -> ActionOutcome:
        """Stop an active probe transaction through the guarded reset path."""
        if not self.probing.active:
            return ActionOutcome(False, "Probe abort ignored — no probe is active")
        reset_sent = False
        try:
            self.send_realtime(REALTIME_HOLD)
            self.send_realtime(REALTIME_SOFT_RESET)
            reset_sent = True
        except RuntimeError as exc:
            self._publish_notice(f"Probe stop signal could not be sent — {exc}")
        self._preserve_reference_on_next_reset = reset_sent
        self.probing.cancel()
        self._z_probe_pending = False
        self._z_probe_offset_confirmed = False
        self._z_commissioning_pending = False
        self._work_zero_request_pending_ack = False
        self._work_zero_expected_offset = None
        self._work_zero_expected_axes = ""
        suffix = "; wait for the reset status before moving, then retry" if reset_sent else "; reconnect before moving, then retry"
        message = f"Probe aborted ({reason}) — no work offset was changed{suffix}"
        self._publish_notice(message)
        return ActionOutcome(True, message)

    @property
    def auto_xyz_calibration_state(self) -> str:
        return self.calibration.state.value

    @property
    def auto_xyz_calibration_status(self) -> str:
        return self.calibration.status_text

    def start_auto_xyz_calibration(self, seed: tuple[float, float, float], *,
                                   definition=None, commissioning_record=None) -> ActionOutcome:
        """Start the commissioned calibration transaction over ordinary GRBL traffic."""
        homing = self._homing_input_motion_allowed("Auto XYZ calibration")
        if not homing.accepted:
            return homing
        definition = definition or (self._simulation_plate_definition if self.simulation_active
                                    else CalibrationPlateDefinition())
        if commissioning_record is None and self.simulation_active:
            commissioning_record = self._simulation_plate_record
        status = self.status
        spindle = 0.0 if status is None or status.spindle is None else status.spindle
        envelope = (self.profile.travel_x, self.profile.travel_y, self.profile.travel_z)
        return self.calibration.start(
            seed=tuple(float(value) for value in seed), definition=definition,
            commissioning_record=commissioning_record,
            reference_trusted=self.reference_trusted,
            controller_idle=bool(status and status.state == "Idle"),
            spindle_rpm=spindle, envelope=envelope)

    def abort_auto_xyz_calibration(self) -> ActionOutcome:
        return self.calibration.abort()

    def start_z_touch_plate_input_test(self) -> ActionOutcome:
        if not self.z_touch_plate_definition:
            return ActionOutcome(False, "Enable the movable Z touch plate first.")
        if not self.connected or self.status is None or not self.status.can_jog:
            return ActionOutcome(False, "Connect to GRBL and wait for Idle before testing the Z touch plate input.")
        if self.job_active or self.motion_busy or self.manual_pending_acks:
            return ActionOutcome(False, "The Z touch plate input test requires no other machine operation.")
        self._z_touch_plate.start_input_test(self.status.pins)
        return ActionOutcome(True, self._z_touch_plate.input_result.message)

    def _z_touch_plate_probe_direction(self) -> int:
        """Return the machine-coordinate direction from Z home toward the plate.

        The TTC plate is below the X/Y home corner, so the built-in plate
        workflow probes away from the declared Z homing end. For this machine
        Z homes at the maximum end: homing still travels in the already
        commissioned controller direction, while the plate is reached in
        negative machine Z.
        """
        z_axis = self.machine_definition.axes["Z"]
        return 1 if z_axis.switch_end is MachineAxisEnd.MIN else -1

    def _check_z_touch_plate_probe_envelope(
        self, distances: tuple[float, ...], operation: str,
    ) -> ActionOutcome | None:
        """Check a probe search and its follow-up moves as one path.

        Retracts are evaluated from the post-touch position, not from the
        pre-probe position. This matters when probing starts exactly at a
        virtual envelope boundary, as it does after minimum-end Z homing.
        """
        current = self.session.virtual_position
        if current is None:
            return ActionOutcome(False, f"{operation} probe requires a trusted machine position.")
        for distance in distances:
            proposed = current.z + distance
            if proposed < -0.001 or proposed > self.profile.travel_z + 0.001:
                return ActionOutcome(
                    False,
                    f"{operation} probe is outside the virtual envelope — "
                    f"Z jog would end at {proposed:.3f} mm; allowed range is 0.000 to "
                    f"{self.profile.travel_z:.3f} mm",
                )
            current = Position(current.x, current.y, proposed)
        return None

    def start_z_touch_plate_commissioning_sample(self) -> ActionOutcome:
        homing = self._homing_input_motion_allowed("Z touch commissioning")
        if not homing.accepted:
            return homing
        definition = self.z_touch_plate_definition
        if definition is None:
            return ActionOutcome(False, "Enable the movable Z touch plate first.")
        if not self._z_touch_plate.input_tested and not (self._z_touch_plate_record and self._z_touch_plate_record.input_tested):
            return ActionOutcome(False, "Pass the no-motion Z touch plate input test first.")
        if self.status is None or not self.status.can_jog or self.status.spindle not in (None, 0):
            return ActionOutcome(False, "GRBL must be Idle with the spindle off before commissioning.")
        if self.probing.active or self.motion_busy or self.job_active or self.manual_pending_acks:
            return ActionOutcome(False, "Another machine operation is active.")
        if self.status.pins and "P" in self.status.pins.upper():
            return ActionOutcome(False, "The touch plate input must be open before probing.")
        if not self.reference_trusted:
            return ActionOutcome(False, "Home the machine to establish a trusted reference before commissioning.")
        probe_direction = self._z_touch_plate_probe_direction()
        envelope_failure = self._check_z_touch_plate_probe_envelope((
            probe_direction * definition.max_search,
            -probe_direction * definition.retract,
            -probe_direction * definition.safe_retract,
        ), "Commissioning")
        if envelope_failure is not None:
            return envelope_failure
        slow_distance = probe_direction * min(definition.max_search, max(0.5, definition.max_search / 5))
        outcome = self.probing.start(ProbePlan(
            "Z", probe_direction * definition.max_search, slow_distance, definition.retract, definition.safe_retract,
            definition.fast_feed, definition.slow_feed, definition.fast_feed,
            purpose="commissioning", transaction_id=secrets.token_urlsafe(12),
            retract_direction=-probe_direction,
        ), connected=self.connected, spindle_off=True)
        if outcome.accepted:
            self._z_commissioning_pending = True
        return outcome

    @property
    def z_probe_completion_snapshot(self) -> dict:
        return dict(self._z_probe_completion)

    def _fail_z_probe_completion(self, reason: str) -> None:
        was_lowering = self._z_probe_completion.get("state") == "lowering"
        self._z_probe_completion.update(state="failed", message=reason)
        self._z_probe_completion_context = None
        self._z_probe_descent_ack = False
        self.session.invalidate_work_zero(reason)
        self._clear_saved_work_zero("Z")
        if was_lowering:
            try:
                self.cancel_jog()
            except (RuntimeError, ValueError):
                pass
        self._publish_notice(reason)

    def _z_probe_frame_matches(self, status: GrblStatus) -> bool:
        import math
        frame = self._z_probe_completion_context
        if not frame or frame["generation"] != self._session_generation:
            return False
        if not self.reference_trusted or frame["reference"] != self.session.envelope.reference:
            return False
        if frame["fingerprint"] != self.z_touch_plate_fingerprint:
            return False
        pos, offset = status.machine_position, self.session.work_offset
        if pos is None or offset is None:
            return False
        if not all(math.isfinite(v) for v in (pos.x,pos.y,pos.z,offset.x,offset.y,offset.z)):
            return False
        if abs(pos.x-frame["xy"][0]) > 0.01 or abs(pos.y-frame["xy"][1]) > 0.01:
            return False
        expected = frame.get("offset")
        return expected is not None and all(abs(a-b) <= 0.001 for a,b in zip(
            (offset.x,offset.y,offset.z), expected))

    def _observe_z_probe_completion(self, status: GrblStatus) -> None:
        state = self._z_probe_completion.get("state")
        frame = self._z_probe_completion_context
        if not frame or not self.status_fresh:
            return
        if state == "probing" and frame.get("retract_ack"):
            if status.state.split(":")[0] in {"Alarm", "Door", "Hold"} or status.spindle != 0:
                self._fail_z_probe_completion("Probe retract could not confirm a safe spindle-off Idle state")
                return
            if not self._z_probe_frame_matches(status):
                self._fail_z_probe_completion("Z probe result changed; probe Z again before continuing")
                return
            if status.state == "Idle" and status.spindle == 0 and "P" not in status.pins.upper():
                if abs(status.machine_position.z-frame["retracted_z"]) <= 0.05:
                    self._z_probe_completion.update(state="waiting-removal",
                        message="Z zero verified. Remove the puck and clip, then Continue to lower to work Z0.")
        elif state == "lowering":
            if not self._z_probe_frame_matches(status) or status.spindle != 0 or "P" in status.pins.upper() or status.state in {"Alarm", "Door", "Hold"}:
                self._fail_z_probe_completion("Z descent stopped because the machine state changed")
                return
            if self._z_probe_descent_ack and status.state == "Idle" and abs(status.machine_position.z-frame["offset"][2]) <= 0.01:
                self._z_plate_removal_required = False
                self._z_probe_completion.update(state="complete", current_work_z=0.0,
                    message="Z probe complete: tool is at work Z0. XY is unchanged; spindle is off.")
                self._z_probe_completion_context = None

    def poll_z_probe_completion(self) -> None:
        frame = self._z_probe_completion_context
        if frame and self._z_probe_completion.get("state") in {"lowering", "probing"} and frame.get("deadline") and time.monotonic() > frame["deadline"]:
            self._fail_z_probe_completion("Z descent did not confirm its target; inspect the position before retrying")

    def continue_z_probe_to_surface(self, transaction_id: str | None = None) -> ActionOutcome:
        import math
        if self._z_probe_completion.get("state") != "waiting-removal" or not self._z_plate_removal_required:
            return ActionOutcome(False, "No verified Z-probe result is waiting for puck removal")
        current_transaction = str(self._z_probe_completion.get("transaction_id", ""))
        if transaction_id is not None and transaction_id != current_transaction:
            return ActionOutcome(False, "The displayed probe result is no longer current; review the latest result before continuing")
        ready = self._motion_operation_allowed()
        if not ready.accepted:
            return ready
        status = self.status
        if not self.status_fresh or status is None or status.state != "Idle" or status.spindle != 0 or status.feed not in (None, 0):
            return ActionOutcome(False, "Wait for fresh Idle with the spindle off before lowering to Z0")
        if "P" in status.pins.upper():
            return ActionOutcome(False, "The probe input is still active; remove the puck and clip")
        if not self._z_probe_frame_matches(status):
            self._fail_z_probe_completion("Position, tool setup or work zero changed; probe Z again")
            return ActionOutcome(False, self._z_probe_completion["message"])
        frame = self._z_probe_completion_context
        delta = frame["offset"][2] - status.machine_position.z
        feed = frame["feed"]
        if not math.isfinite(delta) or not math.isfinite(feed) or feed <= 0 or delta*frame["direction"] < -0.001:
            return ActionOutcome(False, "Calculated Z0 is not toward the probed surface; probe Z again")
        if abs(delta) <= 0.001:
            self._z_plate_removal_required = False
            self._z_probe_completion.update(state="complete", current_work_z=0.0,
                message="Tool is already at verified work Z0; XY unchanged and spindle off")
            self._z_probe_completion_context = None
            return ActionOutcome(True, self._z_probe_completion["message"])
        outcome = self.motion.jog("Z", delta, feed)
        if outcome.accepted:
            self._z_probe_descent_ack = False
            frame["deadline"] = time.monotonic() + 10 + 120*abs(delta)/feed
            self._z_probe_completion.update(state="lowering", message="Lowering straight down to calculated work Z0; spindle off")
        return outcome

    def acknowledge_z_touch_plate_removed(self) -> ActionOutcome:
        if self._z_probe_completion.get("state") in {"probing", "waiting-removal", "lowering"}:
            return ActionOutcome(False, "Use Continue to work Z0 in the probe-result dialog")
        if not self._z_plate_removal_required:
            return ActionOutcome(False, "No touch plate removal acknowledgement is pending.")
        self._z_plate_removal_required = False
        self._z_probe_completion_context = None
        self._z_probe_completion.update(state="idle", message="Puck removal acknowledged; no descent requested")
        return ActionOutcome(True, "Touch plate and clip removal acknowledged; the machine is ready for the next job.")

    def save_z_touch_plate_commissioning(self, samples: tuple[float, ...]) -> ActionOutcome:
        definition = self.z_touch_plate_definition
        if definition is None:
            return ActionOutcome(False, "Enable the movable Z touch plate first.")
        if not self._z_touch_plate.input_tested and not (self._z_touch_plate_record and self._z_touch_plate_record.input_tested):
            return ActionOutcome(False, "Pass the no-motion Z touch plate input test first.")
        try:
            record = ZTouchPlateRecord.commissioned_record(
                self.machine_id or "", tuple(float(value) for value in samples), definition.tolerance,
                self.z_touch_plate_fingerprint,
            )
            record.validate()
            self.z_touch_plate_store.save(record)
        except (OSError, ValueError, TypeError) as exc:
            return ActionOutcome(False, f"Z touch plate commissioning rejected — {exc}")
        self._z_touch_plate_record = record
        return ActionOutcome(True, "Z touch plate commissioning saved; workpiece probing is ready.")

    def probe_work_z(self) -> ActionOutcome:
        homing = self._homing_input_motion_allowed("Work-Z probe")
        if not homing.accepted:
            return homing
        definition = self.z_touch_plate_definition
        record = self._z_touch_plate_record
        if definition is None:
            return ActionOutcome(False, "Enable the movable Z touch plate first.")
        if self.z_touch_plate_status != "ready":
            return ActionOutcome(False, f"Z touch plate is {self.z_touch_plate_status.replace('_', ' ')}.")
        if self.status is None or not self.status.can_jog:
            return ActionOutcome(False, "GRBL must be Idle before probing work Z.")
        if self.status.spindle not in (None, 0):
            return ActionOutcome(False, "Turn the spindle off before probing work Z.")
        if self.probing.active or self.motion_busy or self.job_active or self.manual_pending_acks:
            return ActionOutcome(False, "Another machine operation is active.")
        if self.status.pins and "P" in self.status.pins.upper():
            return ActionOutcome(False, "The touch plate input must be open before probing.")
        current = self.session.machine_position
        if current is None or not self.reference_trusted:
            return ActionOutcome(False, "Home the machine to establish a trusted reference before probing work Z.")
        probe_direction = self._z_touch_plate_probe_direction()
        envelope_failure = self._check_z_touch_plate_probe_envelope((
            probe_direction * definition.max_search,
            -probe_direction * definition.retract,
            -probe_direction * definition.safe_retract,
        ), "Z")
        if envelope_failure is not None:
            return envelope_failure
        slow_distance = probe_direction * min(definition.max_search, max(0.5, definition.max_search / 5))
        plan = ProbePlan(
            "Z", probe_direction * definition.max_search, slow_distance, definition.retract, definition.safe_retract,
            definition.fast_feed, definition.slow_feed, definition.fast_feed,
            wcs_slot=1, offset_axis="Z", offset_value=definition.plate_thickness,
            purpose="work_z", transaction_id=secrets.token_urlsafe(12),
            retract_direction=-probe_direction,
        )
        outcome = self.probing.start(plan, connected=self.connected, spindle_off=True)
        if outcome.accepted:
            self._z_probe_pending = True
            self._z_probe_offset_confirmed = False
            self._z_probe_completion_context = {
                "generation": self._session_generation, "reference": self.session.envelope.reference,
                "fingerprint": self.z_touch_plate_fingerprint, "xy": (current.x, current.y),
                "direction": probe_direction, "feed": definition.slow_feed, "retract_ack": False,
            }
            self._z_probe_completion = {"state": "probing", "message": "Probing Z and verifying the measured work offset",
                "plate_thickness": definition.plate_thickness, "target_work_z": 0.0,
                "transaction_id": plan.transaction_id}
        return outcome

    def save_step_prepare_settings(self, settings: StepPrepareSettings) -> None:
        settings.validate()
        self.step_prepare_store.save(settings)
        self.step_prepare_settings = settings

    def invalidate_machine_reference(self, reason: str = "Manually invalidated") -> None:
        self.session.invalidate_reference(reason)

    def disconnect(self, reason: str | None = None) -> ConnectionOutcome:
        was_simulation = self.simulation_active
        self.wifi_setup.cancel()
        outcome = self.connection_service.disconnect()
        self.motion.reset()
        self.job.reset()
        self.calibration.reset()
        self.homing.reset(outcome.message)
        self.probing.reset()
        self._z_probe_pending = False
        self._z_probe_offset_confirmed = False
        self._z_commissioning_pending = False
        self._z_plate_removal_required = False
        self.tool_setting.reset()
        self.fixtures.reset()
        self.manual_pending_acks = 0
        self._work_zero_request_pending_ack = False
        self._work_zero_expected_offset = None
        self._work_zero_expected_axes = ""
        self._preserve_reference_on_next_reset = False
        self.status = None
        self._last_status_received_at = 0.0
        self._status_generation = -1
        self._job_nonce = ""
        self._begin_session_generation()
        self.session.clear_status()
        self.session.invalidate_reference(reason or outcome.message)
        if was_simulation:
            self._simulation_plate_record = None
            self._saved_work_zero = self._simulation_physical_saved_work_zero
            self._simulation_saved_work_zero = None
            self._simulation_physical_saved_work_zero = None
        return outcome

    def establish_reference(self) -> ActionOutcome:
        return self.session.establish_reference()

    def invalidate_reference(self, reason: str = "Manually invalidated") -> None:
        self.session.invalidate_reference(reason)

    def invalidate_safety_trust(self, reason: str = "Independent safety input changed") -> None:
        """Invalidate every software trust record after an external safety trip."""
        self._invalidate_job_start_authorization()
        self.session.invalidate_reference(reason)
        self.calibration.reset()
        self._z_commissioning_pending = False
        # A calibration record is evidence for the current safe session only;
        # an independent E-stop requires it to be re-established.
        self._simulation_plate_record = None

    def jog(self, axis: str, distance: float, feed: float = 500.0) -> ActionOutcome:
        blocked = self._motion_operation_allowed()
        if not blocked.accepted:
            return blocked
        return self.motion.jog(axis, distance, feed)

    def start_live_jog(self, axis: str, direction: float, allow_unreferenced: bool, feed: float = 500.0, *, lease_token: str | None = None) -> ActionOutcome:
        blocked = self._motion_operation_allowed()
        if not blocked.accepted:
            return blocked
        return self.motion.start_live_jog(axis, direction, allow_unreferenced, feed, lease_token=lease_token)

    def poll_live_jog(self) -> None:
        if self.motion.live_jog_axis is not None and (
            not self.connected or not self.status_fresh or not self.homing_inputs_safe
            or not self.operation_transport_ready or self.job_active
        ):
            self.motion.stop_live_jog()
            return
        self.motion.poll_live_jog()

    def renew_live_jog(self, token: str) -> ActionOutcome:
        renewed = self.motion.renew_live_jog(token)
        return ActionOutcome(renewed, "Jog hold renewed" if renewed else "Jog hold ended; press again to jog")

    def stop_live_jog(self) -> ActionOutcome:
        return self.motion.stop_live_jog()

    def cancel_jog(self) -> None:
        if self._z_probe_completion.get("state") == "lowering":
            self._fail_z_probe_completion("Z descent canceled; verify the tool position")
        self.motion.cancel()
        self.send_realtime(REALTIME_JOG_CANCEL)

    def move_to(self, target: Position, feed: float = 500.0) -> ActionOutcome:
        blocked = self._motion_operation_allowed()
        if not blocked.accepted:
            return blocked
        return self.motion.move_to(target, feed)

    def return_to_reference(self, feed: float = 500.0) -> ActionOutcome:
        blocked = self._motion_operation_allowed()
        if not blocked.accepted:
            return blocked
        return self.motion.return_to_reference(feed)

    def return_to_work_zero(self, feed: float = 500.0) -> ActionOutcome:
        blocked = self._motion_operation_allowed()
        if not blocked.accepted:
            return blocked
        if self.session.awaiting_work_zero_report or self._work_zero_request_pending_ack:
            return ActionOutcome(False, "Wait for the updated work-zero report before returning.")
        persisted = None
        saved = self._saved_work_zero
        current = self.session.machine_position
        if saved is not None and {"X", "Y"} <= saved.confirmed_axes and current is not None:
            # A partial saved record can define the XY origin, but its Z value
            # is not a target unless Z was separately confirmed. Keep the
            # current machine Z while returning to the saved XY origin.
            z = saved.z if "Z" in saved.confirmed_axes else current.z
            persisted = Position(saved.x, saved.y, z)
        return self.motion.return_to_work_zero(feed, persisted)

    def set_work_zero(self, axes: str) -> ActionOutcome:
        if not self.operation_transport_ready:
            return ActionOutcome(False, "Work zero requires verified Wi-Fi; USB is setup only")
        if not self.connected:
            return ActionOutcome(False, "Work-zero command ignored — not connected")
        if self.job_active:
            return ActionOutcome(False, "Work-zero command ignored — a job is active")
        if self.motion_busy or self.manual_pending_acks:
            return ActionOutcome(False, "Work-zero command ignored — another machine operation is active")
        if not self.session.can_move:
            return ActionOutcome(False, "Work-zero command ignored — GRBL is not Idle")
        normalized = "".join(axis for axis in "XYZ" if axis in axes.upper())
        machine_position = self.session.machine_position
        previous_offset = self.session.work_offset
        outcome = self.session.request_work_zero_confirmation(axes)
        if not outcome.accepted:
            return outcome
        try:
            if machine_position is not None:
                base_offset = previous_offset or Position(0.0, 0.0, 0.0)
                expected = [base_offset.x, base_offset.y, base_offset.z]
                for index, axis in enumerate("XYZ"):
                    if axis in normalized:
                        expected[index] = getattr(machine_position, axis.lower())
                self._work_zero_expected_offset = Position(*expected)
                self._work_zero_expected_axes = normalized
            self._work_zero_request_pending_ack = True
            self.send_manual(make_work_zero(axes))
        except (RuntimeError, ValueError) as exc:
            self._work_zero_request_pending_ack = False
            self._work_zero_expected_offset = None
            self._work_zero_expected_axes = ""
            self.session.invalidate_work_zero()
            return ActionOutcome(False, f"Work zero not sent — {exc}")
        return outcome

    def start_spindle(self, rpm: int) -> ActionOutcome:
        if not self.can_jog:
            return ActionOutcome(False, "Spindle start ignored — machine is not ready or GRBL is not Idle")
        if not 1 <= rpm <= 24000:
            return ActionOutcome(False, "Spindle RPM must be between 1 and 24000")
        try:
            self.send_manual(f"M3 S{rpm}\n".encode("ascii"))
        except RuntimeError as exc:
            return ActionOutcome(False, f"Spindle start failed — {exc}")
        return ActionOutcome(True, f"Spindle start requested at {rpm} RPM")

    def stop_spindle(self) -> ActionOutcome:
        if not self.connected:
            return ActionOutcome(False, "Spindle stop ignored — not connected")
        try:
            self.send_manual(b"M5\n")
        except RuntimeError as exc:
            return ActionOutcome(False, f"Spindle stop failed — {exc}")
        return ActionOutcome(True, "Spindle stop requested")

    def soft_reset(self) -> ActionOutcome:
        if not self.connected:
            return ActionOutcome(False, "Soft reset ignored — not connected")
        try:
            self._preserve_reference_on_next_reset = False
            self.send_realtime(b"\x18")
        except RuntimeError as exc:
            return ActionOutcome(False, f"Soft reset failed — {exc}")
        return ActionOutcome(True, "Soft reset requested")

    def hold(self) -> ActionOutcome:
        try:
            self.send_realtime(b"!")
        except RuntimeError as exc:
            return ActionOutcome(False, f"Feed hold failed — {exc}")
        return ActionOutcome(True, "Feed hold requested")

    def resume(self) -> ActionOutcome:
        if not self.operation_transport_ready:
            return ActionOutcome(False, "Resume requires verified Wi-Fi; USB is setup only")
        try:
            self.send_realtime(b"~")
        except RuntimeError as exc:
            return ActionOutcome(False, f"Resume failed — {exc}")
        return ActionOutcome(True, "Resume requested")

    def close(self) -> None:
        was_simulation = self.simulation_active
        self.wifi_setup.cancel()
        outcome = self.connection_service.close()
        self.motion.reset()
        self.job.reset()
        self.calibration.reset()
        self.manual_pending_acks = 0
        self._work_zero_request_pending_ack = False
        self._work_zero_expected_offset = None
        self._work_zero_expected_axes = ""
        self._preserve_reference_on_next_reset = False
        self.status = None
        self._status_generation = -1
        self._job_nonce = ""
        self._begin_session_generation()
        self.session.clear_status()
        self.session.invalidate_reference(outcome.message)
        if was_simulation:
            self._simulation_plate_record = None
            self._saved_work_zero = self._simulation_physical_saved_work_zero
            self._simulation_saved_work_zero = None
            self._simulation_physical_saved_work_zero = None

    def send_manual(self, command: bytes) -> None:
        self.connection_service.send_line(command)
        self.manual_pending_acks += 1

    def send_line(self, command: bytes, display_text: str | None = None) -> None:
        """Send an application-approved line through the single transport owner."""
        self.connection_service.send_line(command, display_text=display_text)

    def send_realtime(self, command: bytes) -> None:
        self.connection_service.send_realtime(command)

    def apply_status(self, status: GrblStatus, *, session_generation: int | None = None) -> bool:
        if session_generation is not None and session_generation != self._session_generation:
            return False
        self.status = status
        self._last_status_received_at = time.monotonic()
        self._status_generation = self._session_generation
        enabled = [axis for axis, item in self.machine_definition.axes.items()
                   if item.switch_mode is SwitchMode.SINGLE]
        if enabled:
            wiring = {bool(self.machine_definition.axes[axis].active_low) for axis in enabled}
            if len(wiring) != 1:
                self._homing_input_observation = HomingInputInterpretation(
                    "unknown", status.pins, reason="Homing input polarity differs by axis; resolve NC/NO declarations before moving.")
            else:
                convention = SwitchWiring.NC if next(iter(wiring)) else SwitchWiring.NO
                observation = interpret_pn_transition(
                    self._homing_input_baseline_pins, status.pins, "".join(enabled), convention,
                    grbl_limit_inverted=(not self.simulation_active and convention is SwitchWiring.NC))
                if self._homing_input_baseline_pins is None and observation.state == "released":
                    self._homing_input_baseline_pins = observation.pins
                self._homing_input_observation = observation
        awaiting_confirmation = self.session.awaiting_work_zero_report
        expected = self._work_zero_expected_offset
        expected_axes = self._work_zero_expected_axes
        restored_work_zero = expected is None and self.session.awaiting_work_zero_report
        matching_work_zero = (
            expected is not None
            and bool(expected_axes)
            and status.work_offset is not None
            and all(
                abs(getattr(status.work_offset, axis.lower()) - getattr(expected, axis.lower())) <= 0.001
                for axis in expected_axes
            )
        )
        fresh_work_zero = restored_work_zero or matching_work_zero
        self.session.update_status(status, confirm_pending_work_zero=False)
        if fresh_work_zero:
            self.session.confirm_work_zero_axes(expected_axes or "XYZ")
        if fresh_work_zero:
            self._work_zero_expected_offset = None
            self._work_zero_expected_axes = ""
        input_result = self._z_touch_plate.observe_pins(status.pins)
        if input_result.passed and self.z_touch_plate_definition is not None:
            current = self._z_touch_plate_record
            if current is None or not current.input_tested or current.fingerprint != self.z_touch_plate_fingerprint:
                definition = self.z_touch_plate_definition
                updated_record = ZTouchPlateRecord(
                    self.machine_id or "", current.samples if current else (), definition.tolerance,
                    self.z_touch_plate_fingerprint, True, current.timestamp if current else "",
                )
                try:
                    self.z_touch_plate_store.save(updated_record)
                    self._z_touch_plate_record = updated_record
                except (OSError, ValueError, TypeError):
                    self._publish_notice("Z touch plate input passed, but the result could not be saved.")
        probing_state_before = self.probing.state
        self.homing.observe_status(status, self.machine_definition)
        self.travel_calibration.observe_status(status)
        self.probing.observe_status(status)
        if self._z_probe_pending and self.probing.state.value == "failed":
            reason = self.probing.failure_reason or "Z probe failed; no completion move is permitted"
            self._fail_z_probe_completion(reason)
            self._z_probe_pending = False
            self._z_probe_offset_confirmed = False
        calibration_failed = self.calibration.observe_status(status)
        if calibration_failed and self.calibration.state.value == "failed":
            self.manual_pending_acks = 0
            self.session.invalidate_work_zero("Auto XYZ calibration failed; work zero requires re-confirmation")
        if self.calibration.work_offset_confirmed:
            self.session.work_zero_confirmed = True
        if self._z_probe_pending and probing_state_before.value == "confirm_offset" and self.probing.state.value == "safe_retract":
            self._z_probe_offset_confirmed = True
        self.fixtures.observe_status(status)
        if status.work_offset is not None:
            if fresh_work_zero:
                self._save_work_zero(status.work_offset, expected_axes or self.session.pending_work_zero_axes or "XYZ")
            elif not awaiting_confirmation and self._saved_work_zero is not None:
                saved = self._saved_work_zero
                matching_axes = "".join(
                    axis for axis in "XYZ"
                    if axis in saved.confirmed_axes
                    and abs(getattr(status.work_offset, axis.lower()) - getattr(saved, axis.lower())) <= 0.001
                )
                if matching_axes:
                    # A fresh WCO report that still matches the saved
                    # machine-coordinate origin restores only those axes.
                    self.session.confirm_work_zero_axes(matching_axes)
        self.job.observe_status(status)
        self.motion.observe_status(status)
        self._observe_z_probe_completion(status)
        return True

    def _save_work_zero(self, offset: Position, axes: str = "XYZ") -> None:
        updated_axes = frozenset(axis for axis in "XYZ" if axis in axes.upper())
        previous = self._saved_work_zero
        coordinates = {
            axis: getattr(previous, axis.lower()) if previous is not None else 0.0
            for axis in "XYZ"
        }
        for axis in updated_axes:
            coordinates[axis] = getattr(offset, axis.lower())
        confirmed_axes = updated_axes | (previous.confirmed_axes if previous is not None else frozenset())
        saved = SavedWorkZero(
            coordinates["X"], coordinates["Y"], coordinates["Z"], confirmed_axes
        )
        if self.simulation_active:
            self._simulation_saved_work_zero = saved
            self._saved_work_zero = saved
            return
        try:
            self.work_zero_store.save(saved, self.machine_id)
        except OSError:
            self._publish_notice("Work zero confirmed, but it could not be saved for the next session")
            return
        self._saved_work_zero = saved

    def _clear_saved_work_zero(self, axes: str | None = None) -> None:
        saved = self._saved_work_zero
        if axes is not None and saved is not None:
            remaining = saved.confirmed_axes - frozenset(axes.upper())
            if remaining:
                saved = SavedWorkZero(saved.x, saved.y, saved.z, remaining)
            else:
                saved = None
        else:
            saved = None
        self._saved_work_zero = saved
        if self.simulation_active:
            self._simulation_saved_work_zero = saved
            return
        try:
            if saved is None:
                self.work_zero_store.clear(self.machine_id)
            else:
                self.work_zero_store.save(saved, self.machine_id)
        except OSError:
            self._publish_notice("Previous saved work-zero coordinates could not be updated")

    def handle_response(self, response: str, feed: float = 500.0) -> bool:
        """Dispatch one controller response to the owning application service."""
        text = response.strip()
        lowered = text.lower()
        calibration_ack = self.calibration.awaiting_ack and lowered == "ok"
        if self.travel_calibration.handle_response(text):
            return True
        if self.calibration.handle_response(text):
            if calibration_ack:
                self.manual_pending_acks = max(0, self.manual_pending_acks - 1)
            if self.calibration.state.value == "failed":
                self.manual_pending_acks = 0
                self.session.invalidate_work_zero("Auto XYZ calibration failed; work zero requires re-confirmation")
            return True
        if self.homing.handle_response(text):
            return True
        if self.probing.handle_response(text):
            if self._z_probe_pending and self.probing.state.value == "complete":
                if self._z_probe_offset_confirmed and self.session.work_offset is not None:
                    self.session.confirm_work_zero_axes("Z")
                    self._save_work_zero(self.session.work_offset, "Z")
                    self._z_probe_pending = False
                    self._z_probe_offset_confirmed = False
                    self._z_plate_removal_required = True
                    frame = self._z_probe_completion_context
                    report, plan = self.probing.slow_report, self.probing.plan
                    if frame is not None and report is not None and plan is not None:
                        import math
                        offset = self.session.work_offset
                        values = (report.x, report.y, report.z, offset.x, offset.y, offset.z, plan.safe_retract_distance)
                        if all(math.isfinite(v) for v in values):
                            frame.update(offset=(offset.x,offset.y,offset.z), retract_ack=True, deadline=time.monotonic()+10,
                                retracted_z=report.z+plan.retract_direction*plan.safe_retract_distance)
                            self._z_probe_completion.update(measured_machine_z=report.z,
                                message="Touch found and Z offset verified; waiting for safe retract and Idle")
                        else:
                            self._fail_z_probe_completion("Z probe returned invalid coordinates; probe Z again")
                    self._publish_notice("Work Z0 confirmed from the touch plate; remove the plate and clip before machining.")
            elif self._z_probe_pending and self.probing.state.value == "failed":
                self._fail_z_probe_completion("Z probe failed; no completion move is permitted")
                self._z_probe_pending = False
                self._z_probe_offset_confirmed = False
            elif self._z_commissioning_pending and self.probing.state.value == "complete":
                if self.probing.slow_report is not None:
                    self._z_touch_plate.add_sample(self.probing.slow_report.z)
                self._z_commissioning_pending = False
                if len(self._z_touch_plate.samples) == 3:
                    definition = self.z_touch_plate_definition
                    if definition is not None:
                        try:
                            record = ZTouchPlateRecord.commissioned_record(
                                self.machine_id or "", tuple(self._z_touch_plate.samples), definition.tolerance,
                                self.z_touch_plate_fingerprint, input_tested=True,
                            )
                            record.validate()
                            self.z_touch_plate_store.save(record)
                            self._z_touch_plate_record = record
                            self._publish_notice("Z touch plate commissioning passed and was saved.")
                        except (OSError, ValueError, TypeError) as exc:
                            self._z_touch_plate.samples.clear()
                            self._publish_notice(f"Z touch plate commissioning failed — {exc}")
                else:
                    self._publish_notice(f"Z touch plate sample {len(self._z_touch_plate.samples)} of 3 recorded.")
            elif self._z_commissioning_pending and self.probing.state.value == "failed":
                self._z_commissioning_pending = False
            return True
        if self.tool_setting.handle_response(text):
            return True
        if self._z_probe_completion.get("state") == "lowering":
            if lowered.startswith(("error:", "alarm:")):
                self._fail_z_probe_completion("Z descent failed: " + text)
            elif lowered == "ok" and self.motion.pending_acks:
                self._z_probe_descent_ack = True
        if self.motion.handle_response(text, feed):
            return True
        if self.manual_pending_acks and (lowered == "ok" or lowered.startswith("error:") or lowered.startswith("alarm:")):
            self.manual_pending_acks -= 1
            if self._work_zero_request_pending_ack:
                self._work_zero_request_pending_ack = False
                if lowered != "ok":
                    self._work_zero_expected_offset = None
                    self._work_zero_expected_axes = ""
                    self.session.invalidate_work_zero()
            return True
        return self.job.handle_response(text)

    def reset(self, preserve_reference: bool = False) -> None:
        if self._z_probe_completion_context is not None:
            self._fail_z_probe_completion("Controller reset; probe Z again before lowering")
        preserve_reference = preserve_reference or self._preserve_reference_on_next_reset
        self._preserve_reference_on_next_reset = False
        self.manual_pending_acks = 0
        self.motion.reset()
        self.job.reset()
        if preserve_reference:
            self.homing.clear_activity()
        else:
            self.homing.reset("GRBL reset")
        self.probing.reset()
        self.calibration.reset()
        self.travel_calibration.reset()
        self._z_probe_pending = False
        self._z_probe_offset_confirmed = False
        self._z_commissioning_pending = False
        self._z_plate_removal_required = False
        self.tool_setting.reset()
        self.fixtures.reset()
        self._work_zero_request_pending_ack = False
        self._work_zero_expected_offset = None
        self._work_zero_expected_axes = ""
        self.status = None
        self._status_generation = -1
        self._job_nonce = ""
        self._begin_session_generation()
        self.session.clear_status(retain_work_zero=preserve_reference)
        if not preserve_reference:
            self.session.invalidate_reference("GRBL reset")

    def handle_transport_response(self, response: str, feed: float = 500.0, preserve_reference: bool = False) -> tuple[GrblStatus | None, bool]:
        """Dispatch one normalized transport response and apply GRBL state changes."""
        text = response.strip()
        self.connection_service.note_wifi_bootstrap_usb_line(text)
        if self.wifi_setup.handle_response(text, time.monotonic()):
            return None, False
        self.handle_response(text, feed)
        status = parse_status(text)
        if status is not None:
            self.apply_status(status, session_generation=self._session_generation)
        reset = text.startswith("Grbl ") or "[MSG:Reset" in text
        if reset:
            self.reset(preserve_reference=preserve_reference)
        return status, reset
