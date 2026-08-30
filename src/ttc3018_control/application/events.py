"""Typed transient events emitted by application services."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class EventLevel(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True)
class ApplicationEvent:
    """Base event; events are data, never UI callbacks or commands."""


@dataclass(frozen=True)
class NoticeEvent(ApplicationEvent):
    message: str
    level: EventLevel = EventLevel.INFO


@dataclass(frozen=True)
class LogEvent(ApplicationEvent):
    kind: str
    text: str


@dataclass(frozen=True)
class ConfirmationRequest(ApplicationEvent):
    token: str
    operation: str
    title: str
    message: str


@dataclass(frozen=True)
class CloseRequested(ApplicationEvent):
    reason: str = ""

