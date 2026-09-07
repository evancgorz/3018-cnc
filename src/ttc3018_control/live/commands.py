"""Remote command value objects and an exactly-once in-memory command ledger."""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Callable


@dataclass(frozen=True)
class RemoteCommand:
    request_id: str
    session_id: str
    action: str
    job_nonce: str
    created_at: float
    confirmation: str = ""


@dataclass(frozen=True)
class RemoteCommandResult:
    accepted: bool
    action: str
    message: str
    request_id: str
    status_code: int = 200

    def as_json(self) -> dict[str, object]:
        return {
            "accepted": self.accepted,
            "action": self.action,
            "message": self.message,
            "request_id": self.request_id,
        }


class CommandLedger:
    """Reject stale/duplicate requests before the Qt bridge sees them."""

    def __init__(self, submit: Callable[[RemoteCommand], RemoteCommandResult], *, clock: Callable[[], float] | None = None) -> None:
        self._submit = submit
        self._clock = clock or time.monotonic
        self._results: dict[tuple[str, str], RemoteCommandResult] = {}

    def submit(self, command: RemoteCommand) -> RemoteCommandResult:
        key = (command.session_id, command.request_id)
        previous = self._results.get(key)
        if previous is not None:
            return previous
        if self._clock() - command.created_at > 30:
            result = RemoteCommandResult(False, command.action, "Command expired", command.request_id, 409)
        else:
            result = self._submit(command)
        self._results[key] = result
        if len(self._results) > 512:
            self._results.pop(next(iter(self._results)))
        return result
