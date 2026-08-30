from __future__ import annotations

import math
from pathlib import Path
import queue
import threading
import time

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot
from PySide6.QtWidgets import QFileDialog, QMessageBox

from ..application.machine_session import MachineSession
from ..connection_settings import ConnectionSettings, ConnectionSettingsStore
from ..commissioning import CommissioningProfile, CommissioningStore, InputTestTracker
from ..gcode import GCodeError, GCodeProgram, load_gcode, parse_gcode
from ..plaque_engraver import BORDER_STYLES, generate_plaque_gcode
from ..grbl import (
    GrblStatus,
    Position,
    REALTIME_HOLD,
    REALTIME_JOG_CANCEL,
    REALTIME_RESUME,
    REALTIME_SOFT_RESET,
    REALTIME_STATUS,
    make_setting,
    make_jog,
    make_work_zero,
    parse_setting,
    parse_status,
)
from ..job import JobStreamer
from ..machine_state import MachineProfile, ProfileStore, check_job_bounds
from ..serial_connection import GrblConnection, SerialEvent, available_ports
from ..step_engraver import STEP_MODES, STEP_ORIENTATIONS, STEP_ZERO_LOCATIONS, generate_step_gcode
from ..step_geometry import STEP_PLANES, StepImportError, StepPlanarModel, load_step
from ..tcp_connection import TcpGrblConnection
from ..text_engraver import FONT_NAMES, generate_text_gcode
from ..wifi_setup import make_station_commands
from ..wifi_discovery import discover_grbl_hosts


