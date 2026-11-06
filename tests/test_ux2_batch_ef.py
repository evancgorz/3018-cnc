"""Batch E public-boundary acceptance for the loopback digital twin."""

from __future__ import annotations

import json
import time

import pytest

from ttc3018_control.application.controller import ApplicationController
from ttc3018_control.qt.view_model import ControllerViewModel
from ttc3018_control.simulation.trace import load_trace


def _pump(view_model: ControllerViewModel, predicate, timeout: float = 8.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        view_model._poll()
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError(
        "digital-twin public path did not reach the expected state: "
        f"state={view_model.application.status!r}; "
        f"homing={view_model.application.homing.state.value}; "
        f"reference={view_model.application.reference_trusted}"
    )


def _declarations(*, enabled: set[str]) -> dict[str, dict[str, object]]:
    return {
        axis: {
            "enabled": axis in enabled,
            "end": "max",
            "pin": f"{axis}1" if axis in enabled else "",
            # Use a normally-open twin declaration so the default released
            # sensor bank is a trustworthy ``Pn:none`` baseline.
            "active_low": False,
            "hard_limit": True,
            "debounce_ms": 0,
        }
        for axis in "XYZ"
    }


def _capture_transport_commands(controller: ApplicationController, commands: list[str]) -> None:
    transport = controller.transport
    assert transport is not None
    send_line = transport.send_line
    send_realtime = transport.send_realtime

    def capture_line(command: bytes, **kwargs) -> None:
        commands.append(command.decode("ascii", errors="replace").strip())
        send_line(command, **kwargs)

    def capture_realtime(command: bytes) -> None:
        commands.append(" ".join(f"0x{byte:02X}" for byte in command))
        send_realtime(command)

    transport.send_line = capture_line
    transport.send_realtime = capture_realtime


@pytest.mark.parametrize(
    ("route", "enabled", "expected_mode"),
    [
        ("three-switch", {"X", "Y", "Z"}, "guarded homing"),
    ],
)
def test_e5_public_twin_reference_and_zero_routes(
    tmp_path, qapp, route: str, enabled: set[str], expected_mode: str,
) -> None:
    """Exercise the homing-first reference path and per-axis WCO confirmation."""
    physical_calls: list[str] = []

    def forbidden_factory():
        physical_calls.append("physical")
        raise AssertionError("public twin acceptance touched a physical factory")

    controller = ApplicationController(
        tmp_path / route,
        usb_factory=forbidden_factory,
        wifi_factory=forbidden_factory,
    )
    if enabled:
        assert controller.save_homing_limit_declarations(_declarations(enabled=enabled)).accepted
    view_model = ControllerViewModel(controller)
    commands: list[str] = []
    transitions: list[str] = []
    notices: list[str] = []
    view_model.toast_requested.connect(notices.append)
    seed = 20260911
    evidence = tmp_path / "evidence" / f"{route}.json"
    runtime = None

    def mark(kind: str, payload: dict | None = None) -> None:
        transitions.append(kind)
        controller.record_simulation_event(kind, payload)

    try:
        view_model.connect_to_simulation()
        runtime = controller.simulation_runtime
        assert runtime is not None
        _capture_transport_commands(controller, commands)
        mark("e5_configuration", {
            "scenario": route,
            "seed": seed,
            "transport": "owned-loopback-tcp",
            "configuration": f"{route} homing / manual per-axis work zero",
            "expected_outcome": "trusted reference and all three fresh WCO acknowledgements",
        })
        _pump(view_model, lambda: controller.status is not None and controller.status.state == "Idle")
        mark("initial_idle", {"state": controller.status.state})
        assert view_model.workflow_reference_mode == expected_mode

        view_model.select_guided_step(2)
        assert view_model.guided_step == 2
        view_model.home_machine()
        assert controller.homing.active, notices
        _pump(
            view_model,
            lambda: controller.reference_trusted
            and controller.homing.state.value == "complete"
            and not controller.homing.active
            and view_model.guided_step == 3,
        )
        mark("three_switch_homing_complete", {
            "homing_state": controller.homing.state.value,
            "reference": repr(controller.session.envelope.reference),
        })

        assert view_model.workflow_steps[2]["state"] == "complete"
        assert view_model.guided_step == 3
        for axis in "XYZ":
            view_model.set_work_zero(axis)
            _pump(view_model, lambda axis=axis: axis in controller.session.confirmed_work_zero_axes)
            mark("work_zero_axis_confirmed", {
                "axis": axis,
                "confirmed_axes": sorted(controller.session.confirmed_work_zero_axes),
                "wco": repr(controller.work_offset),
            })
        assert controller.work_zero_confirmed
        assert view_model.guided_step == 4
        mark("expected_outcome_observed", {
            "expected": "trusted reference and all three fresh WCO acknowledgements",
            "observed": "trusted reference and all three fresh WCO acknowledgements",
            "transport_commands": tuple(commands),
        })
        controller.export_simulation_trace(evidence)
    finally:
        if runtime is not None:
            controller.disconnect("Batch E route cleanup")
            assert runtime.started is False
            runtime.trace.record(
                runtime.trace.events[-1].time_ns if runtime.trace.events else 0,
                "e5_cleanup",
                {"owned_process_cleanup": True, "route": route},
                source="application",
            )
            runtime.trace.export_json(evidence)
            runtime.trace.export_markdown(evidence.with_suffix(".md"), title="Batch E route evidence")
            view_model.close()
        else:
            view_model.close()
            controller.close()

    assert not physical_calls
    exported = json.loads(evidence.read_text(encoding="utf-8"))
    event_kinds = {event["kind"] for event in exported["events"]}
    assert {"e5_configuration", "initial_idle", "expected_outcome_observed", "e5_cleanup"} <= event_kinds
    assert any(event["kind"] == "e5_configuration" and event["payload"]["seed"] == seed
               for event in exported["events"])
    assert any(event["kind"] == "e5_cleanup" and event["payload"]["owned_process_cleanup"]
               for event in exported["events"])
    assert load_trace(evidence)
    assert any(command.startswith("G10 L20") for command in commands)


def test_c6_workflow_and_review_projection_cache_until_facts_change(tmp_path, monkeypatch, qapp) -> None:
    """Repeated QML reads share one projection and one preflight result."""
    import ttc3018_control.qt.view_model as view_model_module

    projection_calls = 0
    original_project = view_model_module.project_workflow

    def counted_project(observation):
        nonlocal projection_calls
        projection_calls += 1
        return original_project(observation)

    monkeypatch.setattr(view_model_module, "project_workflow", counted_project)
    controller = ApplicationController(tmp_path)
    view_model = ControllerViewModel(controller)
    try:
        projection_calls = 0
        _ = view_model.workflow_steps
        _ = view_model.work_zero_methods
        _ = view_model.setup_warnings
        _ = view_model.workflow_json
        # The constructor already published the initial projection; all
        # repeated reads in this unchanged revision reuse that cached value.
        assert projection_calls == 0

        preflight_calls = 0
        original_preflight = controller.preflight

        def counted_preflight():
            nonlocal preflight_calls
            preflight_calls += 1
            return original_preflight()

        monkeypatch.setattr(controller, "preflight", counted_preflight)
        controller.load_generated("G21 G90\nG1 X1 F100\n", "cache.nc")
        assert preflight_calls == 1
        preflight_calls = 0
        cache_key = view_model._workflow_cache_key
        _ = view_model.review_facts
        assert view_model._workflow_cache_key == cache_key, (cache_key, view_model._workflow_cache_key)
        _ = view_model.review_facts
        _ = view_model.workflow_steps
        assert preflight_calls == 0

        previous_calls = projection_calls
        view_model._review_acknowledged = True
        _ = view_model.workflow_steps
        assert projection_calls == previous_calls + 1
    finally:
        view_model.close()
