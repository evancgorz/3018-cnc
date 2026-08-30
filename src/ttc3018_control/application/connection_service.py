"""Qt-independent USB and Wi-Fi transport lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
import queue
import threading
from typing import Any, Callable, Iterable

from .state import ConnectionMode


@dataclass(frozen=True)
class ConnectionOutcome:
    accepted: bool
    message: str
    mode: ConnectionMode | None = None
    host: str = ""
    port: int | None = None


@dataclass(frozen=True)
class WifiAttempt:
    attempt_id: int
    transport: Any | None
    host: str
    port: int
    error: str = ""


class ConnectionService:
    """Own exactly one active transport and all connection attempts.

    The service deliberately knows nothing about Qt. Wi-Fi discovery runs in a
    daemon worker and completion is consumed by the application poll loop.
    Concrete transports are injected so this service can be tested with fakes.
    """

    def __init__(
        self,
        usb_factory: Callable[[], Any],
        wifi_factory: Callable[[], Any],
        discover_hosts: Callable[[int], Iterable[str]],
    ) -> None:
        self._usb_factory = usb_factory
        self._wifi_factory = wifi_factory
        self._discover_hosts = discover_hosts
        self.transport: Any | None = None
        self.mode = ConnectionMode.USB
        self.endpoint = ""
        self.port = 23
        self._wifi_connecting = False
        self._wifi_attempt_id = 0
        self._wifi_results: queue.Queue[WifiAttempt] = queue.Queue()
        self._wifi_cancel_event: threading.Event | None = None
        self._wifi_worker: threading.Thread | None = None
        self._state_lock = threading.RLock()
        self._closed = False

    @property
    def connected(self) -> bool:
        with self._state_lock:
            return bool(self.transport is not None and self.transport.connected)

    @property
    def wifi_connecting(self) -> bool:
        with self._state_lock:
            return self._wifi_connecting

    def connect_usb(self, port: str) -> ConnectionOutcome:
        port = port.strip()
        if not port:
            return ConnectionOutcome(False, "Select a serial port first")
        with self._state_lock:
            if self._closed:
                return ConnectionOutcome(False, "Connection service is closed")
            if self.connected or self._wifi_connecting:
                return ConnectionOutcome(False, "Disconnect the current connection first")
            transport = None
            try:
                transport = self._usb_factory()
                transport.connect(port)
            except (OSError, ValueError, RuntimeError) as exc:
                self._safe_disconnect(transport)
                return ConnectionOutcome(False, f"Connection failed: {exc}")
            self.transport = transport
            self.mode = ConnectionMode.USB
            self.endpoint = port
        return ConnectionOutcome(True, f"Connected to {port}; waiting for GRBL status", self.mode, port)

    def begin_wifi(self, host: str, port: int) -> ConnectionOutcome:
        with self._state_lock:
            if self._closed:
                return ConnectionOutcome(False, "Connection service is closed")
            if self.connected:
                return ConnectionOutcome(False, "Disconnect the current connection first")
            if self._wifi_connecting:
                return ConnectionOutcome(False, "Wi-Fi discovery is already running")
            if not 1 <= port <= 65535:
                return ConnectionOutcome(False, "TCP port must be between 1 and 65535")
            self.mode = ConnectionMode.WIFI
            self.port = port
            self._wifi_connecting = True
            self._wifi_attempt_id += 1
            attempt_id = self._wifi_attempt_id
            cancel_event = threading.Event()
            self._wifi_cancel_event = cancel_event

        def worker() -> None:
            last_error = "No GRBL controller answered on the local network"

            def try_candidate(candidate: str) -> tuple[str, str]:
                if cancel_event.is_set():
                    return "canceled", ""
                candidate_transport = None
                try:
                    candidate_transport = self._wifi_factory()
                    candidate_transport.connect(candidate, port, timeout=1.2)
                except Exception as exc:
                    self._safe_disconnect(candidate_transport)
                    return "failed", str(exc)
                with self._state_lock:
                    canceled = (
                        cancel_event.is_set()
                        or self._closed
                        or attempt_id != self._wifi_attempt_id
                    )
                    if not canceled:
                        self._wifi_results.put(
                            WifiAttempt(attempt_id, candidate_transport, candidate, port)
                        )
                        return "connected", ""
                self._safe_disconnect(candidate_transport)
                return "canceled", ""

            try:
                # A configured endpoint is authoritative and should be tried
                # before discovery. Some controller firmware permits only one
                # TCP client; probing it first can otherwise delay or reject
                # the persistent connection that follows.
                configured_host = host.strip()
                if configured_host:
                    status, error = try_candidate(configured_host)
                    if status != "failed":
                        return
                    last_error = error

                if cancel_event.is_set():
                    return
                try:
                    candidates = self._discover_hosts(port)
                except Exception as exc:
                    candidates = ()
                    last_error = str(exc)
                for candidate in dict.fromkeys(candidates):
                    if candidate == configured_host:
                        continue
                    status, error = try_candidate(candidate)
                    if status != "failed":
                        return
                    last_error = error
                with self._state_lock:
                    if (
                        not cancel_event.is_set()
                        and not self._closed
                        and attempt_id == self._wifi_attempt_id
                    ):
                        self._wifi_results.put(
                            WifiAttempt(attempt_id, None, "", port, last_error)
                        )
            finally:
                with self._state_lock:
                    if self._wifi_worker is threading.current_thread():
                        self._wifi_worker = None

        thread = threading.Thread(target=worker, daemon=True, name="ttc3018-wifi-connect")
        with self._state_lock:
            self._wifi_worker = thread
        thread.start()
        return ConnectionOutcome(True, f"Trying {host or 'saved host'}:{port}; discovering GRBL if needed…", self.mode, host, port)

    def poll_wifi(self) -> ConnectionOutcome | None:
        while True:
            try:
                result = self._wifi_results.get_nowait()
            except queue.Empty:
                return None
            with self._state_lock:
                current_attempt = result.attempt_id == self._wifi_attempt_id and not self._closed
            if current_attempt:
                break
            self._safe_disconnect(result.transport)
        if result.transport is None:
            with self._state_lock:
                if result.attempt_id != self._wifi_attempt_id or self._closed:
                    return None
                self._wifi_connecting = False
                self._wifi_cancel_event = None
            return ConnectionOutcome(False, f"Wi-Fi connection failed: {result.error}", self.mode, port=result.port)
        with self._state_lock:
            if result.attempt_id != self._wifi_attempt_id or self._closed:
                discard_reason = "service is closed or the attempt was canceled"
            elif self.transport is not None and self.transport.connected:
                discard_reason = "another connection is active"
            else:
                self.transport = result.transport
                self.mode = ConnectionMode.WIFI
                self.endpoint = result.host
                self.port = result.port
                self._wifi_connecting = False
                self._wifi_cancel_event = None
                return ConnectionOutcome(True, f"Connected to {result.host}:{result.port} over Wi-Fi TCP", self.mode, result.host, result.port)
        if discard_reason == "another connection is active":
            self._safe_disconnect(result.transport)
            return ConnectionOutcome(False, "Wi-Fi connection discarded because another connection is active")
        self._safe_disconnect(result.transport)
        return ConnectionOutcome(False, "Wi-Fi connection discarded because the service is closed or canceled")

    def disconnect(self) -> ConnectionOutcome:
        with self._state_lock:
            self._cancel_wifi_locked()
            transport = self.transport
            self.transport = None
            self._wifi_connecting = False
            self._drain_wifi_results_locked()
        self._safe_disconnect(transport)
        return ConnectionOutcome(True, "Disconnected; physical position cannot be guaranteed", self.mode)

    def close(self) -> ConnectionOutcome:
        """Release every transport lease before the application exits.

        A Wi-Fi discovery worker may finish after the UI has begun closing. It
        is canceled, joined for the bounded connection timeout, and any result
        it produced is drained and disconnected so no socket remains owned by
        a forgotten transport object.
        """
        with self._state_lock:
            self._closed = True
            worker = self._wifi_worker
        outcome = self.disconnect()
        if worker is not None and worker is not threading.current_thread():
            worker.join(timeout=2.0)
        with self._state_lock:
            self._drain_wifi_results_locked()
            if self._wifi_worker is worker and worker is not None and not worker.is_alive():
                self._wifi_worker = None
        return outcome

    def send_line(self, command: bytes, display_text: str | None = None) -> None:
        if self.transport is None:
            raise RuntimeError("Not connected")
        self.transport.send_line(command, display_text=display_text)

    def send_realtime(self, command: bytes) -> None:
        if self.transport is None:
            raise RuntimeError("Not connected")
        self.transport.send_realtime(command)

    def events(self):
        if self.transport is None:
            return ()
        return self.transport.events

    def _cancel_wifi_locked(self) -> None:
        self._wifi_attempt_id += 1
        if self._wifi_cancel_event is not None:
            self._wifi_cancel_event.set()
        self._wifi_cancel_event = None

    def _drain_wifi_results_locked(self) -> None:
        while True:
            try:
                result = self._wifi_results.get_nowait()
            except queue.Empty:
                return
            self._safe_disconnect(result.transport)

    @staticmethod
    def _safe_disconnect(transport: Any | None) -> None:
        if transport is None:
            return
        try:
            transport.disconnect()
        except Exception:
            # Shutdown must release every other resource even if one adapter
            # has already lost its underlying OS handle.
            return
