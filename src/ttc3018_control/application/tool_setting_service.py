"""Application service for fixed tool-setter commissioning and measurement."""

from __future__ import annotations

from typing import Callable

from ..controller_adapters import ControllerAdapter
from ..grbl import Position
from ..tool_settings import ToolSetterRecord, calculate_tool_length_offset
from .machine_session import ActionOutcome, MachineSession


class ToolSettingService:
    def __init__(self, session: MachineSession, adapter: ControllerAdapter, send_line: Callable[[bytes], None],
                 on_notice: Callable[[str], None] | None = None) -> None:
        self.session = session
        self.adapter = adapter
        self._send_line = send_line
        self._on_notice = on_notice or (lambda _message: None)
        self.active_offset: float | None = None

    def apply_measurement(self, record: ToolSetterRecord, measured_trigger_z: float, *, connected: bool,
                          spindle_off: bool) -> ActionOutcome:
        try:
            record.validate()
        except ValueError as exc:
            return ActionOutcome(False, str(exc))
        if not record.commissioned:
            return ActionOutcome(False, "Tool setter must have three repeatable commissioning samples.")
        if not connected or not self.session.envelope.trusted:
            return ActionOutcome(False, "A connected, homed machine reference is required to measure a tool.")
        if not spindle_off:
            return ActionOutcome(False, "Turn the spindle off before measuring a tool.")
        offset = calculate_tool_length_offset(record.reference_trigger_z, measured_trigger_z)
        try:
            self._send_line(self.adapter.tool_offset_command(offset))
        except (RuntimeError, ValueError) as exc:
            return ActionOutcome(False, f"Tool offset was not sent — {exc}")
        self.active_offset = offset
        self._on_notice(f"Tool length offset requested: {offset:.4f} mm")
        return ActionOutcome(True, "Tool length offset requested; wait for the controller confirmation.")

    def clear(self, *, connected: bool) -> ActionOutcome:
        if not connected:
            self.active_offset = None
            return ActionOutcome(True, "Tool offset cleared locally after disconnect.")
        try:
            self._send_line(self.adapter.clear_tool_offset_command())
        except (RuntimeError, ValueError) as exc:
            return ActionOutcome(False, f"Tool offset clear was not sent — {exc}")
        self.active_offset = None
        return ActionOutcome(True, "Tool length offset cleared.")

    def reset(self) -> None:
        self.active_offset = None

