from __future__ import annotations

from pathlib import Path

from ttc3018_control.application.ux_state import (
    OperationCategory,
    OperationCoordinator,
    OperationState,
)
from ttc3018_control.qt.ui_preferences import UiPreferences, UiPreferencesStore


def test_operation_coordinator_tracks_tokens_scopes_and_stale_results() -> None:
    now = [10.0]
    coordinator = OperationCoordinator(lambda: now[0])
    first = coordinator.begin(OperationCategory.BACKGROUND, "Preview", blocking_scopes={"preview"})
    assert first.state is OperationState.QUEUED
    assert coordinator.update(first.token, phase="Generating…", progress=0.4).state is OperationState.RUNNING
    try:
        coordinator.begin(OperationCategory.BACKGROUND, "Another preview", blocking_scopes={"preview"})
    except RuntimeError:
        pass
    else:
        raise AssertionError("overlapping preview operations must be rejected")
    assert coordinator.finish(first.token, success=True, summary="Ready") is not None
    assert coordinator.update(first.token, phase="late") is None
    assert coordinator.history[-1].state is OperationState.SUCCEEDED


def test_operation_cancel_requires_cancellable_and_bounds_history() -> None:
    coordinator = OperationCoordinator(lambda: 1.0)
    operation = coordinator.begin(OperationCategory.BACKGROUND, "Import", cancellable=True)
    assert coordinator.cancel(operation.token) is not None
    assert coordinator.cancel(operation.token) is None
    for index in range(105):
        current = coordinator.begin(OperationCategory.BACKGROUND, f"Task {index}")
        coordinator.finish(current.token, success=True)
    assert len(coordinator.history) == 100


def test_ui_preferences_are_versioned_and_atomic(tmp_path: Path) -> None:
    path = tmp_path / "config" / "ui-preferences.json"
    store = UiPreferencesStore(path)
    store.save(UiPreferences(first_run_complete=True, expert_mode=True, last_workspace=1))
    loaded = store.load()
    assert loaded.first_run_complete
    assert loaded.expert_mode
    assert loaded.last_workspace == 1

    path.write_text('{"version": 99, "expert_mode": true}', encoding="utf-8")
    assert store.load() == UiPreferences()
