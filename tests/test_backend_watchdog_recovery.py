from __future__ import annotations

from datetime import datetime
from queue import Queue
from types import SimpleNamespace
import time

from ttc3018_control.application.controller import ApplicationController
from ttc3018_control.application.machine_session import ActionOutcome
from ttc3018_control.application.state import ConnectionMode
from ttc3018_control.backend import BackendRuntime
from ttc3018_control.backend.dispatcher import ActionDispatcher
from ttc3018_control.backend.watchdog_recovery import JobWatchdogRecovery
from ttc3018_control.connection_settings import ConnectionSettings
from ttc3018_control.grbl import GrblStatus, Position
from ttc3018_control.serial_connection import SerialEvent


class _FakeRecoveryApplication:
    def __init__(self) -> None:
        self.settings = SimpleNamespace(wifi_host="192.168.1.22", wifi_port=23)
        self.connection_service = SimpleNamespace(
            mode=ConnectionMode.WIFI, endpoint="192.168.1.22", port=23,
            wifi_connecting=False,
        )
        self.connected = False
        self.status = None
        self.status_fresh = False
        self.manual_pending_acks = 0
        self.disconnects: list[str] = []
        self.reconnects = 0
        self.stops = 0
        self.status_requests = 0
        self.homes = 0

    def disconnect(self, reason: str):
        self.disconnects.append(reason)
        self.connected = False
        self.connection_service.wifi_connecting = False
        return ActionOutcome(True, "Disconnected")

    def reconnect_saved_wifi(self):
        self.reconnects += 1
        self.connection_service.wifi_connecting = True
        return ActionOutcome(True, "Connecting")

    def stop_spindle(self):
        self.stops += 1
        self.manual_pending_acks += 1
        return ActionOutcome(True, "M5 requested")

    def request_status(self):
        self.status_requests += 1

    def home_machine(self):
        self.homes += 1
        return ActionOutcome(True, "Homing started")


def test_watchdog_recovery_waits_for_fresh_idle_zero_and_never_auto_homes() -> None:
    app = _FakeRecoveryApplication()
    recovery = JobWatchdogRecovery(clock=lambda: 0.0)

    recovery.start(app, "controller silence", now=10.0)
    assert recovery.snapshot(app)["state"] == "reconnecting"
    assert app.reconnects == 1
    assert app.homes == 0

    app.connected = True
    app.connection_service.wifi_connecting = False
    recovery.poll(app, now=11.0)
    assert recovery.snapshot(app)["state"] == "waiting-for-m5-ack"
    assert app.stops == 1
    assert app.status_requests == 0
    assert app.homes == 0

    app.manual_pending_acks = 0
    recovery.poll(app, now=11.5)
    assert recovery.snapshot(app)["state"] == "waiting-for-idle"
    assert app.status_requests == 1

    app.status = SimpleNamespace(state="Run", spindle=0)
    app.status_fresh = True
    recovery.poll(app, now=12.0)
    assert recovery.snapshot(app)["state"] == "waiting-for-idle"
    assert recovery.snapshot(app)["can_continue_to_home"] is False

    app.status = SimpleNamespace(state="Idle", spindle=1000)
    recovery.poll(app, now=13.0)
    assert recovery.snapshot(app)["state"] == "waiting-for-idle"

    app.status = SimpleNamespace(state="Idle", spindle=0)
    recovery.poll(app, now=14.0)
    snapshot = recovery.snapshot(app)
    assert snapshot["state"] == "ready"
    assert snapshot["can_continue_to_home"] is True
    assert snapshot["can_cancel"] is True
    assert snapshot["automatic_homing"] is False
    assert app.homes == 0

    result = recovery.continue_to_home(app)
    assert result.accepted is True
    assert app.homes == 1
    assert recovery.snapshot(app)["state"] == "home-requested"


def test_recovery_homing_completes_only_after_new_fresh_idle_and_trusted_reference() -> None:
    app = _FakeRecoveryApplication()
    recovery = JobWatchdogRecovery(clock=lambda: 0.0)
    app.connected = True
    app.status_fresh = True
    app.status = SimpleNamespace(state="Idle", spindle=0)
    recovery._state = "ready"
    assert recovery.continue_to_home(app).accepted
    assert recovery.active
    app.reference_trusted = True
    recovery.poll(app)
    assert recovery.snapshot()["state"] == "home-requested"  # pre-home status is insufficient
    app.status = SimpleNamespace(state="Home", spindle=0)
    recovery.poll(app)
    assert recovery.snapshot()["state"] == "home-requested"
    app.status = SimpleNamespace(state="Idle", spindle=0)
    app.reference_trusted = False
    recovery.poll(app)
    assert recovery.snapshot()["state"] == "home-requested"
    app.reference_trusted = True
    app.status_fresh = False
    recovery.poll(app)
    assert recovery.snapshot()["state"] == "home-requested"
    app.status_fresh = True
    recovery.poll(app)
    assert recovery.snapshot()["state"] == "recovered"
    assert not recovery.active
    assert app.homes == 1


