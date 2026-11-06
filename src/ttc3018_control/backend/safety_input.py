"""Qt-free safety-input contracts for an independently observable E-stop.

This module deliberately contains no GPIO, serial, USB, network, or machine
I/O code.  A commissioned adapter supplies two normally-closed channel
observations; the backend owns the state machine and treats missing or
untrustworthy feedback as unsafe.  ``FakeSafetyInputAdapter`` is intentionally
the only concrete adapter in this software-only slice.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import json
import math
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol


class SafetyInputState(StrEnum):
    CLEAR = "clear"
    ACTIVE = "active"
    LATCHED = "latched"
    UNKNOWN = "unknown"
    FAULT = "fault"


@dataclass(frozen=True)
class SafetyInputSample:
    """One adapter observation.

    ``*_closed`` is ``True`` when that normally-closed safety channel is
    electrically healthy.  ``False`` means the channel is open/active and
    ``None`` means that channel could not be observed.
    """

    channel_a_closed: bool | None
    channel_b_closed: bool | None
    timestamp: float
    session_id: str
    source: str = "safety-input-adapter"
    raw: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not math.isfinite(float(self.timestamp)):
            raise ValueError("safety input timestamp must be finite")
        if not isinstance(self.session_id, str):
            raise ValueError("safety input session_id must be a string")
        if not isinstance(self.source, str) or not self.source.strip():
            raise ValueError("safety input source must be a non-empty string")
        for value in (self.channel_a_closed, self.channel_b_closed):
            if value is not None and not isinstance(value, bool):
                raise ValueError("safety input channels must be boolean or null")
        object.__setattr__(self, "raw", dict(self.raw))


@dataclass(frozen=True)
class SafetyInputStatus:
    """Backend-published interpretation of the independent safety input."""

    state: SafetyInputState
    raw_state: SafetyInputState
    timestamp: float
    sample_timestamp: float | None
    observed_session_id: str
    session_id: str
    channel_a_closed: bool | None
    channel_b_closed: bool | None
    stable_for: float
    debounce_seconds: float
    stale_after: float
    reason: str
    sample_count: int
    adapter_available: bool
    latched: bool
    commissioned: bool
    power_removal: str = "unknown"
    transition_id: int = 0
    raw: Mapping[str, Any] = field(default_factory=dict)
    source: str = ""

    @property
    def blocks_motion(self) -> bool:
        """Whether backend actions must fail closed for this status."""

        return self.commissioned and (
            self.latched or self.state is not SafetyInputState.CLEAR or self.power_removal != "confirmed"
        )

    @property
    def trustworthy_clear(self) -> bool:
        return (
            self.commissioned and self.state is SafetyInputState.CLEAR and not self.latched
            and self.power_removal == "confirmed"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "raw_state": self.raw_state.value,
            "timestamp": self.timestamp,
            "sample_timestamp": self.sample_timestamp,
            "observed_session_id": self.observed_session_id,
            "session_id": self.session_id,
            "channel_a_closed": self.channel_a_closed,
            "channel_b_closed": self.channel_b_closed,
            "stable_for": self.stable_for,
            "debounce_seconds": self.debounce_seconds,
            "stale_after": self.stale_after,
            "reason": self.reason,
            "sample_count": self.sample_count,
            "adapter_available": self.adapter_available,
            "latched": self.latched,
            "commissioned": self.commissioned,
            "power_removal": self.power_removal,
            "transition_id": self.transition_id,
            "blocks_motion": self.blocks_motion,
            "trustworthy_clear": self.trustworthy_clear,
            "raw": dict(self.raw),
            "source": self.source,
        }


class SafetyInputAdapter(Protocol):
    """Minimal adapter boundary owned and polled by the backend."""

    def read(self, now: float | None = None) -> SafetyInputSample | None:
        """Return the newest sample, or ``None`` when feedback is lost."""

    def close(self) -> None:
        """Release adapter resources."""


class FakeSafetyInputAdapter:
    """Deterministic software adapter for unit tests and the digital twin."""

    def __init__(self, *, session_id: str = "fake-session", clock: Callable[[], float] | None = None) -> None:
        self.session_id = session_id
        self._clock = clock
        self._sample: SafetyInputSample | None = None
        self._lost = True
        self.closed = False

    def set_channels(
        self,
        channel_a_closed: bool | None,
        channel_b_closed: bool | None,
        *,
        timestamp: float | None = None,
        raw: Mapping[str, Any] | None = None,
    ) -> SafetyInputSample:
        if timestamp is None:
            if self._clock is None:
                raise ValueError("timestamp or a clock is required")
            timestamp = self._clock()
        self._sample = SafetyInputSample(
            channel_a_closed, channel_b_closed, float(timestamp), self.session_id,
            source="fake-safety-input", raw=raw or {},
        )
        self._lost = False
        return self._sample

    def lose_feedback(self) -> None:
        self._lost = True

    def read(self, now: float | None = None) -> SafetyInputSample | None:
        del now
        if self.closed or self._lost:
            return None
        return self._sample

    def close(self) -> None:
        self.closed = True


class SafetyInputMonitor:
    """Fail-closed dual-channel state machine with explicit recovery."""

    def __init__(
        self,
        *,
        session_id: str = "",
        commissioned: bool = False,
        debounce_seconds: float = 0.05,
        stale_after: float = 0.5,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._clock = clock
        self._session_id = str(session_id)
        self._commissioned = bool(commissioned)
        self.debounce_seconds = self._finite_nonnegative(debounce_seconds, "debounce_seconds")
        self.stale_after = self._finite_positive(stale_after, "stale_after")
        self._latched = False
        self._sample_count = 0
        self._stable_since: float | None = None
        self._pending_clear = False
        self._last_unsafe_reason = ""
        self._transition_id = 0
        self._classification: tuple[Any, ...] | None = None
        self._status = SafetyInputStatus(
            state=SafetyInputState.UNKNOWN,
            raw_state=SafetyInputState.UNKNOWN,
            timestamp=0.0,
            sample_timestamp=None,
            observed_session_id="",
            session_id=self._session_id,
            channel_a_closed=None,
            channel_b_closed=None,
            stable_for=0.0,
            debounce_seconds=self.debounce_seconds,
            stale_after=self.stale_after,
            reason="Safety input adapter is not commissioned",
            sample_count=0,
            adapter_available=False,
            latched=False,
            commissioned=self._commissioned,
            transition_id=0,
        )

    @staticmethod
    def _finite_nonnegative(value: float, name: str) -> float:
        value = float(value)
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"{name} must be finite and nonnegative")
        return value

    @staticmethod
    def _finite_positive(value: float, name: str) -> float:
        value = float(value)
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"{name} must be finite and positive")
        return value

    @property
    def status(self) -> SafetyInputStatus:
        return self._status

    @property
    def latched(self) -> bool:
        return self._latched

    def set_session_id(self, session_id: str) -> SafetyInputStatus:
        self._session_id = str(session_id)
        # A session transition invalidates the last observation.  A previous
        # trip remains latched, so restart/reconnect cannot restore trust.
        self._stable_since = None
        self._pending_clear = False
        return self._publish(
            now=self._status.timestamp,
            state=SafetyInputState.UNKNOWN,
            raw_state=SafetyInputState.UNKNOWN,
            sample=None,
            observed_session_id="",
            adapter_available=False,
            reason=("Safety input session changed; fresh feedback is required"
                    if self._latched else "Safety input session changed; waiting for fresh feedback"),
        )

    def set_commissioned(self, commissioned: bool) -> SafetyInputStatus:
        self._commissioned = bool(commissioned)
        self._stable_since = None
        self._pending_clear = False
        if not self._commissioned:
            self._latched = False
        return self._publish(
            now=self._status.timestamp,
            state=SafetyInputState.UNKNOWN,
            raw_state=SafetyInputState.UNKNOWN,
            sample=None,
            observed_session_id="",
            adapter_available=False,
            reason=("Safety input adapter is not commissioned"
                    if not self._commissioned else "Commissioning enabled; fresh feedback is required"),
        )

    def restore_latched(self, *, reason: str, timestamp: float = 0.0) -> SafetyInputStatus:
        """Restore a prior trip without treating restart as a physical reset."""

        self._latched = True
        self._stable_since = None
        self._pending_clear = False
        self._last_unsafe_reason = str(reason)
        return self._publish(
            now=float(timestamp), state=SafetyInputState.UNKNOWN,
            raw_state=SafetyInputState.UNKNOWN, sample=None,
            observed_session_id="", adapter_available=False,
            reason=f"{reason}; fresh feedback and explicit acknowledgement required",
        )

    def observe_adapter(self, adapter: SafetyInputAdapter, *, now: float | None = None) -> SafetyInputStatus:
        current = self._now(now)
        try:
            sample = adapter.read(current)
        except Exception as exc:  # adapter failures are unsafe, never clear
            return self.observe(None, now=current, adapter_error=f"Safety input adapter failure: {exc}")
        return self.observe(sample, now=current)

    def observe(
        self,
        sample: SafetyInputSample | None,
        *,
        now: float | None = None,
        adapter_error: str | None = None,
    ) -> SafetyInputStatus:
        current = self._now(now)
        if sample is not None and not isinstance(sample, SafetyInputSample):
            raise TypeError("safety input sample must be SafetyInputSample or None")
        if sample is not None:
            self._sample_count += 1

        if not self._commissioned:
            return self._publish(
                now=current, state=SafetyInputState.UNKNOWN,
                raw_state=SafetyInputState.UNKNOWN, sample=sample,
                observed_session_id=sample.session_id if sample else "",
                adapter_available=sample is not None,
                reason="Safety input observed but adapter is not commissioned",
            )

        if adapter_error:
            return self._unsafe(
                current, SafetyInputState.FAULT, adapter_error, sample=sample,
                observed_session_id=sample.session_id if sample else "",
                adapter_available=False,
            )
        if sample is None:
            return self._unsafe(
                current, SafetyInputState.UNKNOWN,
                "Safety input adapter feedback lost", sample=None,
                observed_session_id="", adapter_available=False,
            )
        if sample.session_id != self._session_id:
            return self._unsafe(
                current, SafetyInputState.UNKNOWN,
                "Safety input sample belongs to a different backend session",
                sample=sample, observed_session_id=sample.session_id,
                adapter_available=True,
            )
        if current < sample.timestamp or current - sample.timestamp > self.stale_after:
            return self._unsafe(
                current, SafetyInputState.UNKNOWN,
                "Safety input feedback is stale or timestamped in the future",
                sample=sample, observed_session_id=sample.session_id,
                adapter_available=True,
            )
        a, b = sample.channel_a_closed, sample.channel_b_closed
        if a is None and b is None:
            return self._unsafe(
                current, SafetyInputState.UNKNOWN,
                "Both safety input channels are unavailable", sample=sample,
                observed_session_id=sample.session_id, adapter_available=True,
            )
        if a is None or b is None:
            return self._unsafe(
                current, SafetyInputState.FAULT,
                "One safety input channel is unavailable", sample=sample,
                observed_session_id=sample.session_id, adapter_available=True,
            )
        if a != b:
            return self._unsafe(
                current, SafetyInputState.FAULT,
                "Safety input channels disagree", sample=sample,
                observed_session_id=sample.session_id, adapter_available=True,
            )
        if not a and not b:
            return self._unsafe(
                current, SafetyInputState.ACTIVE,
                "Emergency-stop safety channels are open", sample=sample,
                observed_session_id=sample.session_id, adapter_available=True,
            )

        # Both channels are closed.  A clear signal must settle before it can
        # be trusted, and a trip always needs explicit operator acknowledgement.
        if self._stable_since is None:
            self._stable_since = current
        self._pending_clear = current - self._stable_since >= self.debounce_seconds
        if self._latched:
            reason = (
                (self._last_unsafe_reason or "Safety input previously tripped")
                + "; physical release observed; acknowledgement required"
            )
            return self._publish(
                now=current, state=SafetyInputState.LATCHED,
                raw_state=SafetyInputState.CLEAR, sample=sample,
                observed_session_id=sample.session_id, adapter_available=True,
                reason=reason,
            )
        if not self._pending_clear:
            return self._publish(
                now=current, state=SafetyInputState.UNKNOWN,
                raw_state=SafetyInputState.CLEAR, sample=sample,
                observed_session_id=sample.session_id, adapter_available=True,
                reason="Safety input clear candidate is settling",
            )
        return self._publish(
            now=current, state=SafetyInputState.CLEAR,
            raw_state=SafetyInputState.CLEAR, sample=sample,
            observed_session_id=sample.session_id, adapter_available=True,
            reason="Both safety channels are closed and feedback is fresh",
        )

    def acknowledge(self, *, now: float | None = None) -> bool:
        """Clear a latched trip only after a fresh, settled clear observation."""

        current = self._now(now)
        if not self._latched or not self._pending_clear:
            return False
        if self._status.raw_state is not SafetyInputState.CLEAR or not self._status.adapter_available:
            return False
        if self._status.session_id != self._session_id:
            return False
        self._latched = False
        self._last_unsafe_reason = ""
        self._pending_clear = False
        sample = SafetyInputSample(
            self._status.channel_a_closed, self._status.channel_b_closed,
            self._status.sample_timestamp if self._status.sample_timestamp is not None else current,
            self._session_id, source="safety-input-acknowledgement",
            raw=self._status.raw,
        )
        self.observe(sample, now=current)
        return self._status.state is SafetyInputState.CLEAR and not self._latched

    def _unsafe(
        self,
        now: float,
        state: SafetyInputState,
        reason: str,
        *,
        sample: SafetyInputSample | None,
        observed_session_id: str,
        adapter_available: bool,
    ) -> SafetyInputStatus:
        self._latched = True
        self._pending_clear = False
        self._stable_since = None
        self._last_unsafe_reason = reason
        return self._publish(
            now=now, state=SafetyInputState.LATCHED if state is SafetyInputState.CLEAR else state,
            raw_state=state, sample=sample,
            observed_session_id=observed_session_id,
            adapter_available=adapter_available, reason=reason,
        )

    def _publish(
        self,
        *,
        now: float,
        state: SafetyInputState,
        raw_state: SafetyInputState,
        sample: SafetyInputSample | None,
        observed_session_id: str,
        adapter_available: bool,
        reason: str,
    ) -> SafetyInputStatus:
        sample_timestamp = sample.timestamp if sample is not None else None
        channels = (
            sample.channel_a_closed if sample is not None else None,
            sample.channel_b_closed if sample is not None else None,
        )
        stable_for = max(0.0, float(now) - self._stable_since) if self._stable_since is not None else 0.0
        classification = (
            state, raw_state, observed_session_id, channels, adapter_available,
            self._latched, self._commissioned, reason,
        )
        if classification != self._classification:
            self._transition_id += 1
            self._classification = classification
        self._status = SafetyInputStatus(
            state=state, raw_state=raw_state, timestamp=float(now),
            sample_timestamp=sample_timestamp, observed_session_id=observed_session_id,
            session_id=self._session_id, channel_a_closed=channels[0],
            channel_b_closed=channels[1], stable_for=stable_for,
            debounce_seconds=self.debounce_seconds, stale_after=self.stale_after,
            reason=reason, sample_count=self._sample_count,
            adapter_available=adapter_available, latched=self._latched,
            commissioned=self._commissioned, transition_id=self._transition_id,
            raw={} if sample is None else sample.raw,
            source="" if sample is None else sample.source,
        )
        return self._status

    def _now(self, now: float | None) -> float:
        current = self._clock() if now is None and self._clock is not None else now
        if current is None:
            raise ValueError("now or a monitor clock is required")
        current = float(current)
        if not math.isfinite(current):
            raise ValueError("safety input observation time must be finite")
        return current


class SafetyInputAuditLog:
    """Append-only, local, secret-free safety transition record."""

    def __init__(self, root: Path, *, filename: str = "safety-input.audit.jsonl") -> None:
        self.path = Path(root) / filename

    def append(self, status: SafetyInputStatus, *, event: str) -> None:
        payload = {"event": str(event), "status": status.to_dict()}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str) + "\n")

    def last_status(self) -> dict[str, Any] | None:
        if not self.path.exists():
            return None
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return None
        for line in reversed(lines):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except (ValueError, TypeError, json.JSONDecodeError):
                # A truncated trailing record must not hide an earlier latch.
                continue
            status = item.get("status") if isinstance(item, dict) else None
            if isinstance(status, dict):
                return status
        return None


__all__ = [
    "FakeSafetyInputAdapter",
    "SafetyInputAdapter",
    "SafetyInputAuditLog",
    "SafetyInputMonitor",
    "SafetyInputSample",
    "SafetyInputState",
    "SafetyInputStatus",
]
