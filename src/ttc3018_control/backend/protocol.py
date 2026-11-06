"""Small, versioned wire protocol used by the headless backend.

The protocol intentionally uses ordinary JSON values only.  Bytes and rich
application dataclasses are converted at the boundary, keeping the transport
independent from Qt and straightforward to exercise with loopback tests.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

SCHEMA_VERSION = 1
PROTOCOL_VERSION = 1
MAX_REQUEST_BYTES = 256 * 1024
MAX_RESPONSE_BYTES = 1024 * 1024


class ProtocolError(ValueError):
    """A malformed or unsupported protocol message."""


def encode_message(value: Any, *, limit: int = MAX_RESPONSE_BYTES) -> bytes:
    try:
        data = json.dumps(value, ensure_ascii=False, separators=(",", ":"),
                         allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ProtocolError(f"message is not JSON-safe: {exc}") from exc
    if len(data) > limit:
        raise ProtocolError("message exceeds bounded protocol size")
    return data


def decode_message(data: bytes, *, limit: int = MAX_REQUEST_BYTES) -> dict[str, Any]:
    if not isinstance(data, (bytes, bytearray)) or len(data) > limit:
        raise ProtocolError("request exceeds bounded protocol size")
    try:
        value = json.loads(bytes(data).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError("request is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ProtocolError("request must be a JSON object")
    return value


REQUEST_FIELDS = frozenset({"schema_version", "protocol_version", "operation", "payload",
                           "request_id", "expected_revision", "idempotency_key"})


def request(operation: str, payload: dict[str, Any] | None = None, *,
            request_id: str = "", expected_revision: int | None = None,
            idempotency_key: str = "") -> dict[str, Any]:
    if not isinstance(operation, str) or not operation or len(operation) > 80:
        raise ProtocolError("operation must be a bounded non-empty string")
    if payload is not None and not isinstance(payload, dict):
        raise ProtocolError("payload must be a JSON object")
    result = {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "operation": operation,
        "payload": payload or {},
    }
    if request_id:
        result["request_id"] = request_id
    if expected_revision is not None:
        result["expected_revision"] = int(expected_revision)
    if idempotency_key:
        result["idempotency_key"] = idempotency_key
    return result


def response(*, ok: bool, result: Any = None, error: str | Mapping[str, Any] = "") -> dict[str, Any]:
    if isinstance(error, Mapping):
        error_detail = dict(error)
        error_text = str(error_detail.get("message", "Backend request failed"))
    else:
        error_text = str(error) if error else ""
        error_detail = ({"code": "request_failed", "message": error_text,
                         "retryable": False, "details": {}} if error_text else {})
    return {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "ok": bool(ok),
        "result": result,
        # Keep the short error string for existing clients while exposing the
        # structured form to newer clients.
        "error": error_text,
        "error_detail": error_detail,
    }


def validate_versions(message: dict[str, Any]) -> None:
    if message.get("schema_version") != SCHEMA_VERSION:
        raise ProtocolError("schema version mismatch")
    if message.get("protocol_version") != PROTOCOL_VERSION:
        raise ProtocolError("protocol version mismatch")


def validate_request(message: dict[str, Any]) -> None:
    """Reject unknown envelope fields before dispatching an operation."""
    validate_versions(message)
    unknown = set(message) - REQUEST_FIELDS
    if unknown:
        raise ProtocolError(f"unsupported request fields: {', '.join(sorted(unknown))}")
    operation = message.get("operation")
    payload = message.get("payload", {})
    if not isinstance(operation, str) or not operation or len(operation) > 80:
        raise ProtocolError("operation must be a bounded non-empty string")
    if not isinstance(payload, dict):
        raise ProtocolError("payload must be a JSON object")
    request_id = message.get("request_id", "")
    idempotency_key = message.get("idempotency_key", "")
    if request_id and (not isinstance(request_id, str) or len(request_id) > 128):
        raise ProtocolError("request_id is invalid")
    if idempotency_key and (not isinstance(idempotency_key, str) or len(idempotency_key) > 128):
        raise ProtocolError("idempotency_key is invalid")
    expected_revision = message.get("expected_revision")
    if expected_revision is not None and (isinstance(expected_revision, bool) or not isinstance(expected_revision, int) or expected_revision < 0):
        raise ProtocolError("expected_revision is invalid")
