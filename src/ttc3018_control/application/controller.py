"""Composition root for the Qt-independent TTC 3018 application layer."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from ..connection_settings import ConnectionSettings, ConnectionSettingsStore
from ..grbl import GrblStatus, Position, REALTIME_JOG_CANCEL, make_work_zero
from ..machine_state import MachineProfile, ProfileStore
from ..serial_connection import GrblConnection
from ..tcp_connection import TcpGrblConnection
from ..wifi_discovery import discover_grbl_hosts
from .connection_service import ConnectionOutcome, ConnectionService
from .generation_service import GenerationService
from .job_service import JobService
from .machine_session import ActionOutcome, MachineSession
from .motion_service import MotionService


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
    ) -> None:
        self.profile_store = ProfileStore(root / "config" / "machine-profile.json")
        self.connection_store = ConnectionSettingsStore(root / "config" / "connection.json")
        try:
            profile = self.profile_store.load()
        except (OSError, ValueError, TypeError):
            profile = MachineProfile()
        try:
            settings = self.connection_store.load()
        except (OSError, ValueError, TypeError):
            settings = ConnectionSettings()

        self.session = MachineSession(profile=profile)
        self.settings = settings
        self.status: GrblStatus | None = None
        self.manual_pending_acks = 0
        self.connection_service = ConnectionService(GrblConnection, TcpGrblConnection, discover_grbl_hosts)
        self.generation_service = GenerationService()
        self.motion = MotionService(
            self.session,
            self.connection_service.send_line,
            self.connection_service.send_realtime,
            on_notice=on_notice,
            on_change=on_change,
            on_position_complete=on_position_complete,
        )
        self.job = JobService(
            self.session,
            self.connection_service.send_line,
            self.connection_service.send_realtime,
            on_notice=on_notice,
            on_change=on_change,
            on_ready_to_return=on_ready_to_return,
        )

    @property
    def connected(self) -> bool:
        return self.connection_service.connected

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

    def disconnect(self) -> ConnectionOutcome:
        outcome = self.connection_service.disconnect()
        self.motion.reset()
        self.job.reset()
        self.manual_pending_acks = 0
        return outcome

    def establish_reference(self) -> ActionOutcome:
        return self.session.establish_reference()

    def invalidate_reference(self, reason: str = "Manually invalidated") -> None:
        self.session.invalidate_reference(reason)

    def jog(self, axis: str, distance: float, feed: float = 500.0) -> ActionOutcome:
        return self.motion.jog(axis, distance, feed)

    def start_live_jog(self, axis: str, direction: float, allow_unreferenced: bool, feed: float = 500.0) -> ActionOutcome:
        return self.motion.start_live_jog(axis, direction, allow_unreferenced, feed)

    def stop_live_jog(self) -> ActionOutcome:
        return self.motion.stop_live_jog()

    def cancel_jog(self) -> None:
        self.motion.cancel()
        self.send_realtime(REALTIME_JOG_CANCEL)

    def move_to(self, target: Position, feed: float = 500.0) -> ActionOutcome:
        return self.motion.move_to(target, feed)

    def return_to_reference(self, feed: float = 500.0) -> ActionOutcome:
        return self.motion.return_to_reference(feed)

    def return_to_work_zero(self, feed: float = 500.0) -> ActionOutcome:
        return self.motion.return_to_work_zero(feed)

    def set_work_zero(self, axes: str) -> ActionOutcome:
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
        return outcome

    def close(self) -> None:
        self.connection_service.disconnect()
        self.motion.reset()
        self.job.reset()
        self.manual_pending_acks = 0

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
        self.session.update_status(status)
        self.job.observe_status(status)
        self.motion.observe_status(status)

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

    def reset(self) -> None:
        self.manual_pending_acks = 0
        self.motion.reset()
        self.job.reset()
