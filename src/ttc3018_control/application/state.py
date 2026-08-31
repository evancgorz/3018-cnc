"""Qt-independent snapshots shared by application adapters."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ..grbl import GrblStatus, Position
from ..machine_state import MachineProfile


class ConnectionMode(str, Enum):
    USB = "USB serial"
    WIFI = "Wi-Fi TCP"


@dataclass(frozen=True)
class JobSnapshot:
    state: str = "idle"
    completed: int = 0
    total: int = 0
    error: str = ""

    @property
    def progress(self) -> float:
        return self.completed / self.total if self.total else 0.0


@dataclass(frozen=True)
class ProgramSnapshot:
    path: str = ""
    command_count: int = 0
    minimum: Position | None = None
    maximum: Position | None = None
    estimated_seconds: float = 0.0


@dataclass(frozen=True)
class ApplicationState:
    """Authoritative, presentation-neutral state for one controller session."""

    connection_mode: ConnectionMode = ConnectionMode.USB
    connected: bool = False
    status: GrblStatus | None = None
    machine_position: Position | None = None
    work_position: Position | None = None
    virtual_position: Position | None = None
    reference_trusted: bool = False
    work_zero_confirmed: bool = False
    profile: MachineProfile = MachineProfile()
    unreferenced_jog_allowed: bool = False
    program: ProgramSnapshot | None = None
    job: JobSnapshot = JobSnapshot()
    active_operation: str = ""

