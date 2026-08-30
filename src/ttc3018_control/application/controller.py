"""Composition root for the Qt-independent TTC 3018 application layer."""

from __future__ import annotations

from pathlib import Path
import queue
import time
from typing import Callable, Iterable

from ..connection_settings import ConnectionSettings, ConnectionSettingsStore
from ..grbl import GrblStatus, Position, REALTIME_HOLD, REALTIME_JOG_CANCEL, REALTIME_SOFT_RESET, REALTIME_STATUS, make_work_zero, parse_status
from ..machine_state import MachineProfile, ProfileStore
from ..work_zero_settings import SavedWorkZero, WorkZeroStore
from ..serial_connection import GrblConnection, available_ports
from ..step_prepare_settings import StepPrepareSettings, StepPrepareSettingsStore
from ..tcp_connection import TcpGrblConnection
from ..wifi_discovery import discover_grbl_hosts
from .connection_service import ConnectionOutcome, ConnectionService
from .events import ApplicationEvent, LogEvent, NoticeEvent
from .generation_service import GenerationService
from .job_service import JobService
from .machine_session import ActionOutcome, MachineSession
from .motion_service import MotionService
from .ports import ConnectionSettingsStorePort, ProfileStorePort, StepPrepareSettingsStorePort, WorkZeroStorePort
from .state import ApplicationState, ConnectionMode, JobSnapshot, ProgramSnapshot
from .wifi_service import WifiProvisioningService


