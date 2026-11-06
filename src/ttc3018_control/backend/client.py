"""Qt-free authenticated client for the Pine backend."""

from __future__ import annotations

import json
from pathlib import Path
import secrets
import urllib.error
import urllib.request
from typing import Any

from .discovery import (AmbiguousBackendRootError, BackendRootRegistry, DiscoveryRecord,
                        DiscoveryStore, discover_backend_root)
from .contracts import ActionCommand, ActionResult, BackendEvent, BackendSnapshot, StructuredError
from .protocol import (MAX_RESPONSE_BYTES, PROTOCOL_VERSION, ProtocolError,
                       decode_message, encode_message, request, validate_versions)


class BackendUnavailable(ConnectionError):
    pass


class BackendRootAmbiguous(BackendUnavailable):
    """Several registered backend roots need an explicit user selection."""


class BackendIncompatible(BackendUnavailable):
    """A backend was reached but its advertised contract cannot be used."""


class BackendRequestRejected(RuntimeError):
    """The backend was reachable but rejected a typed request."""
    def __init__(self, message: str, *, error: StructuredError | None = None) -> None:
        super().__init__(message)
        self.error = error or StructuredError("request_rejected", message)


class BackendClient:
    def __init__(self, root: Path | None = None, *, timeout: float = 1.5,
                 registry: BackendRootRegistry | None = None) -> None:
        try:
            self.root = discover_backend_root(root, registry=registry)
        except AmbiguousBackendRootError as exc:
            raise BackendRootAmbiguous(str(exc)) from exc
        self.discovery = DiscoveryStore(self.root)
        self.timeout = max(0.1, float(timeout))
        self.record: DiscoveryRecord | None = None
        self.backend_unavailable = False
        self._sequence = 0

    @property
    def connected(self) -> bool:
        return self.record is not None and not self.backend_unavailable

    def attach(self, record: DiscoveryRecord | None = None) -> dict[str, Any]:
        candidate = record or self.discovery.read()
        if candidate is None:
            raise BackendUnavailable(
                f"No usable Pine backend discovery record at {self.discovery.path}. "
                "Use the running backend's application data directory."
            )
        try:
            try:
                candidate.validate()
            except (ValueError, TypeError, KeyError) as exc:
                raise BackendIncompatible(f"Backend discovery is incompatible: {exc}") from exc
            previous_session = self.record.session_id if self.record is not None else ""
            self.record = candidate
            if previous_session and previous_session != candidate.session_id:
                self._sequence = 0
            result = self._request("health", {})
            if result.get("session_id") != candidate.session_id or int(result.get("pid", -1)) != candidate.pid:
                raise BackendUnavailable("Backend session changed during attach")
            self.backend_unavailable = False
            # A fresh full snapshot is mandatory before callers enable actions.
            snapshot = self.snapshot()
            return {"health": result, "snapshot": snapshot}
        except BackendIncompatible:
            self.record = None
            self.backend_unavailable = True
            raise
        except Exception as exc:
            self.record = None
            self.backend_unavailable = True
            if isinstance(exc, BackendUnavailable):
                raise
            raise BackendUnavailable(f"Backend health check failed: {exc}") from exc

    def _request(self, operation: str, payload: dict[str, Any], *,
                 expected_revision: int | None = None, idempotency_key: str = "",
                 request_id: str | None = None) -> dict[str, Any]:
        record = self.record or self.discovery.read()
        if record is None:
            raise BackendUnavailable("Backend is unavailable")
        record.validate()
        body = encode_message(request(operation, payload,
                                       expected_revision=expected_revision,
                                       idempotency_key=idempotency_key,
                                       request_id=request_id or ""))
        req = urllib.request.Request(
            f"http://{record.host}:{record.port}/v1", data=body, method="POST",
            headers={"Content-Type": "application/json", "Content-Length": str(len(body)),
                     "X-Pine-Token": record.token, "X-Pine-Protocol": str(PROTOCOL_VERSION)},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as stream:
                data = stream.read(MAX_RESPONSE_BYTES + 1)
                if len(data) > MAX_RESPONSE_BYTES:
                    raise ProtocolError("response exceeds bounded size")
                # Responses can contain bounded raster previews. Request and
                # response limits are intentionally different, so decoding a
                # valid large snapshot must use the response bound here.
                result = decode_message(data, limit=MAX_RESPONSE_BYTES)
        except urllib.error.HTTPError as exc:
            if exc.code == 426:
                self.backend_unavailable = True
                raise BackendIncompatible("Backend protocol version is incompatible") from exc
            if exc.code < 500:
                try:
                    payload = decode_message(exc.read(MAX_RESPONSE_BYTES + 1),
                                             limit=MAX_RESPONSE_BYTES)
                    detail = StructuredError.from_value(payload.get("error_detail", payload.get("error")))
                    raise BackendRequestRejected(detail.message, error=detail) from exc
                except BackendRequestRejected:
                    raise
                except Exception:
                    raise BackendRequestRejected(f"Backend HTTP {exc.code}") from exc
            self.backend_unavailable = True
            raise BackendUnavailable(str(exc)) from exc
        except (OSError, urllib.error.URLError, ProtocolError) as exc:
            self.backend_unavailable = True
            raise BackendUnavailable(str(exc)) from exc
        try:
            validate_versions(result)
        except ProtocolError as exc:
            raise BackendIncompatible(str(exc)) from exc
        if not result.get("ok", False):
            detail = StructuredError.from_value(result.get("error_detail", result.get("error")))
            raise BackendRequestRejected(detail.message, error=detail)
        return result.get("result")

    def health(self) -> dict[str, Any]:
        return self._request("health", {})

    def version(self) -> dict[str, Any]:
        return self.health()

    def snapshot(self) -> dict[str, Any]:
        return self._request("snapshot", {})

    def typed_snapshot(self) -> BackendSnapshot:
        return BackendSnapshot.from_dict(self.snapshot())

    def safety_input_status(self) -> dict[str, Any]:
        """Read the backend-owned independent safety-input projection."""
        return self.invoke("safety-input-status")

    def acknowledge_safety_input(self) -> dict[str, Any]:
        """Request the guarded physical-input acknowledgement route."""
        return self.invoke("acknowledge-safety-input")

    def events(self, *, after: int | None = None, limit: int = 100) -> dict[str, Any]:
        result = self._request("events", {"sequence": self._sequence if after is None else after, "limit": limit})
        self._sequence = max(self._sequence, int(result.get("next_sequence", self._sequence)))
        return result

    def typed_events(self, *, after: int | None = None, limit: int = 100) -> tuple[BackendEvent, ...]:
        result = self.events(after=after, limit=limit)
        return tuple(BackendEvent.from_dict(item) for item in result.get("events", ()))

    def invoke(self, action: str, *, expected_revision: int | None = None,
               idempotency_key: str | None = None, request_id: str | None = None,
               **arguments: Any) -> dict[str, Any]:
        return self._request(
            "action", {"name": action, "arguments": arguments},
            expected_revision=expected_revision,
            idempotency_key=idempotency_key or secrets.token_urlsafe(12),
            request_id=request_id,
        )

    def invoke_command(self, command: ActionCommand) -> ActionResult:
        return ActionResult.from_value(self._request(
            "action", {"name": command.name, "arguments": dict(command.arguments)},
            expected_revision=command.expected_revision,
            idempotency_key=command.idempotency_key or secrets.token_urlsafe(12),
            request_id=command.request_id,
        ))

    def confirm(self, token: str, accepted: bool = True) -> dict[str, Any]:
        return self._request("confirmation", {"token": token, "accepted": accepted})

    def shutdown(self, *, safe_abort: bool = False) -> dict[str, Any]:
        result = self._request("shutdown", {"safe_abort": bool(safe_abort)},
                              idempotency_key=secrets.token_urlsafe(12))
        self.record = None
        self.backend_unavailable = True
        return result

    def heartbeat(self) -> dict[str, Any]:
        """Refresh authenticated ownership health without altering machine state."""
        result = self.health()
        self.backend_unavailable = False
        return result
