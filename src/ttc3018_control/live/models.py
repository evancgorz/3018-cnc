"""Small immutable models shared by the LAN viewer and application adapter."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any


def _position(value: Any) -> str | None:
    if value is None:
        return None
    return "X{:.3f} Y{:.3f} Z{:.3f}".format(value.x, value.y, value.z)


@dataclass(frozen=True)
class LiveStatusSnapshot:
    """Sanitized status; never put controller objects or filesystem paths here."""

    schema_version: int = 1
    sequence: int = 0
    timestamp: str = ""
    connected: bool = False
    grbl_state: str = "Unknown"
    job_state: str = "idle"
    job_name: str = ""
    job_nonce: str = ""
    progress: int = 0
    elapsed_seconds: float = 0.0
    remaining_seconds: float | None = None
    estimated_seconds: float = 0.0
    machine_position: str = "—"
    work_position: str = "—"
    reference_trusted: bool = False
    work_zero_confirmed: bool = False
    spindle: str = "Off"
    feed: str = "0"
    can_pause: bool = False
    can_resume: bool = False
    can_abort: bool = False
    camera_state: str = "off"
    remote_state: str = "off"

    @classmethod
    def from_application(cls, controller: Any, *, sequence: int, camera_state: str = "off", remote_state: str = "off") -> "LiveStatusSnapshot":
        state = controller.state
        status = state.status
        program = state.program
        job = state.job
        job_state = job.state
        return cls(
            sequence=sequence,
            timestamp=datetime.now(timezone.utc).isoformat(),
            connected=state.connected,
            grbl_state=status.state if status else "Unknown",
            job_state=job_state,
            job_name=(program.path.rsplit("\\", 1)[-1].rsplit("/", 1)[-1] if program else ""),
            progress=round(job.progress * 100),
            elapsed_seconds=controller.job_elapsed_seconds,
            remaining_seconds=controller.job_remaining_seconds,
            estimated_seconds=controller.job_estimated_seconds,
            machine_position=_position(state.machine_position) or "—",
            work_position=_position(state.work_position) or "—",
            reference_trusted=state.reference_trusted,
            work_zero_confirmed=state.work_zero_confirmed,
            spindle=(f"{status.spindle:g} RPM" if status and status.spindle is not None else "Off"),
            feed=(f"{status.feed:g}" if status and status.feed is not None else "0"),
            can_pause=job_state in {"running", "draining"} and state.connected,
            can_resume=job_state == "paused" and state.connected,
            can_abort=job_state in {"running", "draining", "paused"} and state.connected,
            camera_state=camera_state,
            remote_state=remote_state,
        )

    def as_json(self) -> dict[str, Any]:
        return asdict(self)
