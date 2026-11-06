"""Qt-independent USB and Wi-Fi transport lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
import queue
import threading
import time
from typing import Any, Callable, Iterable

from .state import ConnectionMode
from .wifi_bootstrap import WifiBootstrap


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
        simulation_factory: Callable[[], Any] | None = None,
        simulation_transport_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._usb_factory = usb_factory
        self._wifi_factory = wifi_factory
        self._discover_hosts = discover_hosts
        self._simulation_factory = simulation_factory
        self._simulation_transport_factory = simulation_transport_factory
        self.simulation_runtime: Any | None = None
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
        self._auto_candidates: list[tuple[str, str]] = []
        self._auto_index = 0
        self._auto_failures: list[str] = []
        self.usb_setup_only = False
        self._wifi_bootstrap: WifiBootstrap | None = None

    @property
    def connected(self) -> bool:
        with self._state_lock:
            return bool(self.transport is not None and self.transport.connected)

    @property
    def wifi_connecting(self) -> bool:
        with self._state_lock:
            return self._wifi_connecting

    @property
    def auto_connecting(self) -> bool:
        with self._state_lock:
            return bool(self._auto_candidates and not self.connected)

    @property
    def auto_connection_failures(self) -> tuple[str, ...]:
        with self._state_lock:
            return tuple(self._auto_failures)

    @property
    def auto_connection_state(self) -> str:
        with self._state_lock:
            if self.connected:
                return "connected"
            if self._auto_candidates:
                return "trying"
            return "failed" if self._auto_failures else "idle"

    @property
    def wifi_bootstrap_snapshot(self) -> dict[str, object]:
        with self._state_lock:
            if self._wifi_bootstrap is not None:
                return dict(self._wifi_bootstrap.snapshot)
            return {"state": "idle", "message": "USB is for Wi-Fi bootstrap only",
                    "host": "", "port": self.port, "usb_bootstrap_only": True,
                    "attempted_hosts": ()}

    def start_wifi_bootstrap(self, settings: Any, *, now: float | None = None) -> ConnectionOutcome:
        """Start read-only IP bootstrap while retaining authoritative USB.

        The application must call only after confirming no active operation or
        command acknowledgements and fresh Idle/zero-spindle USB status.
        No provisioning, reboot, scan, or reference preservation is implied.
        """
        with self._state_lock:
            if self._closed or self.mode is not ConnectionMode.USB or not self.connected:
                return ConnectionOutcome(False, "Wi-Fi bootstrap requires the active USB connection")
            if self._wifi_connecting or self.auto_connecting:
                return ConnectionOutcome(False, "Another connection attempt is active")
            if self._wifi_bootstrap is not None and self._wifi_bootstrap.state in {"querying-ip", "connecting", "verifying"}:
                return ConnectionOutcome(False, "Wi-Fi bootstrap is already running")
            self.cancel_wifi_bootstrap()
            try:
                self._wifi_bootstrap = WifiBootstrap(self.transport, self._wifi_factory, settings,
                    now=time.monotonic() if now is None else now)
            except (ValueError, RuntimeError, OSError) as exc:
                return ConnectionOutcome(False, f"Wi-Fi bootstrap could not start: {exc}")
            return ConnectionOutcome(True, self._wifi_bootstrap.message, ConnectionMode.USB)

    def note_wifi_bootstrap_usb_line(self, line: str) -> None:
        with self._state_lock:
            if self._wifi_bootstrap is not None and self.mode is ConnectionMode.USB:
                self._wifi_bootstrap.note_usb_line(line)

    def poll_wifi_bootstrap(self, *, usb_status: Any, usb_status_age: float | None,
                            allow_handoff: bool, now: float | None = None) -> ConnectionOutcome | None:
        with self._state_lock:
            bootstrap = self._wifi_bootstrap
            if bootstrap is None or self._closed:
                return None
            if self.transport is not bootstrap.usb or self.mode is not ConnectionMode.USB:
                if bootstrap.state != "ready":
                    bootstrap.cancel()
                return None
            result = bootstrap.poll(usb_status=usb_status, usb_status_age=usb_status_age,
                allow_handoff=allow_handoff, now=time.monotonic() if now is None else now)
            if result is not None:
                # Exactly the validated candidate socket becomes authoritative.
                old_usb = self.transport
                self.transport = result.transport
                self.mode, self.endpoint, self.port = ConnectionMode.WIFI, result.host, result.port
                self._auto_candidates = []
                self._safe_disconnect(old_usb)
                return ConnectionOutcome(True, bootstrap.message, ConnectionMode.WIFI, result.host, result.port)
            if bootstrap.state in {"unavailable", "needs-setup", "canceled"} and not bootstrap._terminal_reported:
                bootstrap._terminal_reported = True
                return ConnectionOutcome(False, bootstrap.message, ConnectionMode.USB)
            return None

    def cancel_wifi_bootstrap(self) -> None:
        with self._state_lock:
            if self._wifi_bootstrap is not None:
                self._wifi_bootstrap.cancel()
                self._wifi_bootstrap = None

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

    def connect_simulation(self) -> ConnectionOutcome:
        """Start a loopback twin and connect through the ordinary TCP transport."""
        with self._state_lock:
            if self._closed:
                return ConnectionOutcome(False, "Connection service is closed")
            if self.connected or self._wifi_connecting:
                return ConnectionOutcome(False, "Disconnect the current connection first")
        runtime = None
        transport = None
        try:
            if self._simulation_factory is None or self._simulation_transport_factory is None:
                raise RuntimeError("Digital twin support is unavailable")
            runtime = self._simulation_factory()
            host, port = runtime.start()
            if host != "127.0.0.1":
                raise RuntimeError("Digital twin endpoint is not loopback")
            transport = self._simulation_transport_factory()
            transport.connect(host, port)
        except Exception as exc:
            self._safe_disconnect(transport)
            if runtime is not None:
                try:
                    runtime.stop()
                except Exception:
                    pass
            return ConnectionOutcome(False, f"Digital twin failed to start: {exc}")
        with self._state_lock:
            if self._closed or self.connected:
                self._safe_disconnect(transport)
                try:
                    runtime.stop()
                except Exception:
                    pass
                return ConnectionOutcome(False, "Digital twin connection was superseded")
            self.transport = transport
            self.simulation_runtime = runtime
            self.mode = ConnectionMode.SIMULATION
            self.endpoint = "127.0.0.1"
            self.port = port
        return ConnectionOutcome(True, f"Connected to Virtual Machine (Digital Twin) on loopback:{port}", self.mode, "127.0.0.1", port)

    def begin_wifi(self, host: str, port: int, *, discover: bool = True) -> ConnectionOutcome:
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
                if discover:
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
        suffix = "; discovering GRBL if neededâ€¦" if discover else "â€¦"
        return ConnectionOutcome(True, f"Trying {host or 'saved host'}:{port}{suffix}", self.mode, host, port)

    def begin_auto_connect(self, settings: Any, usb_ports: Iterable[str]) -> ConnectionOutcome:
        """Start the bounded, backend-owned saved physical connection plan.

        Only the saved TCP endpoint and a saved/currently discovered COM
        endpoint are candidates.  A missing saved COM port is replaced only
        when discovery returns exactly one endpoint; multiple new ports are
        intentionally left for the operator chooser.
        """
        with self._state_lock:
            if self._closed:
                return ConnectionOutcome(False, "Connection service is closed")
            if self.connected:
                return ConnectionOutcome(True, "Existing controller connection adopted", self.mode, self.endpoint, self.port)
            if self._wifi_connecting or self.auto_connecting:
                return ConnectionOutcome(False, "Automatic connection is already running")
            available = tuple(dict.fromkeys(str(port).strip() for port in usb_ports if str(port).strip()))
            saved_usb = str(getattr(settings, "usb_port", "")).strip()
            usb_candidate = saved_usb if saved_usb and saved_usb in available else (available[0] if len(available) == 1 else "")
            wifi_host = str(getattr(settings, "wifi_host", "")).strip()
            wifi_port = int(getattr(settings, "wifi_port", 23) or 23)
            wifi_candidate = (wifi_host, wifi_port) if wifi_host and 1 <= wifi_port <= 65535 else None
            preferred = str(getattr(settings, "preferred_transport", "USB serial"))
            usb = [("usb", usb_candidate)] if usb_candidate else []
            wifi = [("wifi", f"{wifi_host}:{wifi_port}")] if wifi_candidate else []
            self._auto_candidates = (wifi + usb) if preferred == "Wi-Fi TCP" else (usb + wifi)
            self._auto_index = 0
            self._auto_failures = []
            if not usb_candidate and len(available) > 1:
                self._auto_failures.append("USB: multiple discovered COM endpoints; operator choice required")
            elif saved_usb and saved_usb not in available:
                self._auto_failures.append(f"USB {saved_usb}: saved endpoint is not currently present")
            if not self._auto_candidates:
                message = "No saved physical endpoint is available; choose a controller"
                if self._auto_failures:
                    message += " â€” " + " Â· ".join(self._auto_failures)
                return ConnectionOutcome(False, message)
            return self._start_auto_candidate_locked()

    def cancel_auto_connect(self) -> ConnectionOutcome:
        with self._state_lock:
            if not self._auto_candidates:
                return ConnectionOutcome(True, "Automatic connection is not running")
            self._auto_candidates = []
            self._auto_index = 0
            self._auto_failures = []
            self._cancel_wifi_locked()
            self._wifi_connecting = False
            self._drain_wifi_results_locked()
        return ConnectionOutcome(True, "Automatic connection canceled")

    def _start_auto_candidate_locked(self) -> ConnectionOutcome:
        while self._auto_index < len(self._auto_candidates):
            kind, value = self._auto_candidates[self._auto_index]
            self._auto_index += 1
            if kind == "usb":
                outcome = self.connect_usb(value)
                if outcome.accepted:
                    self._auto_candidates = []
                    return outcome
                self._auto_failures.append(f"USB {value}: {outcome.message}")
                continue
            host, raw_port = value.rsplit(":", 1)
            outcome = self.begin_wifi(host, int(raw_port), discover=False)
            if outcome.accepted:
                return outcome
            self._auto_failures.append(f"Wi-Fi {value}: {outcome.message}")
        message = "Automatic connection failed"
        if self._auto_failures:
            message += " â€” " + " Â· ".join(self._auto_failures)
        self._auto_candidates = []
        return ConnectionOutcome(False, message)

    def poll_wifi(self) -> ConnectionOutcome | None:
        while True:
            try:
                result = self._wifi_results.get_nowait()
            except queue.Empty:
                return None
            with self._state_lock:
                current_attempt = result.attempt_id == self._wifi_attempt_id and not self._closed
            if not current_attempt:
                self._safe_disconnect(result.transport)
                continue
            if result.transport is None:
                with self._state_lock:
                    if result.attempt_id != self._wifi_attempt_id or self._closed:
                        return None
                    self._wifi_connecting = False
                    self._wifi_cancel_event = None
                    automatic = bool(self._auto_candidates)
                    if automatic:
                        self._auto_failures.append(f"Wi-Fi {result.host or 'saved endpoint'}:{result.port}: {result.error}")
                        return self._start_auto_candidate_locked()
                return ConnectionOutcome(False, f"Wi-Fi connection failed: {result.error}", self.mode, port=result.port)
            break
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
                self._auto_candidates = []
                return ConnectionOutcome(True, f"Connected to {result.host}:{result.port} over Wi-Fi TCP", self.mode, result.host, result.port)
        if discard_reason == "another connection is active":
            self._safe_disconnect(result.transport)
            return ConnectionOutcome(False, "Wi-Fi connection discarded because another connection is active")
        self._safe_disconnect(result.transport)
        return ConnectionOutcome(False, "Wi-Fi connection discarded because the service is closed or canceled")

    def disconnect(self) -> ConnectionOutcome:
        with self._state_lock:
            self.cancel_wifi_bootstrap()
            self._cancel_wifi_locked()
            self._auto_candidates = []
            self._auto_index = 0
            transport = self.transport
            runtime = self.simulation_runtime
            self.transport = None
            self.simulation_runtime = None
            self._wifi_connecting = False
            self._drain_wifi_results_locked()
        self._safe_disconnect(transport)
        if runtime is not None:
            try:
                runtime.stop()
            except Exception:
                pass
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
        if self.usb_setup_only and self.mode is ConnectionMode.USB:
            normalized = command.strip().upper()
            if normalized not in {b"[ESP111]", b"$$", b"$I", b"$G", b"$#", b"$N", b"M5"}:
                raise RuntimeError("USB is bootstrap only; connect verified Wi-Fi before physical operations")
        self.transport.send_line(command, display_text=display_text)

    def send_realtime(self, command: bytes) -> None:
        if self.transport is None:
            raise RuntimeError("Not connected")
        if self.usb_setup_only and self.mode is ConnectionMode.USB and command not in {b"?", b"!", b"\x18", b"\x85"}:
            raise RuntimeError("USB is bootstrap only; realtime resume/operation requires verified Wi-Fi")
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
