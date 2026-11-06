"""Bounded USB-assisted Wi-Fi handoff without motion or provisioning.

ESP3D's read-only current-IP command is [ESP111]:
https://github.com/luc-github/ESP3DLib/blob/master/docs/Commands.txt
The USB transport stays authoritative until the SAME candidate TCP connection
reports fresh Idle/zero-spindle state matching fresh USB machine position.
Matching position is a consistency check, not a cryptographic device identity.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from ipaddress import IPv4Address
import math
import queue
import re
import threading
import time
from typing import Any, Callable

from ..grbl import GrblStatus, parse_status


@dataclass(frozen=True)
class BootstrapHandoff:
    transport: Any
    host: str
    port: int


def _usable_ip(value: str) -> str | None:
    try:
        ip = IPv4Address(value.strip())
    except (ValueError, AttributeError):
        return None
    if ip.is_unspecified or ip.is_loopback or ip.is_multicast or ip.is_link_local or ip.is_reserved:
        return None
    return str(ip)


def _station_ip(line: str) -> str | None:
    # A bare address is the documented plain [ESP111] reply. Also accept
    # explicit STA-connected reports, but never AP, mask, gateway or secrets.
    text = line.strip()
    if re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", text):
        return _usable_ip(text)
    lower = text.lower()
    if "mode=ap" in lower or "ap ip" in lower:
        return None
    if "mode=sta" in lower and "status=connected" not in lower:
        return None
    match = re.search(r"(?:\bIP[:=]\s*|\bConnected with\s+)(\d{1,3}(?:\.\d{1,3}){3})", text, re.I)
    return _usable_ip(match.group(1)) if match else None


def _safe_idle(status: GrblStatus | None) -> bool:
    if status is None or status.state != "Idle" or status.spindle != 0 or status.feed != 0:
        return False
    pos = status.machine_position
    return pos is not None and all(math.isfinite(v) for v in (pos.x, pos.y, pos.z))


class WifiBootstrap:
    QUERY_WAIT = 0.5
    CONNECT_TIMEOUT = 1.2
    STATUS_TIMEOUT = 2.0
    USB_STATUS_MAX_AGE = 0.75
    POSITION_TOLERANCE = 0.05

    def __init__(self, usb: Any, factory: Callable[[], Any], settings: Any, *, now: float):
        self.usb = usb
        self.factory = factory
        self.port = int(getattr(settings, "wifi_port", 23))
        if not 1 <= self.port <= 65535:
            raise ValueError("TCP port must be between 1 and 65535")
        self.saved_host = _usable_ip(str(getattr(settings, "wifi_host", "")))
        self.reported_host: str | None = None
        self.state = "querying-ip"
        self.message = "USB bootstrap only: requesting controller IP; physical jobs require verified Wi-Fi"
        self.query_until = now + self.QUERY_WAIT
        self._candidates: list[str] = []
        self._tried: set[str] = set()
        self._results: queue.Queue = queue.Queue()
        self._result_lock = threading.Lock()
        self._cancel = threading.Event()
        self.worker: threading.Thread | None = None
        self.candidate: Any | None = None
        self.host = ""
        self.deadline = 0.0
        self.next_query = 0.0
        self._response_bytes = 0
        self._last_error = "No saved or controller-reported station IP; Wi-Fi setup is required"
        self._terminal_reported = False
        # No SSID/password reads, writes, restart, controller reset or scan.
        usb.send_line(b"[ESP111]", display_text="[ESP111] (read-only IP query)")

    @property
    def snapshot(self) -> dict[str, object]:
        return {"state": self.state, "message": self.message, "host": self.host,
                "port": self.port, "usb_bootstrap_only": self.state != "ready",
                "attempted_hosts": tuple(sorted(self._tried))}

    def note_usb_line(self, line: str) -> None:
        if self.state != "querying-ip":
            return
        candidate = _station_ip(line)
        if candidate:
            self.reported_host = candidate

    def cancel(self) -> None:
        with self._result_lock:
            self._cancel.set()
            while True:
                try:
                    transport, _host, _error = self._results.get_nowait()
                except queue.Empty:
                    break
                self._disconnect(transport)
        self._disconnect(self.candidate)
        self.candidate = None
        if self.state != "ready":
            self.state = "canceled"
            self.message = "Wi-Fi bootstrap canceled; USB remains bootstrap only"

    @staticmethod
    def _disconnect(transport: Any | None) -> None:
        if transport is not None:
            try:
                transport.disconnect()
            except Exception:
                pass

    def _connect_next(self, now: float) -> None:
        if not self._candidates:
            self.state = "needs-setup" if not self._tried else "unavailable"
            self.message = "USB bootstrap only: " + self._last_error
            return
        host = self._candidates.pop(0)
        self.host = host
        self._tried.add(host)
        self.state = "connecting"
        self.message = f"USB bootstrap only: connecting to reported/saved Wi-Fi {host}:{self.port}"

        def connect() -> None:
            transport = None
            error = ""
            try:
                transport = self.factory()
                transport.connect(host, self.port, timeout=self.CONNECT_TIMEOUT)
                if not transport.connected:
                    raise RuntimeError("TCP connection closed before verification")
            except Exception as exc:
                self._disconnect(transport)
                transport = None
                error = f"{host}:{self.port}: {type(exc).__name__}: {exc}"
            with self._result_lock:
                if self._cancel.is_set():
                    self._disconnect(transport)
                else:
                    self._results.put((transport, host, error))
        self.worker = threading.Thread(target=connect, daemon=True, name="ttc3018-wifi-bootstrap")
        self.worker.start()

    def _fail_candidate(self, error: str, now: float) -> None:
        self._disconnect(self.candidate)
        self.candidate = None
        self._last_error = error
        self._connect_next(now)

    def poll(self, *, usb_status: GrblStatus | None, usb_status_age: float | None,
             allow_handoff: bool, now: float) -> BootstrapHandoff | None:
        if self._cancel.is_set() or self.state in {"ready", "canceled", "needs-setup", "unavailable"}:
            return None
        if not self.usb.connected:
            self.cancel()
            self.message = "USB disconnected before Wi-Fi handoff; reconnect USB to retry"
            return None
        if self.state == "querying-ip":
            if now < self.query_until:
                return None
            self._candidates = list(dict.fromkeys(h for h in (self.reported_host, self.saved_host) if h))
            self._connect_next(now)
            return None
        if self.state == "connecting":
            try:
                transport, host, error = self._results.get_nowait()
            except queue.Empty:
                return None
            if transport is None:
                self._last_error = error
                self._connect_next(now)
                return None
            self.candidate, self.host = transport, host
            self.state = "verifying"
            self.message = f"USB bootstrap only: validating live GRBL status on {host}:{self.port}"
            self.deadline = now + self.STATUS_TIMEOUT
            self.next_query = now
            self._response_bytes = 0
        if self.state != "verifying":
            return None
        if not self.candidate.connected:
            self._fail_candidate("Wi-Fi closed before verified handoff", now)
            return None
        if now >= self.deadline:
            self._fail_candidate("Wi-Fi status/USB readiness verification timed out", now)
            return None
        if now >= self.next_query:
            try:
                self.candidate.send_realtime(b"?")
            except Exception as exc:
                self._fail_candidate(f"Wi-Fi status query failed: {exc}", now)
                return None
            self.next_query = now + 0.25
        for _ in range(128):
            try:
                event = self.candidate.events.get_nowait()
            except queue.Empty:
                return None
            if event.kind == "error":
                self._fail_candidate("Wi-Fi transport failed during verification", now)
                return None
            if event.kind != "rx":
                continue
            self._response_bytes += len(event.text)
            if self._response_bytes > 32768:
                self._fail_candidate("Wi-Fi verification response exceeded bound", now)
                return None
            timestamp = getattr(event, "timestamp", None)
            if timestamp is None:
                continue
            try:
                event_age = (datetime.now(timestamp.tzinfo) - timestamp).total_seconds()
            except (TypeError, ValueError, AttributeError):
                continue
            if not 0 <= event_age <= self.USB_STATUS_MAX_AGE:
                continue
            try:
                status = parse_status(event.text)
            except (ValueError, OverflowError):
                self._fail_candidate("Malformed GRBL status during Wi-Fi verification", now)
                return None
            if status is None:
                continue
            if not _safe_idle(status):
                self._fail_candidate("Wi-Fi must report Idle, zero feed/spindle and finite machine position", now)
                return None
            if not allow_handoff or not _safe_idle(usb_status):
                continue
            if usb_status_age is None or not math.isfinite(usb_status_age) or not 0 <= usb_status_age <= self.USB_STATUS_MAX_AGE:
                continue
            a, b = status.machine_position, usb_status.machine_position
            if any(abs(x - y) > self.POSITION_TOLERANCE for x, y in zip((a.x,a.y,a.z), (b.x,b.y,b.z))):
                self._fail_candidate("Wi-Fi machine position does not match fresh USB status", now)
                return None
            transport = self.candidate
            self.candidate = None
            self.state = "ready"
            self.message = "Wi-Fi handoff verified; physical operations require fresh reference and work zero"
            return BootstrapHandoff(transport, self.host, self.port)
        return None