def test_watchdog_recovery_retry_budget_and_cancel_do_not_home() -> None:
    app = _FakeRecoveryApplication()
    recovery = JobWatchdogRecovery(clock=lambda: 0.0)
    recovery.start(app, "controller silence", now=0.0)
    for failed_attempt in range(1, recovery.MAX_RECONNECT_ATTEMPTS + 1):
        retry_at = float(failed_attempt)
        recovery.poll(app, now=retry_at, connection_outcome=ActionOutcome(False, "connection failed"))
        if failed_attempt < recovery.MAX_RECONNECT_ATTEMPTS:
            recovery.poll(app, now=retry_at + recovery.RECONNECT_RETRY_DELAY)
    snapshot = recovery.snapshot(app)
    assert app.reconnects == recovery.MAX_RECONNECT_ATTEMPTS
    assert snapshot["state"] == "failed"
    assert snapshot["can_continue_to_home"] is False
    assert app.homes == 0


def test_watchdog_retries_saved_wifi_and_m5_when_stop_ack_times_out() -> None:
    app = _FakeRecoveryApplication()
    recovery = JobWatchdogRecovery(clock=lambda: 0.0)
    recovery.start(app, "controller silence", now=0.0, auto_home=True)

    app.connected = True
    app.connection_service.wifi_connecting = False
    recovery.poll(app, now=1.0)
    assert app.stops == 1
    assert recovery.snapshot(app)["state"] == "waiting-for-m5-ack"

    recovery.poll(app, now=1.0 + recovery.SAFE_IDLE_TIMEOUT)
    assert recovery.snapshot(app)["state"] == "reconnecting"
    assert app.connected is False
    assert app.reconnects == 1

    recovery.poll(app, now=1.0 + recovery.SAFE_IDLE_TIMEOUT + recovery.RECONNECT_RETRY_DELAY)
    assert app.reconnects == 2
    app.connected = True
    app.connection_service.wifi_connecting = False
    recovery.poll(app, now=15.0)
    assert app.stops == 2
    assert recovery.snapshot(app)["state"] == "waiting-for-m5-ack"
    assert app.homes == 0

    app = _FakeRecoveryApplication()
    recovery = JobWatchdogRecovery(clock=lambda: 0.0)
    recovery.start(app, "controller silence", now=0.0)
    app.connected = True
    recovery.poll(app, now=1.0)
    app.manual_pending_acks = 0
    recovery.poll(app, now=1.5)
    app.status = SimpleNamespace(state="Idle", spindle=0)
    app.status_fresh = True
    recovery.poll(app, now=2.0)
    result = recovery.cancel()
    assert result.accepted is True
    assert recovery.snapshot(app)["state"] == "cancelled"
    assert app.homes == 0


def test_detected_reset_auto_homes_only_after_m5_and_fresh_idle_zero() -> None:
    app = _FakeRecoveryApplication()
    recovery = JobWatchdogRecovery(clock=lambda: 0.0)

    recovery.start(app, "GRBL controller reset detected", now=10.0, auto_home=True)
    assert app.disconnects
    assert app.reconnects == 1
    assert app.homes == 0
    assert recovery.snapshot(app)["automatic_homing"] is True

    app.connected = True
    app.connection_service.wifi_connecting = False
    recovery.poll(app, now=11.0)
    assert app.stops == 1
    assert app.homes == 0

    app.manual_pending_acks = 0
    recovery.poll(app, now=11.5)
    assert app.status_requests == 1
    app.status = SimpleNamespace(state="Run", spindle=0)
    app.status_fresh = True
    recovery.poll(app, now=12.0)
    assert app.homes == 0
    app.status = SimpleNamespace(state="Idle", spindle=1000)
    recovery.poll(app, now=12.5)
    assert app.homes == 0
    app.status = SimpleNamespace(state="Idle", spindle=0)
    recovery.poll(app, now=13.0)

    snapshot = recovery.snapshot(app)
    assert app.homes == 1
    assert snapshot["state"] == "home-requested"
    assert snapshot["automatic_homing"] is True
    assert snapshot["can_continue_to_home"] is False
    assert snapshot["can_cancel"] is False


