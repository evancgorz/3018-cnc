from __future__ import annotations

from pathlib import Path
import threading
import time

from PySide6.QtCore import Property, QObject, QTimer, QUrl, Signal, Slot

from ..application.controller import ApplicationController
from ..gcode import GCodeError
from ..plaque_engraver import BORDER_STYLES
from ..grbl import (
    GrblStatus,
    Position,
)
from ..machine_state import MachineProfile
from ..step_engraver import STEP_MODES, STEP_ORIENTATIONS, STEP_ZERO_LOCATIONS
from ..step_geometry import STEP_PLANES, StepImportError, StepPlanarModel
from ..text_engraver import FONT_NAMES


class ControllerViewModel(QObject):
    """Qt-facing controller facade; QML never touches a transport or GRBL command."""

    state_changed = Signal()
    toast_requested = Signal(str)
    confirmation_requested = Signal(str, str, str)
    ports_changed = Signal()
    unreferenced_jog_requested = Signal()
    close_requested = Signal()
    step_import_completed = Signal(object, str)
    step_model_imported = Signal(str)

    def __init__(self, application: ApplicationController | None = None) -> None:
        super().__init__()
        root = Path.cwd()
        self.application = application or ApplicationController(root)
        self.application.bind_callbacks(
            on_notice=self._set_notice,
            on_change=self._emit_state,
            on_position_complete=self._on_motion_position_complete,
            on_ready_to_return=self.return_to_work_zero,
        )
        self.connection = None
        self._close_after_return_pending = False
        self._last_status_poll = 0.0
        self._unreferenced_jog_allowed = False
        self._pending_confirmation: tuple[str, object] | None = None
        self._confirmation_token = ""
        self._confirmation_sequence = 0
        self._ports: list[str] = []
        self._connection_text = "Disconnected"
        self._state_text = "Unknown"
        self._machine_position_text = "X—  Y—  Z—"
        self._work_position_text = "X—  Y—  Z—"
        self._reference_text = "Position unknown"
        self._work_zero_text = "Not confirmed"
        self._spindle_text = "Off"
        self._feed_text = "0"
        self._pins_text = "—"
        self._job_file_text = "No G-code loaded"
        self._job_summary_text = "Load a metric, pre-sliced engraving file."
        self._preview_strokes: list[list[list[float]]] = []
        self._preview_model_strokes: list[list[list[float]]] = []
        self._preview_stock_width = 0.0
        self._preview_stock_height = 0.0
        self._preview_summary = ""
        self._step_operations: list[dict[str, object]] = []
        self._step_preview_valid = False
        self._step_model: StepPlanarModel | None = None
        self._step_path: Path | None = None
        self._step_source_text = "No STEP model imported"
        self._step_import_status = "Import a planar STEP model to begin."
        self._step_importing = False
        self._log_lines: list[str] = []
        self.transport = self.application.settings.preferred_transport
        self.port = ""
        self.wifi_host = self.application.settings.wifi_host
        self.wifi_port = self.application.settings.wifi_port
        self._refresh_ports()
        self.step_import_completed.connect(self._finish_step_import)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)
        self._timer.start(50)

    @property
    def session(self):
        return self.application.session

    @property
    def status(self):
        return self.application.status

    @status.setter
    def status(self, value) -> None:
        self.application.status = value

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

    def _on_motion_position_complete(self) -> None:
        if self._close_after_return_pending and self.at_reference:
            self._close_after_return_pending = False
            self.close_requested.emit()

    @Property(str, notify=state_changed)
    def connection_text(self) -> str:
        return self._connection_text

    @Property(str, notify=state_changed)
    def confirmation_token(self) -> str:
        return self._confirmation_token

    @Property(str, notify=state_changed)
    def grbl_state(self) -> str:
        return self._state_text

    @Property(str, notify=state_changed)
    def machine_position(self) -> str:
        return self._machine_position_text

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

    @Property("QVariantList", notify=state_changed)
    def preview_model_strokes(self) -> list[list[list[float]]]:
        return self._preview_model_strokes

    @Property(float, notify=state_changed)
    def preview_stock_width(self) -> float:
        return self._preview_stock_width

    @Property(float, notify=state_changed)
    def preview_stock_height(self) -> float:
        return self._preview_stock_height

    @Property("QVariantList", notify=state_changed)
    def step_operations(self) -> list[dict[str, object]]:
        return self._step_operations

    @Property(bool, notify=state_changed)
    def step_preview_valid(self) -> bool:
        return self._step_preview_valid

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

    @Property("QStringList", notify=state_changed)
    def log_lines(self) -> list[str]:
        return self._log_lines

    @Property(str, notify=state_changed)
    def job_state(self) -> str:
        return self.application.job_state.title()

    @Property(int, notify=state_changed)
    def job_progress(self) -> int:
        return round(self.application.job_progress * 100)

    @Property(bool, notify=state_changed)
    def connected(self) -> bool:
        return self.application.connected

    @Property(str, notify=state_changed)
    def preferred_transport(self) -> str:
        return self.transport

    @Property(str, notify=state_changed)
    def saved_wifi_host(self) -> str:
        return self.wifi_host

    @Property(int, notify=state_changed)
    def saved_wifi_port(self) -> int:
        return self.wifi_port

    @Property(bool, notify=state_changed)
    def at_reference(self) -> bool:
        position = self.application.virtual_position
        return bool(self.connected and position is not None and self._is_reference_position(position))

    @Property(bool, notify=state_changed)
    def requires_exit_prompt(self) -> bool:
        return bool(self.connected and not self.at_reference)

    @Property(bool, notify=state_changed)
    def can_return_to_reference(self) -> bool:
        return self.application.can_return_to_reference

    @Property(bool, notify=state_changed)
    def can_jog(self) -> bool:
        return self.application.can_jog

    @Property(bool, notify=state_changed)
    def can_live_jog(self) -> bool:
        return self.application.can_live_jog

    @Property(bool, notify=state_changed)
    def live_jog_active(self) -> bool:
        """Whether a held-jog session is active, including during GRBL state changes."""
        return self.application.live_jog_active

    @Property(bool, notify=state_changed)
    def unreferenced_jog_allowed(self) -> bool:
        return self._unreferenced_jog_allowed

    @Property(bool, notify=state_changed)
    def job_active(self) -> bool:
        return self.application.job_active

    @Property(bool, notify=state_changed)
    def can_start_job(self) -> bool:
        return self.application.can_start_job

    @Property("QStringList", notify=ports_changed)
    def ports(self) -> list[str]:
        return self._ports

    def apply_status(self, status: GrblStatus) -> None:
        """Apply a status report directly for tests and non-transport adapters."""
        self.application.apply_status(status)
        self._project_status(status)

    @Slot(str)
    def show_preview_notice(self, message: str) -> None:
        """Temporary navigation feedback while a workspace is being migrated."""
        self._set_notice(message)

    @Slot()
    def show_connection_notice(self) -> None:
        self._set_notice("Use the Connect control to choose USB serial or Wi-Fi TCP.")

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
            self._set_notice("Confirmation expired; review the current machine state and try again")
            return
        self._pending_confirmation = None
        self._confirmation_token = ""
        operation, payload = pending
        if operation == "spindle_start":
            outcome = self.application.start_spindle(int(payload))
            self._set_notice(outcome.message)
        elif operation == "job_start":
            if not self.application.can_start_job:
                self._set_notice("Job confirmation expired — the machine or loaded program is no longer ready")
                return
            fits, reason = self.application.preflight()
            if not fits:
                self._set_notice(f"Job blocked — {reason}")
                return
            outcome = self.application.start_job()
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

    @Slot(QUrl)
    def import_step_file(self, selected_file: QUrl) -> None:
        """Import a STEP URL selected by Qt Quick's file dialog."""

        if self._step_importing:
            self._set_notice("STEP import is already in progress")
            return
        path_text = selected_file.toLocalFile()
        if not path_text:
            self._set_notice("STEP import rejected — choose a local STEP file")
            return
        path = Path(path_text)
        self._step_importing = True
        self._step_source_text = f"Importing {path.name}…"
        self._step_import_status = "Reading STEP geometry and finding planar machining faces…"
        self._emit_state()
        threading.Thread(target=self._import_step_worker, args=(path,), daemon=True).start()

    def _import_step_worker(self, path: Path) -> None:
        try:
            model = self.application.import_step(path)
        except Exception as exc:
            self.step_import_completed.emit(None, str(exc))
        else:
            self.step_import_completed.emit(model, "")

    @Slot(object, str)
    def _finish_step_import(self, model: object, error: str) -> None:
        self._step_importing = False
        if not isinstance(model, StepPlanarModel):
            detail = error or "The STEP importer returned no model"
            self._step_source_text = "STEP import failed"
            self._step_import_status = f"Import failed: {detail}"
            self._set_notice(f"STEP import rejected — {detail}")
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
        self._set_notice(f"Imported planar STEP model {model.path.name}")
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
            self._set_notice(f"STEP preview rejected — {exc}")
        else:
            self._preview_strokes = self._strokes_for_qml(job.strokes)
            self._preview_model_strokes = self._strokes_for_qml(job.result.model_strokes)
            self._preview_stock_width = job.result.stock_width
            self._preview_stock_height = job.result.stock_height
            self._preview_summary = self._step_job_summary(job.result)
            self._step_operations = self._operations_for_qml(job.result)
            self._step_preview_valid = True
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
            "The controller will restart and join the selected 2.4 GHz network. The current manual reference will be cleared.",
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
        if not self.can_live_jog:
            self._set_notice("Live jog ignored — machine is not ready or GRBL is not Idle")
            return
        if not self.application.reference_trusted and not self._unreferenced_jog_allowed:
            self.unreferenced_jog_requested.emit()
            return
        outcome = self.application.start_live_jog(axis, direction, self._unreferenced_jog_allowed, 500.0)
        if not outcome.accepted:
            self._set_notice(outcome.message)

    @Slot()
    def stop_live_jog(self) -> None:
        outcome = self.application.stop_live_jog()
        if not outcome.accepted:
            self._set_notice(outcome.message)
        self._last_status_poll = 0.0

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
    def establish_reference(self) -> None:
        outcome = self.application.establish_reference()
        if outcome.accepted:
            self._unreferenced_jog_allowed = False
        self._set_notice(outcome.message)
        self._emit_state()

    @Slot(str)
    def set_work_zero(self, axes: str) -> None:
        outcome = self.application.set_work_zero(axes)
        if not outcome.accepted:
            self._set_notice(outcome.message)
            return
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

    @Slot()
    def return_to_reference_and_close(self) -> None:
        if not self.can_return_to_reference:
            self._set_notice("Return to reference is unavailable until GRBL is Idle with a trusted position")
            return
        self._close_after_return_pending = True
        self.return_to_reference()

    @Slot(QUrl)
    def load_gcode_file(self, selected_file: QUrl) -> None:
        if self.job_active:
            self._set_notice("G-code load ignored — a job is active")
            return
        path_text = selected_file.toLocalFile()
        if not path_text:
            return
        try:
            program = self.application.load_program(Path(path_text))
        except (OSError, GCodeError) as exc:
            self._set_notice(f"G-code rejected — {exc}")
            return
        bounds = program.bounds
        size = bounds.size
        self._preview_strokes = self._strokes_for_program(program)
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
        self._preview_stock_width = stock_width
        self._preview_stock_height = stock_height
        self._preview_summary = summary
        self._job_file_text = filename
        self._job_summary_text = summary
        self._set_notice(f"Generated {filename} and loaded it for review")
        self._emit_state()

    @Slot()
    def start_job(self) -> None:
        if not self.can_start_job or self.program is None:
            self._set_notice("Job blocked — connect, reference, confirm XYZ work zero, and load a fitting job")
            return
        fits, reason = self.application.preflight()
        if not fits:
            self._set_notice(f"Job blocked — {reason}")
            return
        self._request_confirmation(
            "job_start",
            None,
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
        self.disconnect()

    def _refresh_ports(self) -> None:
        self._ports = [f"{device} — {description}" for device, description in self.application.usb_ports()]
        if self._ports and not self.port:
            self.port = self._ports[0]
        self.ports_changed.emit()

    def _poll(self) -> None:
        self._poll_wifi_result()
        self.application.poll_wifi_setup(time.monotonic())
        if not self.connected:
            return
        events = self.application.transport_events()
        try:
            while not events.empty():
                self._handle_event(events.get_nowait())
            now = time.monotonic()
            if self.connected and now - self._last_status_poll >= 0.5:
                self.application.request_status()
                self._last_status_poll = now
        except RuntimeError as exc:
            self._disconnected(str(exc))

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
            if self._close_after_return_pending and self.at_reference:
                self._close_after_return_pending = False
                self.close_requested.emit()
            self._project_status(status)
        if reset:
            if self.status is not None:
                self._project_status(self.status)
            else:
                self._emit_state()

    def _project_status(self, status: GrblStatus) -> None:
        self._state_text = status.state
        self._connection_text = f"Connected — GRBL {status.state}"
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
        self._emit_state()

    @staticmethod
    def _strokes_for_qml(strokes: tuple[tuple[tuple[float, float], ...], ...] | list[tuple[tuple[float, float], ...]]) -> list[list[list[float]]]:
        return [[[float(x), float(y)] for x, y in stroke] for stroke in strokes]

    @classmethod
    def _strokes_for_program(cls, program: GCodeProgram) -> list[list[list[float]]]:
        return cls._strokes_for_qml(tuple(tuple((segment.start.x, segment.start.y), (segment.end.x, segment.end.y)) for segment in program.segments))

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
        if any(patch.tilted for patch in model.surface_patches):
            return "Planar surface"
        if model.features:
            return "Detected feature"
        return "Engraving"

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
        self._close_after_return_pending = False
        self._unreferenced_jog_allowed = False
        self._connection_text = "Disconnected"
        self._state_text = "Unknown"
        self._machine_position_text = "X—  Y—  Z—"
        self._work_position_text = "X—  Y—  Z—"
        self._reference_text = "Position unknown"
        self._work_zero_text = "Not confirmed"
        self._spindle_text = "Off"
        self._emit_state()

    def _set_notice(self, message: str) -> None:
        self.toast_requested.emit(message)

    def _request_confirmation(self, operation: str, payload: object, title: str, message: str) -> None:
        self._confirmation_sequence += 1
        self._confirmation_token = f"{operation}:{self._confirmation_sequence}"
        self._pending_confirmation = (operation, payload)
        self.confirmation_requested.emit(self._confirmation_token, title, message)
        self._emit_state()

    def _append_log(self, event) -> None:
        line = f"{event.timestamp:%H:%M:%S}  {event.kind.upper():<11} {event.text}"
        self._log_lines = (*self._log_lines[-399:], line)
        self._emit_state()

    def _emit_state(self) -> None:
        self.state_changed.emit()

    @staticmethod
    def _format_position(position: Position | None) -> str:
        if position is None:
            return "X—  Y—  Z—"
        return f"X{position.x:.2f}  Y{position.y:.2f}  Z{position.z:.2f}"

    @staticmethod
    def _is_reference_position(position: Position) -> bool:
        return abs(position.x) <= 0.001 and abs(position.y) <= 0.001 and abs(position.z) <= 0.001
