"""Authenticated loopback HTTP server for a :class:`BackendRuntime`."""

from __future__ import annotations

from http import HTTPStatus
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
import secrets
import threading
from typing import Any
import uuid

from .discovery import BackendOwnershipError, DiscoveryRecord, DiscoveryStore, OwnerRecord
from .dispatcher import ActionDispatcher, ActionRejected
from .protocol import (MAX_REQUEST_BYTES, MAX_RESPONSE_BYTES, ProtocolError,
                       PROTOCOL_VERSION, SCHEMA_VERSION, decode_message,
                       encode_message, response, validate_request, validate_versions)
from .runtime import BackendRuntime


def _authenticated_health(record: DiscoveryRecord, *, timeout: float = 0.35) -> bool:
    """Probe an advertised owner using its token and exact protocol/session."""
    connection = http.client.HTTPConnection(record.host, record.port, timeout=timeout)
    try:
        connection.request("GET", "/v1/health", headers={
            "X-Pine-Token": record.token, "X-Pine-Protocol": str(PROTOCOL_VERSION),
        })
        stream = connection.getresponse()
        if stream.status != HTTPStatus.OK:
            return False
        result = decode_message(stream.read(MAX_RESPONSE_BYTES + 1))
        validate_versions(result)
        payload = result.get("result")
        return bool(result.get("ok")) and isinstance(payload, dict) \
            and payload.get("pid") == record.pid \
            and payload.get("session_id") == record.session_id
    except (OSError, http.client.HTTPException, ProtocolError, ValueError, TypeError):
        return False
    finally:
        connection.close()


class _LoopbackServer(ThreadingHTTPServer):
    allow_reuse_address = False
    daemon_threads = True