def test_runtime_starts_auto_home_recovery_only_from_detected_reset_line(tmp_path, monkeypatch) -> None:
    runtime = BackendRuntime(tmp_path)
    app = runtime.application
    events = Queue()
    events.put(SerialEvent("rx", "Grbl 1.1h ['$' for help]", datetime.now()))
    monkeypatch.setattr(app, "transport_events", lambda: events)
    calls: list[str] = []
    monkeypatch.setattr(app, "disconnect", lambda reason: calls.append(f"disconnect:{reason}") or ActionOutcome(True, "ok"))
    monkeypatch.setattr(app, "reconnect_saved_wifi", lambda: calls.append("reconnect") or ActionOutcome(True, "connecting"))

    runtime._drain_transport_events()

    recovery = runtime._job_watchdog_recovery.snapshot(app)
    assert recovery["state"] == "reconnecting"
    assert recovery["automatic_homing"] is True
    assert recovery["reason"] == "GRBL controller reset detected"
    assert calls[0].startswith("disconnect:")
    assert calls[1] == "reconnect"


def test_runtime_watchdog_starts_saved_wifi_recovery_and_exposes_snapshot(tmp_path, monkeypatch) -> None:
    runtime = BackendRuntime(tmp_path)
    app = runtime.application
    calls: list[str] = []
    monkeypatch.setattr(app, "disconnect", lambda reason: calls.append(f"disconnect:{reason}") or ActionOutcome(True, "ok"))
    monkeypatch.setattr(app, "reconnect_saved_wifi", lambda: calls.append("reconnect") or ActionOutcome(True, "connecting"))
    monkeypatch.setattr(app, "check_job_watchdog", lambda: "controller produced no responses")

    snapshot = runtime.poll_once(now=100.0)
    recovery = snapshot["watchdog_recovery"]
    assert recovery["state"] == "reconnecting"
    assert recovery["reconnect_attempts"] == 1
    assert recovery["saved_wifi_host"] == app.settings.wifi_host
    assert recovery["automatic_homing"] is True
    assert calls[0].startswith("disconnect:")
    assert calls[1] == "reconnect"


def test_saved_wifi_reconnect_uses_only_the_configured_endpoint(tmp_path, monkeypatch) -> None:
    app = ApplicationController(tmp_path)
    app.settings = ConnectionSettings("10.0.0.41", 2323, "USB serial", "")
    calls: list[tuple[str, int, bool]] = []
    monkeypatch.setattr(
        app.connection_service, "begin_wifi",
        lambda host, port, *, discover=True: (
            calls.append((host, port, discover)) or ActionOutcome(True, "connecting")
        ),
    )

    result = app.reconnect_saved_wifi()
    assert result.accepted is True
    assert calls == [("10.0.0.41", 2323, False)]


class _ConnectedTransport:
    connected = True


def test_dispatcher_requires_recovery_ready_and_routes_explicit_home_or_cancel(tmp_path, monkeypatch) -> None:
    runtime = BackendRuntime(tmp_path)
    app = runtime.application
    app.connection_service.transport = _ConnectedTransport()
    app.connection_service.mode = ConnectionMode.WIFI
    app.connection_service.endpoint = app.settings.wifi_host
    app.connection_service.port = app.settings.wifi_port
    app.status = GrblStatus("Idle", Position(0, 0, 0), Position(0, 0, 0),
                            Position(0, 0, 0), 0, 0, "", {})
    app._status_generation = app._session_generation
    app._last_status_received_at = time.monotonic()
    monkeypatch.setattr(app, "home_machine", lambda: ActionOutcome(True, "Homing started"))
    recovery = runtime._job_watchdog_recovery
    recovery._state = "ready"
    recovery._status_before_stop = None
    dispatcher = ActionDispatcher(runtime)

    assert runtime._refresh_snapshot()["watchdog_recovery"]["can_continue_to_home"] is True
    assert dispatcher.invoke("continue-to-home")["accepted"] is True
    assert runtime._refresh_snapshot()["watchdog_recovery"]["state"] == "home-requested"

    recovery._state = "ready"
    recovery._status_before_stop = None
    assert dispatcher.invoke("cancel-recovery")["accepted"] is True
    assert runtime._refresh_snapshot()["watchdog_recovery"]["state"] == "cancelled"

    recovery._state = "reconnecting"
    rejected = dispatcher.invoke("continue-to-home")
    assert rejected["accepted"] is False
    assert runtime._refresh_snapshot()["watchdog_recovery"]["state"] == "reconnecting"
