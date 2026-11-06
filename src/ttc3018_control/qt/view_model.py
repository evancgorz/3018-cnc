from __future__ import annotations

from pathlib import Path
import json
import logging
import secrets
import time

from PySide6.QtCore import Property, QObject, QTimer, QUrl, Signal, Slot

from ..application.controller import ApplicationController
from ..application.ux_state import (
    IssueSnapshot,
    OperationCategory,
    OperationCoordinator,
    OperationSnapshot,
    OperationState,
    ReadinessSnapshot,
)
from ..application.workflow_projection import (
    GUIDED_STEP_NAMES,
    WorkflowObservation,
    project_workflow,
)
from ..application.envelope_projection import EnvelopeMarker, project_machine_position
from ..gcode import GCodeError
from ..plaque_engraver import BORDER_STYLES
from ..grbl import (
    GrblStatus,
    Position,
)
from ..machine_state import MachineProfile
from ..machine_config import DEFAULT_Z_TOUCH_PLATE_THICKNESS
from ..simulation.safety import AutoXYZCalibrationWorkflow
from ..step_engraver import STEP_MODES, STEP_ORIENTATIONS, STEP_ZERO_LOCATIONS
from ..step_geometry import STEP_PLANES, StepImportError, StepPlanarModel
from ..step_prepare_settings import StepPrepareSettings
from ..text_engraver import FONT_NAMES
from ..live.frames import FrameHub
from ..live.server import LiveWebServer
from ..live_settings import LiveSettings, LiveSettingsStore
from ..tailscale import TailscaleService, TailscaleStatus
from .camera_service import CameraService
from .live_bridge import RemoteCommandBridge
from .task_runner import TaskResult, TaskRunner
from .ui_preferences import UiPreferences, UiPreferencesStore