class BackendServer:
    """Own one ephemeral loopback listener and its discovery record."""

    def __init__(self, runtime: BackendRuntime, *, root=None, token: str | None = None,
                 session_id: str | None = None) -> None:
        self.runtime = runtime
        self.discovery = DiscoveryStore(root or runtime.root)
        self.token = token or secrets.token_urlsafe(32)
        self.session_id = session_id or uuid.uuid4().hex
        self.runtime.set_session_id(self.session_id)
        self._http: _LoopbackServer | None = None
        self._thread: threading.Thread | None = None
        self._serve_started = threading.Event()
        self._poll_thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.record: DiscoveryRecord | None = None
        self._owner_record: OwnerRecord | None = None
        self.dispatcher = ActionDispatcher(runtime)

    @property
    def address(self) -> tuple[str, int]:
        if self._http is None:
            raise RuntimeError("backend server is not started")
        host, port = self._http.server_address[:2]
        return str(host), int(port)

    @property
    def running(self) -> bool:
        return self._http is not None and not self._stop.is_set()

    def start(self, *, poll: bool = True) -> DiscoveryRecord:
        if self._http is not None:
            return self.record  # type: ignore[return-value]
        existing = self.discovery.read()
        if existing is not None:
            if self.discovery.pid_is_alive(existing.pid):
                if _authenticated_health(existing):
                    raise BackendOwnershipError(
                        f"a healthy backend already owns this root (pid {existing.pid})"
                    )
                raise BackendOwnershipError(
                    f"a backend process is alive but its health endpoint is unavailable (pid {existing.pid})"
                )
            self.discovery.remove(existing)
        self._stop.clear()
        owner = self
        self._owner_record = OwnerRecord(os.getpid(), self.session_id)
        self.discovery.acquire_owner(self._owner_record)

        class Handler(BaseHTTPRequestHandler):
            server_version = "PineBackend/1"
            protocol_version = "HTTP/1.1"

            def setup(self):
                super().setup()
                self.connection.settimeout(2.0)

            def log_message(self, format, *args):  # pragma: no cover - intentionally quiet
                return

            def _authorized(self) -> bool:
                return secrets.compare_digest(str(self.headers.get("X-Pine-Token", "")), owner.token)

            def _send(self, status: int, body: dict[str, Any]) -> None:
                try:
                    encoded = encode_message(body, limit=MAX_RESPONSE_BYTES)
                except ProtocolError:
                    encoded = encode_message(response(ok=False, error="response exceeds bounded size"))
                    status = HTTPStatus.INTERNAL_SERVER_ERROR
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(encoded)

            def _reject(self, status: int, message: str, *, code: str = "request_rejected",
                        retryable: bool = False) -> None:
                self._send(status, response(ok=False, error={
                    "code": code, "message": message, "retryable": retryable, "details": {},
                }))

            def do_GET(self):  # noqa: N802
                if not self._authorized():
                    self._reject(HTTPStatus.UNAUTHORIZED, "authentication required")
                    return
                if self.path not in {"/v1/health", "/v1/version"}:
                    self._reject(HTTPStatus.NOT_FOUND, "unknown endpoint")
                    return
                expected = str(self.headers.get("X-Pine-Protocol", PROTOCOL_VERSION))
                if expected != str(PROTOCOL_VERSION):
                    self._reject(HTTPStatus.UPGRADE_REQUIRED, "protocol version mismatch")
                    return
                self._send(HTTPStatus.OK, response(ok=True, result={
                    "schema_version": SCHEMA_VERSION, "protocol_version": PROTOCOL_VERSION,
                    "pid": __import__("os").getpid(), "session_id": owner.session_id,
                    "backend": "pine-backend",
                }))

            def do_POST(self):  # noqa: N802
                if not self._authorized():
                    self._reject(HTTPStatus.UNAUTHORIZED, "authentication required")
                    return
                if self.path != "/v1":
                    self._reject(HTTPStatus.NOT_FOUND, "unknown endpoint")
                    return
                try:
                    length = int(self.headers.get("Content-Length", "-1"))
                except ValueError:
                    length = -1
                if length < 0 or length > MAX_REQUEST_BYTES:
                    self._reject(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "request exceeds bounded size")
                    return
                try:
                    message = decode_message(self.rfile.read(length))
                    validate_request(message)
                    operation = message.get("operation")
                    payload = message.get("payload", {})
                    if not isinstance(operation, str) or not isinstance(payload, dict):
                        raise ProtocolError("operation and payload are required")
                    if operation == "health":
                        result = {"schema_version": SCHEMA_VERSION, "protocol_version": PROTOCOL_VERSION,
                                  "pid": __import__("os").getpid(), "session_id": owner.session_id}
                    elif operation == "snapshot":
                        result = owner.runtime.snapshot()
                    elif operation == "events":
                        sequence = payload.get("sequence", 0)
                        limit = payload.get("limit", 100)
                        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
                            raise ProtocolError("event sequence must be a nonnegative integer")
                        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
                            raise ProtocolError("event limit must be between 1 and 500")
                        result = owner.runtime.events_since(sequence, limit)
                    elif operation == "action":
                        name = payload.get("name")
                        arguments = payload.get("arguments", {})
                        if not isinstance(name, str) or not isinstance(arguments, dict):
                            raise ProtocolError("action name and arguments are required")
                        result = owner.dispatcher.invoke(
                            name, arguments,
                            expected_revision=message.get("expected_revision"),
                            idempotency_key=str(message.get("idempotency_key", "")),
                        )
                    elif operation == "confirmation":
                        result = owner.dispatcher.confirmation_response(payload.get("token", ""), payload.get("accepted"))
                    elif operation == "shutdown":
                        result = owner.dispatcher.invoke("shutdown", payload)
                    else:
                        raise ProtocolError("unknown operation")
                    self._send(HTTPStatus.OK, response(ok=True, result=result))
                    if operation == "shutdown" and result.get("accepted"):
                        threading.Thread(target=owner.stop, kwargs={"shutdown_runtime": False}, daemon=True).start()
                except (ProtocolError, ActionRejected, ValueError, TypeError) as exc:
                    message = str(exc)
                    conflict = "revision mismatch" in message or "expired" in message
                    self._reject(HTTPStatus.CONFLICT if conflict else HTTPStatus.BAD_REQUEST,
                                 message, code="state_conflict" if conflict else "invalid_request",
                                 retryable=conflict)
                except Exception as exc:  # keep malformed client traffic from killing the server
                    self._reject(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

        try:
            self._http = _LoopbackServer(("127.0.0.1", 0), Handler)
            host, port = self.address
            self.record = DiscoveryRecord(SCHEMA_VERSION, PROTOCOL_VERSION, os.getpid(), host, port, self.token, self.session_id)
            self.discovery.write(self.record)
            self._serve_started.clear()
            http_instance = self._http
            def serve() -> None:
                self._serve_started.set()
                http_instance.serve_forever()
            self._thread = threading.Thread(target=serve, name="pine-backend-http", daemon=True)
            self._thread.start()
            self._serve_started.wait(timeout=1.0)
            shutdown_event = getattr(self._http, "_BaseServer__is_shut_down")
            deadline = threading.Event()
            # ``serve_forever`` clears this event at entry. Waiting for that
            # transition makes the later shutdown call race-free.
            while shutdown_event.is_set() and self._thread.is_alive():
                if deadline.wait(0.001):
                    break
            if poll:
                self._poll_thread = threading.Thread(target=self.runtime.run, kwargs={"stop_event": self._stop},
                                                      name="pine-backend-runtime", daemon=True)
                self._poll_thread.start()
            return self.record
        except Exception:
            if self._http is not None:
                self._http.server_close()
                self._http = None
            self.discovery.remove_owner(self._owner_record)
            self._owner_record = None
            raise

    def stop(self, *, shutdown_runtime: bool = True) -> None:
        if self._http is None:
            self.discovery.remove_owner(self._owner_record)
            self._owner_record = None
            return
        if shutdown_runtime and not self.runtime.closed:
            self.runtime.shutdown()
        self._stop.set()
        http = self._http
        self._http = None
        shutdown_event = getattr(http, "_BaseServer__is_shut_down")
        if self._thread is not None and not shutdown_event.is_set():
            # ``shutdown`` waits on an internal event and can block the
            # caller if a platform races the first serve-forever iteration.
            # Run that wait on a daemon helper while closing the listener and
            # releasing the exact owner marker synchronously.
            threading.Thread(target=http.shutdown, name="pine-backend-shutdown",
                             daemon=True).start()
            http.server_close()
        else:
            # The startup path can fail before serve_forever enters its loop.
            setattr(http, "_BaseServer__shutdown_request", True)
            http.server_close()
        http.server_close()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=0.5)
        if self._poll_thread and self._poll_thread is not threading.current_thread():
            self._poll_thread.join(timeout=0.5)
        if self.record is not None:
            self.discovery.remove(self.record)
        self.discovery.remove_owner(self._owner_record)
        self._owner_record = None
