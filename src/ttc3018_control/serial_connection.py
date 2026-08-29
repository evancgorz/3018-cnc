from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import queue
import threading
import time

import serial
from serial.tools import list_ports


@dataclass(frozen=True)
class SerialEvent:
    kind: str
    text: str
    timestamp: datetime


def available_ports() -> list[tuple[str, str]]:
    return sorted(
        ((port.device, port.description) for port in list_ports.comports()),
        key=lambda item: item[0],
    )


class GrblConnection:
    """One persistent, thread-safe connection to a GRBL serial endpoint."""

    def __init__(self) -> None:
        self.events: queue.Queue[SerialEvent] = queue.Queue()
        self._serial: serial.Serial | None = None
        self._reader: threading.Thread | None = None
        self._stop = threading.Event()
        self._write_lock = threading.Lock()

    @property
    def connected(self) -> bool:
        return self._serial is not None and self._serial.is_open

    def connect(self, port: str, baudrate: int = 115200) -> None:
        if self.connected:
            raise RuntimeError("Already connected")

        endpoint = serial.Serial()
        endpoint.port = port
        endpoint.baudrate = baudrate
        endpoint.timeout = 0.2
        endpoint.write_timeout = 1.0
        endpoint.rtscts = False
        endpoint.dsrdtr = False
        endpoint.dtr = False
        endpoint.rts = False
        endpoint.open()

        self._serial = endpoint
        self._stop.clear()
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        self._emit("system", f"Connected to {port} at {baudrate} baud")

        # Many GRBL boards reset when a serial connection opens. Keep this
        # connection alive and allow the startup banner to arrive before polling.
        time.sleep(0.3)
        self.send_realtime(b"?")

    def disconnect(self) -> None:
        self._stop.set()
        endpoint = self._serial
        self._serial = None
        if endpoint is not None and endpoint.is_open:
            endpoint.close()
        if self._reader is not None and self._reader.is_alive():
            self._reader.join(timeout=1.0)
        self._reader = None
        self._emit("system", "Disconnected")

    def send_line(self, command: bytes, display_text: str | None = None) -> None:
        if not command.endswith(b"\n"):
            command += b"\n"
        self._write(command, "tx", display_text)

    def send_realtime(self, command: bytes) -> None:
        self._write(command, "tx-realtime")

    def _write(self, data: bytes, kind: str, display_text: str | None = None) -> None:
        endpoint = self._serial
        if endpoint is None or not endpoint.is_open:
            raise RuntimeError("Not connected")
        with self._write_lock:
            endpoint.write(data)
        shown = display_text or (
            " ".join(f"0x{byte:02X}" for byte in data)
            if kind == "tx-realtime"
            else data.decode("ascii").strip()
        )
        self._emit(kind, shown)

    def _read_loop(self) -> None:
        endpoint = self._serial
        if endpoint is None:
            return
        try:
            while not self._stop.is_set() and endpoint.is_open:
                raw = endpoint.readline()
                if raw:
                    self._emit("rx", raw.decode("utf-8", errors="replace").strip())
        except (serial.SerialException, OSError) as exc:
            if not self._stop.is_set():
                self._emit("error", str(exc))

    def _emit(self, kind: str, text: str) -> None:
        self.events.put(SerialEvent(kind, text, datetime.now()))
