from __future__ import annotations

from datetime import datetime
import queue
import socket
import threading

from .serial_connection import SerialEvent


class TcpGrblConnection:
    """Persistent raw TCP connection to a network-enabled GRBL controller."""

    def __init__(self) -> None:
        self.events: queue.Queue[SerialEvent] = queue.Queue()
        self._socket: socket.socket | None = None
        self._reader: threading.Thread | None = None
        self._stop = threading.Event()
        self._write_lock = threading.Lock()

    @property
    def connected(self) -> bool:
        return self._socket is not None

    def connect(self, host: str, port: int, timeout: float = 3.0) -> None:
        if self.connected:
            raise RuntimeError("Already connected")
        if not host.strip():
            raise ValueError("Wi-Fi host cannot be empty")
        if not 1 <= port <= 65535:
            raise ValueError("TCP port must be between 1 and 65535")

        endpoint = socket.create_connection((host.strip(), port), timeout=timeout)
        try:
            endpoint.settimeout(0.2)
            endpoint.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except Exception:
            try:
                endpoint.close()
            except OSError:
                pass
            raise
        self._socket = endpoint
        self._stop.clear()
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        self._emit("system", f"Connected to {host.strip()}:{port} over Wi-Fi TCP")
        self.send_realtime(b"?")

    def disconnect(self) -> None:
        self._stop.set()
        endpoint = self._socket
        self._socket = None
        if endpoint is not None:
            try:
                endpoint.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                endpoint.close()
            except OSError:
                pass
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
        endpoint = self._socket
        if endpoint is None:
            raise RuntimeError("Not connected")
        with self._write_lock:
            endpoint.sendall(data)
        shown = display_text or (
            " ".join(f"0x{byte:02X}" for byte in data)
            if kind == "tx-realtime"
            else data.decode("ascii").strip()
        )
        self._emit(kind, shown)

    def _read_loop(self) -> None:
        endpoint = self._socket
        if endpoint is None:
            return
        buffer = bytearray()
        try:
            while not self._stop.is_set():
                try:
                    chunk = endpoint.recv(4096)
                except TimeoutError:
                    continue
                if not chunk:
                    if not self._stop.is_set():
                        self._emit("error", "Wi-Fi controller closed the connection")
                    break
                buffer.extend(chunk)
                while b"\n" in buffer:
                    raw, _, remainder = buffer.partition(b"\n")
                    buffer = bytearray(remainder)
                    text = raw.rstrip(b"\r").decode("utf-8", errors="replace")
                    if text:
                        self._emit("rx", text)
        except OSError as exc:
            if not self._stop.is_set():
                self._emit("error", str(exc))
        finally:
            if buffer:
                self._emit("rx", bytes(buffer).decode("utf-8", errors="replace"))
            if self._socket is endpoint:
                self._socket = None
            try:
                endpoint.close()
            except OSError:
                pass

    def _emit(self, kind: str, text: str) -> None:
        self.events.put(SerialEvent(kind, text, datetime.now()))
