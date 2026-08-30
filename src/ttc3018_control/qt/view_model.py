from __future__ import annotations

from ..application.machine_session import MachineSession
from ..grbl import GrblStatus, Position

from PySide6.QtCore import Property, QObject, Signal, Slot


class AppViewModel(QObject):
    """Read-only, demo-safe shell state for the Qt migration.

    This intentionally has no transport or motion dependency. Machine command
    slots are added only after the application-service boundary is extracted.
    """

    status_changed = Signal()
    toast_requested = Signal(str)

    def __init__(self, session: MachineSession | None = None) -> None:
        super().__init__()
        self._session = session or MachineSession()
        self._connection = "Disconnected"
        self._grbl_state = "Unknown"
        self._reference = "Position unknown"
        self._work_zero = "Not confirmed"
        self._machine_position = "X—  Y—  Z—"
        self._work_position = "X—  Y—  Z—"
        self._spindle = "Off"

    @Property(str, notify=status_changed)
    def connection(self) -> str:
        return self._connection

    @Property(str, notify=status_changed)
    def grbl_state(self) -> str:
        return self._grbl_state

    @Property(str, notify=status_changed)
    def reference(self) -> str:
        return self._reference

    @Property(str, notify=status_changed)
    def work_zero(self) -> str:
        return self._work_zero

    @Property(str, notify=status_changed)
    def machine_position(self) -> str:
        return self._machine_position

    @Property(str, notify=status_changed)
    def work_position(self) -> str:
        return self._work_position

    @Property(str, notify=status_changed)
    def spindle(self) -> str:
        return self._spindle

    @Slot()
    def show_connection_notice(self) -> None:
        self.toast_requested.emit(
            "Connection controls will be enabled after the shared connection service is migrated."
        )

    @Slot(str)
    def show_preview_notice(self, action: str) -> None:
        self.toast_requested.emit(f"{action} is a visual preview in this migration build.")

    def apply_status(self, status: GrblStatus) -> None:
        """Bridge a fresh GRBL report into UI-safe display properties.

        Connection orchestration will call this method from the Qt main thread
        after the shared transport service is migrated. It does not transmit a
        command or mutate GRBL state.
        """
        self._session.update_status(status)
        self._connection = f"Connected — GRBL {status.state}"
        self._grbl_state = status.state
        self._machine_position = self._format_position(status.machine_position)
        work_position = status.work_position
        if work_position is None and status.machine_position and self._session.work_offset:
            work_position = status.machine_position.minus(self._session.work_offset)
        self._work_position = self._format_position(work_position)
        self._spindle = f"{status.spindle:g} RPM" if status.spindle else "Off"
        self._reference = "Trusted" if self._session.envelope.trusted else "Position unknown"
        self._work_zero = "Confirmed" if self._session.work_zero_confirmed else "Not confirmed"
        self.status_changed.emit()

    def mark_disconnected(self, reason: str = "Disconnected") -> None:
        self._session.invalidate_reference(reason)
        self._connection = "Disconnected"
        self._grbl_state = "Unknown"
        self._reference = "Position unknown"
        self._work_zero = "Not confirmed"
        self._spindle = "Off"
        self.status_changed.emit()

    @staticmethod
    def _format_position(position: Position | None) -> str:
        if position is None:
            return "X—  Y—  Z—"
        return f"X{position.x:.2f}  Y{position.y:.2f}  Z{position.z:.2f}"
