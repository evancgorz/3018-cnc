"""Qt-free typed contracts shared by backend servers, clients, and adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .protocol import PROTOCOL_VERSION, SCHEMA_VERSION


@dataclass(frozen=True)
class StructuredError:
    """Stable machine-readable failure information at the IPC boundary."""

    code: str
    message: str
    retryable: bool = False
    details: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message,
                "retryable": bool(self.retryable), "details": dict(self.details)}

    @classmethod
    def from_value(cls, value: object) -> "StructuredError":
        if isinstance(value, Mapping):
            return cls(str(value.get("code", "request_failed")),
                       str(value.get("message", "Backend request failed")),
                       bool(value.get("retryable", False)),
                       dict(value.get("details", {})) if isinstance(value.get("details", {}), Mapping) else {})
        return cls("request_failed", str(value or "Backend request failed"))


@dataclass(frozen=True)
class CapabilitySnapshot:
    """Capabilities advertised by one backend session.

    Categories are descriptive and intentionally separate from executable
    actions.  A declaration never implies commissioning or authorization.
    """

    actions: tuple[str, ...] = ()
    transport_modes: tuple[str, ...] = ()
    supported: tuple[str, ...] = ()
    simulation_only: tuple[str, ...] = ()
    declared_but_unavailable: tuple[str, ...] = ()
    hardware_commissioned: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"actions": list(self.actions), "transport_modes": list(self.transport_modes),
                "supported": list(self.supported), "simulation_only": list(self.simulation_only),
                "declared_but_unavailable": list(self.declared_but_unavailable),
                "hardware_commissioned": list(self.hardware_commissioned)}

    @classmethod
    def from_dict(cls, value: object) -> "CapabilitySnapshot":
        data = value if isinstance(value, Mapping) else {}
        def values(key: str) -> tuple[str, ...]:
            raw = data.get(key, ())
            return tuple(str(item) for item in raw) if isinstance(raw, (list, tuple)) else ()
        return cls(*(values(key) for key in (
            "actions", "transport_modes", "supported", "simulation_only",
            "declared_but_unavailable", "hardware_commissioned")))


@dataclass(frozen=True)
class BackendEvent:
    sequence: int
    kind: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    timestamp: float = 0.0

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "BackendEvent":
        payload = value.get("payload", {})
        return cls(int(value.get("sequence", 0)), str(value.get("kind", "event")),
                   dict(payload) if isinstance(payload, Mapping) else {},
                   float(value.get("timestamp", 0.0)))


@dataclass(frozen=True)
class BackendSnapshot:
    """Typed envelope for an immutable backend state publication."""

    schema_version: int
    protocol_version: int
    sequence: int
    revision: int
    session_id: str
    available: bool
    connected: bool
    status_state: str
    machine_id: str
    machine_name: str
    capabilities: CapabilitySnapshot
    data: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "BackendSnapshot":
        backend = value.get("backend", {})
        machine = value.get("machine", {})
        backend = backend if isinstance(backend, Mapping) else {}
        machine = machine if isinstance(machine, Mapping) else {}
        return cls(int(value.get("schema_version", 0)), int(value.get("protocol_version", 0)),
                   int(value.get("sequence", 0)), int(value.get("revision", value.get("state_revision", 0))),
                   str(backend.get("session_id", value.get("session_id", ""))),
                   bool(backend.get("available", False)), bool(value.get("connected", False)),
                   str(value.get("status_state", "unavailable")), str(value.get("machine_id", machine.get("machine_id", ""))),
                   str(value.get("machine_name", machine.get("name", ""))),
                   CapabilitySnapshot.from_dict(value.get("capabilities")), dict(value))


@dataclass(frozen=True)
class ActionCommand:
    name: str
    arguments: Mapping[str, Any] = field(default_factory=dict)
    request_id: str = ""
    expected_revision: int | None = None
    idempotency_key: str = ""

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"name": self.name, "arguments": dict(self.arguments)}
        if self.request_id:
            result["request_id"] = self.request_id
        if self.expected_revision is not None:
            result["expected_revision"] = int(self.expected_revision)
        if self.idempotency_key:
            result["idempotency_key"] = self.idempotency_key
        return result


@dataclass(frozen=True)
class ActionResult:
    accepted: bool
    message: str
    token: str = ""
    code: str = ""
    data: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_value(cls, value: object) -> "ActionResult":
        data = dict(value) if isinstance(value, Mapping) else {"value": value}
        return cls(bool(data.get("accepted", True)), str(data.get("message", "Action completed")),
                   str(data.get("token", "")), str(data.get("code", "")), data)

    def to_dict(self) -> dict[str, Any]:
        result = dict(self.data)
        result.update({"accepted": bool(self.accepted), "message": self.message})
        if self.token:
            result["token"] = self.token
        if self.code:
            result["code"] = self.code
        return result


def contract_versions() -> dict[str, int]:
    return {"schema_version": SCHEMA_VERSION, "protocol_version": PROTOCOL_VERSION}
