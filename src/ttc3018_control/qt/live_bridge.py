"""Qt-main-thread bridge for authenticated Pine Live command intents."""

from __future__ import annotations

from threading import Event, Lock
import time

from PySide6.QtCore import QObject, Signal, Slot

from ..application.controller import ApplicationController
from ..live.commands import RemoteCommand, RemoteCommandResult


class RemoteCommandBridge(QObject):
    """Accept requests from an HTTP worker and execute them in Qt's thread."""

    command_requested = Signal(object)

    def __init__(self, controller: ApplicationController, *, audit=None) -> None:
        super().__init__()
        self.controller = controller
        self._audit = audit or (lambda _text: None)
        self._pending: dict[str, tuple[Event, list[RemoteCommandResult]]] = {}
        self._lock = Lock()
        self._closed = False
        self.command_requested.connect(self._execute)

    def submit(self, command: RemoteCommand) -> RemoteCommandResult:
        """Thread-safe HTTP-facing method; wait only for a bounded result."""
        event = Event()
        result_box: list[RemoteCommandResult] = []
        with self._lock:
            if self._closed:
                return RemoteCommandResult(False, command.action, "Pine is shutting down", command.request_id, 503)
            self._pending[command.request_id] = (event, result_box)
        self.command_requested.emit(command)
        if not event.wait(3.0):
            with self._lock:
                self._pending.pop(command.request_id, None)
            return RemoteCommandResult(False, command.action, "Pine did not respond in time", command.request_id, 503)
        return result_box[0]

    @Slot(object)
    def _execute(self, command: RemoteCommand) -> None:
        result = self._execute_now(command)
        with self._lock:
            pending = self._pending.pop(command.request_id, None)
        if pending is not None:
            event, result_box = pending
            result_box.append(result)
            event.set()

    def _execute_now(self, command: RemoteCommand) -> RemoteCommandResult:
        if self._closed:
            return RemoteCommandResult(False, command.action, "Pine is shutting down", command.request_id, 503)
        if time.monotonic() - command.created_at > 30:
            return RemoteCommandResult(False, command.action, "Command expired", command.request_id, 409)
        if command.job_nonce != self.controller.job_nonce:
            return RemoteCommandResult(False, command.action, "The job is no longer current", command.request_id, 409)
        if command.action == "pause":
            if self.controller.job_state not in {"running", "draining"}:
                return RemoteCommandResult(False, command.action, "Pause is available only while the job is running", command.request_id, 409)
            outcome = self.controller.pause_job()
        elif command.action == "resume":
            if self.controller.job_state != "paused":
                return RemoteCommandResult(False, command.action, "Resume is available only while the job is paused", command.request_id, 409)
            outcome = self.controller.resume_job()
        elif command.action == "abort":
            if self.controller.job_state not in {"running", "draining", "paused"}:
                return RemoteCommandResult(False, command.action, "Abort is available only while a job is active", command.request_id, 409)
            self.controller.abort_job("Aborted from Pine Live")
            outcome = type("Outcome", (), {"accepted": True, "message": "Job abort requested"})()
        else:
            return RemoteCommandResult(False, command.action, "Remote action is not supported", command.request_id, 400)
        self._audit(f"Pine Live {command.action}: {'accepted' if outcome.accepted else 'rejected'}")
        return RemoteCommandResult(outcome.accepted, command.action, outcome.message, command.request_id, 200 if outcome.accepted else 409)

    def close(self) -> None:
        with self._lock:
            self._closed = True
            pending = tuple(self._pending.values())
            self._pending.clear()
        result = RemoteCommandResult(False, "unknown", "Pine is shutting down", "", 503)
        for event, result_box in pending:
            result_box.append(result)
            event.set()
