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

    @property
    def connected(self) -> bool:
        return bool(self.transport is not None and self.transport.connected)

    @property
    def wifi_connecting(self) -> bool:
        return self._wifi_connecting

    def connect_usb(self, port: str) -> ConnectionOutcome:
        if self.connected or self._wifi_connecting:
            return ConnectionOutcome(False, "Disconnect the current connection first")
        port = port.strip()
        if not port:
            return ConnectionOutcome(False, "Select a serial port first")
        try:
            transport = self._usb_factory()
            transport.connect(port)
        except (OSError, ValueError, RuntimeError) as exc:
            return ConnectionOutcome(False, f"Connection failed: {exc}")
        self.transport = transport
        self.mode = ConnectionMode.USB
        self.endpoint = port
        return ConnectionOutcome(True, f"Connected to {port}; waiting for GRBL status", self.mode, port)

    def begin_wifi(self, host: str, port: int) -> ConnectionOutcome:
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

        def worker() -> None:
            last_error = "No GRBL controller answered on the local network"
            candidates = [host.strip()] if host.strip() else []
            try:
                candidates.extend(self._discover_hosts(port))
            except OSError as exc:
                last_error = str(exc)
            for candidate in dict.fromkeys(candidates):
                transport = self._wifi_factory()
                try:
                    transport.connect(candidate, port, timeout=1.2)
                except (OSError, ValueError, RuntimeError) as exc:
                    last_error = str(exc)
                    continue
                self._wifi_results.put(WifiAttempt(attempt_id, transport, candidate, port))
                return
            self._wifi_results.put(WifiAttempt(attempt_id, None, "", port, last_error))

        threading.Thread(target=worker, daemon=True).start()
        return ConnectionOutcome(True, f"Trying {host or 'saved host'}:{port}; discovering GRBL if needed…", self.mode, host, port)

    def poll_wifi(self) -> ConnectionOutcome | None:
        while True:
            try:
                result = self._wifi_results.get_nowait()
            except queue.Empty:
                return None
            if result.attempt_id == self._wifi_attempt_id:
                break
            if result.transport is not None:
                result.transport.disconnect()
        self._wifi_connecting = False
        if result.transport is None:
            return ConnectionOutcome(False, f"Wi-Fi connection failed: {result.error}", self.mode, port=result.port)
        if self.connected:
            result.transport.disconnect()
            return ConnectionOutcome(False, "Wi-Fi connection discarded because another connection is active")
        self.transport = result.transport
        self.mode = ConnectionMode.WIFI
        self.endpoint = result.host
        self.port = result.port
        return ConnectionOutcome(True, f"Connected to {result.host}:{result.port} over Wi-Fi TCP", self.mode, result.host, result.port)

    def disconnect(self) -> ConnectionOutcome:
        self._wifi_attempt_id += 1
        if self.transport is not None:
            self.transport.disconnect()
        self.transport = None
        self._wifi_connecting = False
        return ConnectionOutcome(True, "Disconnected; physical position cannot be guaranteed", self.mode)

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
