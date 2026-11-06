"""Headless Pine backend and its authenticated loopback client."""

from .runtime import BackendRuntime
from .client import (BackendClient, BackendIncompatible, BackendRequestRejected,
                     BackendRootAmbiguous, BackendUnavailable)
from .discovery import (AmbiguousBackendRootError, BackendOwnershipError, BackendRootRegistration,
                        BackendRootRegistry, DiscoveryRecord, DiscoveryStore, OwnerRecord,
                        default_data_root, discover_backend_root)
from .dispatcher import ActionDispatcher, ActionRejected
from .server import BackendServer
from .protocol import PROTOCOL_VERSION, SCHEMA_VERSION
from .contracts import (ActionCommand, ActionResult, BackendEvent, BackendSnapshot,
                        CapabilitySnapshot, StructuredError)
from .safety_input import (FakeSafetyInputAdapter, SafetyInputAdapter, SafetyInputAuditLog,
                           SafetyInputMonitor, SafetyInputSample, SafetyInputState,
                           SafetyInputStatus)

__all__ = [
    "BackendClient",
    "BackendIncompatible",
    "BackendRuntime",
    "BackendRequestRejected",
    "BackendUnavailable",
    "BackendRootAmbiguous",
    "AmbiguousBackendRootError",
    "DiscoveryRecord",
    "OwnerRecord",
    "BackendOwnershipError",
    "DiscoveryStore",
    "BackendRootRegistration",
    "BackendRootRegistry",
    "default_data_root",
    "discover_backend_root",
    "BackendServer",
    "ActionDispatcher",
    "ActionRejected",
    "PROTOCOL_VERSION",
    "SCHEMA_VERSION",
    "ActionCommand",
    "ActionResult",
    "BackendEvent",
    "BackendSnapshot",
    "CapabilitySnapshot",
    "StructuredError",
    "FakeSafetyInputAdapter",
    "SafetyInputAdapter",
    "SafetyInputAuditLog",
    "SafetyInputMonitor",
    "SafetyInputSample",
    "SafetyInputState",
    "SafetyInputStatus",
]
