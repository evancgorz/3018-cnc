"""Bounded recovery after controller silence or a positively detected reset.

The backend may reconnect and request a spindle stop automatically. A positive
reset indication enables guarded homing after fresh Idle/zero-RPM confirmation;
silence alone still requires an explicit operator action to home.
"""

from __future__ import annotations

from typing import Any, Callable

from ..application.machine_session import ActionOutcome


class JobWatchdogRecovery:
    """Own the non-resuming recovery sequence for a failed streamed job."""

    # Controller TCP bridges can take several seconds to become responsive
    # after GRBL resets or the motion planner is cleared. Keep retrying the
    # one saved endpoint long enough for that recovery to settle.
    MAX_RECONNECT_ATTEMPTS = 8
    RECONNECT_RETRY_DELAY = 1.0
    RECONNECT_ATTEMPT_TIMEOUT = 8.0
    SAFE_IDLE_TIMEOUT = 12.0

    def __init__(self, *, clock: Callable[[], float]) -> None:
        self._clock = clock
        self._state = "idle"
        self._message = "No watchdog recovery is active."
        self._reason = ""
        self._host = ""
        self._port = 0
        self._attempts = 0
        self._next_attempt_at: float | None = None
        self._attempt_deadline: float | None = None
        self._safe_idle_deadline: float | None = None
        self._status_before_stop: Any | None = None
        self._automatic_home = False
        self._status_before_home: Any | None = None

    @property
    def active(self) -> bool:
        return self._state in {"reconnecting", "waiting-for-m5-ack", "waiting-for-idle", "ready", "home-requested"}

    def start(self, application: Any, reason: str, *, now: float | None = None,
              auto_home: bool = False) -> None:
        """Disconnect and begin exact-endpoint Wi-Fi retry.

        ``auto_home`` is enabled only by recovery paths that have explicitly
        chosen automatic guarded homing. Homing still requires a fresh
        post-M5 Idle report at zero RPM, and the failed job is never resumed.
        """
        current = self._clock() if now is None else float(now)
        self._state = "reconnecting"
        self._reason = str(reason)
        self._automatic_home = bool(auto_home)
        self._message = (
            "Controller reset detected; reconnecting to saved Wi-Fi before guarded homing."
            if self._automatic_home else
            "Controller stopped responding; reconnecting to saved Wi-Fi."
        )
        self._attempts = 0
        self._next_attempt_at = None
        self._attempt_deadline = None
        self._safe_idle_deadline = None
        self._status_before_stop = None
        self._host = ""
        self._port = 0
        if bool(getattr(application, "simulation_active", False)):
            self._fail("Digital-twin watchdog recovery does not reconnect to a physical controller.")
            return
        settings = getattr(application, "settings", None)
        self._host = str(getattr(settings, "wifi_host", "")).strip()
        try:
            self._port = int(getattr(settings, "wifi_port", 0) or 0)
        except (TypeError, ValueError):
            self._port = 0
        if not self._host or not 1 <= self._port <= 65535:
            self._fail("No valid saved Wi-Fi endpoint is available; reconnect the controller manually.")
            return
        try:
            outcome = application.disconnect(
                "Controller reset detected; reconnecting before guarded homing"
                if self._automatic_home else
                "Controller stopped responding during the job"
            )
        except (RuntimeError, ValueError, TypeError, OSError) as exc:
            self._fail(f"Could not close the silent controller session: {exc}")
            return
        if outcome is not None and getattr(outcome, "accepted", True) is False:
            self._fail(f"Could not close the silent controller session: {getattr(outcome, 'message', 'disconnect rejected')}")
            return
        self._begin_attempt(application, current)

    def poll(self, application: Any, *, now: float | None = None,
             connection_outcome: Any | None = None) -> None:
        """Advance retries and the post-stop status gate without blocking."""
        current = self._clock() if now is None else float(now)
        if self._state == "home-requested":
            if not bool(getattr(application, "connected", False)):
                self._restart_connection(application, current, "Wi-Fi disconnected during recovery homing")
                return
            status = getattr(application, "status", None)
            if (bool(getattr(application, "status_fresh", False))
                    and status is not None and status is not self._status_before_home
                    and str(getattr(status, "state", "")) == "Idle"
                    and getattr(status, "spindle", None) == 0
                    and bool(getattr(application, "reference_trusted", False))):
                self._state = "recovered"
                self._message = "Recovery homing complete; controller is Idle with spindle stopped. Prepare the saved job continuation."
            return
        if self._state == "reconnecting":
            if bool(getattr(application, "connected", False)):
                self._on_reconnected(application, current)
                return
            if (connection_outcome is not None
                    and getattr(connection_outcome, "accepted", True) is False):
                self._retry_or_fail(application, current, str(getattr(connection_outcome, "message", "Wi-Fi reconnect failed")))
                return
            if self._attempt_deadline is not None and current >= self._attempt_deadline:
                try:
                    application.disconnect("Saved Wi-Fi recovery attempt timed out")
                except (RuntimeError, ValueError, TypeError, OSError):
                    pass
                self._retry_or_fail(application, current, "Saved Wi-Fi reconnect timed out")
                return
            if self._next_attempt_at is not None and current >= self._next_attempt_at:
                self._begin_attempt(application, current)
            return

        if self._state == "waiting-for-m5-ack":
            if not bool(getattr(application, "connected", False)):
                self._restart_connection(application, current,
                    "Wi-Fi disconnected while waiting for M5 acknowledgement")
                return
            pending_acks = getattr(application, "manual_pending_acks", None)
            if isinstance(pending_acks, int) and pending_acks == 0:
                self._state = "waiting-for-idle"
                self._status_before_stop = getattr(application, "status", None)
                try:
                    application.request_status()
                except (RuntimeError, ValueError, TypeError, OSError) as exc:
                    self._fail(f"Fresh status request after M5 acknowledgement failed: {exc}")
                    return
                self._message = "M5 acknowledged; waiting for a fresh GRBL Idle report at 0 RPM."
                return
            if self._safe_idle_deadline is not None and current >= self._safe_idle_deadline:
                self._restart_connection(application, current,
                    "M5 was not acknowledged after reconnect")
            return

        if self._state != "waiting-for-idle":
            return
        if not bool(getattr(application, "connected", False)):
            self._restart_connection(application, current,
                "Wi-Fi disconnected while confirming spindle stop")
            return
        status = getattr(application, "status", None)
        fresh = bool(getattr(application, "status_fresh", False))
        if (fresh and status is not None and status is not self._status_before_stop
                and str(getattr(status, "state", "")) == "Idle"
                and getattr(status, "spindle", None) == 0):
            self._state = "ready"
            self._safe_idle_deadline = None
            if self._automatic_home:
                self._message = "Fresh GRBL Idle and 0 RPM confirmed; starting guarded homing after controller reset."
                self._request_home(application, automatic=True)
            else:
                self._message = "Fresh GRBL Idle and 0 RPM confirmed. Continue to home or cancel recovery."
            return
        if self._safe_idle_deadline is not None and current >= self._safe_idle_deadline:
            self._restart_connection(application, current,
                "A fresh GRBL Idle report with 0 RPM was not received after M5")

    def continue_to_home(self, application: Any) -> ActionOutcome:
        """Start guarded homing only after the operator explicitly requests it."""
        if self._state != "ready" or not self._fresh_idle_zero(application):
            return ActionOutcome(False, "Continue to home is available only after a fresh Idle/0-RPM report")
        return self._request_home(application, automatic=False)

    def _request_home(self, application: Any, *, automatic: bool) -> ActionOutcome:
        """Call the existing homing guards after this recovery's fresh Idle gate."""
        try:
            outcome = application.home_machine()
        except (RuntimeError, ValueError, TypeError, OSError) as exc:
            message = f"Automatic guarded homing failed — {exc}" if automatic else f"Homing request failed — {exc}"
            self._message = message
            return ActionOutcome(False, message)
        if bool(getattr(outcome, "accepted", False)):
            self._status_before_home = getattr(application, "status", None)
            self._state = "home-requested"
            default_message = (
                "Guarded homing started automatically after controller reset"
                if automatic else "Guarded homing started by operator"
            )
            self._message = str(getattr(outcome, "message", default_message))
        else:
            rejected = str(getattr(outcome, "message", "Homing was not accepted; review the machine state"))
            self._message = f"Automatic guarded homing was blocked — {rejected}" if automatic else rejected
        return outcome

    def cancel(self) -> ActionOutcome:
        """Dismiss the ready-to-home step without issuing motion."""
        if self._state != "ready":
            return ActionOutcome(False, "Recovery can be canceled after fresh Idle/0-RPM is confirmed")
        self._state = "cancelled"
        self._message = "Recovery canceled; the job remains failed and homing was not started."
        return ActionOutcome(True, self._message)

    def snapshot(self, application: Any | None = None) -> dict[str, Any]:
        can_continue = self._state == "ready" and application is not None and self._fresh_idle_zero(application)
        can_cancel = self._state == "ready"
        return {
            "state": self._state,
            "message": self._message,
            "reason": self._reason,
            "saved_wifi_host": self._host,
            "saved_wifi_port": self._port,
            "reconnect_attempts": self._attempts,
            "max_reconnect_attempts": self.MAX_RECONNECT_ATTEMPTS,
            "can_continue_to_home": bool(can_continue),
            "can_cancel": bool(can_cancel),
            "automatic_homing": self._automatic_home,
        }

    def _begin_attempt(self, application: Any, now: float) -> None:
        if self._attempts >= self.MAX_RECONNECT_ATTEMPTS:
            self._fail("Saved Wi-Fi reconnect attempts were exhausted; reconnect the controller manually.")
            return
        self._attempts += 1
        self._next_attempt_at = None
        self._attempt_deadline = now + self.RECONNECT_ATTEMPT_TIMEOUT
        try:
            outcome = application.reconnect_saved_wifi()
        except (RuntimeError, ValueError, TypeError, OSError) as exc:
            self._retry_or_fail(application, now, f"Saved Wi-Fi reconnect could not start: {exc}")
            return
        if not bool(getattr(outcome, "accepted", False)):
            self._retry_or_fail(application, now, str(getattr(outcome, "message", "Saved Wi-Fi reconnect was rejected")))

    def _retry_or_fail(self, application: Any, now: float, message: str) -> None:
        self._attempt_deadline = None
        if self._attempts >= self.MAX_RECONNECT_ATTEMPTS:
            self._fail(f"{message}; reconnect attempts exhausted. Inspect the controller before moving.")
            return
        self._next_attempt_at = now + self.RECONNECT_RETRY_DELAY
        self._message = f"{message}; retrying saved Wi-Fi ({self._attempts}/{self.MAX_RECONNECT_ATTEMPTS})."

    def _restart_connection(self, application: Any, now: float, reason: str) -> None:
        """Retry Wi-Fi and M5 if the controller vanishes during stop verification."""
        try:
            application.disconnect(reason)
        except (RuntimeError, ValueError, TypeError, OSError):
            pass
        self._state = "reconnecting"
        self._safe_idle_deadline = None
        self._status_before_stop = None
        self._retry_or_fail(application, now, reason)

    def _on_reconnected(self, application: Any, now: float) -> None:
        service = getattr(application, "connection_service", None)
        mode = getattr(getattr(service, "mode", None), "value", getattr(service, "mode", ""))
        endpoint = str(getattr(service, "endpoint", ""))
        port = int(getattr(service, "port", 0) or 0)
        if mode != "Wi-Fi TCP" or endpoint != self._host or port != self._port:
            self._fail("Recovery connected through an unexpected endpoint; inspect the connection before moving.")
            return
        self._attempt_deadline = None
        self._next_attempt_at = None
        self._status_before_stop = getattr(application, "status", None)
        try:
            outcome = application.stop_spindle()
            if not bool(getattr(outcome, "accepted", False)):
                self._fail(str(getattr(outcome, "message", "M5 was not accepted")))
                return
        except (RuntimeError, ValueError, TypeError, OSError) as exc:
            self._fail(f"M5 request failed after reconnect: {exc}")
            return
        self._state = "waiting-for-m5-ack"
        self._safe_idle_deadline = now + self.SAFE_IDLE_TIMEOUT
        self._message = "M5 requested over saved Wi-Fi; waiting for its acknowledgement."

    def _fresh_idle_zero(self, application: Any) -> bool:
        status = getattr(application, "status", None)
        return bool(
            self._state == "ready"
            and bool(getattr(application, "connected", False))
            and bool(getattr(application, "status_fresh", False))
            and status is not None
            and status is not self._status_before_stop
            and str(getattr(status, "state", "")) == "Idle"
            and getattr(status, "spindle", None) == 0
        )

    def _fail(self, message: str) -> None:
        self._state = "failed"
        self._message = str(message)
        self._attempt_deadline = None
        self._next_attempt_at = None
        self._safe_idle_deadline = None