class ControllerViewModel(QObject):
    """Qt-facing controller facade; QML never touches a transport or GRBL command."""

    STATUS_FRESHNESS_SECONDS = 2.0

    state_changed = Signal()
    toast_requested = Signal(str)
    confirmation_requested = Signal(str, str, str)
    ports_changed = Signal()
    unreferenced_jog_requested = Signal()
    step_import_completed = Signal(object, str)
    step_model_imported = Signal(str)
    connection_changed = Signal()
    position_changed = Signal()
    readiness_changed = Signal()
    operation_changed = Signal()
    expert_mode_changed = Signal()
    preview_changed = Signal()
    job_changed = Signal()
    issues_changed = Signal()
    profiles_changed = Signal()
    live_changed = Signal()
    simulation_changed = Signal()
    workspace_changed = Signal()
    auto_connection_failed = Signal(str)

    def __init__(self, application: ApplicationController | None = None, *, auto_connect: bool = False,
                 root: Path | None = None) -> None:
        super().__init__()
        supplied_root = Path(root).expanduser().resolve() if root is not None else None
        if application is not None:
            try:
                application_root = Path(application.root).expanduser().resolve()
            except AttributeError as exc:
                raise TypeError("A preconstructed application must expose an explicit root") from exc
            if supplied_root is not None and supplied_root != application_root:
                raise ValueError(
                    "The explicit ViewModel root must match the preconstructed application root"
                )
        elif supplied_root is not None:
            application_root = supplied_root
        else:
            application_root = Path.cwd().resolve()
        self.application = application or ApplicationController(application_root)
        self._application_root = application_root
        self.application.bind_callbacks(
            on_notice=self._set_notice,
            on_change=self._emit_state,
            on_ready_to_return=self.return_to_work_zero,
        )
        self._workspace_index = 0
        self._auto_connect_started = False
        self._auto_connection_state = "idle"
        self._auto_connection_attempts: list[str] = []
        self._auto_failure_reported = False
        self._envelope_marker = EnvelopeMarker("unknown", "MPos unavailable")
        self._backend_session_seen = ""
        self._last_status_poll = 0.0
        self._last_status_projection: tuple[bool, str] | None = None
        self._last_status_received_at = 0.0
        self._last_live_snapshot = 0.0
        self._unreferenced_jog_allowed = False
        self._live_jog_lease_token = ""
        self._live_jog_lease_generation = 0
        self._pending_confirmation: tuple[str, object] | None = None
        self._confirmation_token = ""
        self._confirmation_sequence = 0
        self._ports: list[str] = []
        self._ports_loaded = False
        self._connection_text = "Disconnected"
        self._state_text = "Unknown"
        self._machine_position_text = "X—  Y—  Z—"
        self._work_position_text = "X—  Y—  Z—"
        self._envelope_marker = EnvelopeMarker("unknown", "Controller disconnected")
        self._reference_text = "Position unknown"
        self._work_zero_text = "Not confirmed"
        self._spindle_text = "Off"
        self._feed_text = "0"
        self._pins_text = "—"
        self._simulation_snapshot: dict[str, object] = {}
        self._simulation_hazards: list[str] = []
        self._simulation_stock_metrics: dict[str, object] = {}
        self._simulation_active_hazard: dict[str, object] = {}
        # Terminal safety evidence remains visible until an explicit safe
        # recovery boundary clears it.
        self._simulation_terminal_hazard: dict[str, object] = {}
        self._simulation_export_status = "No simulation evidence exported"
        self._job_file_text = "No G-code loaded"
        self._job_summary_text = "Load a metric, pre-sliced engraving file."
        self._job_provenance: dict[str, object] = {
            "report_state": "unavailable", "file_sha256": "", "report_name": "",
            "release_status": "", "bundle": "", "details": [], "header_notes": [],
            "verification_text": "",
            "notice": "No job is loaded.",
        }
        self._preview_strokes: list[list[list[float]]] = []
        self._preview_cutting_strokes: list[list[list[float]]] = []
        self._preview_rapid_strokes: list[list[list[float]]] = []
        self._preview_model_strokes: list[list[list[float]]] = []
        self._preview_image_url = ""
        self._preview_cutting_image_url = ""
        self._preview_rapid_image_url = ""
        self._preview_path_layers_available = False
        self._preview_image_note = ""
        self._preview_stock_width = 0.0
        self._preview_stock_height = 0.0
        self._preview_summary = ""
        self._program_execution_layer: dict[str, object] = {}
        self._step_operations: list[dict[str, object]] = []
        self._step_preview_valid = False
        self._step_isometric_faces: list[dict[str, object]] = []
        self._step_isometric_paths: list[dict[str, object]] = []
        self._step_isometric_stock_thickness = 0.0
        self._step_model: StepPlanarModel | None = None
        self._step_path: Path | None = None
        self._step_source_text = "No STEP model imported"
        self._step_import_status = "Import a planar STEP model to begin."
        self._step_importing = False
        self._step_task_token = 0
        self._preview_task_token = 0
        self._preview_task_generation = 0
        self._preview_generation = 0
        self._pending_preview: tuple[str, tuple[object, ...]] | None = None
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(150)
        self._preview_timer.timeout.connect(self._run_pending_preview)
        self._live_jog_renew_timer = QTimer(self)
        self._live_jog_renew_timer.setInterval(100)
        self._live_jog_renew_timer.timeout.connect(self._renew_live_jog_lease)
        self._task_runner = TaskRunner(self)
        self._task_runner.completed.connect(self._finish_background_task)
        self._operations = OperationCoordinator()
        self._active_operation: OperationSnapshot | None = None
        self._readiness_snapshot = ReadinessSnapshot()
        self._issue: IssueSnapshot | None = None
        self._position_emit_at = 0.0
        self._last_position_projection = ""
        self._last_preview_fingerprint: tuple[object, ...] | None = None
        self._last_readiness_snapshot = ReadinessSnapshot()
        self._last_issue: IssueSnapshot | None = None
        self._last_operation_snapshot: OperationSnapshot | None = None
        self._last_connection_projection: tuple[object, ...] | None = None
        self._last_job_projection: tuple[object, ...] | None = None
        self._backend_program_projection: tuple[object, ...] | None = None
        self._workflow_cache_key: tuple[object, ...] | None = None
        self._workflow_cache = None
        self._workflow_preflight: tuple[bool, str] = (False, "Load a validated metric G-code program first.")
        self._review_facts_cache_key: tuple[object, ...] | None = None
        self._review_facts_cache: dict[str, object] | None = None
        self._ui_preferences_store = UiPreferencesStore(application_root / "config" / "ui-preferences.json")
        self._ui_preferences = self._ui_preferences_store.load()
        # Guided navigation is session-local and never restored from a
        # persisted preference that could hide an unsafe prerequisite.
        self._guided_step = 1
        self._guided_preflight_confirmed = False
        self._review_acknowledged = False
        self._next_part_available = False
        # Completion may be observed while the streamer is draining. Arm the
        # repeat affordance only after a reviewed run starts.
        self._next_part_armed = False
        # A motion/connection action may complete asynchronously.  Keep one
        # explicit, session-local completion intent so observed completion can
        # advance the guided rail without moving the machine or overriding a
        # deliberate backward review.
        self._guided_completion_pending: int | None = None
        self._last_review_fingerprint: tuple[object, ...] | None = None
        self._log_lines: list[str] = []
        self._live_settings_store = LiveSettingsStore(application_root / "config" / "live.json")
        self._live_settings = self._live_settings_store.load()
        self._live_frames = FrameHub()
        self._camera_service = CameraService(self._live_frames, self)
        self._remote_bridge = RemoteCommandBridge(self.application, audit=self._audit_live)
        self._live_server: LiveWebServer | None = None
        self._tailscale = TailscaleService()
        self._tailscale_status = TailscaleStatus()
        self._tailscale_task_token = 0
        self._live_snapshot = self.application.live_status_snapshot()
        self._logger = logging.getLogger("pine.transport")
        self.transport = self.application.settings.preferred_transport
        self.port = self.application.settings.usb_port
        self.wifi_host = self.application.settings.wifi_host
        self.wifi_port = self.application.settings.wifi_port
        self.step_import_completed.connect(self._finish_step_import)
        self._camera_service.state_changed.connect(lambda _state: self._refresh_live_state())
        self._camera_frame_data = ""
        self._camera_service.frame_data_changed.connect(self._on_camera_frame)
        self._camera_service.camera_list_changed.connect(lambda: self.live_changed.emit())

        # Launch on the earliest incomplete safe prerequisite.  This is derived
        # from current facts, never from a persisted navigation preference.
        step = self._workflow().earliest_incomplete
        self._guided_step = 5 if step == 4 else step

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)
        self._timer.start(50)
        if auto_connect:
            QTimer.singleShot(800, self._auto_connect_last)

    @property
    def session(self):
        return self.application.session

    @property
    def status(self):
        return self.application.status

    @status.setter
    def status(self, value) -> None:
        self.application.status = value
        if value is not None:
            self._last_status_received_at = time.monotonic()

    @property
    def program(self):
        return self.application.program

    @property
    def connection(self):
        """Compatibility view for tests and the temporary Qt adapter."""
        return self.application.transport

    @connection.setter
    def connection(self, value) -> None:
        self.application.set_transport_for_testing(value)

    @Property(str, notify=operation_changed)
    def operation_name(self) -> str:
        return self._active_operation.name if self._active_operation else ""

    @Property(str, notify=operation_changed)
    def operation_phase(self) -> str:
        return self._active_operation.phase if self._active_operation else ""

    @Property(float, notify=operation_changed)
    def operation_progress(self) -> float:
        return float(self._active_operation.progress or 0.0) if self._active_operation else 0.0

    @Property(bool, notify=operation_changed)
    def operation_active(self) -> bool:
        return bool(self._active_operation and self._active_operation.active)

    @Property(str, notify=operation_changed)
    def motion_phase(self) -> str:
        return self.application.motion.phase

    @Property(str, notify=readiness_changed)
    def readiness_connection(self) -> str:
        return self._readiness_snapshot.connection

    @Property(str, notify=readiness_changed)
    def readiness_reference(self) -> str:
        return self._readiness_snapshot.reference

    @Property(str, notify=readiness_changed)
    def readiness_work_zero(self) -> str:
        return self._readiness_snapshot.work_zero

    @Property(str, notify=readiness_changed)
    def readiness_job(self) -> str:
        return self._readiness_snapshot.job

    @Property(str, notify=readiness_changed)
    def readiness_ready(self) -> str:
        return self._readiness_snapshot.ready

    @Property(str, notify=readiness_changed)
    def readiness_next_action(self) -> str:
        return self._readiness_snapshot.next_action

    @Property(str, notify=readiness_changed)
    def readiness_reason(self) -> str:
        return self._readiness_snapshot.reason

    def _workflow(self):
        status = self.application.status
        status_name = getattr(status, "state", "Unknown") if status is not None else "Unknown"
        supervisor_healthy = True
        if self.application.simulation_active:
            supervisor_healthy = getattr(self.application, "supervisor_state", "unavailable") == "healthy"
        program = self.application.program
        program_key = None if program is None else (
            str(program.path), tuple(program.commands), repr(program.bounds),
        )
        try:
            profile_key = repr(self.application.machine_definition.to_profile())
        except (AttributeError, TypeError, ValueError):
            profile_key = repr(self.application.machine_definition)
        physical_safety = self._physical_safety_status()
        physical_safety_key = tuple(
            (key, repr(physical_safety.get(key)))
            for key in ("state", "raw_state", "transition_id", "power_removal",
                        "blocks_motion", "latched", "commissioned", "reason")
        )
        # The projection is read by many QML properties during one state
        # publication.  Key it by the immutable facts it consumes so direct
        # test/adaptor mutations still invalidate it without requiring every
        # caller to remember a private cache-reset hook.
        cache_key = (
            repr(self.application.machine_definition), profile_key,
            bool(self.application.connected), status_name, repr(status),
            bool(self.application.simulation_active), supervisor_healthy,
            bool(getattr(self.application, "status_fresh", False)),
            bool(self.application.reference_trusted), repr(self.application.session.envelope.reference),
            bool(self.application.work_zero_confirmed), repr(self.application.work_offset),
            program_key, bool(self.application.job_active),
            str(self.application.z_touch_plate_status),
            bool(self.application.simulation_plate_commissioned),
            str(self.application.auto_xyz_calibration_state),
            bool(self.application.calibration.work_offset_confirmed),
            physical_safety_key,
            bool(self.simulation_hazard_active), bool(self.simulation_estop_active),
            bool(self.operation_active), bool(self._review_acknowledged),
        )
        if cache_key == self._workflow_cache_key and self._workflow_cache is not None:
            return self._workflow_cache
        profile_valid = True
        try:
            self.application.machine_definition.to_profile().validate()
        except (TypeError, ValueError):
            profile_valid = False
        job_preflight_ok = False
        job_preflight_reason = "Load a validated metric G-code program first."
        if program is not None:
            try:
                job_preflight_ok, job_preflight_reason = self.application.preflight()
                job_preflight_ok = bool(job_preflight_ok)
                job_preflight_reason = str(job_preflight_reason)
            except (AttributeError, TypeError, ValueError):
                job_preflight_ok = False
                job_preflight_reason = "Validation unavailable."
        self._workflow_preflight = (job_preflight_ok, job_preflight_reason)
        spindle_off_confirmed = bool(
            getattr(self.application, "status_fresh", False)
            and status is not None
            and getattr(status, "spindle", None) == 0
        )
        projection = project_workflow(WorkflowObservation(
            machine_definition=self.application.machine_definition,
            connected=bool(self.application.connected),
            controller_state=str(status_name),
            simulation_active=bool(self.application.simulation_active),
            supervision_healthy=supervisor_healthy,
            fresh_status=bool(getattr(self.application, "status_fresh", False)),
            homing_inputs_safe=bool(getattr(self.application, "homing_inputs_safe", True)),
            spindle_off=status is None or getattr(status, "spindle", None) in (None, 0),
            job_spindle_off_confirmed=spindle_off_confirmed,
            reference_trusted=bool(self.application.reference_trusted),
            work_zero_confirmed=bool(self.application.work_zero_confirmed),
            job_loaded=program is not None,
            job_active=bool(self.application.job_active),
            z_plate_status=str(self.application.z_touch_plate_status),
            simulation_plate_commissioned=bool(self.application.simulation_plate_commissioned),
            auto_xyz_state=str(self.application.auto_xyz_calibration_state),
            auto_xyz_wco_confirmed=bool(self.application.calibration.work_offset_confirmed),
            hazard=bool(self.simulation_hazard_active),
            estop=bool(self.simulation_estop_active),
            active_operation=bool(self.operation_active),
            review_acknowledged=bool(self._review_acknowledged),
            profile_valid=profile_valid,
            job_preflight_ok=job_preflight_ok,
        ))
        self._workflow_cache_key = cache_key
        self._workflow_cache = projection
        return projection

    @Property("QVariantMap", notify=state_changed)
    def review_facts(self) -> dict[str, object]:
        """Typed evidence for Review/Run; unknown facts never appear green."""
        # Establish the same state key used by the workflow projection.  This
        # keeps Review and Run on one invalidation boundary and avoids a second
        # preflight calculation for repeated property reads.
        self._workflow()
        if self._review_facts_cache_key == self._workflow_cache_key and self._review_facts_cache is not None:
            return dict(self._review_facts_cache)
        program_loaded = self.application.program is not None
        validation_state = "not_run"
        bounds_checked = False
        reason = "Load a validated metric G-code program first."
        if program_loaded:
            bounds_checked, reason = self._workflow_preflight
            validation_state = "passed" if bounds_checked else "failed"
        if self.application.simulation_active:
            runtime = self.application.simulation_runtime
            supervisor = str(getattr(self.application, "supervisor_state", "unavailable"))
            estop = "active" if self.simulation_estop_active else ("clear" if runtime is not None else "unknown")
            hazard = "active" if self.simulation_hazard_active else "clear"
            if self.simulation_hazard_active:
                collision_analysis = "detected" if self.simulation_collision_active else "hazard"
            else:
                collision_analysis = "not_run"
        else:
            supervisor, estop, hazard = "not_applicable", "not_applicable", "not_applicable"
            collision_analysis = "not_run"
        physical_safety = self._physical_safety_status()
        facts = {
            "program_loaded": program_loaded,
            "validation": validation_state,
            "bounds_checked": bool(bounds_checked),
            "collision_analysis": collision_analysis,
            "supervisor": supervisor,
            "estop": estop,
            "hazard": hazard,
            "fresh_status": str(getattr(self.application, "status_state", "unavailable")) == "fresh",
            "physical_safety_input": str(physical_safety.get("state", "unknown")),
            "physical_power_removal": str(physical_safety.get("power_removal", "unknown")),
            "physical_safety_blocks_motion": bool(physical_safety.get("blocks_motion", False)),
            "physical_safety_clear": bool(
                physical_safety.get("commissioned", False)
                and physical_safety.get("state") == "clear"
                and physical_safety.get("power_removal") == "confirmed"
                and not physical_safety.get("blocks_motion", True)
            ),
            "reason": str(reason),
        }
        self._review_facts_cache_key = self._workflow_cache_key
        self._review_facts_cache = facts
        return dict(facts)

    @Property("QVariantList", notify=state_changed)
    def workflow_steps(self) -> list[dict[str, object]]:
        return [step.as_dict() for step in self._workflow().steps]

    @Property("QVariantList", notify=state_changed)
    def work_zero_methods(self) -> list[dict[str, object]]:
        return [method.as_dict() for method in self._workflow().work_zero_methods]

    @Property("QVariantList", notify=state_changed)
    def setup_warnings(self) -> list[dict[str, object]]:
        return [warning.as_dict() for warning in self._workflow().setup_warnings]

    @Property("QStringList", notify=state_changed)
    def setup_warning_text(self) -> list[str]:
        return [f"{warning.title}: {warning.reason}" for warning in self._workflow().setup_warnings]

    @Property(str, notify=state_changed)
    def workflow_reference_mode(self) -> str:
        return self._workflow().reference_mode

    @Property(str, notify=state_changed)
    def workflow_next_action(self) -> str:
        return self._workflow().next_action

    @Property(str, notify=state_changed)
    def workflow_reason(self) -> str:
        return self._workflow().reason

    @Property(str, notify=state_changed)
    def workflow_json(self) -> str:
        return json.dumps(self._workflow().as_dict(), sort_keys=True, separators=(",", ":"))

    @Property(int, notify=state_changed)
    def guided_step_index(self) -> int:
        return self._guided_step

    @Property(str, notify=state_changed)
    def guided_step_key(self) -> str:
        return self._workflow().steps[self._guided_step].key

    @Property(int, notify=state_changed)
    def current_guided_step(self) -> int:
        return self._guided_step

    @Property("QVariantList", notify=state_changed)
    def guided_steps(self) -> list[dict[str, object]]:
        return self.workflow_steps

    @Property(bool, notify=state_changed)
    def review_acknowledged(self) -> bool:
        return self._review_acknowledged

    @Property(bool, notify=issues_changed)
    def has_issue(self) -> bool:
        return self._issue is not None

    @Property(str, notify=issues_changed)
    def issue_title(self) -> str:
        return self._issue.title if self._issue else ""

    @Property(str, notify=issues_changed)
    def issue_explanation(self) -> str:
        return self._issue.explanation if self._issue else ""

    @Property("QStringList", notify=issues_changed)
    def issue_actions(self) -> list[str]:
        return list(self._issue.actions) if self._issue else []

    @Property(bool, notify=expert_mode_changed)
    def expert_mode(self) -> bool:
        return self._ui_preferences.expert_mode

    @Property(bool, constant=True)
    def first_run_complete(self) -> bool:
        return self._ui_preferences.first_run_complete

    @Slot(bool)
    def set_expert_mode(self, enabled: bool) -> None:
        self._ui_preferences.expert_mode = bool(enabled)
        self.expert_mode_changed.emit()
        try:
            self._ui_preferences_store.save(self._ui_preferences)
        except OSError:
            self._set_notice("Expert-mode preference could not be saved")

    @Slot()
    def complete_first_run(self) -> None:
        self._ui_preferences.first_run_complete = True
        try:
            self._ui_preferences_store.save(self._ui_preferences)
        except OSError:
            self._set_notice("First-run preference could not be saved")

    @Property(str, notify=state_changed)
    def connection_text(self) -> str:
        return self._connection_text

    @Property(str, notify=state_changed)
    def auto_connection_state(self) -> str:
        return self._auto_connection_state

    @Property("QStringList", notify=state_changed)
    def auto_connection_attempts(self) -> list[str]:
        return list(self._auto_connection_attempts)

    @Property(int, notify=workspace_changed)
    def workspace_index(self) -> int:
        return self._workspace_index

    @Property("QStringList", constant=True)
    def workspace_names(self) -> list[str]:
        return ["Machine", "Prepare", "Review", "Run"]

    @Slot(int)
    def select_workspace(self, index: int) -> None:
        index = int(index)
        if index not in range(4):
            return
        if self.application.job_active and index != 3:
            self._set_notice("Run monitoring remains selected while the job is active")
            index = 3
        if index == 0:
            machine_steps = range(1, 4)
            if self._guided_step not in machine_steps:
                self._guided_step = next((step for step in machine_steps
                                          if self._workflow().steps[step].selectable), 1)
        else:
            self._guided_step = {1: 4, 2: 5, 3: 6}[index]
        self._guided_completion_pending = None
        if self._workspace_index != index:
            self._workspace_index = index
            self.workspace_changed.emit()
        self._emit_state()

    @Property(bool, notify=state_changed)
    def backend_available(self) -> bool:
        return bool(getattr(self.application, "backend_available", True))

    @Property(str, notify=state_changed)
    def backend_state(self) -> str:
        return str(getattr(self.application, "backend_state", "local"))

    @Property(str, notify=state_changed)
    def backend_error(self) -> str:
        return str(getattr(self.application, "backend_error", ""))

    @Property(bool, notify=state_changed)
    def header_status_visible(self) -> bool:
        return bool(
            not self.backend_available
            or self._auto_connection_state in {"trying", "failed"}
            or self.safety_attention
        )

    @Property(str, notify=state_changed)
    def header_status_text(self) -> str:
        if not self.backend_available:
            return "Backend unavailable"
        if self._auto_connection_state == "trying":
            return "Connecting…"
        if self._auto_connection_state == "failed":
            return "Device not found"
        if self.safety_attention:
            return "Safety attention"
        return ""

    @Property(bool, notify=state_changed)
    def safety_attention(self) -> bool:
        physical = self._physical_safety_status()
        physical_attention = bool(
            physical.get("blocks_motion", False)
            or (physical.get("commissioned", False) and physical.get("state") not in {"clear"})
        )
        return bool(
            self.simulation_hazard_active
            or self.simulation_estop_active
            or physical_attention
            or (self.connected and not bool(getattr(self.application, "status_fresh", False)))
            or (self.simulation_active and not self.simulation_supervisor_healthy)
        )

    @Property(str, notify=state_changed)
    def safety_attention_text(self) -> str:
        physical = self._physical_safety_status()
        if self.simulation_estop_active:
            return "E-stop active — remove hazardous power and recover explicitly."
        if self.simulation_hazard_active:
            return "Safety supervisor reports a hazard — motion is blocked."
        if physical.get("blocks_motion", False):
            return f"Physical safety input blocks motion — {physical.get('reason', 'verify the safety circuit')}"
        if self.connected and not bool(getattr(self.application, "status_fresh", False)):
            return "Controller status is stale — wait for a fresh report before motion."
        if self.simulation_active and not self.simulation_supervisor_healthy:
            return "Safety supervisor is unavailable — simulation is blocked."
        return ""

    def _physical_safety_status(self) -> dict[str, object]:
        value = getattr(self.application, "physical_safety_input_status", {})
        return dict(value) if isinstance(value, dict) else {}

    @Property(str, notify=state_changed)
    def physical_safety_input_state(self) -> str:
        return str(self._physical_safety_status().get("state", "unknown"))

    @Property(str, notify=state_changed)
    def physical_safety_input_power_removal(self) -> str:
        return str(self._physical_safety_status().get("power_removal", "unknown"))

    @Property(bool, notify=state_changed)
    def physical_safety_input_commissioned(self) -> bool:
        return bool(self._physical_safety_status().get("commissioned", False))

    @Property(bool, notify=state_changed)
    def physical_safety_input_latched(self) -> bool:
        return bool(self._physical_safety_status().get("latched", False))

    @Property(bool, notify=state_changed)
    def physical_safety_input_blocks_motion(self) -> bool:
        return bool(self._physical_safety_status().get("blocks_motion", False))

    @Property(str, notify=state_changed)
    def physical_safety_input_reason(self) -> str:
        return str(self._physical_safety_status().get("reason", "Backend safety-input status unavailable"))

    @Property(str, notify=state_changed)
    def physical_safety_input_status_text(self) -> str:
        status = self._physical_safety_status()
        commissioned = bool(status.get("commissioned", False))
        state = str(status.get("state", "unknown")).upper()
        power = str(status.get("power_removal", "unknown")).upper()
        if not commissioned:
            return f"Physical E-stop input: {state} / UNCOMMISSIONED · hazardous-power removal: {power}"
        channel_a = status.get("channel_a_closed")
        channel_b = status.get("channel_b_closed")
        def channel(value: object) -> str:
            return "closed" if value is True else "open" if value is False else "unknown"
        return (f"Physical E-stop input: {state} · A={channel(channel_a)}, B={channel(channel_b)} · "
                f"power removal: {power} · {self.physical_safety_input_reason}")

    @Property(bool, notify=state_changed)
    def physical_safety_input_acknowledge_available(self) -> bool:
        return bool(self.physical_safety_input_commissioned and self.physical_safety_input_latched)

    @Property(str, notify=state_changed)
    def confirmation_token(self) -> str:
        return self._confirmation_token

    @Property(str, notify=state_changed)
    def grbl_state(self) -> str:
        return self._state_text

    @Property(str, notify=state_changed)
    def machine_position(self) -> str:
        return self._machine_position_text

    @Property("QVariantMap", notify=position_changed)
    def envelope_marker(self) -> dict[str, object]:
        return self._envelope_marker.as_dict()

    @Property(str, notify=position_changed)
    def envelope_marker_text(self) -> str:
        marker = self._envelope_marker
        if marker.state == "unknown":
            return f"Position unknown · {marker.reason}"
        if marker.out_of_bounds:
            return f"OUT OF BOUNDS · {marker.direction} · Z{marker.z:.2f}"
        return f"MPos X{marker.x * self.application.profile.travel_x:.2f} Y{marker.y * self.application.profile.travel_y:.2f} Z{marker.z:.2f}"

    @Property(str, notify=state_changed)
    def work_position(self) -> str:
        return self._work_position_text

    @Property(str, notify=state_changed)
    def reference(self) -> str:
        return self._reference_text

    @Property(bool, notify=state_changed)
    def reference_trusted(self) -> bool:
        return self.application.reference_trusted

    @Property(str, notify=state_changed)
    def work_zero(self) -> str:
        return self._work_zero_text

    @Property(bool, notify=state_changed)
    def work_zero_confirmed(self) -> bool:
        return self.application.work_zero_confirmed

    @Property(bool, notify=state_changed)
    def saved_work_zero_available(self) -> bool:
        return (
            self._saved_work_zero_position() is not None
            and {"X", "Y"} <= self._saved_work_zero_axes()
        )

    @Property(bool, notify=state_changed)
    def saved_work_zero_display_available(self) -> bool:
        return self._saved_work_zero_position() is not None

    @Property(str, notify=state_changed)
    def saved_work_zero_text(self) -> str:
        saved = self._saved_work_zero_position()
        if saved is None:
            return ""
        axes = self._saved_work_zero_axes()
        coordinates = ", ".join(
            f"{axis} {getattr(saved, axis.lower()):.3f} mm" for axis in "XYZ" if axis in axes
        )
        suffix = "" if axes >= frozenset("XYZ") else f" ({''.join(axis for axis in 'XYZ' if axis in axes)} confirmed)"
        return f"Saved previous work-zero coordinates: {coordinates}{suffix}"

    def _saved_work_zero_position(self) -> Position | None:
        # The backend adapter exposes the value as a Position. Keep the
        # in-process composition compatible while all clients migrate to IPC.
        saved = getattr(self.application, "saved_work_zero", None)
        if saved is None:
            saved = getattr(self.application, "_saved_work_zero", None)
        position = getattr(saved, "position", saved)
        return position if isinstance(position, Position) else None

    def _saved_work_zero_axes(self) -> frozenset[str]:
        axes = getattr(self.application, "saved_work_zero_axes", None)
        if axes is None:
            saved = getattr(self.application, "_saved_work_zero", None)
            axes = getattr(saved, "confirmed_axes", None)
        if axes is None:
            return frozenset("XYZ") if self._saved_work_zero_position() is not None else frozenset()
        return frozenset(str(axis).upper() for axis in axes)

    @Property(str, notify=state_changed)
    def spindle(self) -> str:
        return self._spindle_text

    @Property(str, notify=state_changed)
    def feed(self) -> str:
        return self._feed_text

    @Property(str, notify=state_changed)
    def pins(self) -> str:
        return self._pins_text

    @Property(str, notify=state_changed)
    def job_file(self) -> str:
        return self._job_file_text

    @Property(str, notify=state_changed)
    def job_summary(self) -> str:
        return self._job_summary_text

    @Property("QVariantMap", notify=state_changed)
    def job_provenance(self) -> dict[str, object]:
        return dict(self._job_provenance)

    @Property("QVariantMap", notify=state_changed)
    def watchdog_recovery(self) -> dict[str, object]:
        return dict(getattr(self.application, "watchdog_recovery", {}) or {})

    @Property("QVariantMap", notify=state_changed)
    def automatic_continuation(self) -> dict[str, object]:
        return dict(getattr(self.application, "automatic_continuation", {}) or {})

    @Slot()
    def continue_watchdog_home(self) -> None:
        if self.watchdog_recovery.get("can_continue_to_home"):
            self._set_notice(self.application.continue_to_home().message)
            self._emit_state()

    @Slot()
    def cancel_watchdog_recovery(self) -> None:
        if self.watchdog_recovery.get("can_cancel"):
            self._set_notice(self.application.cancel_recovery().message)
            self._emit_state()

    @Property("QVariantMap", notify=state_changed)
    def job_recovery(self) -> dict[str, object]:
        """Advisory recovery evidence from the backend, never a resume cursor."""
        value = getattr(self.application, "job_recovery", {})
        return dict(value) if isinstance(value, dict) else {}

    @Property("QStringList", constant=True)
    def fonts(self) -> list[str]:
        return list(FONT_NAMES)

    @Property("QStringList", constant=True)
    def borders(self) -> list[str]:
        return list(BORDER_STYLES)

    @Property("QStringList", constant=True)
    def step_modes(self) -> list[str]:
        return list(STEP_MODES)

    @Property("QStringList", constant=True)
    def step_orientations(self) -> list[str]:
        return list(STEP_ORIENTATIONS)

    @Property("QStringList", constant=True)
    def step_zero_locations(self) -> list[str]:
        return list(STEP_ZERO_LOCATIONS)

    @Property("QStringList", constant=True)
    def step_planes(self) -> list[str]:
        return list(STEP_PLANES)

    @Property(str, notify=state_changed)
    def step_source(self) -> str:
        return self._step_source_text

    @Property(str, notify=state_changed)
    def step_model_summary(self) -> str:
        if self._step_model is None:
            return self._step_import_status
        model = self._step_model
        feature_text = ""
        if model.features:
            descriptions = ", ".join(
                f"{feature.kind} {feature.depth:.2f} mm"
                + (" through" if feature.is_through else " blind")
                for feature in model.features
            )
            feature_text = f" · detected {descriptions}"
        surface_text = f" · {len(model.surface_patches)} accessible planar surface patch(es)"
        if any(patch.tilted for patch in model.surface_patches):
            surface_text += " · includes ramp(s)"
        return f"{model.width:.2f} × {model.height:.2f} mm · {len(model.loops)} closed loop(s) · {model.face_plane} face · thickness {model.thickness:.2f} mm{feature_text}{surface_text}"

    @Property(bool, notify=state_changed)
    def step_loaded(self) -> bool:
        return self._step_model is not None

    @Property(bool, notify=state_changed)
    def step_feature_detected(self) -> bool:
        return bool(self._step_model and self._step_model.features)

    @Property(bool, notify=state_changed)
    def step_importing(self) -> bool:
        return self._step_importing

    @Property("QVariantList", notify=state_changed)
    def preview_strokes(self) -> list[list[list[float]]]:
        return self._preview_strokes

    @Property("QVariantList", notify=preview_changed)
    def preview_cutting_strokes(self) -> list[list[list[float]]]:
        return self._preview_cutting_strokes

    @Property("QVariantList", notify=preview_changed)
    def preview_rapid_strokes(self) -> list[list[list[float]]]:
        return self._preview_rapid_strokes

    @Property("QVariantList", notify=state_changed)
    def preview_model_strokes(self) -> list[list[list[float]]]:
        return self._preview_model_strokes

    @Property(str, notify=preview_changed)
    def preview_image_url(self) -> str:
        return self._preview_image_url

    @Property(str, notify=preview_changed)
    def preview_cutting_image_url(self) -> str:
        return self._preview_cutting_image_url

    @Property(str, notify=preview_changed)
    def preview_rapid_image_url(self) -> str:
        return self._preview_rapid_image_url

    @Property(bool, notify=preview_changed)
    def preview_path_layers_available(self) -> bool:
        return self._preview_path_layers_available

    @Property(str, notify=preview_changed)
    def preview_image_note(self) -> str:
        return self._preview_image_note

    @Property(int, notify=preview_changed)
    def preview_image_width(self) -> int:
        preview = getattr(self.application, "program_preview", {})
        return int(preview.get("width", 0) or 0) if isinstance(preview, dict) else 0

    @Property(int, notify=preview_changed)
    def preview_image_height(self) -> int:
        preview = getattr(self.application, "program_preview", {})
        return int(preview.get("height", 0) or 0) if isinstance(preview, dict) else 0

    @Property(float, notify=state_changed)
    def preview_stock_width(self) -> float:
        return self._preview_stock_width

    @Property(float, notify=state_changed)
    def preview_stock_height(self) -> float:
        return self._preview_stock_height

    @Property("QVariantMap", notify=state_changed)
    def program_execution_layer(self) -> dict[str, object]:
        value = getattr(self.application, "program_execution_layer", self._program_execution_layer)
        return dict(value) if isinstance(value, dict) else {}

    @Property("QVariantMap", notify=position_changed)
    def live_work_marker(self) -> dict[str, object]:
        """Fresh work-coordinate marker for the job plot (not the envelope)."""
        status = getattr(self.application, "status", None)
        if not bool(getattr(self.application, "status_fresh", False)) or status is None:
            return {"visible": False}
        point = getattr(status, "work_position", None)
        if point is None:
            machine = getattr(status, "machine_position", None)
            offset = getattr(self.application, "work_offset", None)
            if machine is not None and offset is not None:
                point = machine.minus(offset)
        if point is None:
            return {"visible": False}
        return {"visible": True, "x": float(point.x), "y": float(point.y), "z": float(point.z)}

    @Property("QVariantMap", notify=preview_changed)
    def job_plot_bounds(self) -> dict[str, float]:
        program = getattr(self.application, "program", None)
        bounds = getattr(program, "bounds", None)
        minimum, maximum = getattr(bounds, "minimum", None), getattr(bounds, "maximum", None)
        if minimum is None or maximum is None:
            return {}
        return {"min_x": float(minimum.x), "min_y": float(minimum.y),
                "max_x": float(maximum.x), "max_y": float(maximum.y)}

    @Property("QVariantList", notify=state_changed)
    def step_operations(self) -> list[dict[str, object]]:
        return self._step_operations

    @Property(bool, notify=state_changed)
    def step_preview_valid(self) -> bool:
        return self._step_preview_valid

    @Property("QVariantList", notify=state_changed)
    def step_isometric_faces(self) -> list[dict[str, object]]:
        return self._step_isometric_faces

    @Property("QVariantList", notify=state_changed)
    def step_isometric_paths(self) -> list[dict[str, object]]:
        return self._step_isometric_paths

    @Property(float, notify=state_changed)
    def step_isometric_stock_thickness(self) -> float:
        return self._step_isometric_stock_thickness

    @Property(str, notify=state_changed)
    def step_recommended_mode(self) -> str:
        return "Automatic part" if self._step_model is not None else ""

    @Property(float, notify=state_changed)
    def step_suggested_stock_width(self) -> float:
        if self._step_model is None:
            return 0.0
        settings = self.application.step_prepare_settings
        width = self._step_model.height if settings.orientation == "Top (YX)" else self._step_model.width
        return width + settings.tool_diameter

    @Property(float, notify=state_changed)
    def step_suggested_stock_height(self) -> float:
        if self._step_model is None:
            return 0.0
        settings = self.application.step_prepare_settings
        height = self._step_model.width if settings.orientation == "Top (YX)" else self._step_model.height
        return height + settings.tool_diameter

    @Property(float, notify=state_changed)
    def step_suggested_stock_thickness(self) -> float:
        return float(self._step_model.thickness) if self._step_model is not None else 0.0

    @Property(float, notify=state_changed)
    def step_model_width(self) -> float:
        return float(self._step_model.width) if self._step_model is not None else 0.0

    @Property(float, notify=state_changed)
    def step_model_height(self) -> float:
        return float(self._step_model.height) if self._step_model is not None else 0.0

    @Property(str, notify=state_changed)
    def step_default_orientation(self) -> str:
        return self.application.step_prepare_settings.orientation

    @Property(str, notify=state_changed)
    def step_default_zero_location(self) -> str:
        return self.application.step_prepare_settings.zero_location

    @Property(float, notify=state_changed)
    def step_default_tool_diameter(self) -> float:
        return self.application.step_prepare_settings.tool_diameter

    @Property(int, notify=state_changed)
    def step_default_passes(self) -> int:
        return self.application.step_prepare_settings.passes

    @Property(float, notify=state_changed)
    def step_default_max_stepdown(self) -> float:
        return self.application.step_prepare_settings.max_stepdown

    @Property(float, notify=state_changed)
    def step_default_safe_z(self) -> float:
        return self.application.step_prepare_settings.safe_z

    @Property(float, notify=state_changed)
    def step_default_cut_feed(self) -> float:
        return self.application.step_prepare_settings.cut_feed

    @Property(float, notify=state_changed)
    def step_default_plunge_feed(self) -> float:
        return self.application.step_prepare_settings.plunge_feed

    @Property(int, notify=state_changed)
    def step_default_spindle_rpm(self) -> int:
        return self.application.step_prepare_settings.spindle_rpm

    @Property(float, notify=state_changed)
    def step_default_breakthrough(self) -> float:
        return self.application.step_prepare_settings.breakthrough

    @Property(int, notify=state_changed)
    def step_default_tab_count(self) -> int:
        return self.application.step_prepare_settings.tab_count

    @Property(float, notify=state_changed)
    def step_default_tab_width(self) -> float:
        return self.application.step_prepare_settings.tab_width

    @Property(float, notify=state_changed)
    def step_default_tab_height(self) -> float:
        return self.application.step_prepare_settings.tab_height

    @Property(str, notify=state_changed)
    def preview_summary(self) -> str:
        return self._preview_summary

    @Property(str, notify=state_changed)
    def profile_summary(self) -> str:
        profile = self.application.profile
        return f"{profile.name} · X {profile.travel_x:g} · Y {profile.travel_y:g} · Z {profile.travel_z:g} · safe Z {profile.safe_z:g} mm"

    @Property(str, notify=state_changed)
    def profile_name(self) -> str:
        return self.application.profile.name

    @Property(float, notify=state_changed)
    def profile_x(self) -> float:
        return self.application.profile.travel_x

    @Property(float, notify=state_changed)
    def profile_y(self) -> float:
        return self.application.profile.travel_y

    @Property(float, notify=state_changed)
    def profile_z(self) -> float:
        return self.application.profile.travel_z

    @Property(float, notify=state_changed)
    def profile_safe_z(self) -> float:
        return self.application.profile.safe_z

    @Property(str, notify=state_changed)
    def machine_id(self) -> str:
        return self.application.machine_id or ""

    @Property(float, notify=state_changed)
    def tool_length_offset(self) -> float:
        return self.application.tool_setting.active_offset or 0.0

    @Property(bool, notify=state_changed)
    def tool_length_offset_active(self) -> bool:
        return self.application.tool_setting.active_offset is not None

    @Property("QStringList", notify=state_changed)
    def machine_profiles(self) -> list[str]:
        return [f"{machine.name} ({machine.machine_id[:8]})" for machine in self.application.machine_profiles]

    @Property(str, notify=state_changed)
    def machine_capabilities(self) -> str:
        definition = self.application.machine_definition
        labels = {
            "movable_z_plate": "movable Z touch plate / puck (supported)",
            "fixed_tool_setter": "fixed tool setter (configured — workflow unavailable)",
            "movable_xyz": "movable physical XYZ (configured — workflow unavailable)",
            "fixed_xyz": "fixed XYZ (configured — workflow unavailable)",
        }
        enabled = [labels.get(probe.kind.value, probe.kind.value) for probe in definition.probes if probe.enabled]
        return "Optional hardware: " + (", ".join(enabled) if enabled else "none")

    def _probe_enabled(self, kind: str) -> bool:
        return any(probe.kind.value == kind and probe.enabled
                   for probe in self.application.machine_definition.probes)

    @Property(bool, notify=state_changed)
    def movable_z_probe_enabled(self) -> bool:
        return self._probe_enabled("movable_z_plate")

    @Property(bool, notify=state_changed)
    def fixed_tool_setter_enabled(self) -> bool:
        return self._probe_enabled("fixed_tool_setter")

    @Property(bool, notify=state_changed)
    def movable_xyz_probe_enabled(self) -> bool:
        return self._probe_enabled("movable_xyz")

    @Property(bool, notify=state_changed)
    def fixed_xyz_probe_enabled(self) -> bool:
        return self._probe_enabled("fixed_xyz")

    @Property(bool, notify=state_changed)
    def z_touch_plate_enabled(self) -> bool:
        return self.application.z_touch_plate_definition is not None

    @Property(str, notify=state_changed)
    def z_touch_plate_status(self) -> str:
        return self.application.z_touch_plate_status.replace("_", " ")

    @Property(str, notify=state_changed)
    def z_probe_completion_json(self) -> str:
        snapshot = getattr(self.application, "z_probe_completion_snapshot", {})
        if not isinstance(snapshot, dict):
            snapshot = {}
        return json.dumps(snapshot, sort_keys=True)

    @Property(str, notify=state_changed)
    def z_probe_backend_session_id(self) -> str:
        return str(getattr(self.application, "backend_session_id", ""))

    @Property(str, notify=state_changed)
    def z_touch_plate_status_text(self) -> str:
        return {
            "disabled": "Disabled",
            "needs_input_test": "Input test required",
            "needs_commissioning": "Input verified — 3 supervised probe samples required",
            "stale": "Configuration changed — repeat verification",
            "probing": "Probe cycle running",
            "remove_plate": "Remove the plate and clip",
            "commissioning": "Supervised probe sample running",
            "ready": "Ready",
        }.get(self.application.z_touch_plate_status, self.application.z_touch_plate_status.replace("_", " ").title())

    @Property(str, notify=state_changed)
    def z_touch_plate_input_message(self) -> str:
        return self.application.z_touch_plate_input_message

    @Property(str, notify=state_changed)
    def z_touch_plate_input_state(self) -> str:
        return self.application.z_touch_plate_input_state

    @Property(int, notify=state_changed)
    def z_touch_plate_sample_count(self) -> int:
        return self.application.z_touch_plate_sample_count

    @Property(float, notify=state_changed)
    def z_touch_plate_thickness(self) -> float:
        definition = next((probe for probe in self.application.machine_definition.probes
                           if probe.kind.value == "movable_z_plate"), None)
        return (definition.plate_thickness if definition and definition.plate_thickness > 0
                else DEFAULT_Z_TOUCH_PLATE_THICKNESS)

    def _z_plate_value(self, name: str, fallback: float = 0.0) -> float:
        definition = next((probe for probe in self.application.machine_definition.probes
                           if probe.kind.value == "movable_z_plate"), None)
        return float(getattr(definition, name, fallback)) if definition else fallback

    @Property(float, notify=state_changed)
    def z_touch_plate_fast_feed(self) -> float:
        return self._z_plate_value("fast_feed", 100.0)

    @Property(float, notify=state_changed)
    def z_touch_plate_slow_feed(self) -> float:
        return self._z_plate_value("slow_feed", 25.0)

    @Property(float, notify=state_changed)
    def z_touch_plate_max_search(self) -> float:
        return self._z_plate_value("max_search", 5.0)

    @Property(float, notify=state_changed)
    def z_touch_plate_retract(self) -> float:
        return self._z_plate_value("retract", 2.0)

    @Property(float, notify=state_changed)
    def z_touch_plate_safe_retract(self) -> float:
        return self._z_plate_value("safe_retract", 2.0)

    @Property(float, notify=state_changed)
    def z_touch_plate_tolerance(self) -> float:
        return self._z_plate_value("tolerance", 0.05)

    @Property(bool, notify=state_changed)
    def z_touch_plate_active_low(self) -> bool:
        definition = next((probe for probe in self.application.machine_definition.probes
                           if probe.kind.value == "movable_z_plate"), None)
        return bool(definition and definition.active_low)

    @Property(str, notify=state_changed)
    def homing_state(self) -> str:
        return self.application.homing.state.value

    @Property(bool, notify=state_changed)
    def probe_active(self) -> bool:
        """Expose the active probe transaction for direct recovery controls."""
        return bool(self.application.probing.active)

    @Property(str, notify=state_changed)
    def homing_input_polarity(self) -> str:
        declarations = self.application.homing_limit_declarations
        values = {str(item.get("wiring", "")) for item in declarations.values()
                  if bool(item.get("enabled", False))}
        if len(values) == 1:
            return next(iter(values))
        if not values:
            return "Not configured"
        return "Unknown — mixed NC/NO"

    @Property(str, notify=state_changed)
    def homing_input_status(self) -> str:
        observation = self.application.homing_input_observation
        pins = observation.pins or "none"
        return f"{observation.state}: Pn:{pins}"

    @Property(str, notify=state_changed)
    def homing_input_reason(self) -> str:
        return self.application.homing_input_observation.reason

    @Property(bool, notify=state_changed)
    def can_home_machine(self) -> bool:
        return bool(getattr(self.application, "can_home_machine", False))

    @Property(str, notify=state_changed)
    def home_action_block_reason(self) -> str:
        app = self.application
        if bool(getattr(app, "can_home_machine", False)):
            return ""
        if not bool(getattr(app, "connected", False)):
            return "Connect to the controller before homing."
        if not bool(getattr(app, "operation_transport_ready", True)):
            return "USB is for Wi-Fi setup only; use a verified Wi-Fi connection before homing."
        if not bool(getattr(app, "status_fresh", False)):
            return "Wait for a fresh GRBL status report before homing."
        if not bool(getattr(app, "homing_inputs_safe", False)):
            reason = str(getattr(getattr(app, "homing_input_observation", None), "reason", ""))
            return reason or "Release active homing inputs before homing."
        status = getattr(app, "status", None)
        state = str(getattr(status, "state", "Unknown"))
        if state not in {"Idle", "Alarm"}:
            return f"Wait for GRBL to report Idle or Alarm before homing (current state: {state})."
        if getattr(status, "spindle", None) not in (None, 0):
            return "Turn off the spindle before homing."
        definition = getattr(app, "machine_definition", None)
        axes = getattr(definition, "axes", {})
        if any(axes.get(axis) is None for axis in "XYZ"):
            return "Configure X, Y, and Z homing switches before homing."
        if any(getattr(getattr(axes[axis], "switch_mode", None), "value", "none") == "none"
               for axis in "XYZ"):
            return "Configure and commission X, Y, and Z homing switches before homing."
        if bool(getattr(getattr(app, "homing", None), "active", False)):
            return "Homing is already in progress."
        if bool(getattr(getattr(app, "probing", None), "active", False)):
            return "Finish the active probe cycle before homing."
        if bool(getattr(getattr(app, "calibration", None), "active", False)):
            return "Finish the active calibration before homing."
        if bool(getattr(getattr(app, "travel_calibration", None), "active", False)):
            return "Finish or abort travel calibration before homing."
        if bool(getattr(app, "job_active", False)):
            return "Finish or abort the active job before homing."
        if bool(getattr(app, "manual_pending_acks", False)):
            return "Wait for the pending GRBL acknowledgement before homing."
        if bool(getattr(app, "motion_busy", False)):
            return "Wait for the current motion operation to finish before homing."
        return "Homing is unavailable until the controller and homing setup are ready."

    @Property("QStringList", notify=state_changed)
    def log_lines(self) -> list[str]:
        return self._log_lines

    @Property(str, notify=state_changed)
    def job_state(self) -> str:
        return self.application.job_state.title()

    @Property(int, notify=state_changed)
    def job_progress(self) -> int:
        return round(self.application.job_progress * 100)

    @staticmethod
    def _format_duration(seconds: float) -> str:
        total = max(0, round(seconds))
        minutes, remainder = divmod(total, 60)
        hours, minutes = divmod(minutes, 60)
        return f"~{hours}:{minutes:02d}:{remainder:02d}" if hours else f"~{minutes}:{remainder:02d}"

    @Property(str, notify=state_changed)
    def job_estimate(self) -> str:
        seconds = self.application.job_estimated_seconds
        return self._format_duration(seconds) if seconds > 0 else "—"

    @Property(str, notify=state_changed)
    def job_elapsed(self) -> str:
        return self._format_duration(self.application.job_elapsed_seconds).lstrip("~")

    @Property(str, notify=state_changed)
    def job_time_remaining(self) -> str:
        if not self.application.program:
            return ""
        if not self.application.job_active:
            return "Complete" if self.application.job_state == "complete" else self.job_estimate
        remaining = self.application.job_remaining_seconds
        if remaining is None:
            return ""
        text = "Nominal estimate exceeded · remaining unknown" if self.application.job_elapsed_seconds >= self.application.job_estimated_seconds else self._format_duration(remaining) + " nominal"
        return text + (" (paused)" if self.application.job_state == "paused" else "")

    @Property(bool, notify=state_changed)
    def connected(self) -> bool:
        return self.application.connected

    @Property(bool, notify=simulation_changed)
    def simulation_active(self) -> bool:
        return self.application.simulation_active

    @Property(str, notify=simulation_changed)
    def simulation_banner(self) -> str:
        return "DIGITAL TWIN — NO PHYSICAL MACHINE" if self.simulation_active else ""

    @Property(str, notify=simulation_changed)
    def simulation_speed(self) -> str:
        return {"realtime": "Realtime", "2x": "2×", "5x": "5×", "10x": "10×", "uncapped": "Uncapped"}.get(
            self.application.simulation_settings.speed, "Realtime"
        )

    @Property(str, notify=simulation_changed)
    def simulation_workpiece(self) -> str:
        return "Collision-only STEP" if self.application.simulation_settings.workpiece.collision_only else "Pocket + retained island"

    @Property(str, notify=simulation_changed)
    def simulation_snapshot_json(self) -> str:
        return json.dumps(self._simulation_snapshot, sort_keys=True, separators=(",", ":"))

    @Property(str, notify=simulation_changed)
    def simulation_stock_metrics_json(self) -> str:
        return json.dumps(self._simulation_stock_metrics, sort_keys=True, separators=(",", ":"))

    @Property("QStringList", notify=simulation_changed)
    def simulation_hazards(self) -> list[str]:
        return list(self._simulation_hazards)

    @Property(bool, notify=simulation_changed)
    def simulation_supervisor_healthy(self) -> bool:
        if hasattr(self.application, "supervisor_state"):
            return self.application.supervisor_state == "healthy"
        runtime = self.application.simulation_runtime
        if not self.simulation_active or runtime is None:
            return False
        # Prefer the runtime's heartbeat-aware safety decision; the fallback
        # keeps this projection compatible with lightweight test doubles.
        healthy = getattr(runtime, "supervisor_healthy", None)
        if healthy is not None:
            return bool(healthy)
        return bool(runtime.supervisor is not None and runtime.supervisor.is_alive())

    @Property(str, notify=simulation_changed)
    def simulation_supervisor_state(self) -> str:
        if hasattr(self.application, "supervisor_state"):
            return str(self.application.supervisor_state)
        return "healthy" if self.simulation_supervisor_healthy else "unavailable"

    @Property(bool, notify=simulation_changed)
    def simulation_export_available(self) -> bool:
        """Whether the public simulation-only evidence action may be used."""
        return bool(self.simulation_active and self.application.simulation_runtime is not None)

    @Property(str, notify=simulation_changed)
    def simulation_export_status(self) -> str:
        return self._simulation_export_status

    @Property(bool, notify=simulation_changed)
    def simulation_hazard_active(self) -> bool:
        return bool(self._simulation_active_hazard)

    @Property(str, notify=simulation_changed)
    def simulation_collision_state(self) -> str:
        if not self.simulation_hazard_active:
            return "Clear"
        if self.simulation_collision_active:
            return "FIRST CONTACT — INTERLOCK ACTIVE"
        return "SAFETY HAZARD — INTERLOCK ACTIVE"

    @Property(bool, notify=simulation_changed)
    def simulation_collision_active(self) -> bool:
        return str(self._simulation_hazard_value("kind", "")) not in {
            "", "protocol", "supervisor_unavailable", "estop_latched",
            "grbl_alarm", "operator_interlock",
        }

    def _simulation_hazard_value(self, key: str, default: object = "") -> object:
        return self._simulation_active_hazard.get(key, default)

    @Property(str, notify=simulation_changed)
    def simulation_collision_kind(self) -> str:
        return str(self._simulation_hazard_value("kind", ""))

    @Property(str, notify=simulation_changed)
    def simulation_collision_message(self) -> str:
        return str(self._simulation_hazard_value("message", ""))

    @Property(str, notify=simulation_changed)
    def simulation_collision_body(self) -> str:
        body_a = str(self._simulation_hazard_value("body_a", ""))
        body_b = str(self._simulation_hazard_value("body_b", ""))
        return " versus ".join(value for value in (body_a, body_b) if value) or "—"

    @Property(str, notify=simulation_changed)
    def simulation_collision_point(self) -> str:
        point = self._simulation_hazard_value("position", ())
        if not isinstance(point, (list, tuple)) or len(point) != 3:
            return "—"
        try:
            return "X{:.2f}  Y{:.2f}  Z{:.2f}".format(*(float(value) for value in point))
        except (TypeError, ValueError):
            return "—"

    def _simulation_collision_coordinate(self, index: int) -> float:
        point = self._simulation_hazard_value("position", ())
        if not isinstance(point, (list, tuple)) or len(point) != 3:
            return 0.0
        try:
            value = float(point[index])
        except (TypeError, ValueError):
            return 0.0
        return value if value == value and abs(value) != float("inf") else 0.0

    @staticmethod
    def _is_terminal_simulation_hazard(hazard: dict[str, object]) -> bool:
        kind = str(hazard.get("kind", ""))
        severity = str(hazard.get("severity", "alarm")).lower()
        # Warning/diagnostic edges may clear normally.  Safety alarms and
        # interlocks remain visible until deliberate recovery or disconnect.
        return kind not in {"", "protocol"} and severity in {"alarm", "interlock", "terminal"}

    def _clear_terminal_simulation_hazard(self) -> None:
        if self._simulation_terminal_hazard:
            self._simulation_terminal_hazard = {}
            self._simulation_active_hazard = {}
            self.simulation_changed.emit()

    @Property(float, notify=simulation_changed)
    def simulation_collision_x(self) -> float:
        return self._simulation_collision_coordinate(0)

    @Property(float, notify=simulation_changed)
    def simulation_collision_y(self) -> float:
        return self._simulation_collision_coordinate(1)

    @Property(float, notify=simulation_changed)
    def simulation_collision_z(self) -> float:
        return self._simulation_collision_coordinate(2)

    @Property(str, notify=simulation_changed)
    def simulation_homing_status(self) -> str:
        """Public capability projection; physical switch commissioning is never inferred."""
        if not self.simulation_active:
            return "Homing switches: physical capability not commissioned"
        return "Homing switches: DIGITAL TWIN inputs (X/Y/Z)"

    @Property(str, notify=simulation_changed)
    def homing_limit_declarations_json(self) -> str:
        return json.dumps(self.application.homing_limit_declarations, sort_keys=True)

    @Property(bool, notify=simulation_changed)
    def simulation_plate_commissioned(self) -> bool:
        return self.application.simulation_plate_commissioned

    @Property(str, notify=simulation_changed)
    def simulation_limit_status(self) -> str:
        runtime = self.application.simulation_runtime
        if not self.simulation_active or runtime is None:
            return "Limit inputs: unavailable while disconnected"
        safety = getattr(runtime, "estop_status", {})
        states = safety.get("limit_states", {})
        state_text = ", ".join(
            f"{axis}={'ACTIVE' if bool(states.get(axis, False)) else 'clear'}"
            for axis in "XYZ"
        )
        pins = safety.get("limit_pins", safety.get("pins", ""))
        return f"Limit inputs: twin {state_text}; Pn={pins or 'none'}"

    def _simulation_safety_value(self, key: str, default: object = False) -> object:
        runtime = self.application.simulation_runtime
        if not self.simulation_active or runtime is None:
            return default
        return getattr(runtime, "estop_status", {}).get(key, default)

    @Property(bool, notify=simulation_changed)
    def simulation_limit_x(self) -> bool:
        return bool(self._simulation_safety_value("limit_states", {}).get("X", False))

    @Property(bool, notify=simulation_changed)
    def simulation_limit_y(self) -> bool:
        return bool(self._simulation_safety_value("limit_states", {}).get("Y", False))

    @Property(bool, notify=simulation_changed)
    def simulation_limit_z(self) -> bool:
        return bool(self._simulation_safety_value("limit_states", {}).get("Z", False))

    @Property(bool, notify=simulation_changed)
    def simulation_estop_active(self) -> bool:
        return bool(self._simulation_safety_value("active", False))

    @Property(bool, notify=simulation_changed)
    def simulation_estop_latched(self) -> bool:
        return bool(self._simulation_safety_value("latched", False))

    @Property(bool, notify=simulation_changed)
    def simulation_estop_recovery_authorized(self) -> bool:
        return bool(self._simulation_safety_value("recovery_authorized", False))

    @Property(bool, notify=simulation_changed)
    def simulation_estop_recovery_ready(self) -> bool:
        return bool(self.simulation_active and self.simulation_estop_latched
                    and not self.simulation_estop_active
                    and self.application.reference_trusted)

    @Property(str, notify=simulation_changed)
    def simulation_estop_status(self) -> str:
        if not self.simulation_active:
            return "E-stop: safety-rated physical power cutoff remains primary"
        mode = str(self._simulation_safety_value("mode", "configured"))
        if self.simulation_estop_active:
            state = "ACTIVE / LATCHED"
        elif self.simulation_estop_latched:
            state = "RELEASED / LATCHED — fresh reference + acknowledge required"
        elif self.simulation_estop_recovery_authorized:
            state = "RELEASED / ACKNOWLEDGED — recovery authorized"
        else:
            state = "RELEASED / CLEAR"
        pins = str(self._simulation_safety_value("pins", "")) or "none"
        return f"E-stop: DIGITAL TWIN {state}; mode={mode}; pins={pins}; no physical GPIO/reset"

    @Property(bool, notify=simulation_changed)
    def simulation_auto_xyz_available(self) -> bool:
        method = next((item for item in self._workflow().work_zero_methods if item.key == "auto_xyz"), None)
        return bool(method and method.available)

    @Property(str, notify=simulation_changed)
    def simulation_auto_xyz_status(self) -> str:
        if not self.simulation_active:
            return "Auto XYZ calibration plate: unavailable — plate/input not commissioned"
        if not self.application.simulation_plate_commissioned:
            return "Auto XYZ calibration plate: unavailable — commission the simulation fixture first"
        return self.application.auto_xyz_calibration_status

    @Property(str, notify=simulation_changed)
    def simulation_auto_xyz_plan(self) -> str:
        if not self.application.simulation_plate_commissioned:
            return "No calibration plan until the simulation plate is commissioned"
        definition = self.application.simulation_plate_definition
        workflow = AutoXYZCalibrationWorkflow(definition)
        seed = (definition.circle_center_x, definition.circle_center_y,
                min(definition.safe_z, self.application.profile.travel_z))
        if not workflow.start(seed=seed, reference_trusted=True, controller_idle=True,
                              spindle_rpm=0.0, envelope=(self.application.profile.travel_x,
                                                         self.application.profile.travel_y,
                                                         self.application.profile.travel_z),
                              commissioned=True):
            return workflow.failure_reason
        return " → ".join(workflow.commands)

    @Property(str, notify=simulation_changed)
    def auto_xyz_calibration_state(self) -> str:
        return self.application.auto_xyz_calibration_state

    @Property(bool, notify=simulation_changed)
    def simulation_auto_xyz_active(self) -> bool:
        return self.application.calibration.active

    @Property(str, notify=state_changed)
    def preferred_transport(self) -> str:
        return self.transport

    @Property(str, notify=state_changed)
    def saved_wifi_host(self) -> str:
        return self.wifi_host

    @Property(int, notify=state_changed)
    def saved_wifi_port(self) -> int:
        return self.wifi_port

    @Property(str, notify=state_changed)
    def saved_usb_port(self) -> str:
        return self.port

    @Property(bool, notify=state_changed)
    def at_reference(self) -> bool:
        position = self.application.virtual_position
        return bool(self.connected and position is not None and self._is_reference_position(position))

    @Property(bool, notify=state_changed)
    def can_return_to_reference(self) -> bool:
        return self.application.can_return_to_reference

    @Property(str, notify=state_changed)
    def homing_state(self) -> str:
        state = getattr(getattr(self.application, "homing", None), "state", "idle")
        return str(getattr(state, "value", state))

    @Property(str, notify=state_changed)
    def homing_status(self) -> str:
        if self.homing_state == "complete":
            return "Home complete · fresh machine reference"
        if self.homing_state in {"waiting_ack", "waiting_idle"}:
            return "Homing in progress · waiting for a fresh Idle report"
        if self.homing_state == "failed":
            return "Homing failed · reference remains untrusted"
        if not self.can_home_machine:
            return "Home unavailable until connection, Idle, switches, and safety gates are ready"
        return "Ready to home"

    @Property("QVariantMap", notify=state_changed)
    def travel_calibration(self) -> dict[str, object]:
        value = getattr(self.application, "travel_calibration_snapshot", None)
        if value is not None:
            return dict(value)
        service = getattr(self.application, "travel_calibration", None)
        return service.snapshot() if service is not None else {}

    @Property(str, notify=state_changed)
    def travel_calibration_status(self) -> str:
        return str(self.travel_calibration.get("status", "Travel calibration unavailable"))

    @Property(bool, notify=state_changed)
    def travel_calibration_active(self) -> bool:
        return str(self.travel_calibration.get("state", "idle")) in {"settings", "homing", "baseline", "searching", "validating"}

    @Property(bool, notify=state_changed)
    def travel_calibration_can_accept(self) -> bool:
        return bool(self.travel_calibration.get("can_accept", False))

    @Property(bool, notify=state_changed)
    def can_jog(self) -> bool:
        return self.application.can_jog

    @Property(str, notify=state_changed)
    def move_action_block_reason(self) -> str:
        app = self.application
        if bool(getattr(app, "can_jog", False)):
            return ""
        if not bool(getattr(app, "operation_transport_ready", True)):
            return "USB is for Wi-Fi setup only; use a verified Wi-Fi connection before moving."
        if not bool(getattr(app, "connected", False)):
            return "Connect to the controller before moving."
        if not bool(getattr(app, "homing_inputs_safe", False)):
            reason = str(getattr(getattr(app, "homing_input_observation", None), "reason", ""))
            return reason or "Release active homing inputs before moving."
        if bool(getattr(app, "job_active", False)):
            return "Finish or abort the active job before moving."
        if bool(getattr(app, "manual_pending_acks", False)):
            return "Wait for the pending GRBL acknowledgement before moving."
        if bool(getattr(app, "motion_busy", False)):
            return "Wait for the current motion operation to finish."
        status = getattr(app, "status", None)
        if not bool(getattr(app, "status_fresh", False)):
            return "Wait for a fresh GRBL status report before moving."
        state = str(getattr(status, "state", "Unknown"))
        if state != "Idle":
            return f"Wait for GRBL to report Idle before moving (current state: {state})."
        session = getattr(app, "session", None)
        if getattr(session, "machine_position", None) is None:
            return "Wait for a current machine position before moving."
        return "Positioning is unavailable until GRBL reports Idle with a current position."

    @Property(bool, notify=state_changed)
    def can_live_jog(self) -> bool:
        return self.application.can_live_jog

    @Property(bool, notify=state_changed)
    def live_jog_active(self) -> bool:
        """Whether a held-jog session is active, including during GRBL state changes."""
        return bool(self._live_jog_lease_token or getattr(self.application, "live_jog_active", False))

    @Property(bool, notify=state_changed)
    def unreferenced_jog_allowed(self) -> bool:
        return self._unreferenced_jog_allowed

    @Property(bool, notify=state_changed)
    def job_active(self) -> bool:
        return self.application.job_active

    @Property(bool, notify=state_changed)
    def can_start_job(self) -> bool:
        return self.application.can_start_job

    @Property(bool, notify=state_changed)
    def start_job_action_ready(self) -> bool:
        return not bool(self.start_job_block_reason)

    @Property(str, notify=state_changed)
    def start_job_block_reason(self) -> str:
        if not self._review_acknowledged:
            return "Review and acknowledge the current validated path before starting."
        app = self.application
        if not bool(getattr(app, "can_start_job", False)):
            if not bool(getattr(app, "operation_transport_ready", True)):
                return "USB is for Wi-Fi setup only; use a verified Wi-Fi connection before starting a job."
            if not bool(getattr(app, "connected", False)):
                return "Connect to the controller before starting a job."
            if not bool(getattr(app, "status_fresh", False)):
                return "Wait for a fresh GRBL status report before starting a job."
            if not bool(getattr(app, "homing_inputs_safe", False)):
                reason = str(getattr(getattr(app, "homing_input_observation", None), "reason", ""))
                return reason or "Release active homing inputs before starting a job."
            if bool(getattr(app, "simulation_active", False)):
                supervisor = str(getattr(app, "supervisor_state", "unavailable"))
                if supervisor != "healthy":
                    return f"Wait for healthy digital-twin safety supervision (current state: {supervisor})."
                runtime = getattr(app, "simulation_runtime", None)
                if getattr(runtime, "active_hazards", ()):
                    return "Clear the active digital-twin safety hazard before starting a job."
                if bool(getattr(runtime, "estop_status", {}).get("interlocked", False)):
                    return "Release and recover the digital-twin E-stop before starting a job."
            session = getattr(app, "session", None)
            if not bool(getattr(session, "can_move", False)):
                status = getattr(app, "status", None)
                state = str(getattr(status, "state", "Unknown"))
                if state != "Idle":
                    return f"Wait for GRBL to report Idle before starting a job (current state: {state})."
                if getattr(session, "machine_position", None) is None:
                    return "Wait for a current machine position before starting a job."
                return "Wait for a safe, current machine position before starting a job."
            status = getattr(app, "status", None)
            spindle_rpm = getattr(status, "spindle", None)
            if spindle_rpm is None:
                return "Wait for a fresh GRBL report confirming the spindle is off before starting a job."
            if spindle_rpm != 0:
                return "Turn the spindle off and wait for a fresh zero-RPM report before starting a job."
            if not bool(getattr(app, "work_zero_confirmed", False)):
                return "Set and confirm XYZ work zero before starting a job."
            if bool(getattr(app, "manual_pending_acks", False)):
                return "Wait for the pending GRBL acknowledgement before starting a job."
            if bool(getattr(app, "motion_busy", False)):
                return "Wait for the current motion operation to finish before starting a job."
            if bool(getattr(app, "job_active", False)):
                return "A job is already active."
            if bool(getattr(getattr(app, "job", None), "restart_requires_reload", False)):
                return "Reload and review the program after the previous job failure."
            if bool(getattr(app, "_z_plate_removal_required", False)):
                return "Remove the Z touch plate and clip, then acknowledge their removal."
            if getattr(app, "program", None) is None:
                return "Load a G-code program before starting a job."
            try:
                fits, reason = app.preflight()
            except (AttributeError, RuntimeError, TypeError, ValueError):
                fits, reason = False, "Job validation is unavailable."
            if not fits:
                return f"Resolve the job validation issue before starting: {reason}"
            return "The machine is not ready to start a job. Review the current machine and safety state."
        if not self._guided_preflight_confirmed:
            return "Confirm that the material and tool are secure before starting."
        return ""

    @Property(int, notify=state_changed)
    def guided_step(self) -> int:
        return self._guided_step

    @Property(int, constant=True)
    def guided_step_count(self) -> int:
        return 7

    @Property("QStringList", constant=True)
    def guided_step_names(self) -> list[str]:
        return list(GUIDED_STEP_NAMES)

    @Property(str, notify=state_changed)
    def guided_step_title(self) -> str:
        return (
            "Configure the machine",
            "Connect to GRBL",
            "Home the machine",
            "Set the work zero",
            "Prepare a job",
            "Review the validated path",
            "Run the job",
        )[self._guided_step]

    @Property(str, notify=state_changed)
    def guided_step_description(self) -> str:
        return (
            "Review the machine profile, axes, probes, and digital-twin settings. Configuration is periodic setup, not a motion action.",
            "Choose USB serial, Wi-Fi TCP, or the loopback digital twin and wait for a fresh controller report.",
            "Home the machine with all declared switches to establish its trusted reference; incomplete switch commissioning remains blocked.",
            "Choose Manual XYZ, commissioned movable Z, or loopback-only Auto XYZ. Fresh WCO confirmation is required.",
            "Load validated metric G-code or create text, plaque, engraving, or STEP toolpaths.",
            "Inspect the path, envelope, stock fit, collision result, and execution facts, then acknowledge this review.",
            "Complete physical preflight before starting. Pause, resume, abort, progress, hazards, and recovery remain here.",
        )[self._guided_step]

    @Property(bool, notify=state_changed)
    def guided_step_ready(self) -> bool:
        return self._workflow().steps[self._guided_step].continuable

    @Property(str, notify=state_changed)
    def guided_step_reason(self) -> str:
        return self._workflow().steps[self._guided_step].reason

    @Property(bool, notify=state_changed)
    def guided_preflight_confirmed(self) -> bool:
        return self._guided_preflight_confirmed

    @Property("QStringList", notify=ports_changed)
    def ports(self) -> list[str]:
        return self._ports

    def apply_status(self, status: GrblStatus) -> None:
        """Apply a status report directly for tests and non-transport adapters."""
        self.application.apply_status(status)
        self._project_status(status)

    @Slot(str)
    def show_preview_notice(self, message: str) -> None:
        """Show a bounded navigation or preview notice."""
        self._set_notice(message)

    def _arm_guided_completion(self, step: int) -> None:
        """Remember a user action whose completion may advance the rail."""
        if self._guided_step == step:
            self._guided_completion_pending = step

    def _advance_guided_on_completion(self) -> None:
        """Advance only after the controller reports the requested outcome."""
        step = self._guided_completion_pending
        if step is None or self._guided_step != step:
            return
        projection = self._workflow()
        if step == 1:
            # The connection service's accepted outcome is the observed
            # completion of Connect. Safety remains an enforced backend gate,
            # but is not a separate click-through operator step.
            complete = bool(self.application.connected)
        elif step == 2:
            complete = bool(
                self.application.reference_trusted
                and not self.application.homing.active
                and not self.application.motion_busy
            )
        elif step == 3:
            complete = bool(
                self.application.work_zero_confirmed
                and not self.application.manual_pending_acks
                and not self.application.motion_busy
                and not self.application.probing.active
                and not self.application.calibration.active
            )
        else:
            complete = False
        if not complete or not projection.steps[step].continuable:
            return
        self._guided_completion_pending = None
        self._guided_step = 5 if step == 3 else step + 1
        self._set_notice(f"{projection.steps[step].name} complete — continue with {projection.steps[self._guided_step].name}")

    @Slot(int)
    def select_guided_step(self, index: int) -> None:
        """Navigate freely; action-level guards remain authoritative."""
        projection = self._workflow()
        index = int(index)
        if index < 0 or index >= len(projection.steps):
            return
        if index != self._guided_step:
            self._guided_completion_pending = None
            self._guided_step = index
            self._emit_state()

    @Slot(int)
    def select_workflow_step(self, index: int) -> None:
        self.select_guided_step(index)

    @Slot()
    def guided_continue(self) -> None:
        """Advance one step only after its projected prerequisite is true."""
        projection = self._workflow()
        current = projection.steps[self._guided_step]
        if not current.continuable:
            self._set_notice(f"Cannot continue — {current.reason}")
            return
        if self._guided_step < len(projection.steps) - 1:
            self._guided_step = 5 if self._guided_step == 3 else self._guided_step + 1
            self._emit_state()

    @Slot()
    def continue_guided_step(self) -> None:
        self.guided_continue()

    @Slot()
    def guided_back(self) -> None:
        if self.application.job_active:
            if self._guided_step != len(GUIDED_STEP_NAMES) - 1:
                self._guided_step = len(GUIDED_STEP_NAMES) - 1
                self._emit_state()
            self._set_notice("Run monitoring remains selected while the job is active")
            return
        if self._guided_step > 0:
            projection = self._workflow()
            candidate = 3 if self._guided_step == 5 else self._guided_step - 1
            while candidate > 0 and not projection.steps[candidate].selectable:
                candidate -= 1
            if not projection.steps[candidate].selectable:
                candidate = projection.earliest_incomplete
            self._guided_completion_pending = None
            self._guided_step = candidate
            self._emit_state()

    @Slot()
    def back_guided_step(self) -> None:
        self.guided_back()

    @Slot()
    def acknowledge_review(self) -> None:
        if self._guided_step != 5:
            self._set_notice("Review acknowledgement is available on the Review step")
            return
        projection = self._workflow()
        if not projection.steps[5].state == "required":
            self._set_notice(f"Review acknowledgement blocked — {projection.steps[5].reason}")
            return
        self._review_acknowledged = True
        self._set_notice("Review acknowledged for this session")
        self._emit_state()

    @Slot()
    def acknowledge_guided_review(self) -> None:
        self.acknowledge_review()

    @Slot()
    def show_connection_notice(self) -> None:
        self._set_notice("Use the Connect control to choose USB serial or Wi-Fi TCP.")

    @Slot()
    def guided_next(self) -> None:
        self.guided_continue()

    @Slot()
    def guided_previous(self) -> None:
        self.guided_back()

    @Slot()
    def guided_reset(self) -> None:
        step = self._workflow().earliest_incomplete
        self._guided_step = 5 if step == 4 else step
        self._guided_preflight_confirmed = False
        self._review_acknowledged = False
        self._next_part_available = False
        self._guided_completion_pending = None
        self._emit_state()

    @Property(bool, notify=state_changed)
    def next_part_available(self) -> bool:
        """A completed job may be repeated only through an explicit action."""
        return self._next_part_available

    @Slot()
    def prepare_next_part(self) -> None:
        if not self._next_part_available or self.application.job_active or self.application.job_state != "complete":
            self._set_notice("Next part is available only after a successful completed job")
            return
        self._next_part_available = False
        self._next_part_armed = False
        self._guided_completion_pending = None
        self._review_acknowledged = False
        self._guided_preflight_confirmed = False
        step = self._workflow().earliest_incomplete
        self._guided_step = 5 if self.program is not None or step == 4 else step
        self._set_notice("Next part ready — review the current path and complete preflight before starting")
        self._emit_state()

    @Slot()
    def confirm_guided_preflight(self) -> None:
        if self._guided_step != 6:
            return
        self._guided_preflight_confirmed = True
        self._set_notice("Physical preflight acknowledged for this guided run")
        self._emit_state()

    @Slot()
    def guided_start_job(self) -> None:
        if self._guided_step != 6:
            return
        self.start_job()

    @Slot(str, float, float, float, float)
    def save_profile(self, name: str, travel_x: float, travel_y: float, travel_z: float, safe_z: float) -> None:
        try:
            profile = MachineProfile(name.strip(), travel_x, travel_y, travel_z, safe_z)
            profile.validate()
            self.application.save_profile(profile)
        except (OSError, ValueError, TypeError) as exc:
            self._set_notice(f"Machine profile rejected — {exc}")
            return
        self._set_notice("Machine profile saved; the current reference was retained")
        self._emit_state()

    @Slot()
    def invalidate_reference(self) -> None:
        self.application.invalidate_machine_reference("Manually invalidated")
        self._set_notice("Virtual reference invalidated")
        self._emit_state()

    @Slot()
    def acknowledge_unreferenced_jog(self) -> None:
        self._unreferenced_jog_allowed = True
        self._set_notice("Unreferenced jogging enabled for this connected session")
        self._emit_state()

    @Slot()
    def soft_reset(self) -> None:
        if not self.connected:
            self._set_notice("Soft reset ignored — not connected")
            return
        outcome = self.application.soft_reset()
        self._set_notice(outcome.message)

    @Slot(str)
    def confirm_pending_action(self, token: str) -> None:
        pending = self._pending_confirmation
        if pending is None or token != self._confirmation_token:
            self._set_notice("This action was canceled or replaced; choose it again.")
            return
        self._pending_confirmation = None
        self._confirmation_token = ""
        operation, payload = pending
        if operation == "spindle_start":
            outcome = self.application.start_spindle(int(payload))
            self._set_notice(outcome.message)
        elif operation == "job_start":
            if not isinstance(payload, str):
                self._set_notice("Job confirmation expired — review authorization is missing")
                return
            if not self._review_acknowledged or not self._guided_preflight_confirmed:
                self._set_notice("Job confirmation expired — review and physical preflight must remain acknowledged")
                return
            outcome = self.application.start_authorized_job(payload)
            if outcome.accepted:
                self._next_part_armed = True
                self._guided_preflight_confirmed = False
                self._review_acknowledged = False
                self._clear_terminal_simulation_hazard()
            self._set_notice(outcome.message)
        elif operation == "job_abort":
            if not self.application.job_active:
                self._set_notice("Abort ignored — no job is active")
                return
            self.application.abort_job()
            self._set_notice("Job aborted — references retained")
        elif operation == "wifi_setup":
            if not isinstance(payload, tuple) or len(payload) != 3:
                self._set_notice("Wi-Fi setup confirmation expired")
                return
            outcome = self.application.begin_wifi_setup(payload[0], payload[1], payload[2], time.monotonic())
            self._set_notice(outcome.message)
        self._emit_state()

    @Slot()
    def reject_pending_action(self) -> None:
        if self._pending_confirmation is not None:
            self._pending_confirmation = None
            self._confirmation_token = ""
            self._set_notice("Action canceled")
            self._emit_state()

    @Slot(str, str, float, float, float, float, float, float, float, str, int)
    def preview_text(self, text: str, font: str, height: float, depth: float, safe_z: float, cut_feed: float, plunge_feed: float, letter_spacing: float, line_spacing: float, alignment: str, spindle_rpm: int) -> None:
        try:
            engraving = self.application.generate_text(
                text, font=font, text_height=height, depth=depth, safe_z=safe_z,
                cut_feed=cut_feed, plunge_feed=plunge_feed,
                letter_spacing=letter_spacing, line_spacing=line_spacing, alignment=alignment,
                spindle_rpm=spindle_rpm if spindle_rpm > 0 else None,
            )
        except (ValueError, TypeError):
            self._preview_strokes = []
            self._preview_stock_width = 0.0
            self._preview_stock_height = 0.0
            self._preview_summary = "Enter valid text settings to preview the centerline toolpath."
        else:
            result = engraving.result
            self._preview_strokes = self._strokes_for_qml(result.strokes)
            self._preview_stock_width = 0.0
            self._preview_stock_height = 0.0
            self._preview_summary = f"{result.width:.1f} × {result.height:.1f} mm · {result.stroke_count} strokes"
        self._emit_state()

    @Slot(str, str, bool, str, str, float, float, float, float, float, str, float, float, float, float, int)
    def preview_plaque(self, title: str, subtitle: str, subtitle_enabled: bool, title_font: str, subtitle_font: str, title_height: float, subtitle_height: float, width: float, height: float, margin: float, border: str, depth: float, safe_z: float, cut_feed: float, plunge_feed: float, spindle_rpm: int) -> None:
        try:
            plaque = self.application.generate_plaque(
                title, subtitle, subtitle_enabled=subtitle_enabled, title_font=title_font,
                subtitle_font=subtitle_font, title_height=title_height, subtitle_height=subtitle_height,
                width=width, height=height, margin=margin, border=border, depth=depth,
                safe_z=safe_z, cut_feed=cut_feed, plunge_feed=plunge_feed,
                spindle_rpm=spindle_rpm if spindle_rpm > 0 else None,
            )
        except (ValueError, TypeError):
            self._preview_strokes = []
            self._preview_stock_width = 0.0
            self._preview_stock_height = 0.0
            self._preview_summary = "Enter valid plaque settings to preview the centerline toolpath."
        else:
            result = plaque.result
            self._preview_strokes = self._strokes_for_qml(result.strokes)
            self._preview_stock_width = 0.0
            self._preview_stock_height = 0.0
            self._preview_summary = f"{result.width:.1f} × {result.height:.1f} mm · {result.stroke_count} strokes · {border}"
        self._emit_state()

    @Slot(bool)
    def set_physical_preflight_confirmed(self, confirmed: bool) -> None:
        """Record the explicit per-run material/tool check from Preview & Run."""
        self._guided_preflight_confirmed = bool(confirmed)
        self._emit_state()

    @Slot(str, str, float, float, float, float, float, float, float, str, int)
    def request_preview_text(self, *args) -> None:
        self._queue_preview("text", args)

    @Slot(str, str, bool, str, str, float, float, float, float, float, str, float, float, float, float, int)
    def request_preview_plaque(self, *args) -> None:
        self._queue_preview("plaque", args)

    def _queue_preview(self, kind: str, args: tuple[object, ...]) -> None:
        self._preview_generation += 1
        self._pending_preview = (kind, tuple(args))
        self._preview_timer.start()
        if self._active_operation is None:
            self._active_operation = self._operations.begin(
                OperationCategory.BACKGROUND,
                "Preview",
                phase="Updating preview…",
                cancellable=False,
                blocking_scopes={"preview"},
            )
        self._emit_state()

    def _run_pending_preview(self) -> None:
        if self._pending_preview is None:
            return
        kind, args = self._pending_preview
        self._preview_task_generation = self._preview_generation
        self._preview_task_token = self._task_runner.submit(lambda: self._generate_preview(kind, args))

    def _generate_preview(self, kind: str, args: tuple[object, ...]):
        if kind == "text":
            return self.application.generate_text(
                args[0], font=args[1], text_height=args[2], depth=args[3], safe_z=args[4], cut_feed=args[5],
                plunge_feed=args[6], letter_spacing=args[7], line_spacing=args[8], alignment=args[9],
                spindle_rpm=args[10] if args[10] > 0 else None,
            )
        return self.application.generate_plaque(
            args[0], args[1], subtitle_enabled=args[2], title_font=args[3], subtitle_font=args[4],
            title_height=args[5], subtitle_height=args[6], width=args[7], height=args[8], margin=args[9],
            border=args[10], depth=args[11], safe_z=args[12], cut_feed=args[13], plunge_feed=args[14],
            spindle_rpm=args[15] if args[15] > 0 else None,
        )

    def _start_step_import(self, path: Path) -> None:
        """Start the shared asynchronous STEP import pipeline."""
        if self._step_importing:
            self._set_notice("STEP import is already in progress")
            return
        if not path.is_file():
            detail = f"STEP file does not exist: {path}"
            self._step_source_text = "STEP import failed"
            self._step_import_status = f"Import failed: {detail}"
            self._set_notice(f"STEP import rejected — {detail}")
            self._emit_state()
            return
        self._step_importing = True
        self._step_source_text = f"Importing {path.name}…"
        self._step_import_status = "Reading STEP geometry and finding planar machining faces…"
        self._active_operation = self._operations.begin(
            OperationCategory.BACKGROUND,
            "STEP import",
            phase="Reading STEP geometry…",
            cancellable=False,
            blocking_scopes={"step_import"},
        )
        self._emit_state()
        self._step_task_token = self._task_runner.submit(lambda: self.application.import_step(path))

    @Slot(QUrl)
    def import_step_file(self, selected_file: QUrl) -> None:
        """Import a STEP URL selected by Qt Quick's file dialog."""
        path_text = selected_file.toLocalFile()
        if not path_text:
            self._set_notice("STEP import rejected — choose a local STEP file")
            return
        self._start_step_import(Path(path_text))

    @Slot()
    def load_bundled_showcase_step(self) -> None:
        """Load the versioned showcase fixture through the normal importer."""
        try:
            path = self.application.bundled_showcase_step_path
        except (FileNotFoundError, OSError, RuntimeError, ValueError, TypeError) as exc:
            detail = str(exc)
            self._step_source_text = "Bundled showcase STEP unavailable"
            self._step_import_status = f"Import failed: {detail}"
            self._set_notice(f"Bundled showcase STEP unavailable — {detail}")
            self._emit_state()
            return
        self._start_step_import(path)

    @Slot(object)
    def _finish_background_task(self, result: TaskResult) -> None:
        if result.token == self._tailscale_task_token:
            self._tailscale_task_token = 0
            if result.error is not None:
                self._tailscale_status = TailscaleStatus("Error", message=str(result.error))
                if self._live_server:
                    self._live_server.stop()
                    self._live_server = None
                self._set_notice(f"Pine Live could not be enabled — {result.error}")
            else:
                self._tailscale_status = result.value
                if not isinstance(result.value, TailscaleStatus) or not result.value.ready:
                    if self._live_server:
                        self._live_server.stop()
                        self._live_server = None
                    self._set_notice(self._tailscale_status.message)
                else:
                    if self._live_server:
                        self._live_server.public_url = result.value.serve_url
                        self._live_server.allowed_origins = (result.value.serve_url.rstrip("/"),)
                        self._live_server.secure_cookie = True
                    self._live_settings.enabled = True
                    self._live_settings.bind_host = "127.0.0.1"
                    self._save_live_settings()
                    self._camera_service.start()
                    self._set_notice("Pine Live is available over your Tailscale network")
            self._refresh_live_state()
            return
        if result.token == self._preview_task_token:
            self._preview_task_token = 0
            if self._preview_task_generation != self._preview_generation:
                return
            if result.error is not None:
                self._preview_summary = "Enter valid settings to preview the toolpath."
                self._finish_operation(success=False, error=str(result.error), recovery_action="Review settings")
            else:
                artifact = result.value
                generated = artifact.result
                self._preview_strokes = self._strokes_for_qml(generated.strokes)
                self._preview_stock_width = 0.0
                self._preview_stock_height = 0.0
                suffix = f" · {generated.border}" if hasattr(generated, "border") else ""
                self._preview_summary = f"{generated.width:.1f} × {generated.height:.1f} mm · {generated.stroke_count} strokes{suffix}"
                self._finish_operation(success=True, summary="Preview ready")
            self._emit_state()
            return
        if result.token != self._step_task_token:
            return
        self._step_task_token = 0
        if result.error is not None:
            self._finish_step_import(None, str(result.error))
        else:
            self._finish_step_import(result.value, "")

    @Slot(object, str)
    def _finish_step_import(self, model: object, error: str) -> None:
        self._step_importing = False
        if not isinstance(model, StepPlanarModel):
            detail = error or "The STEP importer returned no model"
            self._step_source_text = "STEP import failed"
            self._step_import_status = f"Import failed: {detail}"
            self._set_notice(f"STEP import rejected — {detail}")
            self._finish_operation(success=False, error=detail, recovery_action="Import STEP")
            self._emit_state()
            return
        self._step_model = model
        self._step_path = model.path
        self._step_source_text = model.path.name
        self._step_import_status = ""
        self._preview_strokes = self._strokes_for_step_model(model)
        self._preview_model_strokes = []
        self._preview_stock_width = 0.0
        self._preview_stock_height = 0.0
        self._preview_summary = self.step_model_summary
        self._step_operations = []
        self._step_preview_valid = False
        self._set_step_isometric_model(model)
        self._set_notice(f"Imported planar STEP model {model.path.name}")
        self._finish_operation(success=True, summary=f"Imported {model.path.name}")
        self._emit_state()
        self.step_model_imported.emit(self._recommended_step_mode(model))

    @Slot(str)
    def set_step_plane(self, plane: str) -> None:
        if self._step_path is None:
            return
        try:
            model = self.application.import_step(self._step_path, plane)
        except StepImportError as exc:
            self._set_notice(f"STEP face unavailable — {exc}")
            return
        self._step_model = model
        self._preview_strokes = self._strokes_for_step_model(model)
        self._preview_model_strokes = []
        self._preview_stock_width = 0.0
        self._preview_stock_height = 0.0
        self._preview_summary = self.step_model_summary
        self._step_operations = []
        self._step_preview_valid = False
        self._set_step_isometric_model(model)
        self._set_notice(f"Selected {model.face_plane} machining face")
        self._emit_state()
        self.step_model_imported.emit(self._recommended_step_mode(model))

    @Slot(str, str, float, float, str, float, float, int, float, float, int, float, float, float, float, float, int, float)
    def preview_step(self, mode: str, orientation: str, stock_width: float, stock_height: float, zero_location: str, tool_diameter: float, depth: float, passes: int, stock_thickness: float, breakthrough: float, tab_count: int, tab_width: float, tab_height: float, safe_z: float, cut_feed: float, plunge_feed: float, spindle_rpm: int, max_stepdown: float = 0.0) -> None:
        if self._step_model is None:
            self._preview_strokes = []
            self._preview_stock_width = 0.0
            self._preview_stock_height = 0.0
            self._preview_summary = "Import a planar STEP model first."
            self._step_operations = []
            self._step_preview_valid = False
            self._emit_state()
            return
        try:
            job = self.application.generate_step(
                self._step_model, mode=mode, orientation=orientation,
                stock_width=stock_width, stock_height=stock_height,
                zero_location=zero_location, tool_diameter=tool_diameter,
                depth=depth, passes=passes, safe_z=safe_z,
                cut_feed=cut_feed, plunge_feed=plunge_feed,
                spindle_rpm=spindle_rpm if spindle_rpm > 0 else None,
                stock_thickness=stock_thickness, breakthrough=breakthrough,
                max_stepdown=max_stepdown if max_stepdown > 0 else None,
                tab_count=tab_count, tab_width=tab_width, tab_height=tab_height,
            )
        except (ValueError, TypeError) as exc:
            self._preview_strokes = []
            self._preview_model_strokes = []
            self._preview_stock_width = 0.0
            self._preview_stock_height = 0.0
            self._preview_summary = "Enter valid STEP machining settings to preview the toolpath."
            self._step_operations = []
            self._step_preview_valid = False
            self._step_isometric_paths = []
            self._set_notice(f"STEP preview rejected — {exc}")
        else:
            self._preview_strokes = self._strokes_for_qml(job.strokes)
            self._preview_model_strokes = self._strokes_for_qml(job.result.model_strokes)
            self._preview_stock_width = job.result.stock_width
            self._preview_stock_height = job.result.stock_height
            self._preview_summary = self._step_job_summary(job.result)
            self._step_operations = self._operations_for_qml(job.result)
            self._step_preview_valid = True
            self._set_step_isometric_job(job.result, orientation)
        self._emit_state()

    @Slot(str, str, float, int, float, float, float, float, int, float, int, float, float)
    def save_step_prepare_defaults(
        self,
        orientation: str,
        zero_location: str,
        tool_diameter: float,
        passes: int,
        max_stepdown: float,
        safe_z: float,
        cut_feed: float,
        plunge_feed: float,
        spindle_rpm: int,
        breakthrough: float,
        tab_count: int,
        tab_width: float,
        tab_height: float,
    ) -> None:
        settings = StepPrepareSettings(
            orientation=orientation,
            zero_location=zero_location,
            tool_diameter=tool_diameter,
            passes=passes,
            max_stepdown=max_stepdown,
            safe_z=safe_z,
            cut_feed=cut_feed,
            plunge_feed=plunge_feed,
            spindle_rpm=spindle_rpm,
            breakthrough=breakthrough,
            tab_count=tab_count,
            tab_width=tab_width,
            tab_height=tab_height,
        )
        try:
            self.application.save_step_prepare_settings(settings)
        except (OSError, ValueError, TypeError) as exc:
            self._set_notice(f"Prepare defaults were not saved — {exc}")
            return
        self._emit_state()

    @Slot(str, str, float, float, float, float, float, float, float, str, int)
    def create_text(self, text: str, font: str, height: float, depth: float, safe_z: float, cut_feed: float, plunge_feed: float, letter_spacing: float, line_spacing: float, alignment: str, spindle_rpm: int) -> None:
        try:
            engraving = self.application.generate_text(
                text, font=font, text_height=height, depth=depth, safe_z=safe_z,
                cut_feed=cut_feed, plunge_feed=plunge_feed,
                letter_spacing=letter_spacing, line_spacing=line_spacing, alignment=alignment,
                spindle_rpm=spindle_rpm if spindle_rpm > 0 else None,
            )
        except (ValueError, TypeError) as exc:
            self._set_notice(f"Text settings rejected — {exc}")
            return
        result = engraving.result
        self._load_generated_program(engraving.gcode, engraving.filename, result.strokes, f"Text · {result.width:.1f} × {result.height:.1f} mm · {result.stroke_count} strokes")

    @Slot(str, str, bool, str, str, float, float, float, float, float, str, float, float, float, float, int)
    def create_plaque(self, title: str, subtitle: str, subtitle_enabled: bool, title_font: str, subtitle_font: str, title_height: float, subtitle_height: float, width: float, height: float, margin: float, border: str, depth: float, safe_z: float, cut_feed: float, plunge_feed: float, spindle_rpm: int) -> None:
        try:
            plaque = self.application.generate_plaque(
                title, subtitle, subtitle_enabled=subtitle_enabled, title_font=title_font,
                subtitle_font=subtitle_font, title_height=title_height, subtitle_height=subtitle_height,
                width=width, height=height, margin=margin, border=border, depth=depth,
                safe_z=safe_z, cut_feed=cut_feed, plunge_feed=plunge_feed,
                spindle_rpm=spindle_rpm if spindle_rpm > 0 else None,
            )
        except (ValueError, TypeError) as exc:
            self._set_notice(f"Plaque settings rejected — {exc}")
            return
        result = plaque.result
        self._load_generated_program(plaque.gcode, plaque.filename, result.strokes, f"Plaque · {result.width:.1f} × {result.height:.1f} mm · {result.stroke_count} strokes")

    @Slot(str, str, float, float, str, float, float, int, float, float, int, float, float, float, float, float, int, float)
    def create_step(self, mode: str, orientation: str, stock_width: float, stock_height: float, zero_location: str, tool_diameter: float, depth: float, passes: int, stock_thickness: float, breakthrough: float, tab_count: int, tab_width: float, tab_height: float, safe_z: float, cut_feed: float, plunge_feed: float, spindle_rpm: int, max_stepdown: float = 0.0) -> None:
        if self._step_model is None:
            self._set_notice("STEP job unavailable — import a planar STEP model first")
            return
        if not self._step_preview_valid:
            self._set_notice("STEP job unavailable — resolve the rejected preview first")
            return
        try:
            job = self.application.generate_step(
                self._step_model, mode=mode, orientation=orientation,
                stock_width=stock_width, stock_height=stock_height,
                zero_location=zero_location, tool_diameter=tool_diameter,
                depth=depth, passes=passes, safe_z=safe_z,
                cut_feed=cut_feed, plunge_feed=plunge_feed,
                spindle_rpm=spindle_rpm if spindle_rpm > 0 else None,
                stock_thickness=stock_thickness, breakthrough=breakthrough,
                max_stepdown=max_stepdown if max_stepdown > 0 else None,
                tab_count=tab_count, tab_width=tab_width, tab_height=tab_height,
            )
        except (ValueError, TypeError) as exc:
            self._set_notice(f"STEP machining settings rejected — {exc}")
            return
        self._load_generated_program(
            job.gcode,
            job.filename,
            job.strokes,
            self._step_job_summary(job.result),
            job.result.stock_width,
            job.result.stock_height,
        )
        self._preview_model_strokes = self._strokes_for_qml(job.result.model_strokes)
        self._set_step_isometric_job(job.result, orientation)
        self._emit_state()

    @Slot(QUrl)
    def save_gcode_file(self, selected_file: QUrl) -> None:
        if self.program is None:
            self._set_notice("Save ignored — no validated G-code is loaded")
            return
        path_text = selected_file.toLocalFile()
        if not path_text:
            return
        try:
            Path(path_text).write_text("\n".join(self.program.commands) + "\n", encoding="ascii")
        except OSError as exc:
            self._set_notice(f"G-code not saved — {exc}")
            return
        self._set_notice(f"Saved validated G-code to {Path(path_text).name}")

    @Slot()
    def refresh_ports(self) -> None:
        if self.application.simulation_active:
            self._set_notice("Serial discovery is unavailable during a digital-twin session")
            return
        self._refresh_ports()

    @Slot(str)
    def connect_to_usb(self, port_label: str) -> None:
        if self.connected:
            self.disconnect()
            return
        port = port_label.split(" ", 1)[0].strip()
        outcome = self.application.connect_usb(port)
        if not outcome.accepted:
            self._set_notice(outcome.message)
            return
        self.transport = outcome.mode.value if outcome.mode else "USB serial"
        self.port = port
        self._auto_connection_state = "connected"
        self._arm_guided_completion(1)
        try:
            self.application.save_usb_settings(port)
        except (OSError, ValueError):
            self._logger.exception("Unable to save the last successful USB connection")
        self._connection_text = outcome.message
        self._set_notice(self._connection_text)
        self._emit_state()

    @Slot(str, int)
    def connect_to_wifi(self, host: str, port: int) -> None:
        if self.connected:
            self.disconnect()
            return
        outcome = self.application.begin_wifi(host, port)
        if not outcome.accepted:
            self._set_notice(outcome.message)
            return
        self.transport = outcome.mode.value if outcome.mode else "Wi-Fi TCP"
        self._auto_connection_state = "trying"
        self._connection_text = outcome.message
        self._emit_state()

    @Slot(str, str)
    def configure_wifi(self, ssid: str, password: str) -> None:
        if self.transport != "USB serial" or not self.connected:
            self._set_notice("Wi-Fi setup requires an active USB connection")
            return
        if self.status is None or not self.status.can_jog:
            self._set_notice("Wi-Fi setup requires GRBL Idle")
            return
        try:
            self.application.validate_wifi_setup(ssid, password, self.wifi_port)
        except ValueError as exc:
            self._set_notice(f"Invalid Wi-Fi settings — {exc}")
            return
        self._request_confirmation(
            "wifi_setup",
            (ssid, password, self.wifi_port),
            "Switch controller to station mode?",
            "The controller will restart and join the selected 2.4 GHz network. The current machine reference will be cleared; home again after reconnecting.",
        )

    @Slot()
    def disconnect(self) -> None:
        self._disconnected("Disconnected by operator")

    @Slot(str, float)
    def jog(self, axis: str, distance: float) -> None:
        if not self.can_jog:
            self._set_notice("Jog ignored — machine is not ready or GRBL is not Idle")
            return
        if not self.application.reference_trusted and not self._unreferenced_jog_allowed:
            self.unreferenced_jog_requested.emit()
            return
        outcome = self.application.jog(axis, distance, 500.0)
        if not outcome.accepted:
            self._set_notice(f"Jog blocked — {outcome.message}")

    @Slot(str, float)
    def start_live_jog(self, axis: str, direction: float) -> None:
        if self._live_jog_lease_token:
            self.stop_live_jog()
        if not self.can_live_jog:
            self._set_notice("Live jog ignored — machine is not ready or GRBL is not Idle")
            return
        if not self.application.reference_trusted and not self._unreferenced_jog_allowed:
            self.unreferenced_jog_requested.emit()
            return
        token = secrets.token_hex(16)
        self._live_jog_lease_generation += 1
        generation = self._live_jog_lease_generation
        self._live_jog_lease_token = token
        renew_action = getattr(self.application, "renew_live_jog", None)
        try:
            if callable(renew_action):
                outcome = self.application.start_live_jog(
                    axis, direction, self._unreferenced_jog_allowed, 500.0, lease_token=token
                )
            else:
                # The in-process controller remains available to isolated GUI
                # fixtures; production clients expose renew_live_jog and use
                # the backend-enforced lease contract.
                outcome = self.application.start_live_jog(
                    axis, direction, self._unreferenced_jog_allowed, 500.0
                )
        except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as exc:
            self.stop_live_jog()
            self._set_notice(f"Live jog start failed — {exc}")
            return
        if not outcome.accepted:
            self.stop_live_jog()
            self._set_notice(outcome.message)
            return
        if self._live_jog_lease_token != token or self._live_jog_lease_generation != generation:
            # A release may race an in-flight start. Never revive its heartbeat;
            # send a final cancel in case the delayed start reached the owner last.
            self.application.stop_live_jog()
            return
        if callable(renew_action):
            self._live_jog_renew_timer.start()
        self._emit_state()

    def _renew_live_jog_lease(self) -> None:
        token = self._live_jog_lease_token
        if not token:
            self._live_jog_renew_timer.stop()
            return
        renew_action = getattr(self.application, "renew_live_jog", None)
        if not callable(renew_action):
            self._fail_live_jog_lease(token, "backend lease renewal is unavailable")
            return
        try:
            outcome = renew_action(token)
        except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as exc:
            self._fail_live_jog_lease(token, str(exc))
            return
        if not outcome.accepted:
            self._fail_live_jog_lease(token, outcome.message)

    def _fail_live_jog_lease(self, token: str, message: str) -> None:
        if token != self._live_jog_lease_token:
            return
        self.stop_live_jog()
        self._set_notice(f"Live jog stopped — {message}")
        self._emit_state()

    @Slot()
    def stop_live_jog(self) -> None:
        self._live_jog_renew_timer.stop()
        self._live_jog_lease_generation += 1
        self._live_jog_lease_token = ""
        outcome = self.application.stop_live_jog()
        if not outcome.accepted:
            self._set_notice(outcome.message)
        self._last_status_poll = 0.0
        self._emit_state()

    @Slot(int)
    def start_spindle(self, rpm: int) -> None:
        if not self.can_jog:
            self._set_notice("Spindle start ignored — machine is not ready or GRBL is not Idle")
            return
        if not 1 <= rpm <= 24000:
            self._set_notice("Spindle RPM must be between 1 and 24000")
            return
        self._request_confirmation(
            "spindle_start",
            rpm,
            "Start spindle?",
            f"Start the spindle clockwise at {rpm} RPM? Keep clear of the tool and be ready to cut physical power.",
        )

    @Slot()
    def stop_spindle(self) -> None:
        if not self.connected:
            self._set_notice("Spindle stop ignored — not connected")
            return
        outcome = self.application.stop_spindle()
        self._set_notice(outcome.message)

    @Slot(float, float, float, float)
    def move_to(self, x: float, y: float, z: float, feed: float = 500.0) -> None:
        if not self.can_jog:
            self._set_notice("Position move ignored — machine is not ready")
            return
        outcome = self.application.move_to(Position(x, y, z), feed)
        if not outcome.accepted:
            self._set_notice(f"Position move blocked — {outcome.message}")

    @Slot()
    def connect_to_simulation(self) -> None:
        if self.connected:
            self.disconnect()
            return
        outcome = self.application.connect_simulation()
        if not outcome.accepted:
            self._set_notice(outcome.message)
            return
        self.transport = "Virtual Machine (Digital Twin)"
        self._connection_text = outcome.message
        self._arm_guided_completion(1)
        self._auto_connection_state = "connected"
        self._set_notice("DIGITAL TWIN — no physical machine is connected")
        self.simulation_changed.emit()
        self._emit_state()

    @Slot(str, str)
    def configure_simulation(self, speed_label: str, workpiece_label: str) -> None:
        speed = {"Realtime": "realtime", "2×": "2x", "5×": "5x", "10×": "10x", "Uncapped": "uncapped"}.get(speed_label, speed_label)
        outcome = self.application.configure_simulation(speed, workpiece_label)
        self._set_notice(outcome.message)
        self._emit_state()

    @Slot(str, str, int, str)
    def save_connection_defaults(self, mode: str, host: str, port: int, usb_port: str) -> None:
        try:
            if mode == "Wi-Fi TCP":
                self.application.save_wifi_settings(host.strip(), int(port))
                self.wifi_host, self.wifi_port = host.strip(), int(port)
            else:
                self.application.save_usb_settings(usb_port.strip())
                self.port = usb_port.strip()
            self._set_notice("Connection defaults saved")
        except (OSError, RuntimeError, ValueError) as exc:
            self._set_notice(f"Connection defaults rejected — {exc}")
        self._emit_state()

    @Slot(str)
    def save_homing_limit_declarations(self, declarations_json: str) -> bool:
        try:
            declarations = json.loads(declarations_json)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            self._set_notice(f"Homing/limit declarations rejected — {exc}")
            return False
        outcome = self.application.save_homing_limit_declarations(declarations)
        self._set_notice(outcome.message)
        self._emit_state()
        return bool(outcome.accepted)

    @Slot(float, float, float, float)
    def start_travel_calibration(self, increment_mm: float, max_overshoot_mm: float,
                                 search_feed: float, return_feed: float) -> None:
        outcome = self.application.start_travel_calibration(
            increment_mm=increment_mm, max_overshoot_mm=max_overshoot_mm,
            search_feed=search_feed, return_feed=return_feed,
        )
        if outcome.accepted:
            self._guided_completion_pending = None
            self._guided_step = 6
        self._set_notice(outcome.message)
        self._emit_state()

    @Slot()
    def abort_travel_calibration(self) -> None:
        outcome = self.application.abort_travel_calibration()
        self._set_notice(outcome.message)
        self._emit_state()

    @Slot()
    def accept_travel_calibration(self) -> None:
        outcome = self.application.accept_travel_calibration()
        self._set_notice(outcome.message)
        self._emit_state()

    @Slot()
    def commission_simulation_calibration_plate(self) -> None:
        outcome = self.application.commission_simulation_calibration_plate()
        self._set_notice(outcome.message)
        self._emit_state()

    @Slot(QUrl)
    def export_simulation_evidence(self, selected_file: QUrl) -> None:
        """Export JSON and Markdown evidence through the public twin boundary."""
        path_text = selected_file.toLocalFile()
        if not path_text:
            return
        if not self.simulation_export_available:
            message = "Simulation evidence export unavailable — connect the digital twin first"
            self._simulation_export_status = message
            self._set_notice(message)
            self.simulation_changed.emit()
            return
        path = Path(path_text)
        if path.suffix.lower() != ".json":
            path = path.with_suffix(".json")
        try:
            self.application.record_simulation_event("evidence_export_requested", {"path": path.name})
            self.application.export_simulation_trace(path)
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            self._simulation_export_status = f"Evidence export failed — {exc}"
            self._set_notice(self._simulation_export_status)
            self.simulation_changed.emit()
            return
        self._simulation_export_status = f"Evidence exported: {path.name} + {path.with_suffix('.md').name}"
        self._set_notice(self._simulation_export_status)
        self.simulation_changed.emit()

    @Slot()
    def home_machine(self) -> None:
        if not self.can_home_machine:
            self._set_notice("Homing blocked — configure all X/Y/Z switches, wait for fresh Idle, and turn the spindle off")
            self._emit_state()
            return
        outcome = self.application.home_machine()
        if outcome.accepted:
            self._arm_guided_completion(2)
        self._set_notice(outcome.message)
        self._emit_state()

    @Slot()
    def acknowledge_physical_safety_input(self) -> None:
        method = getattr(self.application, "acknowledge_safety_input", None)
        if not callable(method):
            self._set_notice("Physical safety-input acknowledgement is unavailable in this client")
            self._emit_state()
            return
        outcome = method()
        self._set_notice(outcome.message)
        self._emit_state()

    @Slot()
    def release_simulation_estop(self) -> None:
        outcome = self.application.release_simulation_estop()
        if outcome.accepted:
            self._clear_terminal_simulation_hazard()
        self._set_notice(outcome.message)
        self._emit_state()

    @Slot()
    def acknowledge_simulation_estop(self) -> None:
        outcome = self.application.acknowledge_simulation_estop()
        if outcome.accepted:
            self._clear_terminal_simulation_hazard()
        self._set_notice(outcome.message)
        self._emit_state()

    @Slot(bool, bool)
    def inject_simulation_estop(self, reset_asserted: bool, feedback_electrical: bool) -> None:
        """Exercise only the owned twin's symbolic reset/feedback inputs."""
        outcome = self.application.inject_simulation_estop(
            reset_asserted=bool(reset_asserted),
            feedback_electrical=bool(feedback_electrical),
        )
        self._set_notice(outcome.message)
        self._emit_state()

    @Slot(str, bool)
    def inject_simulation_limit(self, axis: str, active: bool) -> None:
        """Set a twin switch's logical state, honoring its declared NC/NO wiring."""
        normalized_axis = str(axis).upper()
        declarations = getattr(self.application, "homing_limit_declarations", {})
        declaration = declarations.get(normalized_axis, {}) if isinstance(declarations, dict) else {}
        active_low = bool(declaration.get("active_low", False)) if isinstance(declaration, dict) else False
        # The application/twin boundary accepts the raw electrical level. The
        # public checkbox represents a logical actuated switch, so translate
        # it here without changing the raw electrical API used by other tests.
        electrical_active = not bool(active) if active_low else bool(active)
        outcome = self.application.set_simulation_limit_input(normalized_axis, electrical_active)
        self._set_notice(outcome.message)
        self._emit_state()

    @Slot(float, float, float)
    def start_auto_xyz_calibration(self, x: float, y: float, z: float) -> None:
        outcome = self.application.start_auto_xyz_calibration((x, y, z))
        if outcome.accepted:
            self._arm_guided_completion(3)
        self._set_notice(outcome.message)
        self._emit_state()

    @Slot()
    def abort_auto_xyz_calibration(self) -> None:
        outcome = self.application.abort_auto_xyz_calibration()
        self._set_notice(outcome.message)
        self._emit_state()

    @Slot()
    def abort_probe(self) -> None:
        outcome = self.application.abort_probe()
        self._set_notice(outcome.message)
        self._emit_state()

    @Slot(bool, bool, bool, bool, bool)
    def save_machine_capabilities(self, limit_switches: bool, z_plate: bool, tool_setter: bool,
                                  movable_xyz: bool, fixed_fixture: bool) -> None:
        outcome = self.application.save_capabilities(limit_switches=limit_switches, z_plate=z_plate,
                                                     tool_setter=tool_setter, movable_xyz=movable_xyz,
                                                     fixed_fixture=fixed_fixture)
        self._set_notice(outcome.message)
        self._emit_state()

    @Slot(bool)
    def save_z_touch_plate_capability(self, enabled: bool) -> None:
        outcome = self.application.save_z_plate_capability(enabled)
        self._set_notice(outcome.message)
        self._emit_state()

    @Slot(bool, bool, bool, bool)
    def save_probe_capabilities(self, z_plate: bool, tool_setter: bool,
                                movable_xyz: bool, fixed_xyz: bool) -> None:
        outcome = self.application.save_probe_capabilities(
            z_plate=z_plate, tool_setter=tool_setter,
            movable_xyz=movable_xyz, fixed_xyz=fixed_xyz,
        )
        self._set_notice(outcome.message)
        self._emit_state()

    @Slot(bool, bool, bool, bool, float, bool, float, float, float, float, float, float)
    def save_probe_configuration(self, z_plate: bool, tool_setter: bool,
                                 movable_xyz: bool, fixed_xyz: bool,
                                 thickness: float, active_low: bool,
                                 fast_feed: float, slow_feed: float,
                                 max_search: float, retract: float,
                                 safe_retract: float, tolerance: float) -> bool:
        outcome = self.application.save_probe_configuration(
            z_plate=z_plate, tool_setter=tool_setter, movable_xyz=movable_xyz,
            fixed_xyz=fixed_xyz, plate_thickness=thickness, active_low=active_low,
            fast_feed=fast_feed, slow_feed=slow_feed, max_search=max_search,
            retract=retract, safe_retract=safe_retract, tolerance=tolerance,
        )
        self._set_notice(outcome.message)
        self._emit_state()
        return bool(outcome.accepted)

    @Slot(float, bool, float, float, float, float, float, float)
    def save_z_touch_plate_settings(self, thickness: float, active_low: bool, fast_feed: float,
                                    slow_feed: float, max_search: float, retract: float,
                                    safe_retract: float, tolerance: float) -> None:
        outcome = self.application.save_z_touch_plate_settings(
            plate_thickness=thickness, active_low=active_low, fast_feed=fast_feed,
            slow_feed=slow_feed, max_search=max_search, retract=retract,
            safe_retract=safe_retract, tolerance=tolerance,
        )
        self._set_notice(outcome.message)
        self._emit_state()

    @Slot()
    def test_z_touch_plate_input(self) -> None:
        outcome = self.application.start_z_touch_plate_input_test()
        self._set_notice(outcome.message)
        self._emit_state()

    @Slot()
    def manually_trigger_z_touch_plate(self) -> None:
        """Start the no-motion test used to verify the physical probe signal."""
        self.test_z_touch_plate_input()

    @Slot()
    def commissioning_z_touch_plate_sample(self) -> None:
        outcome = self.application.start_z_touch_plate_commissioning_sample()
        self._set_notice(outcome.message)
        self._emit_state()

    @Slot()
    def acknowledge_z_touch_plate_removed(self) -> None:
        outcome = self.application.acknowledge_z_touch_plate_removed()
        self._set_notice(outcome.message)
        self._emit_state()

    @Slot(str)
    def continue_z_probe_to_surface(self, transaction_id: str) -> None:
        continue_action = getattr(self.application, "continue_z_probe_to_surface", None)
        if not callable(continue_action):
            self._set_notice("Continue to work Z0 is unavailable from this application client")
            self._emit_state()
            return
        outcome = continue_action(transaction_id)
        self._set_notice(outcome.message)
        self._emit_state()

    @Slot()
    def probe_work_z(self) -> None:
        # The operator explicitly starts this bounded probe from its guarded
        # work-zero control. Keep the removal confirmation at the result step,
        # where it authorizes a distinct Z-only descent after puck removal.
        outcome = self.application.probe_work_z()
        if outcome.accepted:
            self._arm_guided_completion(3)
        self._set_notice(outcome.message)
        self._emit_state()

    @Slot(str)
    def select_machine(self, label: str) -> None:
        for machine in self.application.machine_profiles:
            if label.startswith(machine.name + " ("):
                outcome = self.application.select_machine(machine.machine_id)
                self._set_notice(outcome.message)
                self._emit_state()
                return
        self._set_notice("Machine selection ignored — profile not found")

    @Slot(str)
    def set_work_zero(self, axes: str) -> None:
        outcome = self.application.set_work_zero(axes)
        if not outcome.accepted:
            self._set_notice(outcome.message)
            return
        self._arm_guided_completion(3)
        self._set_notice(outcome.message)
        self._emit_state()

    @Slot()
    def return_to_work_zero(self) -> None:
        outcome = self.application.return_to_work_zero(500.0)
        if not outcome.accepted:
            self._set_notice(f"Return skipped — {outcome.message}")
        else:
            self._set_notice(outcome.message)

    @Slot()
    def retract_safe_z(self) -> None:
        current = self.application.virtual_position
        if current is None:
            self._set_notice("Safe-Z move ignored — no trusted machine position")
            return
        self.move_to(current.x, current.y, self.application.profile.safe_z, 500.0)

    @Slot()
    def return_to_reference(self) -> None:
        outcome = self.application.return_to_reference(500.0)
        if not outcome.accepted:
            self._set_notice(f"Position move blocked — {outcome.message}")

    @Slot(QUrl)
    def load_gcode_file(self, selected_file: QUrl) -> None:
        if self.job_active:
            self._set_notice("G-code load ignored — a job is active")
            return
        path_text = selected_file.toLocalFile()
        if not path_text:
            self._set_notice("G-code load ignored — choose a local file")
            return
        try:
            program = self.application.load_program(Path(path_text))
        except (OSError, GCodeError) as exc:
            self._set_notice(f"G-code rejected — {exc}")
            return
        bounds = program.bounds
        size = bounds.size
        has_raster = self._set_backend_program_preview()
        self._preview_strokes = [] if has_raster else self._strokes_for_program(program)
        self._set_preview_path_layers(program, has_raster)
        self._preview_model_strokes = []
        self._preview_stock_width = 0.0
        self._preview_stock_height = 0.0
        self._preview_summary = f"{len(program.commands)} commands · {size.x:.1f} × {size.y:.1f} mm"
        self._job_file_text = program.path.name
        self._job_summary_text = (
            f"{len(program.commands)} commands; X {bounds.minimum.x:.3f}…{bounds.maximum.x:.3f}, "
            f"Y {bounds.minimum.y:.3f}…{bounds.maximum.y:.3f}, Z {bounds.minimum.z:.3f}…{bounds.maximum.z:.3f} mm "
            f"(size {size.x:.3f} × {size.y:.3f} mm)"
        )
        self._remember_backend_program_projection(program)
        self._guided_preflight_confirmed = False
        self._review_acknowledged = False
        if self._guided_step == 6:
            self._guided_step = 5
        self._set_notice("G-code loaded and validated")
        self._emit_state()

    def _load_generated_program(
        self,
        gcode: str,
        filename: str,
        strokes: tuple[tuple[tuple[float, float], ...], ...],
        summary: str,
        stock_width: float = 0.0,
        stock_height: float = 0.0,
    ) -> None:
        try:
            program = self.application.load_generated(gcode, filename)
        except GCodeError as exc:
            self._set_notice(f"Generated G-code rejected — {exc}")
            return
        self._preview_strokes = self._strokes_for_qml(strokes)
        self._preview_model_strokes = []
        has_raster = self._set_backend_program_preview()
        self._set_preview_path_layers(program, has_raster)
        if has_raster:
            self._preview_strokes = []
        self._preview_stock_width = stock_width
        self._preview_stock_height = stock_height
        self._preview_summary = summary
        self._job_file_text = filename
        self._job_summary_text = summary
        self._remember_backend_program_projection(program)
        self._guided_preflight_confirmed = False
        self._set_notice(f"Generated {filename} and loaded it for review")
        self._emit_state()

    @Slot()
    def start_job(self) -> None:
        if not self.can_start_job or self.program is None:
            self._set_notice("Job blocked — connect, reference, confirm XYZ work zero, and load a fitting job")
            return
        if not self._review_acknowledged:
            self._set_notice("Job blocked — acknowledge the current validated path in Review")
            return
        if not self._guided_preflight_confirmed:
            self._set_notice("Job blocked — complete physical preflight before starting")
            return
        fits, reason = self.application.preflight()
        if not fits:
            self._set_notice(f"Job blocked — {reason}")
            return
        authorization = self.application.authorize_job_start(
            review_acknowledged=self._review_acknowledged,
            physical_preflight_confirmed=self._guided_preflight_confirmed,
        )
        if not authorization.accepted:
            self._set_notice(authorization.message)
            return
        self._request_confirmation(
            "job_start",
            authorization.token,
            "Start engraving job?",
            f"{self.program.path.name}\n\n{reason}\n\nConfirm the material, tool, and physical emergency power are ready.",
        )

    @Slot()
    def pause_job(self) -> None:
        outcome = self.application.pause_job()
        if not outcome.accepted:
            self._set_notice(outcome.message)
        self._emit_state()

    @Slot()
    def resume_job(self) -> None:
        outcome = self.application.resume_job()
        if not outcome.accepted:
            self._set_notice(outcome.message)
        self._emit_state()

    @Slot()
    def abort_job(self) -> None:
        if not self.job_active:
            return
        self._request_confirmation(
            "job_abort",
            None,
            "Abort engraving?",
            "Feed-hold and reset GRBL? The job cannot resume. The current references will be retained while the machine remains connected and powered.",
        )

    @Slot()
    def cancel_jog(self) -> None:
        try:
            self.application.cancel_jog()
        except RuntimeError as exc:
            self._set_notice(f"Jog cancel failed — {exc}")

    @Slot()
    def hold(self) -> None:
        self._set_notice(self.application.hold().message)

    @Slot()
    def resume(self) -> None:
        self._set_notice(self.application.resume().message)

    @Slot()
    def close(self) -> None:
        # aboutToQuit is the last reliable application lifecycle hook. Stop
        # polling before releasing the transport so no timer callback can race
        # the final socket/serial-handle cleanup.
        self.stop_live_jog()
        self._live_jog_renew_timer.stop()
        self._timer.stop()
        self.disable_live_access()
        self._camera_service.stop()
        self._remote_bridge.close()
        self.application.close()
        self.status = None
        self._connection_text = "Disconnected"
        self._state_text = "Unknown"
        self._machine_position_text = "X—  Y—  Z—"
        self._work_position_text = "X—  Y—  Z—"
        self._reference_text = "Position unknown"
        self._work_zero_text = "Not confirmed"
        self._spindle_text = "Off"
        self._emit_state()

    def _refresh_ports(self) -> None:
        if self.application.simulation_active:
            self._ports = []
            self._ports_loaded = True
            self.ports_changed.emit()
            return
        self._ports = [f"{device} — {description}" for device, description in self.application.usb_ports()]
        self._ports_loaded = True
        saved_port = self.application.settings.usb_port
        saved_label = next((label for label in self._ports if label.split(" ", 1)[0] == saved_port), "")
        if saved_label:
            self.port = saved_label
        elif self._ports and not self.port:
            self.port = self._ports[0]
        self.ports_changed.emit()

    def _auto_connect_last(self) -> None:
        """Ask the backend for one bounded saved physical connection plan."""
        if self.connected or self._auto_connect_started:
            return
        self._auto_connect_started = True
        auto_connect = getattr(self.application, "auto_connect_saved", None)
        if callable(auto_connect) and callable(getattr(self.application, "poll_backend", None)):
            self._auto_connection_state = "trying"
            self._auto_failure_reported = False
            outcome = auto_connect()
            if outcome.accepted:
                self._auto_connection_attempts = list(
                    getattr(getattr(self.application, "connection_service", None), "auto_connection_failures", ())
                )
                if self.connected:
                    self._auto_connection_state = "connected"
                else:
                    self._set_notice(outcome.message)
                self._emit_state()
            else:
                self._auto_connection_state = "failed"
                self._auto_connection_attempts = list(
                    getattr(getattr(self.application, "connection_service", None), "auto_connection_failures", ())
                )
                self._connection_text = outcome.message
                self._set_notice(outcome.message)
                self.auto_connection_failed.emit(outcome.message)
                self._emit_state()
            return

        # Compatibility fallback for lightweight test doubles that predate
        # the backend-owned automatic connection operation.
        settings = self.application.settings
        if settings.preferred_transport == "Wi-Fi TCP":
            self._auto_connection_state = "trying"
            self._set_notice(f"Connecting automatically to {settings.wifi_host}:{settings.wifi_port}…")
            self.connect_to_wifi(settings.wifi_host, settings.wifi_port)
            return
        if not self._ports_loaded:
            self._refresh_ports()
        available = {label.split(" ", 1)[0] for label in self._ports}
        if settings.usb_port not in available:
            self._auto_connection_state = "failed"
            message = f"Last USB connection {settings.usb_port} is not available"
            self._set_notice(message)
            self.auto_connection_failed.emit(message)
            return
        self._auto_connection_state = "trying"
        self._set_notice(f"Connecting automatically to {settings.usb_port}…")
        self.connect_to_usb(settings.usb_port)

    def _poll(self) -> None:
        status_projection = (
            bool(self.application.connected),
            str(getattr(self.application, "status_state", "unavailable")),
        )
        if status_projection != self._last_status_projection:
            self._last_status_projection = status_projection
            self._emit_state()
        # A backend-backed shell has no local transport/simulation loop to
        # advance. Rebuild the presentation from the authoritative snapshot
        # and ordered event cursor, and leave the persistent owner untouched.
        backend_poll = getattr(self.application, "poll_backend", None)
        if callable(backend_poll):
            backend_poll()
            backend_auto_state = str(getattr(self.application, "auto_connection_state", "idle"))
            if self._auto_connect_started:
                if self.connected:
                    self._auto_connection_state = "connected"
                elif backend_auto_state == "trying":
                    self._auto_connection_state = "trying"
                elif backend_auto_state == "failed":
                    self._auto_connection_state = "failed"
                    self._auto_connection_attempts = list(getattr(self.application, "auto_connection_failures", ()))
                    if not self._auto_failure_reported:
                        self._auto_failure_reported = True
                        message = "Automatic connection failed"
                        if self._auto_connection_attempts:
                            message += " — " + " · ".join(self._auto_connection_attempts)
                        self._connection_text = message
                        self._set_notice(message)
                        self.auto_connection_failed.emit(message)
            if getattr(self.application, "backend_unavailable", False):
                self._set_notice("Backend unavailable — machine state is read-only until reconnect")
            self._emit_state()
            return
        self._poll_wifi_result()
        self.application.poll_wifi_setup(time.monotonic())
        now = time.monotonic()
        if self._live_server and self._live_server.running and now - self._last_live_snapshot >= 1.0:
            self._last_live_snapshot = now
            self._emit_state()
        if not self.connected:
            return
        runtime = self.application.simulation_runtime
        if self.application.simulation_active and runtime is not None:
            # Keep the QML-facing layer on the public application boundary;
            # it must not reach into the runtime's transport/process details.
            for item in self.application.poll_simulation():
                if item.get("type") == "snapshot":
                    self._simulation_snapshot = dict(item.get("snapshot", {}))
                elif item.get("type") == "stock_metrics":
                    self._simulation_stock_metrics = dict(item.get("metrics", {}))
                elif item.get("type") == "intent":
                    self._apply_simulation_intent(dict(item.get("intent", {})))
                elif item.get("type") == "operator_intent":
                    self._apply_operator_intent(dict(item.get("intent", {})))
                elif item.get("type") == "hazard":
                    hazard = item.get("hazard", {})
                    message = str(hazard.get("message", "Digital twin hazard"))
                    projected = {
                        "kind": str(hazard.get("kind", "protocol")),
                        "message": message,
                        "body_a": str(hazard.get("body_a", "")),
                        "body_b": str(hazard.get("body_b", "")),
                        "position": tuple(hazard.get("position", (0.0, 0.0, 0.0))),
                        "severity": str(hazard.get("severity", "alarm")),
                    }
                    self._simulation_active_hazard = projected
                    if self._is_terminal_simulation_hazard(projected):
                        self._simulation_terminal_hazard = dict(projected)
                    self._simulation_hazards = [*self._simulation_hazards[-49:], message]
                    self._set_notice(f"Digital twin safety supervisor: {message}")
                elif item.get("type") == "hazard_clear":
                    if not self._simulation_terminal_hazard:
                        self._simulation_active_hazard = {}
            self.simulation_changed.emit()
            if not self.simulation_supervisor_healthy:
                self._set_notice("Digital twin safety supervisor is unavailable; simulation is unsafe to continue")
        events = self.application.transport_events()
        try:
            while not events.empty():
                self._handle_event(events.get_nowait())
            now = time.monotonic()
            if self.connected and now - self._last_status_poll >= 0.5:
                self.application.request_status()
                self._last_status_poll = now
            watchdog_failure = self.application.check_job_watchdog()
            if watchdog_failure is not None:
                self._disconnected(
                    "Controller stopped responding during the job. Motion and spindle state are uncertain; "
                    "remove power if needed, then reconnect, home the machine, and reload the job. "
                    f"Details: {watchdog_failure}"
                )
                return
            if self.application.job_active:
                self._emit_state()
        except RuntimeError as exc:
            self._disconnected(str(exc))

    def _apply_simulation_intent(self, intent: dict[str, object]) -> None:
        """Map supervisor scenario intents through public application methods."""
        name = str(intent.get("name", ""))
        args = intent.get("arguments", {})
        args = args if isinstance(args, dict) else {}
        try:
            # Legacy scenario traces may seed a trusted twin envelope through
            # this private replay hook; the operator-facing ViewModel and
            # backend action registry expose only guarded homing.
            if name == "establish_reference":
                outcome = self.application.establish_reference()
            elif name == "jog":
                outcome = self.application.jog(str(args.get("axis", "X")), float(args.get("distance", 0)))
            elif name == "set_work_zero":
                outcome = self.application.set_work_zero(str(args.get("axes", "XYZ")))
            elif name == "start_job":
                authorization = self.application.authorize_job_start(
                    review_acknowledged=self._review_acknowledged,
                    physical_preflight_confirmed=self._guided_preflight_confirmed,
                )
                outcome = (
                    self.application.start_authorized_job(authorization.token)
                    if authorization.accepted else authorization
                )
            elif name == "pause_job":
                outcome = self.application.pause_job()
            elif name == "resume_job":
                outcome = self.application.resume_job()
            elif name == "abort_job":
                self.application.abort_job("Supervisor scenario abort")
                return
            elif name == "disconnect":
                self.disconnect()
                return
            else:
                self._set_notice(f"Unknown digital-twin scenario intent: {name}")
                return
            if not outcome.accepted:
                self._set_notice(f"Scenario intent {name} blocked — {outcome.message}")
        except (RuntimeError, ValueError, TypeError) as exc:
            self._set_notice(f"Scenario intent {name} failed — {exc}")

    def _poll_wifi_result(self) -> None:
        outcome = self.application.poll_wifi()
        if outcome is None:
            return
        if not outcome.accepted:
            self._connection_text = outcome.message
            self._set_notice(self._connection_text)
            self._emit_state()
            return
        self.wifi_host = outcome.host
        self.wifi_port = outcome.port or self.wifi_port
        try:
            self.application.save_wifi_settings(self.wifi_host, self.wifi_port)
        except (OSError, ValueError):
            pass
        self._connection_text = outcome.message
        self._arm_guided_completion(1)
        self._set_notice(self._connection_text)
        self._emit_state()

    def _handle_event(self, event) -> None:
        self._append_log(event)
        if event.kind == "error":
            self._disconnected(f"Connection error: {event.text}")
            return
        if event.kind != "rx":
            return
        text = event.text.strip()
        status, reset = self.application.handle_transport_response(
            text,
            500.0,
        )
        if status is not None:
            if (self.application.simulation_active and status.state == "Alarm"
                    and not self._simulation_active_hazard):
                # Preserve a typed terminal projection even when a GRBL alarm
                # arrives without a preceding supervisor hazard item.
                projected = {
                    "kind": "grbl_alarm",
                    "message": text or "GRBL alarm",
                    "body_a": "controller",
                    "body_b": "",
                    "position": tuple(status.machine_position or (0.0, 0.0, 0.0)),
                    "severity": "alarm",
                }
                self._simulation_active_hazard = projected
                self._simulation_terminal_hazard = dict(projected)
                self._simulation_hazards = [*self._simulation_hazards[-49:], projected["message"]]
            self._project_status(status)
        if reset:
            if self.status is not None:
                self._project_status(self.status)
            else:
                self._emit_state()

    def _project_status(self, status: GrblStatus) -> None:
        self._update_status_projection(status)
        homing = getattr(self.application, "homing", None)
        homing_state = getattr(getattr(homing, "state", "idle"), "value", getattr(homing, "state", "idle"))
        if str(homing_state).lower() == "complete":
            self._unreferenced_jog_allowed = False
            self._clear_terminal_simulation_hazard()
        self._emit_state()

    def _update_status_projection(self, status: GrblStatus) -> None:
        self._state_text = status.state
        self._connection_text = (
            f"DIGITAL TWIN — NO PHYSICAL MACHINE · GRBL {status.state}"
            if self.application.simulation_active else f"Connected — GRBL {status.state}"
        )
        self._feed_text = f"{status.feed:g}" if status.feed is not None else "—"
        self._spindle_text = f"{status.spindle:g} RPM" if status.spindle is not None else "—"
        self._pins_text = status.pins or "None"
        self._machine_position_text = self._format_position(status.machine_position)
        work = status.work_position
        if work is None and status.machine_position and self.application.work_offset:
            work = status.machine_position.minus(self.application.work_offset)
        self._work_position_text = self._format_position(work)
        self._reference_text = "Trusted" if self.application.reference_trusted else "Position unknown"
        self._work_zero_text = "Confirmed" if self.application.work_zero_confirmed else "Not confirmed"
        session_id = str(getattr(self.application, "backend_session_id", ""))
        if not session_id:
            session_id = str(getattr(self.application, "session_generation", ""))
        changed = bool(session_id and self._backend_session_seen and session_id != self._backend_session_seen)
        if session_id:
            self._backend_session_seen = session_id
        if changed:
            self._envelope_marker = EnvelopeMarker(
                "unknown", "Backend session changed; waiting for fresh MPos", session_id=session_id
            )
        else:
            self._envelope_marker = project_machine_position(
                # The travel envelope and move_to planner both use virtual
                # coordinates relative to the trusted home reference. Feeding
                # raw GRBL MPos here made canvas clicks select the wrong frame.
                self.application.virtual_position if self.application.reference_trusted else status.machine_position,
                self.application.profile.travel_x,
                self.application.profile.travel_y,
                self.application.profile.travel_z,
                connected=bool(self.application.connected),
                status_fresh=bool(getattr(self.application, "status_fresh", False)),
                session_id=session_id,
            )

    @staticmethod
    def _strokes_for_qml(strokes: tuple[tuple[tuple[float, float], ...], ...] | list[tuple[tuple[float, float], ...]]) -> list[list[list[float]]]:
        return [[[float(x), float(y)] for x, y in stroke] for stroke in strokes]

    @classmethod
    def _strokes_for_program(cls, program: GCodeProgram, *, rapid: bool | None = None) -> list[list[list[float]]]:
        return cls._strokes_for_qml(
            tuple(
                ((segment.start.x, segment.start.y), (segment.end.x, segment.end.y))
                for segment in program.segments
                if rapid is None or bool(segment.rapid) is rapid
            )
        )

    def _set_preview_path_layers(self, program: GCodeProgram, has_raster: bool) -> None:
        if has_raster:
            self._preview_cutting_strokes = []
            self._preview_rapid_strokes = []
            return
        self._preview_cutting_strokes = self._strokes_for_program(program, rapid=False)
        self._preview_rapid_strokes = self._strokes_for_program(program, rapid=True)
        self._preview_path_layers_available = True

    @classmethod
    def _strokes_for_step_model(cls, model: StepPlanarModel) -> list[list[list[float]]]:
        return cls._strokes_for_qml(
            tuple(
                tuple((point.x, point.y) for point in loop.points + (loop.points[0],))
                for loop in model.loops
            )
        )

    @staticmethod
    def _recommended_step_mode(model: StepPlanarModel) -> str:
        return "Automatic part"

    def _set_step_isometric_model(
        self,
        model: StepPlanarModel,
        orientation: str | None = None,
        offset: tuple[float, float] = (0.0, 0.0),
    ) -> None:
        orientation = orientation or self.application.step_prepare_settings.orientation
        offset_x, offset_y = offset

        def xyz(point, z: float) -> list[float]:
            x, y = (point.y, point.x) if orientation == "Top (YX)" else (point.x, point.y)
            return [float(x + offset_x), float(y + offset_y), float(z)]

        faces: list[dict[str, object]] = []
        seen_surfaces: set[tuple[object, ...]] = set()
        for patch in model.surface_patches:
            key = (
                round(patch.a, 7), round(patch.b, 7), round(patch.c, 7),
                tuple(tuple((round(point.x, 6), round(point.y, 6)) for point in loop.points) for loop in patch.loops),
            )
            if key in seen_surfaces:
                continue
            seen_surfaces.add(key)
            loops = [
                [
                    xyz(
                        point,
                        max(-model.thickness, min(0.0, patch.height_at(point.x, point.y))),
                    )
                    for point in loop.points
                ]
                for loop in patch.loops
                if len(loop.points) >= 3
            ]
            if loops:
                faces.append({"loops": loops, "kind": "ramp" if patch.tilted else "surface"})

        if not faces:
            faces.extend(
                {"loops": [[xyz(point, 0.0) for point in loop.points]], "kind": "surface"}
                for loop in model.loops
            )

        for loop_index in model.outer_loop_indices:
            loop = model.loops[loop_index]
            for point, following in zip(loop.points, loop.points[1:] + loop.points[:1]):
                faces.append(
                    {
                        "loops": [[
                            xyz(point, 0.0),
                            xyz(following, 0.0),
                            xyz(following, -model.thickness),
                            xyz(point, -model.thickness),
                        ]],
                        "kind": "side",
                    }
                )
            faces.append(
                {
                    "loops": [[xyz(point, -model.thickness) for point in reversed(loop.points)]],
                    "kind": "bottom",
                }
            )

        for feature in model.features:
            loop = model.loops[feature.loop_index]
            lower = -min(model.thickness, feature.depth)
            for point, following in zip(loop.points, loop.points[1:] + loop.points[:1]):
                faces.append(
                    {
                        "loops": [[
                            xyz(point, 0.0),
                            xyz(following, 0.0),
                            xyz(following, lower),
                            xyz(point, lower),
                        ]],
                        "kind": "feature",
                    }
                )
        self._step_isometric_faces = faces
        self._step_isometric_paths = []
        self._step_isometric_stock_thickness = float(model.thickness)

    def _set_step_isometric_job(self, job, orientation: str) -> None:
        model = self._step_model
        if model is None:
            self._step_isometric_faces = []
            self._step_isometric_paths = []
            return
        raw_points = [
            (point.y, point.x) if orientation == "Top (YX)" else (point.x, point.y)
            for loop in model.loops
            for point in loop.points
        ]
        placed_points = [point for stroke in job.model_strokes for point in stroke]
        offset = (0.0, 0.0)
        if raw_points and placed_points:
            offset = (
                min(point[0] for point in placed_points) - min(point[0] for point in raw_points),
                min(point[1] for point in placed_points) - min(point[1] for point in raw_points),
            )
        self._set_step_isometric_model(model, orientation, offset)
        paths: list[dict[str, object]] = []
        for path in job.surface_paths:
            paths.append(
                {
                    "points": [[float(x), float(y), float(z) + 0.08] for x, y, z in path],
                    "kind": "surface",
                }
            )
        surface_count = len(job.surface_paths)
        remaining = job.strokes[surface_count:]
        for index, stroke in enumerate(remaining):
            paths.append(
                {
                    "points": [[float(x), float(y), 0.12] for x, y in stroke],
                    "kind": "profile" if index == len(remaining) - 1 and job.mode in {"Automatic part", "Profile cutout"} else "cut",
                }
            )
        self._step_isometric_paths = paths
        self._step_isometric_stock_thickness = float(job.stock_thickness or model.thickness)

    @staticmethod
    def _operations_for_qml(job) -> list[dict[str, object]]:
        return [
            {
                "operationId": operation.operation_id,
                "kind": operation.kind,
                "targetDepth": operation.target_depth,
                "dependsOn": ", ".join(operation.depends_on),
                "strategy": operation.strategy,
                "featureKinds": ", ".join(operation.feature_kinds),
            }
            for operation in job.operations
        ]

    @staticmethod
    def _step_job_summary(job) -> str:
        points = [point for stroke in job.strokes for point in stroke]
        min_x = min(point[0] for point in points)
        min_y = min(point[1] for point in points)
        max_x = max(point[0] for point in points)
        max_y = max(point[1] for point in points)
        simulation_summary = ""
        if job.simulation is not None:
            simulation_summary = (
                f" · simulation passed ({job.simulation.uncovered_area:.2f} mm² uncovered)"
            )
        elif job.surface_simulation is not None:
            simulation_summary = (
                f" · surface simulation passed (max Z error "
                f"{job.surface_simulation.maximum_surface_error:.3f} mm)"
            )
        return (
            f"STEP {job.mode}{f' ({job.feature_summary})' if job.feature_summary else ''} · "
            f"stock {job.stock_width:.1f} × {job.stock_height:.1f} mm · "
            f"tool {job.tool_diameter:.2f} mm · depth {job.depth:.2f} mm · {job.passes} passes · "
            + (f"{job.tab_count} outer tabs · " if job.mode == "Profile cutout" else "")
            + f"{len(job.operations)} operation(s) · {job.stroke_count} paths · {job.cutting_distance:.0f} mm cut · {job.rapid_xy_distance:.0f} mm rapid · "
            + f"{job.retract_count} retracts · ~{job.estimated_minutes:.1f} min · bounds X {min_x:.1f}…{max_x:.1f}, Y {min_y:.1f}…{max_y:.1f} mm"
            + simulation_summary
        )

    def _disconnected(self, reason: str) -> None:
        self.application.disconnect(reason)
        self.status = None
        self._unreferenced_jog_allowed = False
        self._connection_text = "Disconnected"
        self._state_text = "Unknown"
        self._machine_position_text = "X—  Y—  Z—"
        self._work_position_text = "X—  Y—  Z—"
        self._envelope_marker = EnvelopeMarker("unknown", "Controller disconnected")
        self._reference_text = "Position unknown"
        self._work_zero_text = "Not confirmed"
        self._spindle_text = "Off"
        self._simulation_snapshot = {}
        self._simulation_hazards = []
        self._simulation_stock_metrics = {}
        self._simulation_active_hazard = {}
        self._simulation_terminal_hazard = {}
        self._simulation_export_status = "No simulation evidence exported"
        self.simulation_changed.emit()
        self._guided_preflight_confirmed = False
        self._review_acknowledged = False
        self._guided_completion_pending = None
        step = self._workflow().earliest_incomplete
        self._guided_step = 5 if step == 4 else step
        self._last_review_fingerprint = None
        self._issue = IssueSnapshot(
            severity="error",
            title="Controller disconnected",
            explanation=reason or "The controller connection was closed.",
            spindle_uncertain=False,
            reference_lost=True,
            work_zero_lost=True,
            actions=("Connect", "Open console"),
        )
        self._emit_state()

    def _apply_operator_intent(self, intent: dict[str, object]) -> None:
        """Route independent safety actions through public controller methods."""
        action = str(intent.get("action", ""))
        reason = str(intent.get("reason", "Digital twin safety supervisor"))
        try:
            if action == "hold":
                outcome = self.application.hold()
                if not outcome.accepted:
                    self._set_notice(f"Digital twin operator hold rejected — {outcome.message}")
            elif action == "abort":
                self.application.abort_job(f"Digital twin operator: {reason}")
            elif action == "interlock":
                if not self._simulation_active_hazard:
                    projected = {
                        "kind": "operator_interlock",
                        "message": reason,
                        "body_a": "operator",
                        "body_b": "controller",
                        "position": tuple(self._simulation_snapshot.get("machine_position", (0.0, 0.0, 0.0))),
                        "severity": "interlock",
                    }
                    self._simulation_active_hazard = projected
                    self._simulation_terminal_hazard = dict(projected)
                self._set_notice(f"Digital twin operator interlock — {reason}")
            elif action == "recovery_denied":
                self._set_notice(f"Digital twin recovery denied — {reason}")
            elif action == "recover":
                self._clear_terminal_simulation_hazard()
                self._set_notice(f"Digital twin recovery authorized — {reason}")
        except RuntimeError as exc:
            self._set_notice(f"Digital twin operator action failed — {exc}")
        self._emit_state()

    def _audit_live(self, message: str) -> None:
        self._logger.info(message)
        self._set_notice(message)

    def _refresh_live_state(self) -> None:
        remote_state = "available" if self.live_access_enabled else "off"
        self._live_snapshot = self.application.live_status_snapshot(
            camera_state=self._camera_service.state,
            remote_state=remote_state,
        )
        self.live_changed.emit()

    @Slot(str)
    def _on_camera_frame(self, data: str) -> None:
        self._camera_frame_data = data
        self.live_changed.emit()

    def _live_snapshot_for_web(self):
        return self._live_snapshot

    @Property("QStringList", notify=live_changed)
    def live_cameras(self) -> list[str]:
        return self._camera_service.device_names

    @Property(QObject, constant=True)
    def camera_sink(self) -> QObject:
        return self._camera_service.sink

    @Property(str, notify=live_changed)
    def live_camera_frame(self) -> str:
        return self._camera_frame_data

    @Property(str, notify=live_changed)
    def live_camera_state(self) -> str:
        return self._camera_service.state

    @Property(str, notify=live_changed)
    def live_camera_name(self) -> str:
        selected_id = self._live_settings.preferred_camera_id
        device = next(
            (item for item in self._camera_service.devices if bytes(item.id()).hex() == selected_id),
            None,
        )
        return device.description() if device is not None else ""

    @Property(bool, notify=live_changed)
    def tailscale_installed(self) -> bool:
        return self._tailscale.installed

    @Property(str, constant=True)
    def tailscale_download_url(self) -> str:
        return "https://tailscale.com/download/windows"

    @Property(bool, notify=live_changed)
    def live_access_enabled(self) -> bool:
        return bool(self._live_server and self._live_server.running and self._tailscale_status.ready)

    @Property(str, notify=live_changed)
    def live_access_state(self) -> str:
        if self._tailscale_task_token:
            return "Connecting…"
        if self.live_access_enabled:
            return "Tailscale ready"
        return self._tailscale_status.state if self._tailscale_status.state != "Unavailable" else "Off"

    @Property(str, notify=live_changed)
    def live_url(self) -> str:
        return self._live_server.url if self.live_access_enabled else ""

    @Property(str, notify=live_changed)
    def live_pairing_code(self) -> str:
        return self._live_server.pairing.pairing_code if self.live_access_enabled and self._live_server else ""

    @Property(str, notify=live_changed)
    def live_qr_data(self) -> str:
        if not self.live_url or not self.live_pairing_code:
            return ""
        try:
            import base64
            from io import BytesIO
            import qrcode
            image = qrcode.make(self.live_url + "#" + self.live_pairing_code)
            output = BytesIO()
            image.save(output, format="PNG")
            return "data:image/png;base64," + base64.b64encode(output.getvalue()).decode("ascii")
        except (ImportError, OSError):
            return ""

    @Property(int, notify=live_changed)
    def live_viewer_count(self) -> int:
        return self._live_server.viewer_count if self.live_access_enabled and self._live_server else 0

    @Property(int, notify=live_changed)
    def live_session_count(self) -> int:
        return self._live_server.pairing.session_count if self.live_access_enabled and self._live_server else 0

    @Slot()
    def open_live_viewer(self) -> None:
        self._camera_service.start()
        self._refresh_live_state()

    @Slot()
    def stop_live_viewer(self) -> None:
        if not self.live_access_enabled:
            self._camera_service.stop()
        self._refresh_live_state()

    @Slot(str)
    def select_live_camera(self, camera_name: str) -> None:
        device = next((item for item in self._camera_service.devices if item.description() == camera_name), None)
        if device is not None:
            self._camera_service.select(bytes(device.id()).hex())
            self._live_settings.preferred_camera_id = bytes(device.id()).hex()
            self._save_live_settings()
            self._refresh_live_state()

    @Slot()
    def enable_live_access(self) -> None:
        if self.live_access_enabled or self._tailscale_task_token:
            return
        try:
            self._live_server = LiveWebServer(
                self._live_snapshot_for_web,
                self._remote_bridge.submit,
                frame_hub=self._live_frames,
                host="127.0.0.1",
                port=self._live_settings.port,
            )
            self._live_server.start()
            self._tailscale_status = TailscaleStatus("Connecting…", message="Checking Tailscale and enabling secure remote access…")
            local_port = self._live_server.address[1]
            self._tailscale_task_token = self._task_runner.submit(
                lambda: self._tailscale.enable(local_port=local_port, https_port=8443)
            )
            self._set_notice("Checking Tailscale and enabling secure remote access…")
        except (OSError, ValueError) as exc:
            self._live_server = None
            self._set_notice(f"Pine Live could not start — {exc}")
        self._refresh_live_state()

    @Slot()
    def disable_live_access(self) -> None:
        try:
            if self._tailscale_status.target:
                self._tailscale.disable(https_port=8443)
        except Exception as exc:
            self._logger.warning("Tailscale Serve cleanup failed: %s", exc)
            self._set_notice(f"Tailscale cleanup needs attention — {exc}")
        if self._live_server:
            self._live_server.stop()
            self._live_server = None
        self._live_settings.enabled = False
        self._tailscale_status = TailscaleStatus()
        self._save_live_settings()
        self._refresh_live_state()

    @Slot()
    def regenerate_live_pairing(self) -> None:
        if self._live_server:
            self._live_server.pairing.regenerate()
            self._set_notice("Pine Live pairing code regenerated; previous devices were signed out")
            self._refresh_live_state()

    def _save_live_settings(self) -> None:
        try:
            self._live_settings_store.save(self._live_settings)
        except (OSError, ValueError):
            self._set_notice("Pine Live settings could not be saved")

    def _guided_ready(self) -> tuple[bool, str]:
        step = self._workflow().steps[self._guided_step]
        return step.continuable, step.reason

    def _set_notice(self, message: str) -> None:
        logging.getLogger("pine.ui").info(message)
        self.toast_requested.emit(message)

    def _finish_operation(
        self,
        *,
        success: bool,
        summary: str = "",
        error: str = "",
        recovery_action: str = "",
    ) -> None:
        if self._active_operation is None:
            return
        self._operations.finish(
            self._active_operation.token,
            success=success,
            summary=summary,
            error=error,
            recovery_action=recovery_action,
        )
        self._active_operation = None

    def _derive_readiness(self) -> ReadinessSnapshot:
        if not self.connected:
            return ReadinessSnapshot(next_action="Connect", reason="Connect to USB or Wi-Fi TCP first.")
        if self.application.motion_busy or self.application.job_active:
            return ReadinessSnapshot(
                connection="complete",
                reference="complete" if self.application.reference_trusted else "required",
                work_zero="complete" if self.application.work_zero_confirmed else "required",
                job="complete" if self.program else "required",
                ready="working",
                next_action="Monitor operation",
                reason="A machine operation is in progress; keep the safety controls available.",
            )
        if self.status is None or not self.status.can_jog:
            return ReadinessSnapshot(connection="complete", next_action="Wait for Idle", reason="Wait for a fresh GRBL Idle report.")
        if not self.application.reference_trusted:
            return ReadinessSnapshot(connection="complete", reference="required", next_action="Home machine", reason="Home the machine to establish its trusted reference.")
        if not self.application.work_zero_confirmed:
            return ReadinessSnapshot(connection="complete", reference="complete", work_zero="required", next_action="Set work zero", reason="Jog to the material origin and set XYZ work zero.")
        if self.program is None:
            return ReadinessSnapshot(connection="complete", reference="complete", work_zero="complete", next_action="Create or load job", reason="Create text/plaque/STEP output or load validated G-code.")
        fits, reason = self.application.preflight()
        if not fits:
            return ReadinessSnapshot(connection="complete", reference="complete", work_zero="complete", job="warning", next_action="Review job", reason=reason)
        return ReadinessSnapshot(connection="complete", reference="complete", work_zero="complete", job="complete", ready="complete", next_action="Run job", reason="All guarded prerequisites are satisfied.")

    def _derive_issue(self) -> IssueSnapshot | None:
        if not self.connected:
            return self._issue if self._issue and self._issue.title == "Controller disconnected" else None
        if self.application.job_state == "failed":
            return IssueSnapshot(
                title="Job stopped",
                explanation=self.application.job.streamer.error or "The controller rejected the job.",
                spindle_uncertain=True,
                reference_lost=True,
                work_zero_lost=True,
                reload_required=True,
                actions=("Spindle off", "Reconnect", "Reload job", "Open console"),
            )
        if self.status is not None and self.status.state in {"Alarm", "Door", "Sleep"}:
            return IssueSnapshot(
                title=f"Controller {self.status.state}",
                explanation="Motion trust may be lost. Stop safely, inspect the machine, and home before moving again.",
                reference_lost=True,
                work_zero_lost=True,
                actions=("Spindle off", "Home machine", "Open console"),
            )
        return None

    def _sync_controller_operation(self) -> None:
        """Reflect authoritative service activity without owning its lifecycle."""
        if self.application.job_active:
            if self._active_operation is None:
                self._active_operation = self._operations.begin(
                    OperationCategory.JOB,
                    "Engraving job",
                    phase="Running…",
                    cancellable=True,
                    blocking_scopes={"machine_motion", "job"},
                )
            return
        if self.application.motion_busy:
            phase = self.application.motion.phase.replace("_", " ").capitalize()
            if self._active_operation is None:
                self._active_operation = self._operations.begin(
                    OperationCategory.MACHINE_MOTION,
                    "Machine motion",
                    phase=phase,
                    cancellable=True,
                    blocking_scopes={"machine_motion"},
                )
            elif self._active_operation.category is OperationCategory.MACHINE_MOTION:
                updated = self._operations.update(self._active_operation.token, phase=phase)
                if updated is not None:
                    self._active_operation = updated
            return
        if self._active_operation is not None and self._active_operation.category in {OperationCategory.MACHINE_MOTION, OperationCategory.JOB}:
            self._finish_operation(success=True, summary="Controller confirmed complete")

    def _request_confirmation(self, operation: str, payload: object, title: str, message: str) -> None:
        self._confirmation_sequence += 1
        self._confirmation_token = f"{operation}:{self._confirmation_sequence}"
        self._pending_confirmation = (operation, payload)
        self.confirmation_requested.emit(self._confirmation_token, title, message)
        self._emit_state()

    def _append_log(self, event) -> None:
        line = f"{event.timestamp:%H:%M:%S}  {event.kind.upper():<11} {event.text}"
        self._log_lines = (*self._log_lines[-399:], line)
        self._logger.info("%s %-11s %s", event.timestamp.isoformat(timespec="milliseconds"), event.kind.upper(), event.text)
        self._emit_state()

    def _emit_state(self) -> None:
        """Project state once, with narrow signals for high-frequency consumers."""
        self._sync_controller_status_projection()
        self._sync_controller_operation()
        self._sync_backend_program_projection()
        # Warm the shared workflow projection before deriving acknowledgement
        # state.  This keeps the controller callback and the QML-facing
        # properties on one cache boundary, so loading a job performs one
        # preflight for the state publication rather than one per consumer.
        self._workflow()
        # Review acknowledgement is a session-local claim about one exact
        # machine/job/safety snapshot.  Any material change invalidates it;
        # the acknowledgement itself does not alter this fingerprint.
        try:
            definition_fingerprint = self.application.machine_definition.fingerprint()
        except (AttributeError, TypeError, ValueError):
            definition_fingerprint = repr(self.application.machine_definition)
        review_preflight_ok = bool(self._workflow_preflight[0]) if self.application.program is not None else False
        review_fingerprint = (
            definition_fingerprint,
            self.application.program.path.as_posix() if self.application.program is not None else "",
            tuple(self.application.program.commands) if self.application.program is not None else (),
            self._preview_summary,
            bool(self.application.reference_trusted),
            bool(self.application.work_zero_confirmed),
            repr(self.application.work_offset),
            self._state_text,
            bool(self.application.connected),
            bool(self.simulation_hazard_active),
            bool(self.simulation_estop_active),
            bool(self.application.job_active),
            review_preflight_ok,
            bool(self.application.simulation_plate_commissioned),
            str(self.application.auto_xyz_calibration_state),
            bool(self.application.calibration.work_offset_confirmed),
            bool(self.application.simulation_active),
            tuple((key, repr(self._physical_safety_status().get(key))) for key in (
                "state", "raw_state", "transition_id", "power_removal",
                "blocks_motion", "latched", "commissioned", "reason")),
        )
        if self._last_review_fingerprint is None:
            self._last_review_fingerprint = review_fingerprint
        elif review_fingerprint != self._last_review_fingerprint:
            self._last_review_fingerprint = review_fingerprint
            if self._review_acknowledged:
                self._review_acknowledged = False
                self._set_notice("Review acknowledgement cleared — the machine or job state changed")
        self._live_snapshot = self.application.live_status_snapshot(
            camera_state=self._camera_service.state,
            remote_state="available" if self.live_access_enabled else "off",
        )
        readiness = self._derive_readiness()
        issue = self._derive_issue()
        operation = self._active_operation
        if readiness != self._last_readiness_snapshot:
            self._last_readiness_snapshot = readiness
            self._readiness_snapshot = readiness
            self.readiness_changed.emit()
        if issue != self._last_issue:
            self._last_issue = issue
            self._issue = issue
            self.issues_changed.emit()
        if operation != self._last_operation_snapshot:
            self._last_operation_snapshot = operation
            self.operation_changed.emit()
        position_projection = (
            self._machine_position_text,
            self._work_position_text,
            self._envelope_marker.state,
            self._envelope_marker.direction,
            self._envelope_marker.session_id,
        )
        now = time.monotonic()
        safety_changed = self._state_text in {"Alarm", "Door", "Sleep"} or self._spindle_text not in {"Off", "0 RPM"}
        if position_projection != self._last_position_projection and (safety_changed or now - self._position_emit_at >= 1 / 30):
            self._last_position_projection = position_projection
            self._position_emit_at = now
            self.position_changed.emit()
        preview_fingerprint = (
            self._preview_summary,
            self._job_file_text,
            self._preview_image_url,
            self._preview_cutting_image_url,
            self._preview_rapid_image_url,
            self._preview_image_note,
            self._preview_path_layers_available,
            len(self._preview_strokes),
            len(self._preview_cutting_strokes),
            len(self._preview_rapid_strokes),
            len(self._preview_model_strokes),
            self._step_preview_valid,
        )
        if preview_fingerprint != self._last_preview_fingerprint:
            self._last_preview_fingerprint = preview_fingerprint
            self.preview_changed.emit()
        job_projection = (self.application.job_state, self.application.job_progress, self.application.job_active)
        previous_job_state = self._last_job_projection[0] if self._last_job_projection else ""
        if self.application.job_state == "complete" and not self.application.job_active and self._next_part_armed:
            self._next_part_available = True
        elif self.application.job_state in {"failed", "idle"} or not self.connected:
            self._next_part_available = False
        if job_projection != self._last_job_projection:
            self._last_job_projection = job_projection
            self.job_changed.emit()
        connection_projection = (self.connected, self._connection_text)
        if connection_projection != self._last_connection_projection:
            self._last_connection_projection = connection_projection
            self.connection_changed.emit()
        self._advance_guided_on_completion()
        self.state_changed.emit()

    def _sync_backend_program_projection(self) -> None:
        """Refresh job labels and preview when the persistent backend changes its job."""
        if not callable(getattr(self.application, "poll_backend", None)):
            return

        program = self.application.program
        projection = self._backend_program_projection_key(program)
        if projection == self._backend_program_projection:
            return
        self._backend_program_projection = projection
        self._review_acknowledged = False
        self._guided_preflight_confirmed = False

        if program is None:
            self._job_provenance = {
                "report_state": "unavailable", "file_sha256": "", "report_name": "",
                "release_status": "", "bundle": "", "details": [], "header_notes": [],
                "verification_text": "",
                "notice": "No job is loaded.",
            }
            self._job_file_text = "No G-code loaded"
            self._job_summary_text = "Load a metric, pre-sliced engraving file."
            self._preview_strokes = []
            self._preview_cutting_strokes = []
            self._preview_rapid_strokes = []
            self._preview_model_strokes = []
            self._preview_image_url = ""
            self._preview_cutting_image_url = ""
            self._preview_rapid_image_url = ""
            self._preview_path_layers_available = False
            self._preview_image_note = ""
            self._preview_stock_width = 0.0
            self._preview_stock_height = 0.0
            self._preview_summary = ""
            return

        bounds = program.bounds
        size = bounds.size
        command_count = len(program.commands)
        provenance = getattr(self.application, "program_provenance", {})
        self._job_provenance = {
            "report_state": "unavailable", "file_sha256": "", "report_name": "",
            "release_status": "", "bundle": "", "details": [], "header_notes": [],
            "verification_text": "", "notice": "Review report details are unavailable.",
        }
        if isinstance(provenance, dict):
            self._job_provenance.update(provenance)
        else:
            self._job_provenance.update({
                "report_state": "unavailable", "file_sha256": str(getattr(program, "source_sha256", "")),
                "details": [], "notice": "Review report details are unavailable.",
            })
        self._job_file_text = program.path.name or str(program.path)
        self._job_summary_text = (
            f"{command_count} commands; X {bounds.minimum.x:.3f}…{bounds.maximum.x:.3f}, "
            f"Y {bounds.minimum.y:.3f}…{bounds.maximum.y:.3f}, Z {bounds.minimum.z:.3f}…{bounds.maximum.z:.3f} mm "
            f"(size {size.x:.3f} × {size.y:.3f} mm)"
        )
        has_raster = self._set_backend_program_preview()
        self._preview_strokes = [] if has_raster else self._strokes_for_program(program)
        self._set_preview_path_layers(program, has_raster)
        self._preview_model_strokes = []
        self._preview_stock_width = 0.0
        self._preview_stock_height = 0.0
        self._preview_summary = f"{command_count} commands · {size.x:.1f} × {size.y:.1f} mm"

    def _set_backend_program_preview(self) -> bool:
        """Project the backend's complete, pixel-bounded preview when present."""
        preview = getattr(self.application, "program_preview", {})
        if not isinstance(preview, dict):
            preview = {}
        data_url = str(preview.get("data_url", ""))
        if not data_url.startswith("data:image/png;base64,"):
            self._preview_image_url = ""
            self._preview_cutting_image_url = ""
            self._preview_rapid_image_url = ""
            self._preview_path_layers_available = False
            self._preview_image_note = ""
            return False
        self._preview_image_url = data_url
        cutting_data_url = str(preview.get("cutting_data_url", ""))
        rapid_data_url = str(preview.get("rapid_data_url", ""))
        self._preview_cutting_image_url = (
            cutting_data_url if cutting_data_url.startswith("data:image/png;base64,") else ""
        )
        self._preview_rapid_image_url = (
            rapid_data_url if rapid_data_url.startswith("data:image/png;base64,") else ""
        )
        self._preview_path_layers_available = bool(
            preview.get("path_layers_available")
            and self._preview_cutting_image_url
            and self._preview_rapid_image_url
        )
        self._preview_image_note = str(preview.get(
            "note", "Every move is projected into the XY raster preview."
        ))
        return True

    @staticmethod
    def _backend_program_projection_key(program) -> tuple[object, ...] | None:
        if program is None:
            return None
        return (
            str(program.path), len(program.commands), repr(program.bounds),
            float(program.estimated_seconds), str(getattr(program, "source_sha256", "")),
        )

    def _remember_backend_program_projection(self, program) -> None:
        if callable(getattr(self.application, "poll_backend", None)):
            self._backend_program_projection = self._backend_program_projection_key(program)
        provenance = getattr(self.application, "program_provenance", {})
        self._job_provenance = {
            "report_state": "unavailable", "file_sha256": "", "report_name": "",
            "release_status": "", "bundle": "", "details": [], "header_notes": [],
            "verification_text": "", "notice": "Review report details are unavailable.",
        }
        if isinstance(provenance, dict):
            self._job_provenance.update(provenance)
        else:
            self._job_provenance.update({
                "report_state": "unavailable", "file_sha256": str(getattr(program, "source_sha256", "")),
                "details": [], "notice": "Review report details are unavailable.",
            })

    def _sync_controller_status_projection(self) -> None:
        """Never present an old controller report as current machine state."""
        if not self.application.connected:
            return

        state = str(getattr(self.application, "status_state", "unavailable"))
        status = self.application.status
        if state == "fresh" and status is not None:
            self._update_status_projection(status)
            return

        setup_only = bool(getattr(self.application, "connection_setup_only", False))
        service = getattr(self.application, "connection_service", None)
        if service is not None:
            mode = getattr(getattr(service, "mode", None), "value", "")
            setup_only = setup_only or bool(
                getattr(service, "usb_setup_only", False) and mode == "USB serial"
            )
        prefix = "USB setup connection — " if setup_only else "Connected — "
        if state == "stale" and status is not None:
            self._state_text = "Stale"
            self._connection_text = prefix + "GRBL status is stale; waiting for a fresh report"
            marker_reason = "GRBL status is stale; waiting for a fresh MPos"
        else:
            self._state_text = "Waiting"
            self._connection_text = prefix + "waiting for the first GRBL status report"
            marker_reason = "Waiting for the first fresh MPos report"

        # Coordinates, spindle and input state from an old report are not
        # authoritative once its freshness window expires or the new session
        # has not reported yet.
        self._machine_position_text = "X—  Y—  Z—"
        self._work_position_text = "X—  Y—  Z—"
        self._spindle_text = "Unknown"
        self._feed_text = "—"
        self._pins_text = "Unknown"
        session_id = str(getattr(self.application, "backend_session_id", ""))
        if not session_id:
            session_id = str(getattr(self.application, "session_generation", ""))
        self._envelope_marker = EnvelopeMarker("unknown", marker_reason, session_id=session_id)

    @staticmethod
    def _format_position(position: Position | None) -> str:
        if position is None:
            return "X—  Y—  Z—"
        return f"X{position.x:.2f}  Y{position.y:.2f}  Z{position.z:.2f}"

    @staticmethod
    def _is_reference_position(position: Position) -> bool:
        return abs(position.x) <= 0.001 and abs(position.y) <= 0.001 and abs(position.z) <= 0.001
