"""Presentation-neutral UX state for long-running controller operations.

The coordinator deliberately sits above the controller services.  It provides
one consistent description of what the UI is doing without taking ownership of
GRBL acknowledgements or deciding that physical motion has completed.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
import time
from typing import Callable


class OperationCategory(str, Enum):
    BACKGROUND = "background"
    CONNECTION = "connection"
    MACHINE_MOTION = "machine_motion"
    JOB = "job"
    SAFETY = "safety"


class OperationState(str, Enum):
    IDLE = "idle"
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_CONTROLLER = "waiting_controller"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class OperationSnapshot:
    token: int = 0
    category: OperationCategory = OperationCategory.BACKGROUND
    name: str = ""
    phase: str = ""
    state: OperationState = OperationState.IDLE
    progress: float | None = None
    started_at: float | None = None
    cancellable: bool = False
    blocking_scopes: frozenset[str] = frozenset()
    summary: str = ""
    error: str = ""
    recovery_action: str = ""

    @property
    def active(self) -> bool:
        return self.state in {
            OperationState.QUEUED,
            OperationState.RUNNING,
            OperationState.WAITING_CONTROLLER,
        }

    @property
    def elapsed_seconds(self) -> float:
        if self.started_at is None:
            return 0.0
        return max(0.0, time.monotonic() - self.started_at)


@dataclass(frozen=True)
class ReadinessSnapshot:
    connection: str = "required"
    reference: str = "required"
    work_zero: str = "required"
    job: str = "required"
    ready: str = "required"
    next_action: str = "Connect"
    reason: str = "Connect to the controller to begin."


@dataclass(frozen=True)
class IssueSnapshot:
    severity: str = "error"
    title: str = ""
    explanation: str = ""
    spindle_uncertain: bool = False
    reference_lost: bool = False
    work_zero_lost: bool = False
    reload_required: bool = False
    actions: tuple[str, ...] = ()


class OperationCoordinator:
    """Track UI/application operations and reject stale results safely."""

    def __init__(self, clock: Callable[[], float] | None = None) -> None:
        self._clock = clock or time.monotonic
        self._next_token = 0
        self._active: dict[str, OperationSnapshot] = {}
        self._history: list[OperationSnapshot] = []

    @property
    def active(self) -> tuple[OperationSnapshot, ...]:
        return tuple(self._active.values())

    @property
    def history(self) -> tuple[OperationSnapshot, ...]:
        return tuple(self._history)

    def begin(
        self,
        category: OperationCategory,
        name: str,
        *,
        phase: str = "Starting…",
        cancellable: bool = False,
        blocking_scopes: frozenset[str] | set[str] = frozenset(),
    ) -> OperationSnapshot:
        scopes = frozenset(blocking_scopes)
        if any(scopes.intersection(item.blocking_scopes) for item in self._active.values()):
            raise RuntimeError("An operation using one or more requested scopes is already active")
        self._next_token += 1
        snapshot = OperationSnapshot(
            token=self._next_token,
            category=category,
            name=name,
            phase=phase,
            state=OperationState.QUEUED,
            started_at=self._clock(),
            cancellable=cancellable,
            blocking_scopes=scopes,
        )
        self._active[name] = snapshot
        return snapshot

    def update(self, token: int, *, phase: str | None = None, progress: float | None = None, state: OperationState | None = None, summary: str | None = None) -> OperationSnapshot | None:
        current = self._find(token)
        if current is None or not current.active:
            return None
        if progress is not None and not 0.0 <= progress <= 1.0:
            raise ValueError("operation progress must be between 0 and 1")
        updated = replace(
            current,
            phase=current.phase if phase is None else phase,
            progress=progress if progress is not None else current.progress,
            state=state if state is not None else OperationState.RUNNING,
            summary=current.summary if summary is None else summary,
        )
        self._active[updated.name] = updated
        return updated

    def finish(self, token: int, *, success: bool, summary: str = "", error: str = "", recovery_action: str = "") -> OperationSnapshot | None:
        current = self._find(token)
        if current is None or not current.active:
            return None
        finished = replace(
            current,
            state=OperationState.SUCCEEDED if success else OperationState.FAILED,
            phase="Complete" if success else "Failed",
            progress=1.0 if success else current.progress,
            summary=summary,
            error=error,
            recovery_action=recovery_action,
        )
        self._active.pop(current.name, None)
        self._history.append(finished)
        del self._history[:-100]
        return finished

    def cancel(self, token: int, summary: str = "Cancelled") -> OperationSnapshot | None:
        current = self._find(token)
        if current is None or not current.active or not current.cancellable:
            return None
        self._active.pop(current.name, None)
        cancelled = replace(current, state=OperationState.CANCELLED, phase="Cancelled", summary=summary)
        self._history.append(cancelled)
        del self._history[:-100]
        return cancelled

    def is_current(self, token: int) -> bool:
        return self._find(token) is not None

    def _find(self, token: int) -> OperationSnapshot | None:
        return next((item for item in self._active.values() if item.token == token), None)
