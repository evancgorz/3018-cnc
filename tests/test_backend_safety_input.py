from __future__ import annotations

from pathlib import Path

import pytest

from ttc3018_control.application.controller import ApplicationController
from ttc3018_control.backend import (
    BackendRuntime,
    FakeSafetyInputAdapter,
    SafetyInputMonitor,
    SafetyInputSample,
    SafetyInputState,
)
from ttc3018_control.backend.dispatcher import ActionDispatcher, ActionRejected


def _sample(a: bool | None, b: bool | None, timestamp: float, session: str = "session-a") -> SafetyInputSample:
    return SafetyInputSample(a, b, timestamp, session, raw={"a": a, "b": b})


def test_dual_channel_clear_requires_debounce_and_explicit_acknowledgement() -> None:
    monitor = SafetyInputMonitor(session_id="session-a", commissioned=True,
                                 debounce_seconds=0.1, stale_after=1.0)

    settling = monitor.observe(_sample(True, True, 0.0), now=0.0)
    assert settling.state is SafetyInputState.UNKNOWN
    assert not settling.latched
    assert settling.blocks_motion

    clear = monitor.observe(_sample(True, True, 0.1), now=0.1)
    assert clear.state is SafetyInputState.CLEAR
    assert not clear.trustworthy_clear
    assert clear.blocks_motion  # power removal remains unmeasured/unknown

    active = monitor.observe(_sample(False, False, 0.2), now=0.2)
    assert active.state is SafetyInputState.ACTIVE
    assert active.latched

    released = monitor.observe(_sample(True, True, 0.3), now=0.3)
    assert released.state is SafetyInputState.LATCHED
    assert not monitor.acknowledge(now=0.3)

    monitor.observe(_sample(True, True, 0.4), now=0.4)
    assert monitor.acknowledge(now=0.4)
    assert monitor.status.state is SafetyInputState.CLEAR
    assert not monitor.status.latched

    repeated = monitor.observe(_sample(False, False, 0.5), now=0.5)
    assert repeated.state is SafetyInputState.ACTIVE
    assert repeated.latched
    assert repeated.transition_id > active.transition_id


def test_disagreement_missing_channel_and_feedback_loss_latch_fail_closed() -> None:
    monitor = SafetyInputMonitor(session_id="session-a", commissioned=True,
                                 debounce_seconds=0.0, stale_after=0.5)

    disagreement = monitor.observe(_sample(True, False, 1.0), now=1.0)
    assert disagreement.state is SafetyInputState.FAULT
    assert disagreement.raw_state is SafetyInputState.FAULT
    assert disagreement.latched

    missing = monitor.observe(_sample(None, True, 1.1), now=1.1)
    assert missing.state is SafetyInputState.FAULT
    assert "unavailable" in missing.reason

    lost = monitor.observe(None, now=1.2)
    assert lost.state is SafetyInputState.UNKNOWN
    assert lost.latched
    assert not lost.adapter_available


def test_stale_reordered_or_wrong_session_feedback_is_unknown_and_latched() -> None:
    monitor = SafetyInputMonitor(session_id="session-a", commissioned=True,
                                 debounce_seconds=0.0, stale_after=0.5)

    future = monitor.observe(_sample(True, True, 2.0), now=1.0)
    assert future.state is SafetyInputState.UNKNOWN
    assert future.latched

    wrong_session = monitor.observe(_sample(True, True, 2.1, "session-b"), now=2.1)
    assert wrong_session.state is SafetyInputState.UNKNOWN
    assert "different backend session" in wrong_session.reason

    stale = monitor.observe(_sample(True, True, 1.0), now=2.0)
    assert stale.state is SafetyInputState.UNKNOWN
    assert "stale" in stale.reason


def test_fake_adapter_and_runtime_publish_physical_estop_and_restore_latch(tmp_path: Path) -> None:
    adapter = FakeSafetyInputAdapter(session_id="session-a")
    runtime = BackendRuntime(
        tmp_path,
        application=ApplicationController(tmp_path),
        safety_input_adapter=adapter,
        safety_input_commissioned=True,
        safety_input_debounce_seconds=0.0,
        clock=lambda: 1.0,
    )
    runtime.set_session_id("session-a")
    adapter.set_channels(False, False, timestamp=1.0)
    runtime.poll_once(now=1.0)

    status = runtime.safety_input_status
    assert status.state is SafetyInputState.ACTIVE
    assert status.latched
    assert runtime.snapshot()["safety"]["physical_estop"]["state"] == "active"
    assert runtime.snapshot()["can_jog"] is False
    assert runtime.snapshot()["can_start_job"] is False
    assert (tmp_path / "safety-input.audit.jsonl").exists()
    assert any(event["kind"] == "safety_input" for event in runtime.events_since()["events"])

    restarted = BackendRuntime(
        tmp_path,
        application=ApplicationController(tmp_path),
        safety_input_commissioned=True,
        safety_input_debounce_seconds=0.0,
        clock=lambda: 2.0,
    )
    restarted.set_session_id("new-session")
    restored = restarted.safety_input_status
    assert restored.latched
    assert restored.state is SafetyInputState.UNKNOWN
    assert "fresh feedback" in restored.reason


def test_commissioned_runtime_without_adapter_latches_startup_feedback_loss(tmp_path: Path) -> None:
    runtime = BackendRuntime(
        tmp_path,
        application=ApplicationController(tmp_path),
        safety_input_commissioned=True,
        clock=lambda: 4.0,
    )
    status = runtime.safety_input_status
    assert status.latched
    assert status.state is SafetyInputState.FAULT
    assert "adapter is unavailable" in status.reason
    assert runtime.safety_input_blocks_motion
    assert runtime.snapshot()["can_jog"] is False
    assert (tmp_path / "safety-input.audit.jsonl").exists()


def test_dispatcher_keeps_diagnostics_and_stop_paths_reachable_but_blocks_motion(tmp_path: Path) -> None:
    runtime = BackendRuntime(
        tmp_path,
        application=ApplicationController(tmp_path),
        safety_input_commissioned=True,
        safety_input_debounce_seconds=0.0,
    )
    runtime.set_session_id("session-a")
    runtime.update_safety_input(_sample(False, False, 0.0), now=0.0)
    dispatcher = ActionDispatcher(runtime)

    status = dispatcher.invoke("safety-input-status")
    assert status["state"] == "active"
    assert dispatcher.invoke("hold")["accepted"] is False
    with pytest.raises(ActionRejected, match="independent safety input"):
        dispatcher.invoke("jog", {"axis": "X", "distance": 1.0, "feed": 100.0})
