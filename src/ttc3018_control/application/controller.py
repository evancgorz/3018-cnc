"""Composition root for the Qt-independent TTC 3018 application layer."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from ..connection_settings import ConnectionSettings, ConnectionSettingsStore
from ..grbl import GrblStatus
from ..machine_state import MachineProfile, ProfileStore
from ..serial_connection import GrblConnection
from ..tcp_connection import TcpGrblConnection
from ..wifi_discovery import discover_grbl_hosts
from .connection_service import ConnectionService
from .generation_service import GenerationService
from .job_service import JobService
from .machine_session import MachineSession
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

    def close(self) -> None:
        self.connection_service.disconnect()
        self.motion.reset()
        self.job.reset()
        self.manual_pending_acks = 0

    def send_manual(self, command: bytes) -> None:
        self.connection_service.send_line(command)
        self.manual_pending_acks += 1

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