class ApplicationController:
    """Compose application services without importing Qt or presenting UI."""

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
    ) -> None:
        self.profile_store = profile_store or ProfileStore(root / "config" / "machine-profile.json")
        self.connection_store = connection_store or ConnectionSettingsStore(root / "config" / "connection.json")
        self.work_zero_store = work_zero_store or WorkZeroStore(root / "config" / "work-zero.json")
        self.step_prepare_store = step_prepare_store or StepPrepareSettingsStore(
            root / "config" / "step-prepare.json"
        )
        try:
            profile = self.profile_store.load()
        except (OSError, ValueError, TypeError):
            profile = MachineProfile()
        try:
            settings = self.connection_store.load()
        except (OSError, ValueError, TypeError):
            settings = ConnectionSettings()
        try:
            saved_work_zero = self.work_zero_store.load()
        except (OSError, ValueError, TypeError):
            saved_work_zero = None
        try:
            step_prepare_settings = self.step_prepare_store.load()
        except (OSError, ValueError, TypeError):
            step_prepare_settings = StepPrepareSettings()

        self.session = MachineSession(profile=profile)
        self.settings = settings
        self._saved_work_zero = saved_work_zero
        self.step_prepare_settings = step_prepare_settings
        self.status: GrblStatus | None = None
        self.manual_pending_acks = 0
        self._events: queue.Queue[ApplicationEvent] = queue.Queue()
        self._on_notice = on_notice
        self._on_change = on_change or (lambda: None)
        self._preserve_reference_on_next_reset = False
        self._usb_ports = usb_ports or available_ports
        self.connection_service = ConnectionService(
            usb_factory or GrblConnection,
            wifi_factory or TcpGrblConnection,
            discover_hosts or discover_grbl_hosts,
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
            )
        streamer = self.job.streamer
        return ApplicationState(
            connection_mode=ConnectionMode.WIFI if self.connection_service.mode is ConnectionMode.WIFI else ConnectionMode.USB,
            connected=self.connected,
            status=status,
            machine_position=machine_position,
            work_position=work_position,
            virtual_position=self.session.virtual_position,
            reference_trusted=self.reference_trusted,
            work_zero_confirmed=self.work_zero_confirmed,
            profile=self.profile,
            program=program_snapshot,
            job=JobSnapshot(streamer.state, streamer.completed, streamer.total, streamer.error),
        )

    @property
    def profile(self) -> MachineProfile:
        return self.session.profile

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
    def motion_busy(self) -> bool:
        return self.motion.busy

    @property
    def live_jog_active(self) -> bool:
        return bool(self.motion.live_jog_axis or self.motion.live_jog_stop_pending or self.motion.live_jog_alignment_pending)

    @property
    def job_active(self) -> bool:
        return self.job.active

    @property
    def job_state(self) -> str:
        return self.job.state

    @property
    def job_progress(self) -> float:
        return self.job.progress

    @property
    def can_jog(self) -> bool:
        return bool(self.connected and self.session.can_move and not self.job_active and not self.manual_pending_acks and not self.motion_busy)

    @property
    def can_live_jog(self) -> bool:
        controller_accepts_live_jog = self.session.can_move or bool(
            self.motion.live_jog_axis is not None
            and self.status is not None
            and self.status.state == "Jog"
        )
        return bool(
            self.connected
            and controller_accepts_live_jog
            and not self.job_active
            and not self.motion.position_move_active
            and not self.motion.live_jog_stop_pending
            and not self.motion.live_jog_alignment_pending
            and (not self.motion.pending_acks or self.motion.live_jog_axis is not None)
        )

    @property
    def can_return_to_reference(self) -> bool:
        return bool(self.connected and self.reference_trusted and self.session.can_move and not self.job_active and not self.manual_pending_acks and not self.motion_busy)

    @property
    def can_start_job(self) -> bool:
        return bool(
            self.connected
            and self.session.can_move
            and self.work_zero_confirmed
            and not self.manual_pending_acks
            and not self.motion_busy
            and not self.job_active
            and not self.job.restart_requires_reload
            and self.program
            and self.preflight()[0]
        )

    @property
    def transport(self):
        return self.connection_service.transport

    def connect_usb(self, port: str) -> ConnectionOutcome:
        return self.connection_service.connect_usb(port)

    def begin_wifi(self, host: str, port: int) -> ConnectionOutcome:
        return self.connection_service.begin_wifi(host, port)

    def poll_wifi(self) -> ConnectionOutcome | None:
        return self.connection_service.poll_wifi()

    def transport_events(self):
        return self.connection_service.events()

    def usb_ports(self) -> list[tuple[str, str]]:
        """Return currently enumerated USB serial endpoints for the adapter."""
        return self._usb_ports()

    def set_transport_for_testing(self, transport) -> None:
        """Inject a fake transport without exposing service internals to Qt tests."""
        self.connection_service.transport = transport

    @property
    def program(self):
        return self.job.program

    def load_program(self, path: Path):
        return self.job.load_program(path)

    def load_generated(self, gcode: str, filename: str):
        return self.job.load_generated(gcode, filename)

    def preflight(self) -> tuple[bool, str]:
        return self.job.preflight()

    def start_job(self) -> ActionOutcome:
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

    def pause_job(self) -> ActionOutcome:
        return self.job.pause()

    def resume_job(self) -> ActionOutcome:
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
        self.motion.reset()
        self.manual_pending_acks = 0

    def _motion_operation_allowed(self) -> ActionOutcome:
        if not self.connected:
            return ActionOutcome(False, "Motion command ignored — not connected")
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

    def generate_text(self, *args, **kwargs):
        return self.generation_service.text(*args, **kwargs)

    def generate_plaque(self, *args, **kwargs):
        return self.generation_service.plaque(*args, **kwargs)

    def generate_step(self, *args, **kwargs):
        return self.generation_service.step(*args, **kwargs)

    def import_step(self, path, plane: str | None = None):
        return self.generation_service.import_step(path, plane)

    def save_wifi_settings(self, host: str, port: int) -> None:
        self.settings = ConnectionSettings(host, port, "Wi-Fi TCP")
        self.connection_store.save(self.settings)

    def save_profile(self, profile: MachineProfile) -> None:
        profile.validate()
        self.profile_store.save(profile)
        self.session.profile = profile

    def save_step_prepare_settings(self, settings: StepPrepareSettings) -> None:
        settings.validate()
        self.step_prepare_store.save(settings)
        self.step_prepare_settings = settings

    def invalidate_machine_reference(self, reason: str = "Manually invalidated") -> None:
        self.session.invalidate_reference(reason)

    def disconnect(self, reason: str | None = None) -> ConnectionOutcome:
        self.wifi_setup.cancel()
        outcome = self.connection_service.disconnect()
        self.motion.reset()
        self.job.reset()
        self.manual_pending_acks = 0
        self._preserve_reference_on_next_reset = False
        self.status = None
        self.session.clear_status()
        self.session.invalidate_reference(reason or outcome.message)
        return outcome

    def establish_reference(self) -> ActionOutcome:
        return self.session.establish_reference()

    def invalidate_reference(self, reason: str = "Manually invalidated") -> None:
        self.session.invalidate_reference(reason)

    def jog(self, axis: str, distance: float, feed: float = 500.0) -> ActionOutcome:
        blocked = self._motion_operation_allowed()
        if not blocked.accepted:
            return blocked
        return self.motion.jog(axis, distance, feed)

    def start_live_jog(self, axis: str, direction: float, allow_unreferenced: bool, feed: float = 500.0) -> ActionOutcome:
        blocked = self._motion_operation_allowed()
        if not blocked.accepted:
            return blocked
        return self.motion.start_live_jog(axis, direction, allow_unreferenced, feed)

    def stop_live_jog(self) -> ActionOutcome:
        return self.motion.stop_live_jog()

    def cancel_jog(self) -> None:
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
        return self.motion.return_to_work_zero(feed)

    def set_work_zero(self, axes: str) -> ActionOutcome:
        if not self.connected:
            return ActionOutcome(False, "Work-zero command ignored — not connected")
        if self.job_active:
            return ActionOutcome(False, "Work-zero command ignored — a job is active")
        if self.motion_busy or self.manual_pending_acks:
            return ActionOutcome(False, "Work-zero command ignored — another machine operation is active")
        if not self.session.can_move:
            return ActionOutcome(False, "Work-zero command ignored — GRBL is not Idle")
        outcome = self.session.request_work_zero_confirmation(axes)
        if not outcome.accepted:
            return outcome
        try:
            self.send_manual(make_work_zero(axes))
        except (RuntimeError, ValueError) as exc:
            self.session.invalidate_work_zero()
            return ActionOutcome(False, f"Work zero not sent — {exc}")
        self._clear_saved_work_zero()
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
        try:
            self.send_realtime(b"~")
        except RuntimeError as exc:
            return ActionOutcome(False, f"Resume failed — {exc}")
        return ActionOutcome(True, "Resume requested")

    def close(self) -> None:
        self.wifi_setup.cancel()
        outcome = self.connection_service.close()
        self.motion.reset()
        self.job.reset()
        self.manual_pending_acks = 0
        self._preserve_reference_on_next_reset = False
        self.status = None
        self.session.clear_status()
        self.session.invalidate_reference(outcome.message)

    def send_manual(self, command: bytes) -> None:
        self.connection_service.send_line(command)
        self.manual_pending_acks += 1

    def send_line(self, command: bytes, display_text: str | None = None) -> None:
        """Send an application-approved line through the single transport owner."""
        self.connection_service.send_line(command, display_text=display_text)

    def send_realtime(self, command: bytes) -> None:
        self.connection_service.send_realtime(command)

    def apply_status(self, status: GrblStatus) -> None:
        self.status = status
        awaiting_confirmation = self.session.awaiting_work_zero_report
        self.session.update_status(status)
        if status.work_offset is not None:
            if awaiting_confirmation and self.session.work_zero_confirmed:
                self._save_work_zero(status.work_offset)
            elif not self.session.work_zero_confirmed and self._saved_work_zero is not None:
                saved = self._saved_work_zero.position
                if all(
                    abs(actual - expected) <= 0.001
                    for actual, expected in zip(
                        (status.work_offset.x, status.work_offset.y, status.work_offset.z),
                        (saved.x, saved.y, saved.z),
                    )
                ):
                    self.session.work_zero_confirmed = True
        self.job.observe_status(status)
        self.motion.observe_status(status)

    def _save_work_zero(self, offset: Position) -> None:
        saved = SavedWorkZero.from_position(offset)
        try:
            self.work_zero_store.save(saved)
        except OSError:
            self._publish_notice("Work zero confirmed, but it could not be saved for the next session")
            return
        self._saved_work_zero = saved

    def _clear_saved_work_zero(self) -> None:
        self._saved_work_zero = None
        try:
            self.work_zero_store.clear()
        except OSError:
            self._publish_notice("Previous saved work zero could not be removed")

    def handle_response(self, response: str, feed: float = 500.0) -> bool:
        """Dispatch one controller response to the owning application service."""
        text = response.strip()
        lowered = text.lower()
        if self.motion.handle_response(text, feed):
            return True
        if self.manual_pending_acks and (lowered == "ok" or lowered.startswith("error:") or lowered.startswith("alarm:")):
            self.manual_pending_acks -= 1
            return True
        return self.job.handle_response(text)

    def reset(self, preserve_reference: bool = False) -> None:
        preserve_reference = preserve_reference or self._preserve_reference_on_next_reset
        self._preserve_reference_on_next_reset = False
        self.manual_pending_acks = 0
        self.motion.reset()
        self.job.reset()
        self.status = None
        self.session.clear_status(retain_work_zero=preserve_reference)
        if not preserve_reference:
            self.session.invalidate_reference("GRBL reset")

    def handle_transport_response(self, response: str, feed: float = 500.0, preserve_reference: bool = False) -> tuple[GrblStatus | None, bool]:
        """Dispatch one normalized transport response and apply GRBL state changes."""
        text = response.strip()
        if self.wifi_setup.handle_response(text, time.monotonic()):
            return None, False
        self.handle_response(text, feed)
        status = parse_status(text)
        if status is not None:
            self.apply_status(status)
        reset = text.startswith("Grbl ") or "[MSG:Reset" in text
        if reset:
            self.reset(preserve_reference=preserve_reference)
        return status, reset
