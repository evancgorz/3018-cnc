"""Small dependency contracts for application services.

Concrete serial/TCP transports and filesystem stores implement these shapes;
the application layer does not depend on Qt or a particular transport class.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Protocol

from ..connection_settings import ConnectionSettings
from ..machine_state import MachineProfile
from ..work_zero_settings import SavedWorkZero
from ..step_prepare_settings import StepPrepareSettings


class Transport(Protocol):
    @property
    def connected(self) -> bool: ...

    @property
    def events(self): ...

    def disconnect(self) -> None: ...

    def send_line(self, command: bytes, display_text: str | None = None) -> None: ...

    def send_realtime(self, command: bytes) -> None: ...


class ProfileStorePort(Protocol):
    def load(self) -> MachineProfile: ...

    def save(self, profile: MachineProfile) -> None: ...


class ConnectionSettingsStorePort(Protocol):
    def load(self) -> ConnectionSettings: ...

    def save(self, settings: ConnectionSettings) -> None: ...


class WorkZeroStorePort(Protocol):
    def load(self) -> SavedWorkZero | None: ...

    def save(self, saved: SavedWorkZero) -> None: ...

    def clear(self) -> None: ...


class StepPrepareSettingsStorePort(Protocol):
    def load(self) -> StepPrepareSettings: ...

    def save(self, settings: StepPrepareSettings) -> None: ...


class Clock(Protocol):
    def monotonic(self) -> float: ...


class EventSink(Protocol):
    def __call__(self, event: object) -> None: ...


PathLike = Path | str
Callback = Callable[[], None]
