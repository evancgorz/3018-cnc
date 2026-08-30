"""Qt-independent USB-assisted Wi-Fi provisioning workflow."""

from __future__ import annotations

from typing import Callable

from ..wifi_setup import make_station_commands
from .machine_session import ActionOutcome


class WifiProvisioningService:
    """Send the DLC32 station-mode transaction with bounded sequencing."""

    def __init__(
        self,
        send_line: Callable[[bytes, str | None], None],
        on_notice: Callable[[str], None] | None = None,
    ) -> None:
        self._send_line = send_line
        self._on_notice = on_notice or (lambda _message: None)
        self._commands: list[tuple[bytes, str]] = []
        self._index = 0
        self._waiting_for_ack = False
        self._next_at: float | None = None

    @property
    def active(self) -> bool:
        return bool(self._commands)

    @staticmethod
    def validate(ssid: str, password: str, port: int) -> list[tuple[bytes, str]]:
        return make_station_commands(ssid, password, port)

    def start(self, ssid: str, password: str, port: int, now: float) -> ActionOutcome:
        try:
            commands = self.validate(ssid, password, port)
        except ValueError as exc:
            return ActionOutcome(False, str(exc))
        self._commands = commands
        self._index = 0
        self._waiting_for_ack = False
        self._next_at = now
        self.poll(now)
        if not self.active:
            return ActionOutcome(False, "Wi-Fi setup could not start")
        return ActionOutcome(True, "Wi-Fi setup transaction started")

    def handle_response(self, response: str, now: float) -> bool:
        if not self.active or not self._waiting_for_ack:
            return False
        lowered = response.strip().lower()
        if lowered == "ok":
            self._waiting_for_ack = False
            self._next_at = now + 0.1
            return True
        if lowered.startswith("error:") or lowered.startswith("alarm:"):
            self.cancel()
            self._on_notice(f"Controller rejected Wi-Fi configuration: {response.strip()}")
            return True
        return False

    def poll(self, now: float) -> None:
        if not self.active or self._next_at is None or now < self._next_at:
            return
        self._next_at = None
        if self._index >= len(self._commands):
            self._commands = []
            self._on_notice("Controller Wi-Fi configuration sent; reconnect over Wi-Fi after the restart")
            return
        command, display_text = self._commands[self._index]
        try:
            self._send_line(command, display_text)
        except RuntimeError as exc:
            self.cancel()
            self._on_notice(f"Wi-Fi setup interrupted — {exc}")
            return
        self._index += 1
        self._waiting_for_ack = not command.startswith(b"[ESP444]")
        if not self._waiting_for_ack:
            self._next_at = now + 8.0
        elif self._index >= len(self._commands):
            # The final command is always the restart marker, but retain a
            # safe completion path if the protocol list changes later.
            self._next_at = now + 0.1

    def cancel(self) -> None:
        self._commands = []
        self._index = 0
        self._waiting_for_ack = False
        self._next_at = None