class ControllerViewModel(QObject):
    """Qt-facing controller facade; QML never touches a transport or GRBL command."""

    state_changed = Signal()
    toast_requested = Signal(str)
    ports_changed = Signal()
    unreferenced_jog_requested = Signal()
    close_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        root = Path.cwd()
        self.profile_store = ProfileStore(root / "config" / "machine-profile.json")
        self.connection_store = ConnectionSettingsStore(root / "config" / "connection.json")
        self.commissioning_store = CommissioningStore(root / "config" / "commissioning.json")
        try:
            profile = self.profile_store.load()
        except (OSError, ValueError, TypeError):
            profile = MachineProfile()
        try:
            settings = self.connection_store.load()
        except (OSError, ValueError, TypeError):
            settings = ConnectionSettings()

        self.session = MachineSession(profile=profile)
        try:
            self.commissioning_profile = self.commissioning_store.load()
        except (OSError, ValueError, TypeError):
            self.commissioning_profile = CommissioningProfile()
        self._commissioning_tracker = InputTestTracker()
        self._commissioning_settings: dict[int, float] = {}
        self.connection: GrblConnection | TcpGrblConnection | None = None
        self.status: GrblStatus | None = None
        self.job = JobStreamer(self._send_job_line)
        self.program: GCodeProgram | None = None
        self._pending_manual_acks = 0
        self._position_queue: list[tuple[str, float, float]] = []
        self._position_move_active = False
        self._return_after_job_pending = False
        self._close_after_return_pending = False
        self._live_jog_axis: str | None = None
        self._live_jog_axis_last: str | None = None
        self._live_jog_direction = 0.0
        self._live_jog_first_distance: float | None = None
        self._live_jog_position: Position | None = None
        self._live_jog_stop_pending = False
        self._live_jog_alignment_pending = False
        self._wifi_connecting = False
        self._wifi_results: queue.Queue[tuple[TcpGrblConnection | None, str, int]] = queue.Queue()
        self._last_status_poll = 0.0
        self._unreferenced_jog_allowed = False
        self._preserve_references_on_next_reset = False
        self._wifi_setup_commands: list[tuple[bytes, str]] = []
        self._wifi_setup_index = 0
        self._wifi_setup_waiting = False
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
        self._preview_summary = ""
        self._step_model: StepPlanarModel | None = None
        self._step_path: Path | None = None
        self._step_source_text = "No STEP model imported"
        self._log_lines: list[str] = []
        self._commissioning_pins_text = "Active inputs: none"
        self._commissioning_status_text = "No commissioning checks recorded"
        self.transport = settings.preferred_transport
        self.port = ""
        self.wifi_host = settings.wifi_host
        self.wifi_port = settings.wifi_port
        self._refresh_ports()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)
        self._timer.start(50)

    @Property(str, notify=state_changed)
    def connection_text(self) -> str:
        return self._connection_text

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
        return self.session.envelope.trusted

    @Property(str, notify=state_changed)
    def work_zero(self) -> str:
        return self._work_zero_text

    @Property(bool, notify=state_changed)
    def work_zero_confirmed(self) -> bool:
        return self.session.work_zero_confirmed

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
            return "Import a planar STEP model to begin."
        model = self._step_model
        return f"{model.width:.2f} × {model.height:.2f} mm · {len(model.loops)} closed loop(s) · {model.face_plane} face · thickness {model.thickness:.2f} mm"

    @Property(bool, notify=state_changed)
    def step_loaded(self) -> bool:
        return self._step_model is not None

    @Property("QVariantList", notify=state_changed)
    def preview_strokes(self) -> list[list[list[float]]]:
        return self._preview_strokes

    @Property(str, notify=state_changed)
    def preview_summary(self) -> str:
        return self._preview_summary

    @Property(str, notify=state_changed)
    def profile_summary(self) -> str:
        profile = self.session.profile
        return f"{profile.name} · X {profile.travel_x:g} · Y {profile.travel_y:g} · Z {profile.travel_z:g} · safe Z {profile.safe_z:g} mm"

    @Property(str, notify=state_changed)
    def profile_name(self) -> str:
        return self.session.profile.name

    @Property(float, notify=state_changed)
    def profile_x(self) -> float:
        return self.session.profile.travel_x

    @Property(float, notify=state_changed)
    def profile_y(self) -> float:
        return self.session.profile.travel_y

    @Property(float, notify=state_changed)
    def profile_z(self) -> float:
        return self.session.profile.travel_z

    @Property(float, notify=state_changed)
    def profile_safe_z(self) -> float:
        return self.session.profile.safe_z

    @Property("QStringList", notify=state_changed)
    def log_lines(self) -> list[str]:
        return self._log_lines

    @Property(str, notify=state_changed)
    def commissioning_pins(self) -> str:
        return self._commissioning_pins_text

    @Property(str, notify=state_changed)
    def commissioning_summary(self) -> str:
        return self._commissioning_status_text

    @Property(bool, notify=state_changed)
    def x_limit_tested(self) -> bool:
        return self.commissioning_profile.x_limit_tested

    @Property(bool, notify=state_changed)
    def y_limit_tested(self) -> bool:
        return self.commissioning_profile.y_limit_tested

    @Property(bool, notify=state_changed)
    def z_limit_tested(self) -> bool:
        return self.commissioning_profile.z_limit_tested

    @Property(bool, notify=state_changed)
    def probe_tested(self) -> bool:
        return self.commissioning_profile.probe_tested

    @Property(bool, notify=state_changed)
    def x_direction_confirmed(self) -> bool:
        return self.commissioning_profile.x_positive_confirmed

    @Property(bool, notify=state_changed)
    def y_direction_confirmed(self) -> bool:
        return self.commissioning_profile.y_positive_confirmed

    @Property(bool, notify=state_changed)
    def z_direction_confirmed(self) -> bool:
        return self.commissioning_profile.z_positive_confirmed

    @Property(str, notify=state_changed)
    def job_state(self) -> str:
        return self.job.state.title()

    @Property(int, notify=state_changed)
    def job_progress(self) -> int:
        return round(self.job.progress * 100)

    @Property(bool, notify=state_changed)
    def connected(self) -> bool:
        return self.connection is not None and self.connection.connected

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
        position = self.session.virtual_position
        return bool(self.connected and position is not None and self._is_reference_position(position))

    @Property(bool, notify=state_changed)
    def requires_exit_prompt(self) -> bool:
        return bool(self.connected and not self.at_reference)

    @Property(bool, notify=state_changed)
    def can_return_to_reference(self) -> bool:
        return bool(self.connected and self.session.envelope.trusted and self.session.can_move and not self.job_active and not self._pending_manual_acks and not self._position_move_active)

    @Property(bool, notify=state_changed)
    def can_jog(self) -> bool:
        return bool(
            self.connected
            and self.session.can_move
            and not self.job_active
            and not self._position_move_active
            and not self._pending_manual_acks
            and not self._live_jog_stop_pending
            and not self._live_jog_alignment_pending
        )

    @Property(bool, notify=state_changed)
    def can_live_jog(self) -> bool:
        return bool(
            self.connected
            and self.session.can_move
            and not self.job_active
            and not self._position_move_active
            and not self._live_jog_stop_pending
            and not self._live_jog_alignment_pending
            and (not self._pending_manual_acks or self._live_jog_axis is not None)
        )

    @Property(bool, notify=state_changed)
    def unreferenced_jog_allowed(self) -> bool:
        return self._unreferenced_jog_allowed

    @Property(bool, notify=state_changed)
    def job_active(self) -> bool:
        return self.job.state in {"running", "paused"}

    @Property(bool, notify=state_changed)
    def can_start_job(self) -> bool:
        return bool(
            self.program
            and self.connected
            and self.session.can_move
            and self.session.envelope.trusted
            and self.session.work_zero_confirmed
            and not self._pending_manual_acks
            and not self._position_move_active
            and not self.job_active
        )

    @Property("QStringList", notify=ports_changed)
    def ports(self) -> list[str]:
        return self._ports

    def apply_status(self, status: GrblStatus) -> None:
        """Apply a status report directly for tests and non-transport adapters."""
        self.status = status
        self.session.update_status(status)
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
            self.profile_store.save(profile)
        except (OSError, ValueError, TypeError) as exc:
            QMessageBox.critical(None, "Machine profile rejected", str(exc))
            return
        self.session.profile = profile
        self._set_notice("Machine profile saved; the current reference was retained")
        self._emit_state()

    @Slot()
    def invalidate_reference(self) -> None:
        self.session.invalidate_reference("Manually invalidated")
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
        try:
            self._preserve_references_on_next_reset = False
            self._send_realtime(REALTIME_SOFT_RESET)
        except RuntimeError as exc:
            self._set_notice(f"Soft reset failed — {exc}")

    @Slot(str)
    def start_input_test(self, pin: str) -> None:
        if self.status is None:
            self._set_notice("Input test requires a live GRBL status report")
            return
        try:
            result = self._commissioning_tracker.start(pin, self.status.pins)
        except ValueError as exc:
            self._set_notice(str(exc))
            return
        self._commissioning_status_text = result.message
        self._set_notice(result.message)
        self._emit_state()

    @Slot(str, bool)
    def confirm_commissioning_direction(self, axis: str, confirmed: bool) -> None:
        axis = axis.upper()
        if axis not in "XYZ":
            return
        setattr(self.commissioning_profile, f"{axis.lower()}_positive_confirmed", confirmed)
        self._save_commissioning_profile()

    @Slot(float, float, float, float)
    def save_probe_geometry(self, plate_thickness: float, x_edge_offset: float, y_edge_offset: float, hole_diameter: float) -> None:
        self.commissioning_profile.plate_thickness = plate_thickness
        self.commissioning_profile.x_edge_offset = x_edge_offset
        self.commissioning_profile.y_edge_offset = y_edge_offset
        self.commissioning_profile.hole_diameter = hole_diameter
        try:
            self._save_commissioning_profile()
        except ValueError as exc:
            self._set_notice(f"Probe geometry rejected — {exc}")
            return
        self._set_notice("Measured probe geometry saved")

    @Slot()
    def read_commissioning_settings(self) -> None:
        if not self.session.can_move:
            self._set_notice("Settings read requires GRBL Idle")
            return
        try:
            self._send_manual(b"$$\n")
        except RuntimeError as exc:
            self._set_notice(f"Settings request failed — {exc}")
            return
        self._set_notice("Reading GRBL settings")

    @Slot()
    def apply_commissioning_settings(self) -> None:
        if not self.session.can_move:
            self._set_notice("Settings apply requires GRBL Idle")
            return
        if not self.commissioning_profile.ready_for_homing_test:
            self._set_notice("Complete all limit tests, direction checks, and settings review first")
            return
        answer = QMessageBox.question(None, "Apply first homing settings?", "Apply the guarded first-homing configuration with soft and hard limits disabled? Verify the machine-specific homing direction mask before continuing.")
        if answer != QMessageBox.StandardButton.Yes:
            return
        values = {20: 0, 21: 0, 22: 1, 24: 25, 25: 200, 26: 250, 27: 2, 130: self.session.profile.travel_x, 131: self.session.profile.travel_y, 132: self.session.profile.travel_z}
        try:
            for number, value in values.items():
                self._send_manual(make_setting(number, value))
        except (RuntimeError, ValueError) as exc:
            self._set_notice(f"Commissioning settings stopped — {exc}")
            return
        self.commissioning_profile.homing_settings_reviewed = True
        self._save_commissioning_profile()
        self._set_notice("First-homing settings sent")

    @Slot()
    def run_homing_test(self) -> None:
        if not self.session.can_move:
            self._set_notice("Homing requires GRBL Idle")
            return
        if not self.commissioning_profile.ready_for_homing_test:
            self._set_notice("Homing is gated until input tests, directions, and settings review pass")
            return
        answer = QMessageBox.question(None, "Run first homing test?", "Clear the machine, keep physical power within reach, and confirm every switch is installed. Start GRBL homing now?")
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self._send_manual(b"$H\n")
        except RuntimeError as exc:
            self._set_notice(f"Homing not started — {exc}")
            return
        self._set_notice("First homing test started")

    @Slot()
    def mark_homing_verified(self) -> None:
        if self.status is None or not self.status.can_jog:
            self._set_notice("Mark homing verified only after GRBL returns to Idle")
            return
        self.commissioning_profile.homing_verified = True
        self._save_commissioning_profile()
        self._set_notice("Homing marked successful")

    @Slot()
    def enable_protections(self) -> None:
        if not self.commissioning_profile.homing_verified:
            self._set_notice("Verify a successful homing cycle before enabling protections")
            return
        try:
            self._send_manual(make_setting(21, 1))
            self._send_manual(make_setting(20, 1))
        except (RuntimeError, ValueError) as exc:
            self._set_notice(f"Protection settings stopped — {exc}")
            return
        self._set_notice("Hard and soft limits enable requested")

    @Slot(str, str, float, float, float, float, float, float, float, str, int)
    def preview_text(self, text: str, font: str, height: float, depth: float, safe_z: float, cut_feed: float, plunge_feed: float, letter_spacing: float, line_spacing: float, alignment: str, spindle_rpm: int) -> None:
        try:
            engraving = generate_text_gcode(
                text, font=font, text_height=height, depth=depth, safe_z=safe_z,
                cut_feed=cut_feed, plunge_feed=plunge_feed,
                letter_spacing=letter_spacing, line_spacing=line_spacing, alignment=alignment,
                spindle_rpm=spindle_rpm if spindle_rpm > 0 else None,
            )
        except (ValueError, TypeError):
            self._preview_strokes = []
            self._preview_summary = "Enter valid text settings to preview the centerline toolpath."
        else:
            self._preview_strokes = self._strokes_for_qml(engraving.strokes)
            self._preview_summary = f"{engraving.width:.1f} × {engraving.height:.1f} mm · {engraving.stroke_count} strokes"
        self._emit_state()

    @Slot(str, str, bool, str, str, float, float, float, float, float, str, float, float, float, float, int)
    def preview_plaque(self, title: str, subtitle: str, subtitle_enabled: bool, title_font: str, subtitle_font: str, title_height: float, subtitle_height: float, width: float, height: float, margin: float, border: str, depth: float, safe_z: float, cut_feed: float, plunge_feed: float, spindle_rpm: int) -> None:
        try:
            plaque = generate_plaque_gcode(
                title, subtitle, subtitle_enabled=subtitle_enabled, title_font=title_font,
                subtitle_font=subtitle_font, title_height=title_height, subtitle_height=subtitle_height,
                width=width, height=height, margin=margin, border=border, depth=depth,
                safe_z=safe_z, cut_feed=cut_feed, plunge_feed=plunge_feed,
                spindle_rpm=spindle_rpm if spindle_rpm > 0 else None,
            )
        except (ValueError, TypeError):
            self._preview_strokes = []
            self._preview_summary = "Enter valid plaque settings to preview the centerline toolpath."
        else:
            self._preview_strokes = self._strokes_for_qml(plaque.strokes)
            self._preview_summary = f"{plaque.width:.1f} × {plaque.height:.1f} mm · {plaque.stroke_count} strokes · {border}"
        self._emit_state()

    @Slot()
    def import_step(self) -> None:
        path_text, _ = QFileDialog.getOpenFileName(
            None,
            "Import planar STEP model",
            "",
            "STEP files (*.step *.stp);;All files (*.*)",
        )
        if not path_text:
            return
        try:
            model = load_step(Path(path_text))
        except StepImportError as exc:
            QMessageBox.critical(None, "STEP import rejected", str(exc))
            return
        self._step_model = model
        self._step_path = model.path
        self._step_source_text = model.path.name
        self._preview_strokes = self._strokes_for_step_model(model)
        self._preview_summary = self.step_model_summary
        self._set_notice(f"Imported planar STEP model {model.path.name}")
        self._emit_state()

    @Slot(str)
    def set_step_plane(self, plane: str) -> None:
        if self._step_path is None:
            return
        try:
            model = load_step(self._step_path, plane)
        except StepImportError as exc:
            self._set_notice(f"STEP face unavailable — {exc}")
            return
        self._step_model = model
        self._preview_strokes = self._strokes_for_step_model(model)
        self._preview_summary = self.step_model_summary
        self._set_notice(f"Selected {model.face_plane} machining face")
        self._emit_state()

    @Slot(str, str, float, float, str, float, float, int, float, float, float, int)
    def preview_step(self, mode: str, orientation: str, stock_width: float, stock_height: float, zero_location: str, tool_diameter: float, depth: float, passes: int, safe_z: float, cut_feed: float, plunge_feed: float, spindle_rpm: int) -> None:
        if self._step_model is None:
            self._preview_strokes = []
            self._preview_summary = "Import a planar STEP model first."
            self._emit_state()
            return
        try:
            job = generate_step_gcode(
                self._step_model, mode=mode, orientation=orientation,
                stock_width=stock_width, stock_height=stock_height,
                zero_location=zero_location, tool_diameter=tool_diameter,
                depth=depth, passes=passes, safe_z=safe_z,
                cut_feed=cut_feed, plunge_feed=plunge_feed,
                spindle_rpm=spindle_rpm if spindle_rpm > 0 else None,
            )
        except (ValueError, TypeError):
            self._preview_strokes = []
            self._preview_summary = "Enter valid STEP machining settings to preview the toolpath."
        else:
            self._preview_strokes = self._strokes_for_qml(job.strokes)
            self._preview_summary = self._step_job_summary(job)
        self._emit_state()

    @Slot(str, str, float, float, float, float, float, float, float, str, int)
    def create_text(self, text: str, font: str, height: float, depth: float, safe_z: float, cut_feed: float, plunge_feed: float, letter_spacing: float, line_spacing: float, alignment: str, spindle_rpm: int) -> None:
        try:
            engraving = generate_text_gcode(
                text, font=font, text_height=height, depth=depth, safe_z=safe_z,
                cut_feed=cut_feed, plunge_feed=plunge_feed,
                letter_spacing=letter_spacing, line_spacing=line_spacing, alignment=alignment,
                spindle_rpm=spindle_rpm if spindle_rpm > 0 else None,
            )
        except (ValueError, TypeError) as exc:
            QMessageBox.critical(None, "Text settings rejected", str(exc))
            return
        self._load_generated_program(engraving.gcode, "generated-text.gcode", engraving.strokes, f"Text · {engraving.width:.1f} × {engraving.height:.1f} mm · {engraving.stroke_count} strokes")

    @Slot(str, str, bool, str, str, float, float, float, float, float, str, float, float, float, float, int)
    def create_plaque(self, title: str, subtitle: str, subtitle_enabled: bool, title_font: str, subtitle_font: str, title_height: float, subtitle_height: float, width: float, height: float, margin: float, border: str, depth: float, safe_z: float, cut_feed: float, plunge_feed: float, spindle_rpm: int) -> None:
        try:
            plaque = generate_plaque_gcode(
                title, subtitle, subtitle_enabled=subtitle_enabled, title_font=title_font,
                subtitle_font=subtitle_font, title_height=title_height, subtitle_height=subtitle_height,
                width=width, height=height, margin=margin, border=border, depth=depth,
                safe_z=safe_z, cut_feed=cut_feed, plunge_feed=plunge_feed,
                spindle_rpm=spindle_rpm if spindle_rpm > 0 else None,
            )
        except (ValueError, TypeError) as exc:
            QMessageBox.critical(None, "Plaque settings rejected", str(exc))
            return
        self._load_generated_program(plaque.gcode, "generated-plaque.gcode", plaque.strokes, f"Plaque · {plaque.width:.1f} × {plaque.height:.1f} mm · {plaque.stroke_count} strokes")

    @Slot(str, str, float, float, str, float, float, int, float, float, float, int)
    def create_step(self, mode: str, orientation: str, stock_width: float, stock_height: float, zero_location: str, tool_diameter: float, depth: float, passes: int, safe_z: float, cut_feed: float, plunge_feed: float, spindle_rpm: int) -> None:
        if self._step_model is None:
            QMessageBox.critical(None, "STEP job unavailable", "Import a planar STEP model first")
            return
        try:
            job = generate_step_gcode(
                self._step_model, mode=mode, orientation=orientation,
                stock_width=stock_width, stock_height=stock_height,
                zero_location=zero_location, tool_diameter=tool_diameter,
                depth=depth, passes=passes, safe_z=safe_z,
                cut_feed=cut_feed, plunge_feed=plunge_feed,
                spindle_rpm=spindle_rpm if spindle_rpm > 0 else None,
            )
        except (ValueError, TypeError) as exc:
            QMessageBox.critical(None, "STEP machining settings rejected", str(exc))
            return
        self._load_generated_program(
            job.gcode,
            "generated-step.gcode",
            job.strokes,
            self._step_job_summary(job),
        )

    @Slot()
    def save_gcode(self) -> None:
        if self.program is None:
            self._set_notice("Save ignored — no validated G-code is loaded")
            return
        path_text, _ = QFileDialog.getSaveFileName(
            None,
            "Save validated G-code",
            self.program.path.name,
            "G-code (*.gcode *.nc);;All files (*.*)",
        )
        if not path_text:
            return
        try:
            Path(path_text).write_text("\n".join(self.program.commands) + "\n", encoding="ascii")
        except OSError as exc:
            QMessageBox.critical(None, "G-code not saved", str(exc))
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
        try:
            port = port_label.split(" ", 1)[0].strip()
            if not port:
                raise ValueError("Select a serial port first")
            connection = GrblConnection()
            connection.connect(port)
        except (OSError, ValueError, RuntimeError) as exc:
            self._set_notice(f"Connection failed: {exc}")
            return
        self.connection = connection
        self.transport = "USB serial"
        self._connection_text = f"Connected to {port}; waiting for GRBL status"
        self._set_notice(self._connection_text)
        self._emit_state()

    @Slot(str, int)
    def connect_to_wifi(self, host: str, port: int) -> None:
        if self.connected:
            self.disconnect()
            return
        if self._wifi_connecting:
            self._set_notice("Wi-Fi discovery is already running")
            return
        self._wifi_connecting = True
        self.transport = "Wi-Fi TCP"
        self._connection_text = f"Trying {host or 'saved host'}:{port}; discovering GRBL if needed…"
        self._emit_state()

        def worker() -> None:
            last_error = "No GRBL controller answered on the local network"
            candidates = [host.strip()] if host.strip() else []
            candidates.extend(discover_grbl_hosts(port))
            for candidate in dict.fromkeys(candidates):
                connection = TcpGrblConnection()
                try:
                    connection.connect(candidate, port, timeout=1.2)
                except (OSError, ValueError, RuntimeError) as exc:
                    last_error = str(exc)
                    continue
                self._wifi_results.put((connection, candidate, port))
                return
            self._wifi_results.put((None, last_error, port))

        threading.Thread(target=worker, daemon=True).start()

    @Slot(str, str)
    def configure_wifi(self, ssid: str, password: str) -> None:
        if not isinstance(self.connection, GrblConnection) or not self.connected:
            self._set_notice("Wi-Fi setup requires an active USB connection")
            return
        if self.status is None or not self.status.can_jog:
            self._set_notice("Wi-Fi setup requires GRBL Idle")
            return
        try:
            commands = make_station_commands(ssid, password, self.wifi_port)
        except ValueError as exc:
            QMessageBox.critical(None, "Invalid Wi-Fi settings", str(exc))
            return
        answer = QMessageBox.question(
            None,
            "Switch controller to station mode?",
            "The controller will restart and join the selected 2.4 GHz network. The current manual reference will be cleared.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.session.invalidate_reference("Controller Wi-Fi reconfiguration")
        self._wifi_setup_commands = commands
        self._wifi_setup_index = 0
        self._wifi_setup_waiting = False
        self._set_notice("Configuring controller Wi-Fi; the controller will restart")
        self._send_next_wifi_setup_command()

    @Slot()
    def disconnect(self) -> None:
        if self.connection is not None:
            self.connection.disconnect()
        self._disconnected("Disconnected; physical position cannot be guaranteed")

    @Slot(str, float)
    def jog(self, axis: str, distance: float) -> None:
        if not self.can_jog:
            self._set_notice("Jog ignored — machine is not ready or GRBL is not Idle")
            return
        if not self.session.envelope.trusted and not self._unreferenced_jog_allowed:
            self.unreferenced_jog_requested.emit()
            return
        outcome = self.session.check_jog(axis, distance)
        if not outcome.accepted:
            self._set_notice(f"Jog blocked — {outcome.message}")
            return
        try:
            self._send_manual(make_jog(axis, distance, 500.0))
        except (RuntimeError, ValueError) as exc:
            self._set_notice(f"Jog not sent — {exc}")

    @Slot(str, float)
    def start_live_jog(self, axis: str, direction: float) -> None:
        axis = axis.upper()
        direction = 1.0 if direction > 0 else -1.0
        if axis not in {"X", "Y", "Z"}:
            self._set_notice("Live jog ignored — axis must be X, Y, or Z")
            return
        if self._live_jog_axis is not None:
            return
        if not self.can_live_jog:
            self._set_notice("Live jog ignored — machine is not ready or GRBL is not Idle")
            return
        if not self.session.envelope.trusted and not self._unreferenced_jog_allowed:
            self.unreferenced_jog_requested.emit()
            return
        position = self.session.virtual_position if self.session.envelope.trusted else self.session.machine_position
        if position is None:
            self._set_notice("Live jog ignored — current position is unavailable")
            return
        current = getattr(position, axis.lower())
        if direction > 0:
            distance = math.ceil(current - 0.001) - current
            if distance <= 0.001:
                distance = 1.0
        else:
            distance = math.floor(current + 0.001) - current
            if distance >= -0.001:
                distance = -1.0
        self._live_jog_axis = axis
        self._live_jog_axis_last = axis
        self._live_jog_direction = direction
        self._live_jog_first_distance = distance
        self._live_jog_position = position
        self._live_jog_stop_pending = False
        self._live_jog_alignment_pending = False
        self._send_next_live_jog()

    @Slot()
    def stop_live_jog(self) -> None:
        if self._live_jog_axis is None:
            return
        self._live_jog_axis_last = self._live_jog_axis
        self._live_jog_axis = None
        self._live_jog_first_distance = None
        self._live_jog_stop_pending = True
        try:
            self._send_realtime(REALTIME_JOG_CANCEL)
        except RuntimeError as exc:
            self._clear_live_jog()
            self._set_notice(f"Live jog stop failed — {exc}")
            return
        self._last_status_poll = 0.0

    @Slot(int)
    def start_spindle(self, rpm: int) -> None:
        if not self.can_jog:
            self._set_notice("Spindle start ignored — machine is not ready or GRBL is not Idle")
            return
        if not 1 <= rpm <= 24000:
            self._set_notice("Spindle RPM must be between 1 and 24000")
            return
        answer = QMessageBox.question(
            None,
            "Start spindle?",
            f"Start the spindle clockwise at {rpm} RPM? Keep clear of the tool and be ready to cut physical power.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self._send_manual(f"M3 S{rpm}\n".encode("ascii"))
        except RuntimeError as exc:
            self._set_notice(f"Spindle start failed — {exc}")
            return
        self._set_notice(f"Spindle start requested at {rpm} RPM")

    @Slot()
    def stop_spindle(self) -> None:
        if not self.connected:
            self._set_notice("Spindle stop ignored — not connected")
            return
        try:
            self._send_manual(b"M5\n")
        except RuntimeError as exc:
            self._set_notice(f"Spindle stop failed — {exc}")
            return
        self._set_notice("Spindle stop requested")

    @Slot(float, float, float, float)
    def move_to(self, x: float, y: float, z: float, feed: float = 500.0) -> None:
        if not self.can_jog:
            self._set_notice("Position move ignored — machine is not ready")
            return
        outcome, moves = self.session.plan_move_to(Position(x, y, z))
        if not outcome.accepted:
            self._set_notice(f"Position move blocked — {outcome.message}")
            return
        if not 0 < feed <= 1500:
            self._set_notice("Jog feed must be between 0 and 1500 mm/min")
            return
        self._position_queue = [(axis, distance, feed) for axis, distance in moves]
        self._position_move_active = bool(self._position_queue)
        self._send_next_position_move()

    @Slot()
    def establish_reference(self) -> None:
        outcome = self.session.establish_reference()
        if outcome.accepted:
            self._unreferenced_jog_allowed = False
        self._set_notice(outcome.message)
        self._emit_state()

    @Slot(str)
    def set_work_zero(self, axes: str) -> None:
        if not self.session.can_move:
            self._set_notice("Work-zero command ignored — GRBL is not Idle")
            return
        outcome = self.session.request_work_zero_confirmation(axes)
        if not outcome.accepted:
            self._set_notice(outcome.message)
            return
        try:
            self._send_manual(make_work_zero(axes))
        except (RuntimeError, ValueError) as exc:
            self.session.invalidate_work_zero()
            self._set_notice(f"Work zero not sent — {exc}")
            return
        self._set_notice(outcome.message)
        self._emit_state()

    @Slot()
    def return_to_work_zero(self) -> None:
        outcome, moves = self.session.plan_return_to_work_zero()
        if not outcome.accepted:
            self._set_notice(f"Return skipped — {outcome.message}")
            return
        self._position_queue = [(axis, distance, 500.0) for axis, distance in moves]
        self._position_move_active = bool(self._position_queue)
        self._set_notice("Returning to work zero via safe Z")
        self._send_next_position_move()

    @Slot()
    def retract_safe_z(self) -> None:
        current = self.session.virtual_position
        if current is None:
            self._set_notice("Safe-Z move ignored — no trusted machine position")
            return
        self.move_to(current.x, current.y, self.session.profile.safe_z, 500.0)

    @Slot()
    def return_to_reference(self) -> None:
        self.move_to(0.0, 0.0, 0.0, 500.0)

    @Slot()
    def return_to_reference_and_close(self) -> None:
        if not self.can_return_to_reference:
            self._set_notice("Return to reference is unavailable until GRBL is Idle with a trusted position")
            return
        self._close_after_return_pending = True
        self.return_to_reference()

    @Slot()
    def load_gcode(self) -> None:
        if self.job_active:
            self._set_notice("G-code load ignored — a job is active")
            return
        path_text, _ = QFileDialog.getOpenFileName(
            None,
            "Load pre-sliced G-code",
            "",
            "G-code (*.nc *.gcode *.tap *.cnc *.txt);;All files (*.*)",
        )
        if not path_text:
            return
        try:
            program = load_gcode(Path(path_text))
        except (OSError, GCodeError) as exc:
            QMessageBox.critical(None, "G-code rejected", str(exc))
            return
        self.program = program
        bounds = program.bounds
        size = bounds.size
        self._preview_strokes = self._strokes_for_program(program)
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
    ) -> None:
        try:
            program = parse_gcode(gcode, Path(filename))
        except GCodeError as exc:
            QMessageBox.critical(None, "Generated G-code rejected", str(exc))
            return
        self.program = program
        self._preview_strokes = self._strokes_for_qml(strokes)
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
        fits, reason = self._job_fit(self.program)
        if not fits:
            self._set_notice(f"Job blocked — {reason}")
            return
        answer = QMessageBox.question(None, "Start engraving job?", f"{self.program.path.name}\n\n{reason}\n\nConfirm the material, tool, and physical emergency power are ready.")
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.job.start(self.program.commands)
        except (RuntimeError, ValueError) as exc:
            self._set_notice(f"Job not started — {exc}")
            return
        self._set_notice("Engraving job started")
        self._emit_state()

    @Slot()
    def pause_job(self) -> None:
        try:
            self._send_realtime(REALTIME_HOLD)
            self.job.pause()
        except RuntimeError as exc:
            self._set_notice(f"Pause failed — {exc}")
        self._emit_state()

    @Slot()
    def resume_job(self) -> None:
        try:
            self._send_realtime(REALTIME_RESUME)
            self.job.resume()
        except RuntimeError as exc:
            self._set_notice(f"Resume failed — {exc}")
        self._emit_state()

    @Slot()
    def abort_job(self) -> None:
        if not self.job_active:
            return
        answer = QMessageBox.question(None, "Abort engraving?", "Feed-hold and reset GRBL? The job cannot resume. The current references will be retained while the machine remains connected and powered.")
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self._preserve_references_on_next_reset = True
            self._send_realtime(REALTIME_HOLD)
            self._send_realtime(REALTIME_SOFT_RESET)
        except RuntimeError:
            pass
        self.job.abort()
        self._pending_manual_acks = 0
        self._position_queue = []
        self._position_move_active = False
        self._set_notice("Job aborted — references retained")
        self._emit_state()

    @Slot()
    def cancel_jog(self) -> None:
        self._clear_live_jog()
        try:
            self._send_realtime(REALTIME_JOG_CANCEL)
        except RuntimeError as exc:
            self._set_notice(f"Jog cancel failed — {exc}")

    @Slot()
    def hold(self) -> None:
        try:
            self._send_realtime(REALTIME_HOLD)
        except RuntimeError as exc:
            self._set_notice(f"Feed hold failed — {exc}")

    @Slot()
    def resume(self) -> None:
        try:
            self._send_realtime(REALTIME_RESUME)
        except RuntimeError as exc:
            self._set_notice(f"Resume failed — {exc}")

    @Slot()
    def close(self) -> None:
        self.disconnect()

    def _refresh_ports(self) -> None:
        self._ports = [f"{device} — {description}" for device, description in available_ports()]
        if self._ports and not self.port:
            self.port = self._ports[0]
        self.ports_changed.emit()

    def _poll(self) -> None:
        self._poll_wifi_result()
        if self.connection is None:
            return
        try:
            while not self.connection.events.empty():
                self._handle_event(self.connection.events.get_nowait())
            now = time.monotonic()
            if self.connected and now - self._last_status_poll >= 0.5:
                self._send_realtime(REALTIME_STATUS)
                self._last_status_poll = now
        except RuntimeError as exc:
            self._disconnected(str(exc))

    def _poll_wifi_result(self) -> None:
        try:
            connection, result, port = self._wifi_results.get_nowait()
        except queue.Empty:
            return
        self._wifi_connecting = False
        if connection is None:
            self._connection_text = f"Wi-Fi connection failed: {result}"
            self._set_notice(self._connection_text)
            self._emit_state()
            return
        self.connection = connection
        self.wifi_host = result
        self.wifi_port = port
        try:
            self.connection_store.save(ConnectionSettings(result, port, "Wi-Fi TCP"))
        except (OSError, ValueError):
            pass
        self._connection_text = f"Connected to {result}:{port} over Wi-Fi"
        self._set_notice(self._connection_text)
        self._emit_state()

    def _handle_event(self, event: SerialEvent) -> None:
        self._append_log(event)
        if event.kind == "error":
            self._disconnected(f"Connection error: {event.text}")
            return
        if event.kind != "rx":
            return
        text = event.text.strip()
        lowered = text.lower()
        if self._handle_wifi_setup_response(text):
            return
        setting = parse_setting(text)
        if setting is not None:
            self._commissioning_settings[setting[0]] = setting[1]
            self._emit_state()
        if self._pending_manual_acks and (lowered == "ok" or lowered.startswith("error:") or lowered.startswith("alarm:")):
            self._pending_manual_acks -= 1
            if lowered == "ok" and self._position_move_active:
                self._send_next_position_move()
            elif lowered == "ok" and self._live_jog_axis is not None:
                self._send_next_live_jog()
            elif lowered == "ok" and self._live_jog_alignment_pending:
                self._clear_live_jog()
                self._set_notice("Live jog stopped at a whole millimeter")
            elif lowered != "ok" and self._position_move_active:
                self._position_queue = []
                self._position_move_active = False
                self._set_notice(f"Position move stopped — GRBL replied: {text}")
            elif lowered != "ok" and self._live_jog_axis is not None:
                self._clear_live_jog()
                self._set_notice(f"Live jog stopped — GRBL replied: {text}")
            elif lowered != "ok" and self._live_jog_alignment_pending:
                self._clear_live_jog()
                self._set_notice(f"Whole-millimeter stop correction rejected — {text}")
        elif self.job.handle_response(text):
            if self.job.state == "complete":
                self._return_after_job_pending = True
                try:
                    self._send_manual(b"M5\n")
                except RuntimeError:
                    self._return_after_job_pending = False
        status = parse_status(text)
        if status is not None:
            self.status = status
            self.session.update_status(status)
            self._update_commissioning(status)
            if self._return_after_job_pending and status.can_jog and not self._pending_manual_acks:
                self._return_after_job_pending = False
                self.return_to_work_zero()
            if self._live_jog_stop_pending and status.can_jog and not self._pending_manual_acks:
                self._finish_live_jog_stop()
            if self._close_after_return_pending and self.at_reference:
                self._close_after_return_pending = False
                self.close_requested.emit()
            self._project_status(status)
        if text.startswith("Grbl ") or "[MSG:Reset" in text:
            if self.job.state in {"running", "paused"}:
                self.job.abort("Controller reset")
            self._pending_manual_acks = 0
            self._position_queue = []
            self._position_move_active = False
            if self._preserve_references_on_next_reset:
                self._preserve_references_on_next_reset = False
            else:
                self.session.invalidate_reference("GRBL reset")
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
        if work is None and status.machine_position and self.session.work_offset:
            work = status.machine_position.minus(self.session.work_offset)
        self._work_position_text = self._format_position(work)
        self._reference_text = "Trusted" if self.session.envelope.trusted else "Position unknown"
        self._work_zero_text = "Confirmed" if self.session.work_zero_confirmed else "Not confirmed"
        self._emit_state()

    def _update_commissioning(self, status: GrblStatus) -> None:
        pins = status.pins or ""
        self._commissioning_pins_text = f"Active inputs: {pins}" if pins else "Active inputs: none"
        tracker = self._commissioning_tracker
        if tracker.target is None or tracker.state not in {"awaiting_press", "awaiting_release"}:
            return
        result = tracker.update(pins)
        self._commissioning_status_text = result.message
        if result.passed:
            attribute = "probe_tested" if tracker.target == "P" else f"{tracker.target.lower()}_limit_tested"
            setattr(self.commissioning_profile, attribute, True)
            self._save_commissioning_profile()
        self._emit_state()

    def _save_commissioning_profile(self) -> None:
        try:
            self.commissioning_store.save(self.commissioning_profile)
        except (OSError, ValueError) as exc:
            raise ValueError(str(exc)) from exc

    def _send_next_wifi_setup_command(self) -> None:
        if not self._wifi_setup_commands or self.connection is None:
            return
        if self._wifi_setup_index >= len(self._wifi_setup_commands):
            self._wifi_setup_commands = []
            self._set_notice("Controller Wi-Fi configuration sent; reconnect over Wi-Fi after the restart")
            return
        command, display_text = self._wifi_setup_commands[self._wifi_setup_index]
        try:
            self.connection.send_line(command, display_text=display_text)
        except RuntimeError as exc:
            self._wifi_setup_commands = []
            self._wifi_setup_waiting = False
            self._set_notice(f"Wi-Fi setup interrupted — {exc}")
            return
        self._wifi_setup_waiting = not command.startswith(b"[ESP444]")
        self._wifi_setup_index += 1
        if not self._wifi_setup_waiting:
            QTimer.singleShot(8000, self._send_next_wifi_setup_command)

    def _handle_wifi_setup_response(self, response: str) -> bool:
        if not self._wifi_setup_waiting:
            return False
        lowered = response.lower()
        if lowered == "ok":
            self._wifi_setup_waiting = False
            QTimer.singleShot(100, self._send_next_wifi_setup_command)
            return True
        if lowered.startswith("error:") or lowered.startswith("alarm:"):
            self._wifi_setup_commands = []
            self._wifi_setup_waiting = False
            self._set_notice(f"Controller rejected Wi-Fi configuration: {response}")
            return True
        return False

    def _send_manual(self, command: bytes) -> None:
        if self.connection is None:
            raise RuntimeError("Not connected")
        self.connection.send_line(command)
        self._pending_manual_acks += 1

    def _send_next_live_jog(self) -> None:
        if self._live_jog_axis is None or self._live_jog_stop_pending or self._live_jog_alignment_pending:
            return
        axis = self._live_jog_axis
        distance = self._live_jog_first_distance
        if distance is None:
            distance = self._live_jog_direction
        else:
            self._live_jog_first_distance = None
        current = self._live_jog_position
        if current is None:
            self._clear_live_jog()
            return
        proposed = self._position_with_axis_delta(current, axis, distance)
        if self.session.envelope.trusted:
            maximum = self.session.profile.travel_for(axis)
            proposed_value = getattr(proposed, axis.lower())
            if proposed_value < -0.001 or proposed_value > maximum + 0.001:
                self._clear_live_jog()
                self._set_notice(f"Live jog stopped at the {axis} travel limit")
                return
        try:
            self._send_manual(make_jog(axis, distance, 500.0))
        except (RuntimeError, ValueError) as exc:
            self._clear_live_jog()
            self._set_notice(f"Live jog stopped — {exc}")
            return
        self._live_jog_position = proposed

    def _finish_live_jog_stop(self) -> None:
        if not self._live_jog_stop_pending or self._pending_manual_acks:
            return
        position = self.session.virtual_position if self.session.envelope.trusted else self.session.machine_position
        if position is None:
            self._clear_live_jog()
            self._set_notice("Live jog stopped; final position was unavailable")
            return
        axis = self._live_jog_axis_last or "X"
        current = getattr(position, axis.lower())
        target = math.floor(current + 0.5)
        distance = target - current
        if abs(distance) <= 0.001:
            self._clear_live_jog()
            self._set_notice("Live jog stopped at a whole millimeter")
            return
        if self.session.envelope.trusted:
            maximum = self.session.profile.travel_for(axis)
            if target < -0.001 or target > maximum + 0.001:
                self._clear_live_jog()
                self._set_notice("Live jog stopped; nearest whole-millimeter position is outside the travel envelope")
                return
        try:
            self._send_manual(make_jog(axis, distance, 500.0))
        except (RuntimeError, ValueError) as exc:
            self._clear_live_jog()
            self._set_notice(f"Whole-millimeter stop correction failed — {exc}")
            return
        self._live_jog_stop_pending = False
        self._live_jog_alignment_pending = True

    def _clear_live_jog(self) -> None:
        if self._live_jog_axis is not None:
            self._live_jog_axis_last = self._live_jog_axis
        self._live_jog_axis = None
        self._live_jog_direction = 0.0
        self._live_jog_first_distance = None
        self._live_jog_position = None
        self._live_jog_stop_pending = False
        self._live_jog_alignment_pending = False

    @staticmethod
    def _position_with_axis_delta(position: Position, axis: str, distance: float) -> Position:
        values = {"X": position.x, "Y": position.y, "Z": position.z}
        values[axis] += distance
        return Position(values["X"], values["Y"], values["Z"])

    def _send_realtime(self, command: bytes) -> None:
        if self.connection is None:
            raise RuntimeError("Not connected")
        self.connection.send_realtime(command)

    def _send_job_line(self, command: bytes) -> None:
        if self.connection is None:
            raise RuntimeError("Not connected")
        self.connection.send_line(command)

    def _send_next_position_move(self) -> None:
        if not self._position_move_active or self._pending_manual_acks:
            return
        if not self._position_queue:
            self._position_move_active = False
            self._set_notice("Position move complete")
            if self._close_after_return_pending and self.at_reference:
                self._close_after_return_pending = False
                self.close_requested.emit()
            self._emit_state()
            return
        axis, distance, feed = self._position_queue.pop(0)
        try:
            self._send_manual(make_jog(axis, distance, feed))
        except (RuntimeError, ValueError) as exc:
            self._position_queue = []
            self._position_move_active = False
            self._set_notice(f"Position move stopped — {exc}")
            self._emit_state()

    def _job_fit(self, program: GCodeProgram) -> tuple[bool, str]:
        if not self.session.envelope.trusted or self.session.envelope.reference is None:
            return False, "Establish the manual machine reference first."
        if self.session.work_offset is None:
            return False, "A fresh GRBL work-offset report is required."
        return check_job_bounds(
            program.bounds.minimum,
            program.bounds.maximum,
            self.session.work_offset,
            self.session.envelope.reference,
            self.session.profile,
        )

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
    def _step_job_summary(job) -> str:
        points = [point for stroke in job.strokes for point in stroke]
        min_x = min(point[0] for point in points)
        min_y = min(point[1] for point in points)
        max_x = max(point[0] for point in points)
        max_y = max(point[1] for point in points)
        return (
            f"STEP {job.mode} · stock {job.stock_width:.1f} × {job.stock_height:.1f} mm · "
            f"tool {job.tool_diameter:.2f} mm · depth {job.depth:.2f} mm · {job.passes} passes · "
            f"{job.stroke_count} paths · bounds X {min_x:.1f}…{max_x:.1f}, Y {min_y:.1f}…{max_y:.1f} mm"
        )

    def _disconnected(self, reason: str) -> None:
        self.session.invalidate_reference(reason)
        self.status = None
        self._clear_live_jog()
        self._pending_manual_acks = 0
        self._position_queue = []
        self._position_move_active = False
        self._return_after_job_pending = False
        self._close_after_return_pending = False
        self._unreferenced_jog_allowed = False
        self._preserve_references_on_next_reset = False
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

    def _append_log(self, event: SerialEvent) -> None:
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
