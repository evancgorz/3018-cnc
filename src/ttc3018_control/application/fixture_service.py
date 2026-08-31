"""Application service for re-probed fixed-fixture restoration."""

from __future__ import annotations

from typing import Callable

from ..fixture_settings import FixtureRecord
from ..controller_adapters import ControllerAdapter
from ..grbl import Position
from .machine_session import ActionOutcome, MachineSession


class FixtureService:
    def __init__(self, session: MachineSession, adapter: ControllerAdapter, send_line: Callable[[bytes], None],
                 on_notice: Callable[[str], None] | None = None) -> None:
        self.session = session
        self.adapter = adapter
        self._send_line = send_line
        self._on_notice = on_notice or (lambda _message: None)

    def restore_from_probe(self, record: FixtureRecord, probe_position: Position, *, connected: bool,
                           spindle_off: bool) -> ActionOutcome:
        try:
            record.validate()
        except ValueError as exc:
            return ActionOutcome(False, str(exc))
        if not connected or not self.session.envelope.trusted:
            return ActionOutcome(False, "Home the machine in the current session before restoring a fixture.")
        if not spindle_off:
            return ActionOutcome(False, "Turn the spindle off before restoring a fixture.")
        origin = record.measured_origin(probe_position)
        try:
            self._send_line(self.adapter.work_offset_command(record.wcs_slot, origin))
        except (RuntimeError, ValueError) as exc:
            return ActionOutcome(False, f"Fixture work offset was not sent — {exc}")
        self._on_notice(f"Fixture {record.name} offset requested; waiting for fresh WCS confirmation.")
        return ActionOutcome(True, f"Fixture {record.name} restoration requested; verify the fresh work offset.")

